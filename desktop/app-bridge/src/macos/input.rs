//! macOS input posting through `CGEventPostToPid`.
//!
//! Every event goes to exactly one process. Posting does not activate the
//! target; if an app brings itself forward in response to an event, the
//! frontmost guard re-activates the application the user was using.
//!
//! Keys follow the `send-keys`-style syntax used by the CLI:
//!
//! - `^` control, `!` alt, `%` alt (alias), `+` shift, `~` meta (Command).
//! - `{ENTER}`, `{TAB}`, `{ESC}`, `{UP}`, `{DOWN}`, `{LEFT}`, `{RIGHT}`,
//!   `{BACKSPACE}`, `{DELETE}`, `{HOME}`, `{END}`, `{PGUP}`, `{PGDN}`,
//!   `{SPACE}`, and `{F1}`..`{F12}`.
//! - `{CMD}`, `{CTRL}`, `{ALT}`, and `{SHIFT}` as modifiers for the next token,
//!   or combined inside one token as `{CMD+SHIFT+T}`.
//! - Any other character is typed as a unicode keyboard event.
//!
//! Modifier prefixes bind to the single key that follows them, so `^s` is
//! control-s and `^ab` is control-a followed by the text `b`. Literal modifier
//! characters need braces (`{+}`, `{^}`). Modifier keys are represented as event
//! flags rather than synthetic modifier key-down/key-up pairs, which is what
//! per-process posting requires.

use std::os::raw::{c_int, c_ulong};
use std::ptr;
use std::thread::sleep;
use std::time::{Duration, Instant};

use core_foundation::base::CFRelease;
use core_graphics::event::CGEventFlags;
use core_graphics::geometry::CGPoint;
use core_graphics::sys::{CGEventRef, CGEventSourceRef};
use objc2::rc::autoreleasepool;
use objc2_app_kit::{NSApplicationActivationOptions, NSWorkspace};

use crate::protocol::error_kind::INVALID_REQUEST;
use crate::protocol::{ErrorInfo, Point, PointerButton};

const EVENT_TYPE_LEFT_MOUSE_DOWN: u32 = 1;
const EVENT_TYPE_LEFT_MOUSE_UP: u32 = 2;
const EVENT_TYPE_RIGHT_MOUSE_DOWN: u32 = 3;
const EVENT_TYPE_RIGHT_MOUSE_UP: u32 = 4;
const EVENT_TYPE_MOUSE_MOVED: u32 = 5;
const EVENT_TYPE_OTHER_MOUSE_DOWN: u32 = 25;
const EVENT_TYPE_OTHER_MOUSE_UP: u32 = 26;
const MOUSE_BUTTON_LEFT: u32 = 0;
const SCROLL_UNIT_LINE: u32 = 1;

#[allow(non_snake_case)]
#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGEventCreateKeyboardEvent(
        source: CGEventSourceRef,
        keycode: u16,
        keydown: bool,
    ) -> CGEventRef;
    fn CGEventCreateMouseEvent(
        source: CGEventSourceRef,
        mouse_type: u32,
        position: CGPoint,
        mouse_button: u32,
    ) -> CGEventRef;
    fn CGEventCreateScrollWheelEvent2(
        source: CGEventSourceRef,
        units: u32,
        wheel_count: u32,
        wheel1: i32,
        wheel2: i32,
        wheel3: i32,
    ) -> CGEventRef;
    fn CGEventSetFlags(event: CGEventRef, flags: u64);
    fn CGEventSetLocation(event: CGEventRef, location: CGPoint);
    fn CGEventKeyboardSetUnicodeString(event: CGEventRef, length: c_ulong, text: *const u16);
    fn CGEventPostToPid(pid: c_int, event: CGEventRef);
}

/// Post `keys` to `pid`. Returns the number of raw key events posted.
pub fn post_key_events(pid: i32, keys: &str) -> Result<u32, ErrorInfo> {
    if pid <= 0 {
        return Err(ErrorInfo::new(INVALID_REQUEST, "pid must be positive"));
    }

    let steps =
        parse::parse_keys(keys).map_err(|message| ErrorInfo::new(INVALID_REQUEST, message))?;
    if steps.is_empty() {
        return Err(ErrorInfo::new(INVALID_REQUEST, "keys is empty"));
    }

    let mut posted = 0;

    for step in steps {
        match step {
            parse::KeyStep::Key { keycode, modifiers } => {
                post_key(pid, keycode, modifiers)?;
                posted += 2;
            }
            parse::KeyStep::Text { text, modifiers } => {
                post_text(pid, &text, modifiers)?;
                posted += 2;
            }
        }
    }

    Ok(posted)
}

/// Post a click at a global screen point.
pub fn click_at(
    pid: i32,
    x: i32,
    y: i32,
    button: PointerButton,
    count: u32,
) -> Result<u32, ErrorInfo> {
    let point = CGPoint::new(f64::from(x), f64::from(y));
    let (down, up) = mouse_event_types(button);
    let mut posted = 0u32;

    for _ in 0..count.max(1) {
        for mouse_type in [down, up] {
            let event = unsafe {
                CGEventCreateMouseEvent(ptr::null_mut(), mouse_type, point, button.macos_button())
            };
            post_owned(pid, event)?;
            posted += 1;
        }
    }

    Ok(posted)
}

/// Post a pointer move to a global screen point.
pub fn move_to(pid: i32, x: i32, y: i32) -> Result<(), ErrorInfo> {
    let event = unsafe {
        CGEventCreateMouseEvent(
            ptr::null_mut(),
            EVENT_TYPE_MOUSE_MOVED,
            CGPoint::new(f64::from(x), f64::from(y)),
            MOUSE_BUTTON_LEFT,
        )
    };

    post_owned(pid, event)
}

/// Post a press, a stepped move, and a release for a pointer drag.
pub fn drag(
    pid: i32,
    from: Point,
    to: Point,
    button: PointerButton,
    duration_ms: u64,
) -> Result<u32, ErrorInfo> {
    let (down, up) = mouse_event_types(button);
    move_to(pid, from.x, from.y)?;
    let mut posted = 1u32;

    let press = unsafe {
        CGEventCreateMouseEvent(
            ptr::null_mut(),
            down,
            CGPoint::new(f64::from(from.x), f64::from(from.y)),
            button.macos_button(),
        )
    };
    post_owned(pid, press)?;
    posted += 1;

    let steps = (duration_ms / 16).clamp(1, 60);
    let pause = std::time::Duration::from_millis(duration_ms / steps);

    for step in 1..=steps {
        let x =
            i64::from(from.x) + (i64::from(to.x) - i64::from(from.x)) * step as i64 / steps as i64;
        let y =
            i64::from(from.y) + (i64::from(to.y) - i64::from(from.y)) * step as i64 / steps as i64;
        let event = unsafe {
            CGEventCreateMouseEvent(
                ptr::null_mut(),
                EVENT_TYPE_MOUSE_MOVED,
                CGPoint::new(x as f64, y as f64),
                button.macos_button(),
            )
        };
        post_owned(pid, event)?;
        posted += 1;
        std::thread::sleep(pause);
    }

    let release = unsafe {
        CGEventCreateMouseEvent(
            ptr::null_mut(),
            up,
            CGPoint::new(f64::from(to.x), f64::from(to.y)),
            button.macos_button(),
        )
    };
    post_owned(pid, release)?;
    posted += 1;

    Ok(posted)
}

/// Post wheel events at a point. Returns the number of raw events posted.
pub fn scroll_wheel(
    pid: i32,
    x: i32,
    y: i32,
    direction: &str,
    amount: i32,
) -> Result<u32, ErrorInfo> {
    let (vertical, horizontal) = scroll_delta(direction, amount).ok_or_else(|| {
        ErrorInfo::new(
            INVALID_REQUEST,
            format!("scroll direction must be up, down, left, or right, not {direction:?}"),
        )
    })?;

    let event = unsafe {
        CGEventCreateScrollWheelEvent2(
            ptr::null_mut(),
            SCROLL_UNIT_LINE,
            2,
            vertical,
            horizontal,
            0,
        )
    };

    if event.is_null() {
        return Err(ErrorInfo::backend(
            "CGEventCreateScrollWheelEvent2 returned null",
        ));
    }

    unsafe { CGEventSetLocation(event, CGPoint::new(f64::from(x), f64::from(y))) };
    post_owned(pid, event)?;

    Ok(1)
}

/// True when `pid` owns the frontmost application.
pub fn is_target_focused(pid: i32) -> bool {
    frontmost_pid() == Some(pid)
}

/// Re-activate the app the user was using when the target brings itself
/// forward in response to a background action.
pub struct FrontmostGuard {
    previous: Option<i32>,
    target: i32,
    finished: bool,
    restored: bool,
}

impl FrontmostGuard {
    pub fn capture(target: i32) -> Self {
        Self {
            previous: frontmost_pid(),
            target,
            finished: false,
            restored: true,
        }
    }

    pub fn finish(&mut self) -> bool {
        if self.finished {
            return self.restored;
        }

        self.finished = true;
        let Some(previous) = self.previous else {
            return self.restored;
        };

        if previous == self.target || frontmost_pid() != Some(self.target) {
            return self.restored;
        }

        activate_pid(previous);
        let deadline = Instant::now() + Duration::from_millis(300);

        loop {
            if is_target_focused(previous) {
                return self.restored;
            }

            if Instant::now() >= deadline {
                self.restored = false;
                return self.restored;
            }

            sleep(Duration::from_millis(10));
        }
    }
}

impl Drop for FrontmostGuard {
    fn drop(&mut self) {
        self.finish();
    }
}

fn frontmost_pid() -> Option<i32> {
    autoreleasepool(|_pool| {
        NSWorkspace::sharedWorkspace()
            .frontmostApplication()
            .map(|application| application.processIdentifier())
    })
}

fn activate_pid(pid: i32) -> bool {
    autoreleasepool(|_pool| {
        let workspace = NSWorkspace::sharedWorkspace();
        let applications = workspace.runningApplications();

        for application in applications.iter() {
            if application.processIdentifier() == pid && !application.isTerminated() {
                return application.activateWithOptions(NSApplicationActivationOptions::empty());
            }
        }

        false
    })
}

/// Bring `pid` to the front and verify that the activation took effect.
pub fn activate_target(pid: i32) -> bool {
    activate_pid(pid);
    let deadline = Instant::now() + Duration::from_millis(300);

    loop {
        if is_target_focused(pid) {
            return true;
        }

        if Instant::now() >= deadline {
            return false;
        }

        sleep(Duration::from_millis(10));
    }
}

fn post_key(pid: i32, keycode: u16, modifiers: parse::Modifiers) -> Result<(), ErrorInfo> {
    post_keyboard_event(pid, keycode, true, modifiers.flags(), None)?;
    post_keyboard_event(pid, keycode, false, modifiers.flags(), None)
}

fn post_text(pid: i32, text: &str, modifiers: parse::Modifiers) -> Result<(), ErrorInfo> {
    post_keyboard_event(pid, 0, true, modifiers.flags(), Some(text))?;
    post_keyboard_event(pid, 0, false, modifiers.flags(), None)
}

fn post_keyboard_event(
    pid: i32,
    keycode: u16,
    keydown: bool,
    flags: CGEventFlags,
    text: Option<&str>,
) -> Result<(), ErrorInfo> {
    let event = unsafe { CGEventCreateKeyboardEvent(ptr::null_mut(), keycode, keydown) };
    if event.is_null() {
        return Err(ErrorInfo::backend(
            "CGEventCreateKeyboardEvent returned null",
        ));
    }

    unsafe {
        CGEventSetFlags(event, flags.bits());

        if let Some(text) = text {
            let utf16: Vec<u16> = text.encode_utf16().collect();
            CGEventKeyboardSetUnicodeString(event, utf16.len() as c_ulong, utf16.as_ptr());
        }
    }

    post_owned(pid, event)
}

fn post_owned(pid: i32, event: CGEventRef) -> Result<(), ErrorInfo> {
    if event.is_null() {
        return Err(ErrorInfo::backend("CoreGraphics returned a null event"));
    }

    unsafe {
        CGEventPostToPid(pid, event);
        CFRelease(event.cast());
    }

    Ok(())
}

fn mouse_event_types(button: PointerButton) -> (u32, u32) {
    match button {
        PointerButton::Left => (EVENT_TYPE_LEFT_MOUSE_DOWN, EVENT_TYPE_LEFT_MOUSE_UP),
        PointerButton::Right => (EVENT_TYPE_RIGHT_MOUSE_DOWN, EVENT_TYPE_RIGHT_MOUSE_UP),
        PointerButton::Middle => (EVENT_TYPE_OTHER_MOUSE_DOWN, EVENT_TYPE_OTHER_MOUSE_UP),
    }
}

fn scroll_delta(direction: &str, amount: i32) -> Option<(i32, i32)> {
    let magnitude = amount.unsigned_abs().clamp(1, 50) as i32;

    match direction.trim().to_ascii_lowercase().as_str() {
        "up" => Some((magnitude, 0)),
        "down" => Some((-magnitude, 0)),
        "left" => Some((0, magnitude)),
        "right" => Some((0, -magnitude)),
        _ => None,
    }
}

/// Pure parser for the keystroke specification. No platform calls live here,
/// which keeps the syntax unit-testable without posting events.
pub mod parse {
    use core_graphics::event::CGEventFlags;

    #[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
    pub struct Modifiers {
        pub command: bool,
        pub control: bool,
        pub alt: bool,
        pub shift: bool,
    }

    impl Modifiers {
        /// CoreGraphics flag bits for the active modifiers.
        pub fn flags(self) -> CGEventFlags {
            let mut flags = CGEventFlags::CGEventFlagNull;

            if self.command {
                flags |= CGEventFlags::CGEventFlagCommand;
            }

            if self.control {
                flags |= CGEventFlags::CGEventFlagControl;
            }

            if self.alt {
                flags |= CGEventFlags::CGEventFlagAlternate;
            }

            if self.shift {
                flags |= CGEventFlags::CGEventFlagShift;
            }

            flags
        }
    }

    #[derive(Debug, Clone, PartialEq, Eq)]
    pub enum KeyStep {
        Key { keycode: u16, modifiers: Modifiers },
        Text { text: String, modifiers: Modifiers },
    }

    /// Parse a keystroke specification into ordered steps.
    pub fn parse_keys(spec: &str) -> Result<Vec<KeyStep>, String> {
        let characters: Vec<char> = spec.chars().collect();
        let mut steps = Vec::new();
        let mut modifiers = Modifiers::default();
        let mut index = 0;

        while index < characters.len() {
            match characters[index] {
                '^' => {
                    modifiers.control = true;
                    index += 1;
                }
                '!' => {
                    modifiers.alt = true;
                    index += 1;
                }
                '%' => {
                    modifiers.alt = true;
                    index += 1;
                }
                '+' => {
                    modifiers.shift = true;
                    index += 1;
                }
                '~' => {
                    modifiers.command = true;
                    index += 1;
                }
                '{' => {
                    let (token, next) = read_braced(&characters, index)?;
                    index = next;

                    if apply_braced_token(&token, &mut modifiers, &mut steps)? {
                        modifiers = Modifiers::default();
                    }
                }
                character => {
                    steps.push(character_step(character, modifiers));
                    modifiers = Modifiers::default();
                    index += 1;
                }
            }
        }

        if modifiers != Modifiers::default() {
            return Err("a modifier prefix has no key; add the key it applies to".to_string());
        }

        Ok(steps)
    }

    /// Handle one `{...}` token. Returns true when the token produced a key and
    /// the pending modifiers should be cleared.
    fn apply_braced_token(
        token: &str,
        modifiers: &mut Modifiers,
        steps: &mut Vec<KeyStep>,
    ) -> Result<bool, String> {
        if token.is_empty() {
            return Err("empty {} key name".to_string());
        }

        if !token.contains('+') || token == "+" {
            if let Some(modifier) = modifier_for(token) {
                *modifiers = merge(*modifiers, modifier);
                return Ok(false);
            }

            steps.push(named_step(token, *modifiers)?);
            return Ok(true);
        }

        let segments: Vec<&str> = token.split('+').collect();
        if segments.iter().any(|segment| segment.is_empty()) {
            return Err(format!("malformed key combination {{{token}}}"));
        }

        let (base, modifier_names) = segments.split_last().expect("split_last on non-empty");
        for name in modifier_names {
            let modifier = modifier_for(name)
                .ok_or_else(|| format!("{name:?} is not a modifier in {{{token}}}"))?;
            *modifiers = merge(*modifiers, modifier);
        }

        steps.push(named_step(base, *modifiers)?);

        Ok(true)
    }

    fn named_step(name: &str, modifiers: Modifiers) -> Result<KeyStep, String> {
        if let Some(keycode) = keycode_for_name(name) {
            return Ok(KeyStep::Key { keycode, modifiers });
        }

        let mut characters = name.chars();
        if let (Some(character), None) = (characters.next(), characters.next()) {
            return Ok(character_step(character, modifiers));
        }

        Err(format!(
            "unknown key name {{{name}}}; use a documented name or a single character"
        ))
    }

    fn character_step(character: char, modifiers: Modifiers) -> KeyStep {
        match keycode_for_char(character) {
            Some(keycode) if modifiers != Modifiers::default() => {
                KeyStep::Key { keycode, modifiers }
            }
            _ => KeyStep::Text {
                text: character.to_string(),
                modifiers,
            },
        }
    }

    fn read_braced(characters: &[char], start: usize) -> Result<(String, usize), String> {
        let mut token = String::new();
        let mut index = start + 1;

        while index < characters.len() {
            if characters[index] == '}' {
                return Ok((token, index + 1));
            }

            token.push(characters[index]);
            index += 1;
        }

        Err("unterminated { in the key spec".to_string())
    }

    fn merge(base: Modifiers, extra: Modifiers) -> Modifiers {
        Modifiers {
            command: base.command || extra.command,
            control: base.control || extra.control,
            alt: base.alt || extra.alt,
            shift: base.shift || extra.shift,
        }
    }

    fn modifier_for(name: &str) -> Option<Modifiers> {
        match name.trim().to_ascii_uppercase().as_str() {
            "CMD" | "COMMAND" | "META" | "SUPER" | "WIN" => Some(Modifiers {
                command: true,
                ..Default::default()
            }),
            "CTRL" | "CONTROL" => Some(Modifiers {
                control: true,
                ..Default::default()
            }),
            "ALT" | "OPTION" | "OPT" => Some(Modifiers {
                alt: true,
                ..Default::default()
            }),
            "SHIFT" => Some(Modifiers {
                shift: true,
                ..Default::default()
            }),
            _ => None,
        }
    }

    /// ANSI US keycodes for named keys. Layout-dependent keys are intentionally
    /// absent; those characters fall back to unicode text events.
    fn keycode_for_name(name: &str) -> Option<u16> {
        match name.trim().to_ascii_uppercase().as_str() {
            "ENTER" | "RETURN" => Some(0x24),
            "TAB" => Some(0x30),
            "SPACE" => Some(0x31),
            "BACKSPACE" | "BS" => Some(0x33),
            "ESC" | "ESCAPE" => Some(0x35),
            "DELETE" | "DEL" | "FORWARDDELETE" => Some(0x75),
            "UP" | "UPARROW" => Some(0x7E),
            "DOWN" | "DOWNARROW" => Some(0x7D),
            "LEFT" | "LEFTARROW" => Some(0x7B),
            "RIGHT" | "RIGHTARROW" => Some(0x7C),
            "HOME" => Some(0x73),
            "END" => Some(0x77),
            "PGUP" | "PAGEUP" => Some(0x74),
            "PGDN" | "PAGEDOWN" => Some(0x79),
            "F1" => Some(0x7A),
            "F2" => Some(0x78),
            "F3" => Some(0x63),
            "F4" => Some(0x76),
            "F5" => Some(0x60),
            "F6" => Some(0x61),
            "F7" => Some(0x62),
            "F8" => Some(0x64),
            "F9" => Some(0x65),
            "F10" => Some(0x6D),
            "F11" => Some(0x67),
            "F12" => Some(0x6F),
            _ => None,
        }
    }

    fn keycode_for_char(character: char) -> Option<u16> {
        match character.to_ascii_lowercase() {
            'a' => Some(0x00),
            's' => Some(0x01),
            'd' => Some(0x02),
            'f' => Some(0x03),
            'h' => Some(0x04),
            'g' => Some(0x05),
            'z' => Some(0x06),
            'x' => Some(0x07),
            'c' => Some(0x08),
            'v' => Some(0x09),
            'b' => Some(0x0B),
            'q' => Some(0x0C),
            'w' => Some(0x0D),
            'e' => Some(0x0E),
            'r' => Some(0x0F),
            'y' => Some(0x10),
            't' => Some(0x11),
            '1' => Some(0x12),
            '2' => Some(0x13),
            '3' => Some(0x14),
            '4' => Some(0x15),
            '6' => Some(0x16),
            '5' => Some(0x17),
            '=' => Some(0x18),
            '9' => Some(0x19),
            '7' => Some(0x1A),
            '-' => Some(0x1B),
            '8' => Some(0x1C),
            '0' => Some(0x1D),
            ']' => Some(0x1E),
            'o' => Some(0x1F),
            'u' => Some(0x20),
            '[' => Some(0x21),
            'i' => Some(0x22),
            'p' => Some(0x23),
            'l' => Some(0x25),
            'j' => Some(0x26),
            '\'' => Some(0x27),
            'k' => Some(0x28),
            ';' => Some(0x29),
            '\\' => Some(0x2A),
            ',' => Some(0x2B),
            '/' => Some(0x2C),
            'n' => Some(0x2D),
            'm' => Some(0x2E),
            '.' => Some(0x2F),
            '`' => Some(0x32),
            ' ' => Some(0x31),
            _ => None,
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        fn key(keycode: u16, modifiers: Modifiers) -> KeyStep {
            KeyStep::Key { keycode, modifiers }
        }

        fn text(text: &str) -> KeyStep {
            KeyStep::Text {
                text: text.to_string(),
                modifiers: Modifiers::default(),
            }
        }

        #[test]
        fn control_prefix_binds_to_one_key() {
            assert_eq!(
                parse_keys("^s").unwrap(),
                vec![key(
                    0x01,
                    Modifiers {
                        control: true,
                        ..Default::default()
                    }
                )]
            );
            assert_eq!(
                parse_keys("^ab").unwrap(),
                vec![
                    key(
                        0x00,
                        Modifiers {
                            control: true,
                            ..Default::default()
                        }
                    ),
                    text("b"),
                ]
            );
        }

        #[test]
        fn modifier_aliases_map_to_flags() {
            for spec in ["!x", "%x"] {
                assert_eq!(
                    parse_keys(spec).unwrap(),
                    vec![key(
                        0x07,
                        Modifiers {
                            alt: true,
                            ..Default::default()
                        }
                    )],
                    "{spec}"
                );
            }

            assert_eq!(
                parse_keys("~q").unwrap(),
                vec![key(
                    0x0C,
                    Modifiers {
                        command: true,
                        ..Default::default()
                    }
                )],
                "meta is Command on macOS"
            );
            assert_eq!(
                parse_keys("+{TAB}").unwrap(),
                vec![key(
                    0x30,
                    Modifiers {
                        shift: true,
                        ..Default::default()
                    }
                )],
                "shift plus a named key"
            );
        }

        #[test]
        fn named_keys_cover_the_documented_set() {
            let cases = [
                ("{ENTER}", 0x24),
                ("{TAB}", 0x30),
                ("{ESC}", 0x35),
                ("{UP}", 0x7E),
                ("{DOWN}", 0x7D),
                ("{LEFT}", 0x7B),
                ("{RIGHT}", 0x7C),
                ("{BACKSPACE}", 0x33),
                ("{DELETE}", 0x75),
                ("{HOME}", 0x73),
                ("{END}", 0x77),
                ("{PGUP}", 0x74),
                ("{PGDN}", 0x79),
                ("{F1}", 0x7A),
                ("{F12}", 0x6F),
            ];

            for (spec, keycode) in cases {
                assert_eq!(
                    parse_keys(spec).unwrap(),
                    vec![key(keycode, Modifiers::default())],
                    "{spec}"
                );
            }
        }

        #[test]
        fn braced_modifiers_combine_with_the_next_key() {
            let expected = vec![key(
                0x11,
                Modifiers {
                    command: true,
                    shift: true,
                    ..Default::default()
                },
            )];

            assert_eq!(parse_keys("{CMD}{SHIFT}t").unwrap(), expected);
            assert_eq!(parse_keys("{CMD+SHIFT+T}").unwrap(), expected);
        }

        #[test]
        fn literal_text_is_one_step_per_character() {
            assert_eq!(parse_keys("hi").unwrap(), vec![text("h"), text("i")]);
        }

        #[test]
        fn shifted_letters_use_the_shift_flag() {
            assert_eq!(
                parse_keys("+a").unwrap(),
                vec![key(
                    0x00,
                    Modifiers {
                        shift: true,
                        ..Default::default()
                    }
                )]
            );
        }

        #[test]
        fn modifier_without_a_key_is_invalid() {
            for spec in ["^", "^!", "{CMD}", "{CTRL}", "{SHIFT}"] {
                assert!(parse_keys(spec).is_err(), "{spec}");
            }
        }

        #[test]
        fn malformed_braces_are_invalid() {
            for spec in ["{ENTER", "{}", "{CMD+}", "{+T}", "{NOPE}"] {
                assert!(parse_keys(spec).is_err(), "{spec}");
            }
        }

        #[test]
        fn literal_modifier_characters_need_braces() {
            assert_eq!(parse_keys("{+}").unwrap(), vec![text("+")]);
            assert_eq!(parse_keys("{^}").unwrap(), vec![text("^")]);
        }

        #[test]
        fn unknown_unicode_characters_become_text_events() {
            assert_eq!(parse_keys("é").unwrap(), vec![text("é")]);
        }
    }
}
