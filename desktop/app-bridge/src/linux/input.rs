//! X11 input driver: XTEST key and pointer injection with focus enforcement.
//!
//! XTEST is seat-global: keys go to the focused window and pointer events move
//! the real cursor. The driver therefore refuses to inject input when the target
//! window is not focused instead of silently steering another application. It
//! writes off `XSetInputFocus` unless `activate_window` asks it to raise a
//! surface first.
//!
//! Connections are opened lazily on the first input request. `new()` stays cheap
//! so a bridge started outside a graphical session does not stall at startup.
//! Every request runs on a helper thread with a deadline, so a wedged X server
//! surfaces as `timeout` rather than hanging the bridge worker.
//!
//! Key specifications accept literal text, `^` control, `!` alt, `+` shift,
//! `~` meta, and brace names such as `{ENTER}`, `{PGDN}`, and `{F12}`. A bare
//! spec that is exactly a key name (`Enter`, `Esc`, `F5`) is sent as that key
//! rather than typed as text. Wrap
//! punctuation that would otherwise start a modifier run in braces (`{+}`,
//! `{!}`); a modifier character with no key after it is typed literally.

use std::env;
use std::sync::{mpsc, Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use x11rb::connection::Connection;
use x11rb::protocol::xproto::{
    self, Atom, ClientMessageData, ClientMessageEvent, ConnectionExt as _, EventMask, InputFocus,
    MapState, Window,
};
use x11rb::protocol::xtest;
use x11rb::rust_connection::RustConnection;

use crate::protocol::{error_kind, ErrorInfo, Point, PointerButton};

/// Budget for the initial X11 connection handshake.
const CONNECT_TIMEOUT: Duration = Duration::from_secs(3);
/// Budget for one input or focus operation.
const OPERATION_TIMEOUT: Duration = Duration::from_secs(8);
/// Budget for focus probes and doctor checks.
const PROBE_TIMEOUT: Duration = Duration::from_secs(2);
/// How long a failed connection attempt is remembered.
const FAILURE_TTL: Duration = Duration::from_secs(5);
/// Upper bound on wheel notches per scroll request.
const MAX_SCROLL_NOTCHES: i32 = 20;
/// Depth limit while searching for the client inside a window-manager frame.
const MAX_SCAN_DEPTH: u8 = 3;
/// Node limit while searching the window tree.
const MAX_SCAN_NODES: usize = 256;
/// Parent-chain walk limit while comparing focus windows.
const MAX_ANCESTOR_DEPTH: usize = 32;
/// Delay between keys so toolkits can process each event.
const KEY_INTERVAL: Duration = Duration::from_millis(4);

/// Capability advertised when XTEST input can be reached.
pub const XTEST_CAPABILITY: &str = "xtest";

const WAYLAND_INPUT_MESSAGE: &str = "Wayland input is seat-global and portal-gated and is not enabled; run an Xorg session (XDG_SESSION_TYPE=x11) or use AT-SPI semantic actions";
const WAYLAND_COORDINATE_MESSAGE: &str = "coordinate input is unavailable on Wayland: the pointer is compositor-owned and there is no XTEST seat; focus the target and use AT-SPI invoke/set_value, or run an Xorg session";
const DISPLAY_MISSING_MESSAGE: &str = "DISPLAY is not set; X11 input requires an Xorg or Xwayland display. Start the bridge inside a graphical session or set DISPLAY=:0";

mod keysym {
    pub const SPACE: u32 = 0x0020;
    pub const TAB: u32 = 0xff09;
    pub const RETURN: u32 = 0xff0d;
    pub const ESCAPE: u32 = 0xff1b;
    pub const BACKSPACE: u32 = 0xff08;
    pub const DELETE: u32 = 0xffff;
    pub const HOME: u32 = 0xff50;
    pub const LEFT: u32 = 0xff51;
    pub const UP: u32 = 0xff52;
    pub const RIGHT: u32 = 0xff53;
    pub const DOWN: u32 = 0xff54;
    pub const PAGE_UP: u32 = 0xff55;
    pub const PAGE_DOWN: u32 = 0xff56;
    pub const END: u32 = 0xff57;
    pub const F1: u32 = 0xffbe;
    pub const SHIFT_L: u32 = 0xffe1;
    pub const CONTROL_L: u32 = 0xffe3;
    pub const META_L: u32 = 0xffe7;
    pub const ALT_L: u32 = 0xffe9;
}

/// X11 input driver for a single process.
#[derive(Debug)]
pub struct X11Input {
    state: Mutex<ConnectionState>,
}

impl X11Input {
    /// Create a driver without touching the X server.
    pub fn new() -> Self {
        Self {
            state: Mutex::new(ConnectionState::default()),
        }
    }

    /// Type a tmux/send-keys-style specification and return the event count.
    pub fn send_keys(&self, specification: &str) -> Result<u32, ErrorInfo> {
        let tokens = parse_keys(specification)?;
        let connection = self.connection()?;

        bounded("keys", OPERATION_TIMEOUT, move || {
            ensure_xtest(&connection)?;
            let keyboard = KeyboardMap::load(&connection)?;
            let mut events = 0u32;

            for token in &tokens {
                let base = effective_key_base(token);
                let (base_code, needs_shift) = keyboard.resolve(&base)?;
                let mut pressed = Vec::new();

                for modifier in Modifier::ORDER {
                    if token.modifiers.contains(&modifier)
                        || (modifier == Modifier::Shift && needs_shift)
                    {
                        pressed.push(modifier);
                    }
                }

                for modifier in &pressed {
                    let code = keyboard.modifier_keycode(*modifier)?;
                    fake_key(&connection, code, true)?;
                    events += 1;
                }

                fake_key(&connection, base_code, true)?;
                fake_key(&connection, base_code, false)?;
                events += 2;

                for modifier in pressed.iter().rev() {
                    let code = keyboard.modifier_keycode(*modifier)?;
                    fake_key(&connection, code, false)?;
                    events += 1;
                }

                connection
                    .flush()
                    .map_err(|error| x11_error("flush key events", error))?;
                std::thread::sleep(KEY_INTERVAL);
            }

            Ok(events)
        })
    }

    /// Move the pointer to an absolute root position and click a button.
    pub fn click_at(
        &self,
        x: i32,
        y: i32,
        button: PointerButton,
        count: u32,
    ) -> Result<u32, ErrorInfo> {
        self.ensure_coordinate_supported()?;

        let x = i16::try_from(x).map_err(|_| {
            ErrorInfo::invalid(format!("click x={x} is outside the X11 coordinate range"))
        })?;
        let y = i16::try_from(y).map_err(|_| {
            ErrorInfo::invalid(format!("click y={y} is outside the X11 coordinate range"))
        })?;
        let connection = self.connection()?;
        let number = button.x11_button();
        let count = count.max(1);

        bounded("click_at", OPERATION_TIMEOUT, move || {
            ensure_xtest(&connection)?;
            warp_pointer(&connection, x, y)?;

            let mut events = 0u32;

            for _ in 0..count {
                fake_button(&connection, number, true)?;
                fake_button(&connection, number, false)?;
                events += 2;
                std::thread::sleep(KEY_INTERVAL);
            }

            connection
                .flush()
                .map_err(|error| x11_error("flush click", error))?;

            Ok(events)
        })
    }

    /// Move the pointer to an absolute root position without pressing a button.
    pub fn move_to(&self, x: i32, y: i32) -> Result<u32, ErrorInfo> {
        self.ensure_coordinate_supported()?;

        let x = i16::try_from(x).map_err(|_| {
            ErrorInfo::invalid(format!("hover x={x} is outside the X11 coordinate range"))
        })?;
        let y = i16::try_from(y).map_err(|_| {
            ErrorInfo::invalid(format!("hover y={y} is outside the X11 coordinate range"))
        })?;
        let connection = self.connection()?;

        bounded("move_to", OPERATION_TIMEOUT, move || {
            ensure_xtest(&connection)?;
            warp_pointer(&connection, x, y)?;
            connection
                .flush()
                .map_err(|error| x11_error("flush pointer move", error))?;

            Ok(1)
        })
    }

    /// Press at `from`, move to `to`, and release for a pointer drag.
    pub fn drag(
        &self,
        from: Point,
        to: Point,
        button: PointerButton,
        duration_ms: u64,
    ) -> Result<u32, ErrorInfo> {
        self.ensure_coordinate_supported()?;

        let from_x = i16::try_from(from.x).map_err(|_| {
            ErrorInfo::invalid(format!(
                "drag start x={} is outside the X11 coordinate range",
                from.x
            ))
        })?;
        let from_y = i16::try_from(from.y).map_err(|_| {
            ErrorInfo::invalid(format!(
                "drag start y={} is outside the X11 coordinate range",
                from.y
            ))
        })?;
        let to_x = i16::try_from(to.x).map_err(|_| {
            ErrorInfo::invalid(format!(
                "drag end x={} is outside the X11 coordinate range",
                to.x
            ))
        })?;
        let to_y = i16::try_from(to.y).map_err(|_| {
            ErrorInfo::invalid(format!(
                "drag end y={} is outside the X11 coordinate range",
                to.y
            ))
        })?;
        let connection = self.connection()?;
        let number = button.x11_button();

        bounded("drag", OPERATION_TIMEOUT, move || {
            ensure_xtest(&connection)?;
            warp_pointer(&connection, from_x, from_y)?;
            fake_button(&connection, number, true)?;
            connection
                .flush()
                .map_err(|error| x11_error("flush drag press", error))?;

            let steps = (duration_ms / 16).clamp(1, 60);
            let pause = Duration::from_millis(duration_ms / steps);

            for step in 1..=steps {
                let x = i64::from(from_x)
                    + (i64::from(to_x) - i64::from(from_x)) * step as i64 / steps as i64;
                let y = i64::from(from_y)
                    + (i64::from(to_y) - i64::from(from_y)) * step as i64 / steps as i64;

                warp_pointer(&connection, x as i16, y as i16)?;
                connection
                    .flush()
                    .map_err(|error| x11_error("flush drag move", error))?;
                std::thread::sleep(pause);
            }

            fake_button(&connection, number, false)?;
            connection
                .flush()
                .map_err(|error| x11_error("flush drag release", error))?;

            Ok(2 + steps as u32)
        })
    }

    /// Scroll at the current pointer position and return the event count.
    pub fn scroll(&self, direction: &str, amount: i32) -> Result<u32, ErrorInfo> {
        let button = match direction.to_ascii_lowercase().as_str() {
            "up" => 4,
            "down" => 5,
            "left" => 6,
            "right" => 7,
            other => {
                return Err(ErrorInfo::invalid(format!(
                    "unsupported scroll direction '{other}'; expected up, down, left, or right"
                )))
            }
        };
        let notches = amount.clamp(1, MAX_SCROLL_NOTCHES);
        self.ensure_coordinate_supported()?;
        let connection = self.connection()?;

        bounded("scroll", OPERATION_TIMEOUT, move || {
            ensure_xtest(&connection)?;
            let mut events = 0u32;

            for _ in 0..notches {
                fake_button(&connection, button, true)?;
                fake_button(&connection, button, false)?;
                events += 2;
                std::thread::sleep(KEY_INTERVAL);
            }

            connection
                .flush()
                .map_err(|error| x11_error("flush scroll", error))?;

            Ok(events)
        })
    }

    /// Return the current input focus (`0` is `None`, `1` is `PointerRoot`).
    pub fn focused_window(&self) -> Result<u32, ErrorInfo> {
        let connection = self.connection()?;

        bounded("focused_window", PROBE_TIMEOUT, move || {
            focused_window_raw(&connection)
        })
    }

    /// True when `window_handle` owns the input focus.
    ///
    /// The handle may be an X11 window id (`0x3a00007` or decimal), a window
    /// title, a WM_CLASS, or a partial match on either. Focus on a window's frame
    /// or on one of its children counts as focused.
    /// Describe where input focus currently sits, for refusal messages.
    pub fn focus_state(&self) -> String {
        let focused = self
            .connection()
            .ok()
            .and_then(|connection| focused_window_raw(&connection).ok());

        match focused {
            Some(0) => "no X11 window has input focus".to_string(),
            Some(window) => format!("input focus is on 0x{window:x}"),
            None => "input focus is unreadable".to_string(),
        }
    }

    pub fn is_window_focused(&self, window_handle: &str) -> Result<bool, ErrorInfo> {
        let handle = window_handle.trim().to_string();

        if handle.is_empty() {
            return Ok(false);
        }

        let connection = self.connection()?;

        bounded("is_window_focused", PROBE_TIMEOUT, move || {
            if let Some(window) = parse_window_id(&handle) {
                return Ok(focus_matches_id(&connection, window)
                    || focus_shares_process(&connection, window));
            }

            if let Some(window) = find_window(&connection, None, Some(&handle)) {
                return Ok(focus_matches_id(&connection, window)
                    || focus_shares_process(&connection, window));
            }

            let focused = focused_window_raw(&connection)?;
            let query = normalize(&handle);
            let atoms = Atoms::load(&connection).ok();
            let title = atoms
                .as_ref()
                .and_then(|atoms| window_title(&connection, atoms, focused));
            let class = atoms
                .as_ref()
                .and_then(|atoms| window_class(&connection, atoms, focused));

            Ok(text_matches(&query, title.as_deref(), class.as_deref()))
        })
    }

    /// Return the window manager's active window, falling back to input focus.
    pub fn active_window(&self) -> Result<Option<u32>, ErrorInfo> {
        let connection = self.connection()?;

        bounded("active_window", PROBE_TIMEOUT, move || {
            let atoms = Atoms::load(&connection)?;
            let root = root_window(&connection)?;

            if let Some(bytes) = property_bytes(
                &connection,
                root,
                atoms.net_active_window,
                xproto::AtomEnum::WINDOW.into(),
                1,
            ) {
                if let Some(id) = property_u32(&connection, &bytes) {
                    if id > 1 {
                        return Ok(Some(id));
                    }
                }
            }

            let focused = focused_window_raw(&connection)?;
            Ok((focused > 1).then_some(focused))
        })
    }

    /// True when the exact window id or another window in its process holds focus.
    pub fn is_window_id_focused(&self, window: Window) -> Result<bool, ErrorInfo> {
        let connection = self.connection()?;

        bounded("is_window_id_focused", PROBE_TIMEOUT, move || {
            Ok(focus_matches_id(&connection, window) || focus_shares_process(&connection, window))
        })
    }

    /// Find the X11 window for an AT-SPI target's process and title.
    ///
    /// Returns `None` when no top-level window (including the client inside a
    /// window-manager frame) matches.
    pub fn resolve_window(
        &self,
        pid: Option<u32>,
        title: Option<&str>,
    ) -> Result<Option<u32>, ErrorInfo> {
        let connection = self.connection()?;
        let title = title.map(str::to_string);

        bounded("resolve_window", PROBE_TIMEOUT, move || {
            Ok(find_window(&connection, pid, title.as_deref()))
        })
    }

    /// Refuse coordinate input early when the session is Wayland-native.
    pub fn ensure_coordinate_supported(&self) -> Result<(), ErrorInfo> {
        match InputEnvironment::current().coordinate_block() {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }

    /// Probe the XTEST extension; used by the doctor report.
    /// Capture a rectangle from the X root window as tightly packed RGB bytes.
    pub fn capture_region(
        &self,
        x: i16,
        y: i16,
        width: u16,
        height: u16,
    ) -> Result<(u16, u16, Vec<u8>), ErrorInfo> {
        let connection = self.connection()?;
        let root = connection
            .setup()
            .roots
            .first()
            .map(|screen| screen.root)
            .ok_or_else(|| ErrorInfo::new(error_kind::UNSUPPORTED, "X11 exposes no screen"))?;

        read_pixels(&connection, root, x, y, width, height)
    }

    /// Capture a window's own pixels, independent of where it sits on screen.
    ///
    /// Root capture fails under WSLg/Xwayland, so window capture is the path the
    /// backend prefers.
    pub fn capture_window(
        &self,
        window: Window,
        width: u16,
        height: u16,
    ) -> Result<(u16, u16, Vec<u8>), ErrorInfo> {
        let connection = self.connection()?;

        read_pixels(&connection, window, 0, 0, width, height)
    }
    /// Ask the window manager to activate a window and give it input focus.
    ///
    /// WSLg has no window manager, and an app's registered X windows are often
    /// small unmapped stubs, so focus goes to the largest viewable surface the
    /// process owns instead of the window id we were given.
    pub fn activate_window(&self, window: Window) -> Result<(), ErrorInfo> {
        let connection = self.connection()?;
        let root = root_window(&connection)?;
        let atoms = Atoms::load(&connection)?;

        if let Ok(atom) = connection.intern_atom(false, b"_NET_ACTIVE_WINDOW") {
            if let Ok(reply) = atom.reply() {
                let event = ClientMessageEvent::new(
                    32,
                    window,
                    reply.atom,
                    ClientMessageData::from([1, 0, 0, 0, 0]),
                );

                let _ = connection.send_event(
                    false,
                    root,
                    EventMask::SUBSTRUCTURE_REDIRECT | EventMask::SUBSTRUCTURE_NOTIFY,
                    event,
                );
            }
        }

        for candidate in focus_candidates(&connection, &atoms, window) {
            let _ = connection.map_window(candidate);

            if connection
                .set_input_focus(InputFocus::PARENT, candidate, x11rb::CURRENT_TIME)
                .is_err()
            {
                continue;
            }

            if connection.flush().is_err() {
                continue;
            }

            if focus_matches_id(&connection, candidate)
                || focus_shares_process(&connection, candidate)
            {
                return Ok(());
            }
        }

        let _ = connection.flush();

        Ok(())
    }

    pub fn probe_xtest(&self) -> Result<bool, ErrorInfo> {
        let connection = self.connection()?;

        bounded("probe_xtest", PROBE_TIMEOUT, move || {
            let reply = xtest::get_version(connection.as_ref(), 2, 2)
                .map_err(|error| xtest_unavailable(&error))?
                .reply()
                .map_err(|error| xtest_unavailable(&error))?;

            Ok(reply.major_version >= 2)
        })
    }

    fn connection(&self) -> Result<Arc<RustConnection>, ErrorInfo> {
        let environment = InputEnvironment::current();

        if let Some(error) = environment.hard_block() {
            return Err(error);
        }

        {
            let state = lock(&self.state);

            if let Some(connection) = &state.connection {
                return Ok(Arc::clone(connection));
            }

            if let Some((at, error)) = &state.failure {
                if at.elapsed() < FAILURE_TTL {
                    return Err(error.clone());
                }
            }
        }

        let Some(display) = environment.display else {
            let error = ErrorInfo::new(error_kind::UNSUPPORTED, DISPLAY_MISSING_MESSAGE);
            self.remember_failure(error.clone());

            return Err(error);
        };

        let result = bounded("connect", CONNECT_TIMEOUT, move || {
            let (connection, _screen) = RustConnection::connect(None).map_err(|error| {
                ErrorInfo::new(
                    error_kind::UNSUPPORTED,
                    format!(
                        "cannot connect to X11 display '{display}': {error}; check DISPLAY and XAUTHORITY (for example export XAUTHORITY=~/.Xauthority)"
                    ),
                )
            })?;

            if connection.setup().roots.is_empty() {
                return Err(ErrorInfo::new(
                    error_kind::UNSUPPORTED,
                    format!("X11 display '{display}' reports no screens"),
                ));
            }

            Ok(Arc::new(connection))
        });

        match result {
            Ok(connection) => {
                let mut state = lock(&self.state);
                state.connection = Some(Arc::clone(&connection));
                state.failure = None;

                Ok(connection)
            }
            Err(error) => {
                self.remember_failure(error.clone());

                Err(error)
            }
        }
    }

    fn remember_failure(&self, error: ErrorInfo) {
        let mut state = lock(&self.state);
        state.failure = Some((Instant::now(), error));
    }
}

impl Default for X11Input {
    fn default() -> Self {
        Self::new()
    }
}

/// Environment facts used for capability and doctor reporting.
#[derive(Debug, Clone)]
pub struct InputEnvironment {
    /// `DISPLAY`, if set and non-empty.
    pub display: Option<String>,
    /// `XDG_SESSION_TYPE`, if set.
    pub session_type: Option<String>,
    /// `WAYLAND_DISPLAY`, if set and non-empty.
    pub wayland_display: Option<String>,
}

impl InputEnvironment {
    /// Read the current process environment.
    pub fn current() -> Self {
        Self {
            display: non_empty_env("DISPLAY"),
            session_type: non_empty_env("XDG_SESSION_TYPE"),
            wayland_display: non_empty_env("WAYLAND_DISPLAY"),
        }
    }

    /// True when this session is Wayland-native or Wayland-backed.
    pub fn wayland(&self) -> bool {
        self.session_type
            .as_deref()
            .map(|value| value.eq_ignore_ascii_case("wayland"))
            .unwrap_or(false)
            || (self.wayland_display.is_some() && self.display.is_none())
    }

    /// True when XTEST input can reach an X server (Xorg or Xwayland).
    pub fn xtest_capable(&self) -> bool {
        self.display.is_some()
    }

    /// Hard stop for sessions that have no X display at all.
    pub fn hard_block(&self) -> Option<ErrorInfo> {
        if self.display.is_none() {
            if self.wayland() {
                return Some(ErrorInfo::new(
                    error_kind::UNSUPPORTED,
                    WAYLAND_INPUT_MESSAGE,
                ));
            }

            return Some(ErrorInfo::new(
                error_kind::UNSUPPORTED,
                DISPLAY_MISSING_MESSAGE,
            ));
        }

        None
    }

    /// Coordinate input is always refused on Wayland because the pointer is not
    /// an X11 resource, even when Xwayland supplies a DISPLAY for X11 clients.
    pub fn coordinate_block(&self) -> Option<ErrorInfo> {
        if self.wayland() {
            return Some(ErrorInfo::new(
                error_kind::UNSUPPORTED,
                WAYLAND_COORDINATE_MESSAGE,
            ));
        }

        None
    }
}

#[derive(Debug, Default)]
struct ConnectionState {
    connection: Option<Arc<RustConnection>>,
    failure: Option<(Instant, ErrorInfo)>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Modifier {
    Ctrl,
    Alt,
    Shift,
    Meta,
}

impl Modifier {
    const ORDER: [Self; 4] = [Self::Ctrl, Self::Alt, Self::Shift, Self::Meta];

    fn from_prefix(prefix: char) -> Option<Self> {
        match prefix {
            '^' => Some(Self::Ctrl),
            '!' => Some(Self::Alt),
            '+' => Some(Self::Shift),
            '~' => Some(Self::Meta),
            _ => None,
        }
    }

    fn keysym(self) -> u32 {
        match self {
            Self::Ctrl => keysym::CONTROL_L,
            Self::Alt => keysym::ALT_L,
            Self::Shift => keysym::SHIFT_L,
            Self::Meta => keysym::META_L,
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::Ctrl => "control",
            Self::Alt => "alt",
            Self::Shift => "shift",
            Self::Meta => "meta",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SpecialKey {
    Enter,
    Tab,
    Escape,
    Backspace,
    Delete,
    Up,
    Down,
    Left,
    Right,
    Home,
    End,
    PageUp,
    PageDown,
    Function(u8),
}

impl SpecialKey {
    fn from_name(name: &str) -> Option<Self> {
        match name.to_ascii_uppercase().as_str() {
            "ENTER" | "RETURN" => Some(Self::Enter),
            "TAB" => Some(Self::Tab),
            "ESC" | "ESCAPE" => Some(Self::Escape),
            "BACKSPACE" | "BS" => Some(Self::Backspace),
            "DELETE" | "DEL" => Some(Self::Delete),
            "UP" => Some(Self::Up),
            "DOWN" => Some(Self::Down),
            "LEFT" => Some(Self::Left),
            "RIGHT" => Some(Self::Right),
            "HOME" => Some(Self::Home),
            "END" => Some(Self::End),
            "PGUP" | "PAGEUP" => Some(Self::PageUp),
            "PGDN" | "PAGEDOWN" => Some(Self::PageDown),
            function if function.starts_with('F') => function[1..]
                .parse::<u8>()
                .ok()
                .filter(|number| (1..=12).contains(number))
                .map(Self::Function),
            _ => None,
        }
    }

    fn keysym(self) -> u32 {
        match self {
            Self::Enter => keysym::RETURN,
            Self::Tab => keysym::TAB,
            Self::Escape => keysym::ESCAPE,
            Self::Backspace => keysym::BACKSPACE,
            Self::Delete => keysym::DELETE,
            Self::Up => keysym::UP,
            Self::Down => keysym::DOWN,
            Self::Left => keysym::LEFT,
            Self::Right => keysym::RIGHT,
            Self::Home => keysym::HOME,
            Self::End => keysym::END,
            Self::PageUp => keysym::PAGE_UP,
            Self::PageDown => keysym::PAGE_DOWN,
            Self::Function(number) => keysym::F1 + u32::from(number) - 1,
        }
    }

    fn description(self) -> String {
        match self {
            Self::Function(number) => format!("{{F{number}}}"),
            other => format!("{{{}}}", other.name()),
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::Enter => "ENTER",
            Self::Tab => "TAB",
            Self::Escape => "ESC",
            Self::Backspace => "BACKSPACE",
            Self::Delete => "DELETE",
            Self::Up => "UP",
            Self::Down => "DOWN",
            Self::Left => "LEFT",
            Self::Right => "RIGHT",
            Self::Home => "HOME",
            Self::End => "END",
            Self::PageUp => "PGUP",
            Self::PageDown => "PGDN",
            Self::Function(_) => "F",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum KeyBase {
    Character(char),
    Special(SpecialKey),
}

impl KeyBase {
    fn keysym(&self) -> Option<u32> {
        match self {
            Self::Character(character) => char_keysym(*character),
            Self::Special(key) => Some(key.keysym()),
        }
    }

    fn description(&self) -> String {
        match self {
            Self::Character(character) => format!("'{character}'"),
            Self::Special(key) => key.description(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct KeyToken {
    modifiers: Vec<Modifier>,
    base: KeyBase,
}

fn parse_keys(specification: &str) -> Result<Vec<KeyToken>, ErrorInfo> {
    let characters: Vec<char> = specification.chars().collect();

    if characters.is_empty() {
        return Err(ErrorInfo::invalid(
            "keys is empty; pass a tmux-style specification such as '^s' or '{ENTER}'",
        ));
    }

    if let Some(base) = bare_key_name(specification) {
        return Ok(vec![KeyToken {
            modifiers: Vec::new(),
            base,
        }]);
    }
    let mut tokens = Vec::new();
    let mut index = 0usize;

    while index < characters.len() {
        let character = characters[index];

        if character == '{' {
            let base = parse_brace(&characters, &mut index)?;
            tokens.push(KeyToken {
                modifiers: Vec::new(),
                base,
            });

            continue;
        }

        if let Some(modifier) = Modifier::from_prefix(character) {
            let mut modifiers = vec![modifier];
            let mut prefix = String::from(character);
            index += 1;

            while let Some(next) = characters.get(index) {
                match Modifier::from_prefix(*next) {
                    Some(next_modifier) => {
                        if !modifiers.contains(&next_modifier) {
                            modifiers.push(next_modifier);
                        }
                        prefix.push(*next);
                        index += 1;
                    }
                    None => break,
                }
            }

            let Some(next) = characters.get(index).copied() else {
                for prefix_character in prefix.chars() {
                    tokens.push(KeyToken {
                        modifiers: Vec::new(),
                        base: KeyBase::Character(prefix_character),
                    });
                }
                continue;
            };

            let base = if next == '{' {
                parse_brace(&characters, &mut index)?
            } else {
                index += 1;
                KeyBase::Character(next)
            };

            tokens.push(KeyToken { modifiers, base });

            continue;
        }

        tokens.push(KeyToken {
            modifiers: Vec::new(),
            base: KeyBase::Character(character),
        });
        index += 1;
    }

    Ok(tokens)
}

/// Treat a whole-spec key name such as ``Enter`` as a key press, not as text.
///
/// A one-character spec stays text, and so does anything that uses the brace,
/// modifier, or space syntax, so this only catches the common mistake of writing
/// `keys("Enter")` when `{ENTER}` was meant.
fn bare_key_name(specification: &str) -> Option<KeyBase> {
    let trimmed = specification.trim();

    if trimmed.chars().count() < 2 || trimmed.chars().any(|value| "{}^!+~ ".contains(value)) {
        return None;
    }

    SpecialKey::from_name(trimmed).map(KeyBase::Special)
}

fn parse_brace(characters: &[char], index: &mut usize) -> Result<KeyBase, ErrorInfo> {
    let start = *index;
    *index += 1;
    let mut name = String::new();

    while let Some(character) = characters.get(*index) {
        if *character == '}' {
            break;
        }

        name.push(*character);
        *index += 1;
    }

    if characters.get(*index) != Some(&'}') {
        let remainder: String = characters[start..].iter().collect();

        return Err(ErrorInfo::invalid(format!(
            "unterminated key token '{remainder}' in keys specification"
        )));
    }

    *index += 1;

    if name.is_empty() {
        return Err(ErrorInfo::invalid(
            "empty key token '{}' in keys specification",
        ));
    }

    if name.chars().count() == 1 {
        return Ok(KeyBase::Character(name.chars().next().unwrap_or(' ')));
    }

    SpecialKey::from_name(&name)
        .map(KeyBase::Special)
        .ok_or_else(|| {
            ErrorInfo::invalid(format!(
                "unsupported key token '{{{name}}}' in keys specification"
            ))
        })
}

fn effective_key_base(token: &KeyToken) -> KeyBase {
    let accelerated = token
        .modifiers
        .iter()
        .any(|modifier| matches!(modifier, Modifier::Ctrl | Modifier::Alt | Modifier::Meta));

    if accelerated && !token.modifiers.contains(&Modifier::Shift) {
        if let KeyBase::Character(character) = token.base {
            if character.is_ascii_uppercase() {
                return KeyBase::Character(character.to_ascii_lowercase());
            }
        }
    }

    token.base.clone()
}

fn char_keysym(character: char) -> Option<u32> {
    match character {
        '\n' | '\r' => Some(keysym::RETURN),
        '\t' => Some(keysym::TAB),
        '\u{7f}' => Some(keysym::DELETE),
        ' ' => Some(keysym::SPACE),
        value if ('\u{20}'..='\u{7e}').contains(&value) => Some(value as u32),
        value if ('\u{a0}'..='\u{ff}').contains(&value) => Some(value as u32),
        value if !value.is_control() => Some(0x0100_0000 | value as u32),
        _ => None,
    }
}

struct KeyboardMap {
    min_keycode: u8,
    keysyms_per_keycode: usize,
    keysyms: Vec<u32>,
}

impl KeyboardMap {
    fn load(connection: &RustConnection) -> Result<Self, ErrorInfo> {
        let setup = connection.setup();
        let min_keycode = setup.min_keycode;
        let max_keycode = setup.max_keycode;

        if max_keycode < min_keycode {
            return Err(ErrorInfo::backend(
                "the X server reports an empty keyboard mapping",
            ));
        }

        let count = max_keycode - min_keycode + 1;
        let reply = xproto::get_keyboard_mapping(connection, min_keycode, count)
            .map_err(|error| x11_error("get_keyboard_mapping", error))?
            .reply()
            .map_err(|error| x11_error("get_keyboard_mapping reply", error))?;
        let keysyms_per_keycode = usize::from(reply.keysyms_per_keycode);

        if keysyms_per_keycode == 0 {
            return Err(ErrorInfo::backend(
                "the X server reports zero keysyms per keycode",
            ));
        }

        Ok(Self {
            min_keycode,
            keysyms_per_keycode,
            keysyms: reply.keysyms,
        })
    }

    fn resolve(&self, base: &KeyBase) -> Result<(u8, bool), ErrorInfo> {
        let Some(keysym) = base.keysym() else {
            return Err(ErrorInfo::invalid(format!(
                "key {} cannot be encoded as an X11 keysym",
                base.description()
            )));
        };

        self.keycode_for(keysym).ok_or_else(|| {
            ErrorInfo::invalid(format!(
                "key {} is not mapped on the current X11 keyboard layout",
                base.description()
            ))
        })
    }

    fn modifier_keycode(&self, modifier: Modifier) -> Result<u8, ErrorInfo> {
        self.keycode_for(modifier.keysym())
            .map(|(code, _)| code)
            .ok_or_else(|| {
                ErrorInfo::invalid(format!(
                    "modifier '{}' is not mapped on the current X11 keyboard layout",
                    modifier.name()
                ))
            })
    }

    fn keycode_for(&self, keysym: u32) -> Option<(u8, bool)> {
        let keycode_count = self.keysyms.len() / self.keysyms_per_keycode;

        if keycode_count == 0 {
            return None;
        }

        let last_keycode = self
            .min_keycode
            .checked_add(u8::try_from(keycode_count - 1).ok()?)?;

        for keycode in self.min_keycode..=last_keycode {
            let Some(levels) = self.levels(keycode) else {
                continue;
            };

            for (level, candidate) in levels.iter().take(2).enumerate() {
                if *candidate == keysym {
                    return Some((keycode, level == 1));
                }
            }
        }

        None
    }

    fn levels(&self, keycode: u8) -> Option<&[u32]> {
        if keycode < self.min_keycode {
            return None;
        }

        let offset = usize::from(keycode - self.min_keycode) * self.keysyms_per_keycode;

        self.keysyms.get(offset..offset + self.keysyms_per_keycode)
    }
}

struct Atoms {
    wm_name: Atom,
    wm_class: Atom,
    net_wm_name: Atom,
    utf8_string: Atom,
    net_wm_pid: Atom,
    net_active_window: Atom,
}

impl Atoms {
    fn load(connection: &RustConnection) -> Result<Self, ErrorInfo> {
        Ok(Self {
            wm_name: intern_atom(connection, "WM_NAME")?,
            wm_class: intern_atom(connection, "WM_CLASS")?,
            net_wm_name: intern_atom(connection, "_NET_WM_NAME")?,
            utf8_string: intern_atom(connection, "UTF8_STRING")?,
            net_wm_pid: intern_atom(connection, "_NET_WM_PID")?,
            net_active_window: intern_atom(connection, "_NET_ACTIVE_WINDOW")?,
        })
    }
}

fn intern_atom(connection: &RustConnection, name: &str) -> Result<Atom, ErrorInfo> {
    Ok(xproto::intern_atom(connection, false, name.as_bytes())
        .map_err(|error| x11_error("intern_atom", error))?
        .reply()
        .map_err(|error| x11_error("intern_atom reply", error))?
        .atom)
}

fn focused_window_raw(connection: &RustConnection) -> Result<u32, ErrorInfo> {
    Ok(xproto::get_input_focus(connection)
        .map_err(|error| x11_error("get_input_focus", error))?
        .reply()
        .map_err(|error| x11_error("get_input_focus reply", error))?
        .focus)
}

fn focus_matches_id(connection: &RustConnection, target: u32) -> bool {
    let Ok(focused) = focused_window_raw(connection) else {
        return false;
    };

    if focused == target {
        return true;
    }

    if focused <= 1 {
        return false;
    }

    window_within(connection, focused, target) || window_within(connection, target, focused)
}

fn window_within(connection: &RustConnection, window: u32, ancestor: u32) -> bool {
    let mut current = window;

    for _ in 0..MAX_ANCESTOR_DEPTH {
        if current == ancestor {
            return true;
        }

        if current == 0 {
            return false;
        }

        let Ok(tree) = xproto::query_tree(connection, current)
            .map_err(|error| x11_error("query_tree", error))
            .and_then(|cookie| {
                cookie
                    .reply()
                    .map_err(|error| x11_error("query_tree reply", error))
            })
        else {
            return false;
        };

        if tree.parent == 0 || tree.parent == current {
            return false;
        }

        current = tree.parent;
    }

    false
}

fn find_window(
    connection: &RustConnection,
    pid: Option<u32>,
    title: Option<&str>,
) -> Option<Window> {
    let atoms = Atoms::load(connection).ok()?;
    let query = title.map(normalize).filter(|value| !value.is_empty());
    let root = connection.setup().roots.first()?.root;
    let roots = xproto::query_tree(connection, root)
        .ok()?
        .reply()
        .ok()?
        .children;
    let mut stack: Vec<(Window, u8)> = roots.into_iter().map(|window| (window, 0)).collect();
    let mut visited = 0usize;
    let mut process_match = None;
    let mut partial_match = None;

    while let Some((window, depth)) = stack.pop() {
        visited += 1;

        if visited > MAX_SCAN_NODES {
            break;
        }

        let window_pid = read_window_pid(connection, &atoms, window);
        let pid_ok = window_has_area(connection, window)
            && match pid {
                Some(value) if value > 0 => window_pid == Some(value),
                _ => true,
            };

        if pid_ok {
            let window_title = window_title(connection, &atoms, window);
            let window_class = window_class(connection, &atoms, window);

            match &query {
                Some(query) => {
                    if text_matches(query, window_title.as_deref(), window_class.as_deref()) {
                        return Some(window);
                    }

                    if partial_match.is_none()
                        && contains_match(query, window_title.as_deref(), window_class.as_deref())
                    {
                        partial_match = Some(window);
                    }
                }
                None => {
                    if process_match.is_none() {
                        process_match = Some(window);
                    }
                }
            }
        }

        if depth < MAX_SCAN_DEPTH {
            if let Ok(children) = xproto::query_tree(connection, window)
                .map_err(|error| x11_error("query_tree", error))
                .and_then(|cookie| {
                    cookie
                        .reply()
                        .map_err(|error| x11_error("query_tree reply", error))
                })
            {
                stack.extend(
                    children
                        .children
                        .into_iter()
                        .map(|child| (child, depth + 1)),
                );
            }
        }
    }

    process_match.or(partial_match)
}

/// True when the focused window belongs to the same process as `window`.
///
/// Chromium/Electron apps redirect focus to a sibling proxy window, so id and
/// ancestry checks alone report an unfocused window.
fn focus_shares_process(connection: &RustConnection, window: Window) -> bool {
    let Ok(focused) = focused_window_raw(connection) else {
        return false;
    };

    if focused <= 1 {
        return false;
    }

    let Ok(atoms) = Atoms::load(connection) else {
        return false;
    };

    match (
        process_window_pid(connection, &atoms, window),
        process_window_pid(connection, &atoms, focused),
    ) {
        (Some(target), Some(focused)) => target != 0 && target == focused,
        _ => false,
    }
}

/// Candidate surfaces to focus, outermost first.
///
/// Registered windows are frequently unmapped stubs (Chromium keeps a 10x10
/// helper window, for example) and Wayland compositors wrap the app in an outer
/// toplevel, so focus tries the app's largest viewable window and the viewable
/// ancestors above it before falling back to the window we resolved.
fn focus_candidates(connection: &RustConnection, atoms: &Atoms, window: Window) -> Vec<Window> {
    let base = process_window_pid(connection, atoms, window)
        .and_then(|pid| largest_viewable_window(connection, atoms, pid))
        .unwrap_or(window);
    let root = root_window(connection).ok();
    let mut chain = Vec::new();
    let mut current = base;

    for _ in 0..MAX_ANCESTOR_DEPTH {
        if is_viewable(connection, current) {
            chain.push(current);
        }

        let parent = match xproto::query_tree(connection, current)
            .ok()
            .and_then(|cookie| cookie.reply().ok())
            .map(|tree| tree.parent)
        {
            Some(parent) => parent,
            None => break,
        };

        if parent == 0 || parent == current || Some(parent) == root {
            break;
        }

        current = parent;
    }

    let mut candidates: Vec<Window> = chain.into_iter().rev().collect();

    if !candidates.contains(&base) {
        candidates.push(base);
    }

    if !candidates.contains(&window) {
        candidates.push(window);
    }

    candidates
}

/// True when the window is mapped and viewable.
fn is_viewable(connection: &RustConnection, window: Window) -> bool {
    xproto::get_window_attributes(connection, window)
        .ok()
        .and_then(|cookie| cookie.reply().ok())
        .map(|attributes| attributes.map_state == MapState::VIEWABLE)
        .unwrap_or(false)
}

/// Largest viewable window owned by `pid`, ignoring stubs and offscreen helpers.
fn largest_viewable_window(connection: &RustConnection, atoms: &Atoms, pid: u32) -> Option<Window> {
    let root = root_window(connection).ok()?;
    let mut stack = vec![root];
    let mut visited = 0usize;
    let mut best: Option<(Window, u64)> = None;

    while let Some(window) = stack.pop() {
        visited += 1;

        if visited > MAX_SCAN_NODES {
            break;
        }

        if let Some(tree) = xproto::query_tree(connection, window)
            .ok()
            .and_then(|cookie| cookie.reply().ok())
        {
            stack.extend(tree.children.iter().copied());
        }

        if read_window_pid(connection, atoms, window) != Some(pid) {
            continue;
        }

        let viewable = xproto::get_window_attributes(connection, window)
            .ok()
            .and_then(|cookie| cookie.reply().ok())
            .map(|attributes| attributes.map_state == MapState::VIEWABLE)
            .unwrap_or(false);

        if !viewable {
            continue;
        }

        let area = xproto::get_geometry(connection, window)
            .ok()
            .and_then(|cookie| cookie.reply().ok())
            .map(|geometry| u64::from(geometry.width) * u64::from(geometry.height))
            .unwrap_or(0);

        if area == 0 {
            continue;
        }

        if best.map_or(true, |(_, largest)| area > largest) {
            best = Some((window, area));
        }
    }

    best.map(|(window, _)| window)
}

/// Walk up from `window` until a `_NET_WM_PID` is found.
fn process_window_pid(connection: &RustConnection, atoms: &Atoms, window: Window) -> Option<u32> {
    let mut current = window;

    for _ in 0..MAX_ANCESTOR_DEPTH {
        if let Some(pid) = read_window_pid(connection, atoms, current) {
            if pid != 0 {
                return Some(pid);
            }
        }

        if current == 0 {
            return None;
        }

        let parent = xproto::query_tree(connection, current)
            .ok()?
            .reply()
            .ok()?
            .parent;

        if parent == current || parent == 0 {
            return None;
        }

        current = parent;
    }

    None
}

fn read_pixels(
    connection: &RustConnection,
    drawable: u32,
    x: i16,
    y: i16,
    width: u16,
    height: u16,
) -> Result<(u16, u16, Vec<u8>), ErrorInfo> {
    if width == 0 || height == 0 {
        return Err(ErrorInfo::new(
            error_kind::CAPTURE_EXCLUDED,
            "window has no drawable area",
        ));
    }

    let reply = xproto::get_image(
        connection,
        xproto::ImageFormat::Z_PIXMAP,
        drawable,
        x,
        y,
        width,
        height,
        !0,
    )
    .map_err(|error| x11_error("GetImage", error))?
    .reply()
    .map_err(|error| x11_error("GetImage", error))?;

    let pixels = width as usize * height as usize;
    let stride = reply.data.len() / pixels.max(1);

    if stride < 3 {
        return Err(x11_error("GetImage", "unexpected pixel format"));
    }

    let mut rgb = Vec::with_capacity(pixels * 3);

    for chunk in reply.data.chunks_exact(stride) {
        rgb.extend_from_slice(&[chunk[2], chunk[1], chunk[0]]);
    }

    Ok((width, height, rgb))
}

fn read_window_pid(connection: &RustConnection, atoms: &Atoms, window: Window) -> Option<u32> {
    let bytes = property_bytes(connection, window, atoms.net_wm_pid, 0, 1)?;
    let raw = [
        *bytes.first()?,
        *bytes.get(1)?,
        *bytes.get(2)?,
        *bytes.get(3)?,
    ];

    if connection.setup().image_byte_order == xproto::ImageOrder::LSB_FIRST {
        Some(u32::from_le_bytes(raw))
    } else {
        Some(u32::from_be_bytes(raw))
    }
}

fn property_u32(connection: &RustConnection, bytes: &[u8]) -> Option<u32> {
    let raw: [u8; 4] = bytes.get(0..4)?.try_into().ok()?;

    if connection.setup().image_byte_order == xproto::ImageOrder::LSB_FIRST {
        Some(u32::from_le_bytes(raw))
    } else {
        Some(u32::from_be_bytes(raw))
    }
}

fn window_title(connection: &RustConnection, atoms: &Atoms, window: Window) -> Option<String> {
    if let Some(bytes) = property_bytes(
        connection,
        window,
        atoms.net_wm_name,
        atoms.utf8_string,
        1024,
    ) {
        let title = String::from_utf8_lossy(&bytes)
            .trim_end_matches('\0')
            .to_string();

        if !title.is_empty() {
            return Some(title);
        }
    }

    property_bytes(connection, window, atoms.wm_name, 0, 1024).map(|bytes| {
        String::from_utf8_lossy(&bytes)
            .trim_end_matches('\0')
            .to_string()
    })
}

fn window_class(connection: &RustConnection, atoms: &Atoms, window: Window) -> Option<String> {
    property_bytes(connection, window, atoms.wm_class, 0, 1024)
        .map(|bytes| String::from_utf8_lossy(&bytes).replace('\0', " "))
}

fn property_bytes(
    connection: &RustConnection,
    window: Window,
    property: Atom,
    type_: Atom,
    length: u32,
) -> Option<Vec<u8>> {
    let reply = xproto::get_property(connection, false, window, property, type_, 0, length)
        .ok()?
        .reply()
        .ok()?;

    if reply.format == 0 {
        return None;
    }

    Some(reply.value)
}

fn text_matches(query: &str, title: Option<&str>, class: Option<&str>) -> bool {
    exact_match(query, title) || exact_match(query, class)
}

fn contains_match(query: &str, title: Option<&str>, class: Option<&str>) -> bool {
    contains(query, title) || contains(query, class)
}

fn exact_match(query: &str, value: Option<&str>) -> bool {
    value
        .map(|value| normalize(value) == query)
        .unwrap_or(false)
}

fn contains(query: &str, value: Option<&str>) -> bool {
    value
        .map(|value| normalize(value).contains(query))
        .unwrap_or(false)
}

fn normalize(value: &str) -> String {
    value.trim().to_lowercase()
}

fn parse_window_id(handle: &str) -> Option<u32> {
    let handle = handle.trim();

    if let Some(hex) = handle
        .strip_prefix("0x")
        .or_else(|| handle.strip_prefix("0X"))
    {
        return u32::from_str_radix(hex, 16).ok().filter(|value| *value > 0);
    }

    if !handle.is_empty() && handle.chars().all(|value| value.is_ascii_digit()) {
        return handle.parse::<u32>().ok().filter(|value| *value > 0);
    }

    None
}

fn root_window(connection: &RustConnection) -> Result<Window, ErrorInfo> {
    connection
        .setup()
        .roots
        .first()
        .map(|screen| screen.root)
        .ok_or_else(|| {
            ErrorInfo::new(
                error_kind::UNSUPPORTED,
                "the X11 display reports no screens",
            )
        })
}

fn window_has_area(connection: &RustConnection, window: Window) -> bool {
    xproto::get_geometry(connection, window)
        .ok()
        .and_then(|cookie| cookie.reply().ok())
        .map(|geometry| geometry.width > 0 && geometry.height > 0)
        .unwrap_or(true)
}

fn ensure_xtest(connection: &RustConnection) -> Result<(), ErrorInfo> {
    let reply = xtest::get_version(connection, 2, 2)
        .map_err(|error| xtest_unavailable(&error))?
        .reply()
        .map_err(|error| xtest_unavailable(&error))?;

    if reply.major_version < 2 {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "the X server reports XTEST older than 2.0; key and pointer injection requires XTEST 2.2",
        ));
    }

    Ok(())
}

fn fake_key(connection: &RustConnection, keycode: u8, press: bool) -> Result<(), ErrorInfo> {
    let event_type = if press {
        xproto::KEY_PRESS_EVENT
    } else {
        xproto::KEY_RELEASE_EVENT
    };

    xtest::fake_input(connection, event_type, keycode, 0, 0, 0, 0, 0)
        .map_err(|error| x11_error("fake key event", error))
        .map(|_| ())
}

fn warp_pointer(connection: &RustConnection, x: i16, y: i16) -> Result<(), ErrorInfo> {
    let root = root_window(connection)?;

    xproto::warp_pointer(connection, 0u32, root, 0, 0, 0, 0, x, y)
        .map_err(|error| x11_error("warp pointer", error))
        .map(|_| ())
}

fn fake_button(connection: &RustConnection, button: u8, press: bool) -> Result<(), ErrorInfo> {
    let event_type = if press {
        xproto::BUTTON_PRESS_EVENT
    } else {
        xproto::BUTTON_RELEASE_EVENT
    };

    xtest::fake_input(connection, event_type, button, 0, 0, 0, 0, 0)
        .map_err(|error| x11_error("fake button event", error))
        .map(|_| ())
}

fn bounded<T, F>(label: &str, timeout: Duration, task: F) -> Result<T, ErrorInfo>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, ErrorInfo> + Send + 'static,
{
    let (sender, receiver) = mpsc::channel();

    let spawn = std::thread::Builder::new()
        .name(format!("x11-{label}"))
        .spawn(move || {
            let _ = sender.send(task());
        });

    if let Err(error) = spawn {
        return Err(ErrorInfo::backend(format!(
            "cannot start the X11 worker thread: {error}"
        )));
    }

    match receiver.recv_timeout(timeout) {
        Ok(result) => result,
        Err(_) => Err(ErrorInfo::new(
            error_kind::TIMEOUT,
            format!("X11 {label} timed out after {} ms", timeout.as_millis()),
        )),
    }
}

fn non_empty_env(name: &str) -> Option<String> {
    env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    match mutex.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    }
}

fn x11_error(context: &str, error: impl std::fmt::Display) -> ErrorInfo {
    ErrorInfo::new(
        error_kind::BACKEND_ERROR,
        format!("X11 {context} failed: {error}"),
    )
}

fn xtest_unavailable(error: impl std::fmt::Display) -> ErrorInfo {
    ErrorInfo::new(
        error_kind::UNSUPPORTED,
        format!(
            "XTEST input is unavailable on this display: {error}; enable the XTEST extension in the X server (Xorg enables it by default, Xwayland exposes it to X11 clients)"
        ),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn character(character: char) -> KeyToken {
        KeyToken {
            modifiers: Vec::new(),
            base: KeyBase::Character(character),
        }
    }

    #[test]
    fn parses_literal_text_one_token_per_character() {
        let tokens = parse_keys("Hi 5?").expect("parse");

        assert_eq!(
            tokens,
            vec![
                character('H'),
                character('i'),
                character(' '),
                character('5'),
                character('?'),
            ]
        );
    }

    #[test]
    fn parses_modifier_prefixes() {
        let tokens = parse_keys("^s!+~x").expect("parse");

        assert_eq!(
            tokens,
            vec![
                KeyToken {
                    modifiers: vec![Modifier::Ctrl],
                    base: KeyBase::Character('s'),
                },
                KeyToken {
                    modifiers: vec![Modifier::Alt, Modifier::Shift, Modifier::Meta],
                    base: KeyBase::Character('x'),
                },
            ]
        );
    }

    #[test]
    fn parses_named_keys_and_functions() {
        let tokens =
            parse_keys("{ENTER}{TAB}{ESC}{BACKSPACE}{DELETE}{UP}{PGDN}{F12}").expect("parse");

        assert_eq!(tokens.len(), 8);
        assert_eq!(tokens[0].base, KeyBase::Special(SpecialKey::Enter));
        assert_eq!(tokens[6].base, KeyBase::Special(SpecialKey::PageDown));
        assert_eq!(tokens[7].base, KeyBase::Special(SpecialKey::Function(12)));
    }

    #[test]
    fn a_bare_key_name_is_a_key_press() {
        assert_eq!(
            parse_keys("Enter").expect("parse"),
            vec![KeyToken {
                modifiers: Vec::new(),
                base: KeyBase::Special(SpecialKey::Enter),
            }]
        );
        assert_eq!(
            parse_keys(" esc ").expect("parse"),
            vec![KeyToken {
                modifiers: Vec::new(),
                base: KeyBase::Special(SpecialKey::Escape),
            }]
        );
        assert_eq!(parse_keys("a").expect("parse"), vec![character('a')]);
        assert_eq!(
            parse_keys("Enter the value").expect("parse").len(),
            "Enter the value".chars().count()
        );
    }

    #[test]
    fn parses_named_key_with_modifier() {
        let tokens = parse_keys("^{F5}").expect("parse");

        assert_eq!(
            tokens,
            vec![KeyToken {
                modifiers: vec![Modifier::Ctrl],
                base: KeyBase::Special(SpecialKey::Function(5)),
            }]
        );
    }

    #[test]
    fn braces_allow_literal_punctuation() {
        let tokens = parse_keys("{+}{^}").expect("parse");

        assert_eq!(tokens, vec![character('+'), character('^')]);
    }

    #[test]
    fn rejects_unknown_named_key() {
        let error = parse_keys("{NOPE}").expect_err("must reject");

        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
        assert!(error.message.contains("NOPE"), "{}", error.message);
    }

    #[test]
    fn trailing_modifier_prefix_is_literal_text() {
        let tokens = parse_keys("Hello!").expect("parse");

        assert_eq!(tokens.last(), Some(&character('!')));
        assert_eq!(parse_keys("^").expect("parse"), vec![character('^')]);
        assert_eq!(
            parse_keys("c++").expect("parse"),
            vec![character('c'), character('+'), character('+')]
        );
    }

    #[test]
    fn rejects_unterminated_brace() {
        let error = parse_keys("{ENTER").expect_err("must reject");

        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
        assert!(error.message.contains("unterminated"), "{}", error.message);
    }

    #[test]
    fn rejects_empty_specification() {
        let error = parse_keys("").expect_err("must reject");

        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
    }

    #[test]
    fn control_uppercase_letters_drop_the_implicit_shift() {
        let tokens = parse_keys("^A").expect("parse");

        assert_eq!(effective_key_base(&tokens[0]), KeyBase::Character('a'));
    }

    #[test]
    fn maps_characters_to_keysyms() {
        assert_eq!(char_keysym('a'), Some(0x61));
        assert_eq!(char_keysym('A'), Some(0x41));
        assert_eq!(char_keysym(' '), Some(keysym::SPACE));
        assert_eq!(char_keysym('\n'), Some(keysym::RETURN));
        assert_eq!(char_keysym('\t'), Some(keysym::TAB));
        assert_eq!(char_keysym('é'), Some(0xe9));
        assert_eq!(char_keysym('☃'), Some(0x0100_2603));
        assert_eq!(char_keysym('\u{1}'), None);
    }

    #[test]
    fn missing_display_fails_with_unsupported() {
        let environment = InputEnvironment::current();

        if environment.display.is_some() {
            return;
        }

        let error = X11Input::new().focused_window().expect_err("must fail");

        assert_eq!(error.kind, error_kind::UNSUPPORTED);
        assert!(
            error.message.contains("DISPLAY") || error.message.contains("Wayland"),
            "{}",
            error.message
        );
    }

    #[test]
    fn wayland_coordinate_input_is_refused_explicitly() {
        let environment = InputEnvironment {
            display: Some(":0".to_string()),
            session_type: Some("wayland".to_string()),
            wayland_display: Some("wayland-0".to_string()),
        };
        let error = environment.coordinate_block().expect("must block");

        assert_eq!(error.kind, error_kind::UNSUPPORTED);
        assert!(error.message.contains("Wayland"), "{}", error.message);
    }

    #[test]
    fn wayland_without_display_is_unsupported() {
        let environment = InputEnvironment {
            display: None,
            session_type: Some("wayland".to_string()),
            wayland_display: Some("wayland-0".to_string()),
        };
        let error = environment.hard_block().expect("must block");

        assert_eq!(error.kind, error_kind::UNSUPPORTED);
        assert!(error.message.contains("Wayland"), "{}", error.message);
    }

    #[test]
    #[ignore = "requires a running X11 server"]
    fn queries_a_live_x11_display() {
        let input = X11Input::new();
        let focus = input.focused_window().expect("focused window");

        println!("input focus is {focus}");
        assert!(input.probe_xtest().expect("xtest probe"));
    }

    #[test]
    fn scroll_rejects_unknown_direction() {
        let error = X11Input::new()
            .scroll("sideways", 1)
            .expect_err("must reject");

        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
        assert!(error.message.contains("sideways"), "{}", error.message);
    }
    #[test]
    fn wayland_display_with_xwayland_is_not_native() {
        let environment = InputEnvironment {
            display: Some(":0".to_string()),
            session_type: None,
            wayland_display: Some("wayland-0".to_string()),
        };

        assert!(!environment.wayland());
        assert!(environment.coordinate_block().is_none());
    }
}
