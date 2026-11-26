//! Linux backend: AT-SPI observation and semantic actions plus XTEST input.
//!
//! AT-SPI stays the semantic backend (`focus`, `invoke`, `get_value`,
//! `set_value`, and target-less clicks). Seat-global input (`keys`, `scroll`,
//! and a `click` with an explicit point) is routed to [`X11Input`], which
//! refuses to inject into an unfocused window. The backend raises the target
//! for the send and restores the previously active window afterwards, unless
//! the caller asked for `activate` or `focus`. X11 connections are opened on
//! demand by the input driver, never by [`LinuxBackend::new`].

mod atspi_backend;
mod input;

use std::sync::{Mutex, MutexGuard};

use crate::protocol::{
    error_kind, outcome, ActionRequest, ActionResult, CheckResult, DoctorReport, ErrorInfo, Health,
    PointerButton, ScreenshotRequest, Snapshot, SnapshotRequest, WindowInfo,
};
use crate::Backend;

pub use atspi_backend::AtspiBackend;
pub use input::{InputEnvironment, X11Input, XTEST_CAPABILITY};

/// Default number of wheel notches when a scroll request omits `amount`.
const DEFAULT_SCROLL_NOTCHES: i32 = 3;

/// Linux backend handle.
#[derive(Debug)]
pub struct LinuxBackend {
    inner: AtspiBackend,
    input: Mutex<Option<X11Input>>,
}

impl LinuxBackend {
    /// Create a backend bound to this process without touching X11.
    pub fn new() -> Self {
        Self {
            inner: AtspiBackend::new(),
            input: Mutex::new(None),
        }
    }
}

impl Default for LinuxBackend {
    fn default() -> Self {
        Self::new()
    }
}

impl Backend for LinuxBackend {
    fn name(&self) -> &'static str {
        self.inner.name()
    }

    fn platform(&self) -> &'static str {
        self.inner.platform()
    }

    fn capabilities(&self) -> Vec<String> {
        let mut capabilities = self.inner.capabilities();
        let environment = InputEnvironment::current();

        if environment.xtest_capable() {
            capabilities.push(XTEST_CAPABILITY.to_string());
        }

        if environment.display.is_some() {
            capabilities.push("screenshot".to_string());
        }

        capabilities
    }

    fn health(&self) -> Health {
        self.inner.health()
    }

    fn doctor(&self) -> DoctorReport {
        let mut report = self.inner.doctor();
        let environment = InputEnvironment::current();
        let wayland = environment.wayland();

        let display_detail = match &environment.display {
            Some(display) if environment.wayland_display.is_some() => {
                format!("{display} (Xwayland; input reaches X11 clients only)")
            }
            Some(display) => format!("{display} (X11)"),
            None => "DISPLAY is unset; X11 input needs an Xorg or Xwayland display".to_string(),
        };
        report.checks.push(CheckResult::new(
            "x11_display",
            environment.display.is_some(),
            display_detail,
        ));

        let wayland_detail = if wayland {
            "Wayland session: keyboard input is deferred and coordinate input is unsupported"
        } else {
            "X11 session; XTEST input is seat-global and requires a focused target"
        };
        report
            .checks
            .push(CheckResult::new("wayland", !wayland, wayland_detail));

        let (xtest_ok, xtest_detail) = match environment.hard_block() {
            Some(error) => (false, error.message),
            None => match self.with_input(|input| input.probe_xtest()) {
                Ok(true) => (true, "XTEST 2.x extension available".to_string()),
                Ok(false) => (
                    false,
                    "the X server reports XTEST older than 2.0".to_string(),
                ),
                Err(error) => (false, error.message),
            },
        };
        report
            .checks
            .push(CheckResult::new("xtest", xtest_ok, xtest_detail));

        if wayland {
            report.notes.push(
                "Wayland input is seat-global and portal-gated; XTEST cannot move the native Wayland pointer"
                    .to_string(),
            );
        }

        report
    }

    fn windows(&self) -> Result<Vec<WindowInfo>, ErrorInfo> {
        self.inner.windows()
    }

    fn snapshot(&self, request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo> {
        self.inner.snapshot(request)
    }

    fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let action = request.action.as_str();
        let explicit = matches!(action, "activate" | "focus");
        let foreground = request.args.delivery_mode.is_foreground();
        let mut front_failed = false;

        if foreground && !explicit {
            let target = self.focus_target(&request.window);
            front_failed = self.ensure_active(&request.window, &target).is_err();
        }

        let background = if explicit || foreground {
            None
        } else {
            Some(ActiveGuard::capture(self, &request.window))
        };

        let mut result = match action {
            "activate" => self.activate_action(request),
            "focus" => self.focus_action(request),
            "keys" => self.keys_action(request),
            "scroll" => self.scroll_action(request),
            "click" | "double_click" | "right_click" | "hover" | "drag"
                if request.args.point.is_some() =>
            {
                self.pointer_action(request)
            }
            "double_click" | "right_click" | "hover" => Err(ErrorInfo::new(
                error_kind::UNSUPPORTED,
                "linux pointer-only actions need args.point; pass the element center as args.point to use XTEST",
            )),
            "drag" => Err(ErrorInfo::new(
                error_kind::UNSUPPORTED,
                "linux drag needs args.point and args.to_point; pass coordinates to use XTEST",
            )),
            _ => self.inner.action(request),
        };

        if foreground && !explicit && front_failed {
            if let Ok(action_result) = result.as_mut() {
                append_note(
                    action_result,
                    "could not bring the target window to the front",
                );
            }
        }

        if let Some(mut guard) = background {
            if !guard.finish() {
                if let Ok(action_result) = result.as_mut() {
                    append_note(
                        action_result,
                        "the previous active window could not be restored",
                    );
                }
            }
        }

        result
    }

    fn screenshot(&self, request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
        self.capture_screenshot(request)
    }
}

impl LinuxBackend {
    fn keys_action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let keys = request.args.keys.as_deref().ok_or_else(|| {
            ErrorInfo::invalid("keys requires args.keys with a tmux-style key specification")
        })?;
        let target = self.focus_target(&request.window);
        self.ensure_active(&request.window, &target)?;
        let events = self.with_input(|input| input.send_keys(keys))?;

        Ok(input_result(
            "keys",
            outcome::KEYSTROKE,
            events,
            format!("sent {events} XTEST key events to '{}'", request.window),
        ))
    }

    fn scroll_action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let direction = request.args.direction.as_deref().ok_or_else(|| {
            ErrorInfo::invalid("scroll requires args.direction (up, down, left, or right)")
        })?;
        let amount = request.args.amount.unwrap_or(DEFAULT_SCROLL_NOTCHES);
        let target = self.focus_target(&request.window);
        self.ensure_active(&request.window, &target)?;
        let events = self.with_input(|input| {
            input.ensure_coordinate_supported()?;
            input.scroll(direction, amount)
        })?;

        Ok(input_result(
            "scroll",
            outcome::POINTER,
            events,
            format!("sent {events} XTEST wheel events to '{}'", request.window),
        ))
    }

    fn pointer_action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let point = request.args.point.as_ref().ok_or_else(|| {
            ErrorInfo::invalid("pointer actions require args.point for coordinate input")
        })?;
        let default_button = match request.action.as_str() {
            "right_click" => PointerButton::Right,
            _ => PointerButton::Left,
        };
        let button = match request
            .args
            .button
            .as_deref()
            .map(str::trim)
            .filter(|name| !name.is_empty())
        {
            Some(_) => request.args.pointer_button()?,
            None => default_button,
        };
        let default_count = if request.action == "double_click" {
            2
        } else {
            1
        };
        let count = request.args.click_count(default_count);
        let inside = self
            .inner
            .windows()
            .ok()
            .and_then(|windows| select_window(&windows, &request.window).cloned())
            .map(|window| {
                let bounds = window.bounds;
                point.x >= bounds.left
                    && point.x < bounds.left + bounds.width
                    && point.y >= bounds.top
                    && point.y < bounds.top + bounds.height
            })
            .unwrap_or(false);

        let events = self.with_input(|input| {
            input.ensure_coordinate_supported()?;
            // A coordinate click is how a user focuses a window; requiring focus
            // first would deadlock any caller that needs to raise the target.
            match request.action.as_str() {
                "hover" => input.move_to(point.x, point.y),
                "drag" => {
                    let to = request.args.to_point.ok_or_else(|| {
                        ErrorInfo::new(
                            error_kind::UNSUPPORTED,
                            "linux drag needs args.to_point; pass a destination to use XTEST",
                        )
                    })?;
                    input.drag(*point, to, button, request.args.drag_duration())
                }
                _ => input.click_at(point.x, point.y, button, count),
            }
        })?;
        let message = match (request.action.as_str(), inside) {
            ("hover", _) => format!("moved the pointer to ({}, {})", point.x, point.y),
            ("drag", _) => format!(
                "dragged {} from ({}, {}) to ({}, {})",
                button.as_str(),
                point.x,
                point.y,
                request.args.to_point.map(|to| to.x).unwrap_or_default(),
                request.args.to_point.map(|to| to.y).unwrap_or_default()
            ),
            ("click", true) | ("double_click", true) | ("right_click", true) => format!(
                "posted {count} {} click(s) at ({}, {}) with XTEST on '{}'",
                button.as_str(),
                point.x,
                point.y,
                request.window
            ),
            ("click", false) | ("double_click", false) | ("right_click", false) => format!(
                "clicked ({}, {}) with XTEST, but that point is outside '{}'; XTEST clicks land wherever the pointer is",
                point.x, point.y, request.window
            ),
            _ => format!("sent {events} XTEST pointer events"),
        };

        Ok(input_result(
            request.action.as_str(),
            outcome::POINTER,
            events,
            message,
        ))
    }

    fn capture_screenshot(&self, request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
        let windows = self.inner.windows()?;
        let window = select_window(&windows, &request.window)
            .cloned()
            .ok_or_else(|| {
                ErrorInfo::new(
                    error_kind::TARGET_NOT_FOUND,
                    format!("no window matches '{}'", request.window),
                )
            })?;
        let bounds = window.bounds;

        if bounds.width <= 0 || bounds.height <= 0 {
            return Err(ErrorInfo::new(
                error_kind::CAPTURE_EXCLUDED,
                "window has no drawable area",
            ));
        }

        let region = || {
            (
                bounds.left as i16,
                bounds.top as i16,
                bounds.width as u16,
                bounds.height as u16,
            )
        };
        let (width, height, rgb) = self.with_input(|input| {
            let resolved = input.resolve_window(Some(window.pid), Some(window.title.as_str()))?;

            // WSLg's Xwayland refuses GetImage on the root window, so capture the
            // window drawable itself and fall back to the screen region.
            match resolved {
                Some(id) => input
                    .capture_window(id, bounds.width as u16, bounds.height as u16)
                    .or_else(|_| {
                        let (x, y, w, h) = region();
                        input.capture_region(x, y, w, h)
                    }),
                None => {
                    let (x, y, w, h) = region();
                    input.capture_region(x, y, w, h)
                }
            }
        })?;

        encode_png(width, height, &rgb)
    }

    fn activate_action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let target = self.focus_target(&request.window);
        self.ensure_active(&request.window, &target)?;

        Ok(ActionResult {
            action: "activate".to_string(),
            delivered: true,
            verified: self
                .with_input(|input| ensure_focused(input, &request.window, &target))
                .is_ok(),
            uncertain: false,
            value: None,
            message: Some(format!("activated '{}'", request.window)),
            outcome: Some(outcome::NONE.to_string()),
        })
    }

    /// Focus an element, raising its window first when AT-SPI refuses.
    fn focus_action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        match self.inner.action(request) {
            Ok(result) => Ok(self.confirm_focus(result, &request.window)),
            Err(error) if error.kind == error_kind::INPUT_BLOCKED => {
                let target = self.focus_target(&request.window);
                self.ensure_active(&request.window, &target)?;

                self.inner
                    .action(request)
                    .map(|result| self.confirm_focus(result, &request.window))
                    .map_err(|_| {
                    ErrorInfo::new(
                        error_kind::INPUT_BLOCKED,
                        format!(
                            "'{}' exposes no usable focus action even after the window was raised; click its bounds with --x/--y, or send keys to the window",
                            request.window
                        ),
                    )
                })
            }
            Err(error) => Err(error),
        }
    }

    /// Downgrade an AT-SPI focus claim when X input focus sits elsewhere.
    fn confirm_focus(&self, mut result: ActionResult, window: &str) -> ActionResult {
        if !result.delivered {
            return result;
        }

        let target = self.focus_target(window);
        let focused = self
            .with_input(|input| ensure_focused(input, window, &target))
            .is_ok();

        result.verified = focused;

        if !focused {
            result.message = Some(
                "AT-SPI accepted the focus request, but no X window holds input focus; keys and scroll stay refused until the window is raised".to_string(),
            );
        }

        result
    }

    /// Focus the window, activating it first when the seat focus is elsewhere.
    fn ensure_active(&self, window: &str, target: &FocusTarget) -> Result<(), ErrorInfo> {
        if self
            .with_input(|input| ensure_focused(input, window, target))
            .is_ok()
        {
            return Ok(());
        }

        self.with_input(|input| {
            let id = match target {
                FocusTarget::Resolved { pid, title } => {
                    input.resolve_window(if *pid > 0 { Some(*pid) } else { None }, Some(title))?
                }
                FocusTarget::Handle(handle) => input.resolve_window(None, Some(handle))?,
            };

            match id {
                Some(id) => input.activate_window(id),
                None => Err(ErrorInfo::new(
                    error_kind::TARGET_NOT_FOUND,
                    format!("no X11 window matches '{window}'"),
                )),
            }
        })?;

        self.with_input(|input| ensure_focused(input, window, target))
    }

    fn with_input<T>(
        &self,
        operation: impl FnOnce(&X11Input) -> Result<T, ErrorInfo>,
    ) -> Result<T, ErrorInfo> {
        let mut slot = lock(&self.input);
        let input = slot.get_or_insert_with(X11Input::new);

        operation(input)
    }

    fn focus_target(&self, window: &str) -> FocusTarget {
        if looks_like_window_id(window) || !looks_like_atspi_handle(window) {
            return FocusTarget::Handle(window.to_string());
        }

        let Some(info) = self
            .inner
            .windows()
            .ok()
            .and_then(|windows| select_window(&windows, window).cloned())
        else {
            return FocusTarget::Handle(window.to_string());
        };

        FocusTarget::Resolved {
            pid: info.pid,
            title: info.title,
        }
    }
}

enum FocusTarget {
    Handle(String),
    Resolved { pid: u32, title: String },
}

fn ensure_focused(input: &X11Input, window: &str, target: &FocusTarget) -> Result<(), ErrorInfo> {
    let focused = match target {
        FocusTarget::Handle(handle) => input.is_window_focused(handle)?,
        FocusTarget::Resolved { pid, title } => {
            let resolved = if *pid > 0 {
                input.resolve_window(Some(*pid), Some(title))?
            } else {
                input.resolve_window(None, Some(title))?
            };

            match resolved {
                Some(window) => input.is_window_focused(&format!("0x{window:x}"))?,
                None => input.is_window_focused(title)?,
            }
        }
    };

    if focused {
        return Ok(());
    }

    let state = input.focus_state();
    Err(ErrorInfo::new(
        error_kind::INPUT_BLOCKED,
        format!(
            "target window '{window}' is not focused ({state}): X11 input is seat-global. Raise the window (taskbar or Alt+Tab; under WSLg the compositor owns focus) or target an element with `focus`, then retry"
        ),
    ))
}

/// Restore the user's active X11 window after a background-intent action.
struct ActiveGuard<'a> {
    backend: &'a LinuxBackend,
    window: String,
    previous: Option<u32>,
    finished: bool,
    restored: bool,
}

impl<'a> ActiveGuard<'a> {
    fn capture(backend: &'a LinuxBackend, window: &str) -> Self {
        let previous = backend
            .with_input(|input| input.active_window())
            .ok()
            .flatten();

        Self {
            backend,
            window: window.to_string(),
            previous,
            finished: false,
            restored: true,
        }
    }

    fn finish(&mut self) -> bool {
        if self.finished {
            return self.restored;
        }

        self.finished = true;
        let Some(previous) = self.previous else {
            return self.restored;
        };

        if !self
            .backend
            .with_input(|input| input.is_window_focused(&self.window))
            .unwrap_or(false)
        {
            return self.restored;
        }

        if self
            .backend
            .with_input(|input| input.is_window_id_focused(previous))
            .unwrap_or(false)
        {
            return self.restored;
        }

        self.restored = self
            .backend
            .with_input(|input| input.activate_window(previous))
            .and_then(|()| {
                self.backend
                    .with_input(|input| input.is_window_id_focused(previous))
            })
            .unwrap_or(false);
        self.restored
    }
}

impl Drop for ActiveGuard<'_> {
    fn drop(&mut self) {
        self.finish();
    }
}

fn append_note(result: &mut ActionResult, note: &str) {
    match result.message.as_mut() {
        Some(message) => {
            message.push_str("; ");
            message.push_str(note);
        }
        None => result.message = Some(note.to_string()),
    }
}

fn input_result(action: &str, outcome: &str, events: u32, message: String) -> ActionResult {
    ActionResult {
        action: action.to_string(),
        delivered: true,
        verified: false,
        uncertain: false,
        value: Some(events.to_string()),
        message: Some(message),
        outcome: Some(outcome.to_string()),
    }
}

fn select_window<'a>(windows: &'a [WindowInfo], query: &str) -> Option<&'a WindowInfo> {
    let normalized = query.trim().to_lowercase();

    if let Some(window) = windows.iter().find(|window| window.handle == query) {
        return Some(window);
    }

    if let Some(window) = windows
        .iter()
        .find(|window| window.title.eq_ignore_ascii_case(query))
    {
        return Some(window);
    }

    windows.iter().find(|window| {
        window.handle.to_lowercase().contains(&normalized)
            || window.title.to_lowercase().contains(&normalized)
            || window
                .process_name
                .as_deref()
                .map(|name| name.to_lowercase().contains(&normalized))
                .unwrap_or(false)
    })
}

fn looks_like_window_id(value: &str) -> bool {
    let value = value.trim();

    if let Some(hex) = value
        .strip_prefix("0x")
        .or_else(|| value.strip_prefix("0X"))
    {
        return u32::from_str_radix(hex, 16).is_ok();
    }

    !value.is_empty() && value.chars().all(|character| character.is_ascii_digit())
}

fn looks_like_atspi_handle(value: &str) -> bool {
    value.starts_with('/') || value.contains("atspi")
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    match mutex.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    }
}

/// Encode tightly packed RGB bytes as a PNG.
fn encode_png(width: u16, height: u16, rgb: &[u8]) -> Result<Vec<u8>, ErrorInfo> {
    let mut out = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut out, width as u32, height as u32);
        encoder.set_color(png::ColorType::Rgb);
        encoder.set_depth(png::BitDepth::Eight);
        let mut writer = encoder
            .write_header()
            .map_err(|error| ErrorInfo::backend(format!("PNG header failed: {error}")))?;
        writer
            .write_image_data(rgb)
            .map_err(|error| ErrorInfo::backend(format!("PNG encode failed: {error}")))?;
    }
    Ok(out)
}
