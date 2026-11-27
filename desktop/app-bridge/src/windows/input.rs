//! Windows synthetic input owned by T8: keys, coordinate clicks, focus, scroll.
//!
//! The module is split in two so the keystroke grammar can be compiled and
//! tested without the Windows SDK:
//!
//! - [`parse`] is platform-free. It turns a tmux-style specification such as
//!   `^s`, `Hello`, or `{CTRL+SHIFT+T}` into ordered key steps.
//! - `platform` performs the Win32 calls and is compiled only on Windows.
//!
//! On a non-Windows host the parser still builds on its own:
//!
//! ```text
//! rustc --edition 2021 --test desktop/app-bridge/src/windows/input.rs -o /tmp/input-tests
//! ```
//!
//! Behavior rules:
//!
//! - the target window is resolved and integrity-checked for every action;
//! - `SetForegroundWindow` runs before input and must take effect within 300 ms;
//! - identity (`is_same_window`) is re-checked immediately before `SendInput`;
//! - `SetCursorPos` is only used for an explicit coordinate click;
//! - implicit actions restore the previous foreground window and pointer;
//!   `activate` and `focus` are explicit foreground intents and do not restore;
//! - password elements never receive `keys`, and disabled targets are refused.

/// Pure parser for the keystroke specification shared with the macOS and Linux
/// backends. It makes no platform calls, so it is unit-testable anywhere.
pub mod parse {
    /// Virtual-key codes for the named keys accepted by [`super::parse::parse_keys`].
    pub mod vk {
        pub const BACKSPACE: u16 = 0x08;
        pub const TAB: u16 = 0x09;
        pub const ENTER: u16 = 0x0D;
        pub const SHIFT: u16 = 0x10;
        pub const CONTROL: u16 = 0x11;
        pub const ALT: u16 = 0x12;
        pub const ESC: u16 = 0x1B;
        pub const SPACE: u16 = 0x20;
        pub const PGUP: u16 = 0x21;
        pub const PGDN: u16 = 0x22;
        pub const END: u16 = 0x23;
        pub const HOME: u16 = 0x24;
        pub const LEFT: u16 = 0x25;
        pub const UP: u16 = 0x26;
        pub const RIGHT: u16 = 0x27;
        pub const DOWN: u16 = 0x28;
        pub const DELETE: u16 = 0x2E;
        pub const WIN: u16 = 0x5B;
        pub const F1: u16 = 0x70;

        /// Virtual key for `{F1}` through `{F12}`.
        pub fn function(number: u8) -> Option<u16> {
            if (1..=12).contains(&number) {
                Some(F1 + u16::from(number) - 1)
            } else {
                None
            }
        }
    }

    /// Modifier flags attached to one step.
    #[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
    pub struct Modifiers {
        pub control: bool,
        pub alt: bool,
        pub shift: bool,
        pub win: bool,
    }

    impl Modifiers {
        /// True when no modifier is pending.
        pub fn is_empty(self) -> bool {
            !self.control && !self.alt && !self.shift && !self.win
        }

        /// Ctrl, Alt, and Win make Windows ignore an unshifted letter's case.
        pub fn accelerated(self) -> bool {
            self.control || self.alt || self.win
        }

        fn merge(self, extra: Self) -> Self {
            Self {
                control: self.control || extra.control,
                alt: self.alt || extra.alt,
                shift: self.shift || extra.shift,
                win: self.win || extra.win,
            }
        }
    }

    /// The key a step taps after its modifiers are held.
    #[derive(Debug, Clone, PartialEq, Eq)]
    pub enum KeyBase {
        /// A named key with a stable virtual-key code.
        Virtual(u16),
        /// Committed literal text; the caller picks scan code or unicode.
        Character(char),
    }

    /// One modifier set plus the key it applies to.
    #[derive(Debug, Clone, PartialEq, Eq)]
    pub struct KeyStep {
        pub modifiers: Modifiers,
        pub base: KeyBase,
    }

    /// Parse a keystroke specification into ordered steps.
    ///
    /// Grammar matches the macOS and Linux backends: `^` ctrl, `!` alt, `+`
    /// shift, `~` meta/Win, and `{NAME}` for named keys and braced literals.
    pub fn parse_keys(spec: &str) -> Result<Vec<KeyStep>, String> {
        let characters: Vec<char> = spec.chars().collect();

        if characters.is_empty() {
            return Err(
                "keys is empty; pass a specification such as '^s', 'Hello', or '{ENTER}'"
                    .to_string(),
            );
        }

        let mut steps = Vec::new();
        let mut modifiers = Modifiers::default();
        let mut index = 0usize;

        while let Some(character) = characters.get(index).copied() {
            match character {
                '^' => {
                    modifiers.control = true;
                    index += 1;
                }
                '!' => {
                    modifiers.alt = true;
                    index += 1;
                }
                '+' => {
                    modifiers.shift = true;
                    index += 1;
                }
                '~' => {
                    modifiers.win = true;
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
                    steps.push(KeyStep {
                        modifiers,
                        base: KeyBase::Character(character),
                    });
                    modifiers = Modifiers::default();
                    index += 1;
                }
            }
        }

        if !modifiers.is_empty() {
            return Err(
                "a modifier prefix has no key; write {^}, {!}, {+}, or {~} for the literal character"
                    .to_string(),
            );
        }

        Ok(steps)
    }

    /// Normalize a literal character the way the other platforms do: an
    /// unshifted accelerated letter is case-insensitive, so `^A` means `^a`.
    pub fn effective_character(character: char, modifiers: Modifiers) -> char {
        if modifiers.accelerated() && !modifiers.shift && character.is_ascii_uppercase() {
            character.to_ascii_lowercase()
        } else {
            character
        }
    }

    /// Handle one `{...}` token. Returns true when the token tapped a key and
    /// the pending modifiers should be cleared.
    fn apply_braced_token(
        token: &str,
        modifiers: &mut Modifiers,
        steps: &mut Vec<KeyStep>,
    ) -> Result<bool, String> {
        if token.is_empty() {
            return Err("empty {} key name in the keys specification".to_string());
        }

        if !token.contains('+') || token == "+" {
            if let Some(modifier) = modifier_for(token) {
                *modifiers = modifiers.merge(modifier);
                return Ok(false);
            }

            steps.push(named_step(token, *modifiers)?);
            return Ok(true);
        }

        let segments: Vec<&str> = token.split('+').collect();

        if segments.iter().any(|segment| segment.is_empty()) {
            return Err(format!(
                "malformed key combination {{{token}}} in the keys specification"
            ));
        }

        let Some((base, modifier_names)) = segments.split_last() else {
            return Err(format!(
                "malformed key combination {{{token}}} in the keys specification"
            ));
        };

        for name in modifier_names {
            let Some(modifier) = modifier_for(name) else {
                return Err(format!("{name:?} is not a modifier in {{{token}}}"));
            };

            *modifiers = modifiers.merge(modifier);
        }

        steps.push(named_step(base, *modifiers)?);

        Ok(true)
    }

    fn named_step(name: &str, modifiers: Modifiers) -> Result<KeyStep, String> {
        if let Some(key) = named_vk(name) {
            return Ok(KeyStep {
                modifiers,
                base: KeyBase::Virtual(key),
            });
        }

        let mut characters = name.chars();

        if let (Some(character), None) = (characters.next(), characters.next()) {
            return Ok(KeyStep {
                modifiers,
                base: KeyBase::Character(character),
            });
        }

        Err(format!(
            "unknown key name {{{name}}}; use a documented name or a single character"
        ))
    }

    fn read_braced(characters: &[char], start: usize) -> Result<(String, usize), String> {
        let mut token = String::new();
        let mut index = start + 1;

        while let Some(character) = characters.get(index) {
            if *character == '}' {
                return Ok((token, index + 1));
            }

            token.push(*character);
            index += 1;
        }

        let remainder: String = characters.get(start..).unwrap_or_default().iter().collect();

        Err(format!(
            "unterminated '{{' in the keys specification near {remainder:?}"
        ))
    }

    fn modifier_for(name: &str) -> Option<Modifiers> {
        match name.trim().to_ascii_uppercase().as_str() {
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
            "WIN" | "META" | "CMD" | "COMMAND" | "SUPER" => Some(Modifiers {
                win: true,
                ..Default::default()
            }),
            _ => None,
        }
    }

    fn named_vk(name: &str) -> Option<u16> {
        let upper = name.trim().to_ascii_uppercase();

        match upper.as_str() {
            "ENTER" | "RETURN" => Some(vk::ENTER),
            "TAB" => Some(vk::TAB),
            "ESC" | "ESCAPE" => Some(vk::ESC),
            "BACKSPACE" | "BS" => Some(vk::BACKSPACE),
            "DELETE" | "DEL" | "FORWARDDELETE" => Some(vk::DELETE),
            "UP" | "UPARROW" => Some(vk::UP),
            "DOWN" | "DOWNARROW" => Some(vk::DOWN),
            "LEFT" | "LEFTARROW" => Some(vk::LEFT),
            "RIGHT" | "RIGHTARROW" => Some(vk::RIGHT),
            "HOME" => Some(vk::HOME),
            "END" => Some(vk::END),
            "PGUP" | "PAGEUP" => Some(vk::PGUP),
            "PGDN" | "PAGEDOWN" => Some(vk::PGDN),
            "SPACE" => Some(vk::SPACE),
            _ => upper
                .strip_prefix('F')
                .and_then(|digits| digits.parse::<u8>().ok())
                .and_then(vk::function),
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        fn character(character: char) -> KeyStep {
            KeyStep {
                modifiers: Modifiers::default(),
                base: KeyBase::Character(character),
            }
        }

        fn key(key: u16, modifiers: Modifiers) -> KeyStep {
            KeyStep {
                modifiers,
                base: KeyBase::Virtual(key),
            }
        }

        fn controls() -> Modifiers {
            Modifiers {
                control: true,
                ..Default::default()
            }
        }

        #[test]
        fn literal_text_is_one_step_per_character() {
            assert_eq!(
                parse_keys("Hi 5?").unwrap(),
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
        fn modifier_prefixes_bind_to_one_key() {
            assert_eq!(
                parse_keys("^s").unwrap(),
                vec![KeyStep {
                    modifiers: controls(),
                    base: KeyBase::Character('s'),
                }]
            );

            assert_eq!(
                parse_keys("^ab").unwrap(),
                vec![
                    KeyStep {
                        modifiers: controls(),
                        base: KeyBase::Character('a'),
                    },
                    character('b'),
                ]
            );

            let modifiers = Modifiers {
                alt: true,
                shift: true,
                win: true,
                ..Default::default()
            };

            assert_eq!(
                parse_keys("!+~x").unwrap(),
                vec![KeyStep {
                    modifiers,
                    base: KeyBase::Character('x'),
                }]
            );
        }

        #[test]
        fn named_keys_cover_the_documented_set() {
            let cases = [
                ("{ENTER}", vk::ENTER),
                ("{TAB}", vk::TAB),
                ("{ESC}", vk::ESC),
                ("{BACKSPACE}", vk::BACKSPACE),
                ("{DELETE}", vk::DELETE),
                ("{UP}", vk::UP),
                ("{DOWN}", vk::DOWN),
                ("{LEFT}", vk::LEFT),
                ("{RIGHT}", vk::RIGHT),
                ("{HOME}", vk::HOME),
                ("{END}", vk::END),
                ("{PGUP}", vk::PGUP),
                ("{PGDN}", vk::PGDN),
                ("{F1}", vk::F1),
                ("{F12}", vk::F1 + 11),
            ];

            for (spec, expected) in cases {
                assert_eq!(
                    parse_keys(spec).unwrap(),
                    vec![key(expected, Modifiers::default())],
                    "{spec}"
                );
            }
        }

        #[test]
        fn braced_escapes_type_literal_punctuation() {
            assert_eq!(
                parse_keys("{+}{!}{^}{~}").unwrap(),
                vec![
                    character('+'),
                    character('!'),
                    character('^'),
                    character('~'),
                ]
            );
        }

        #[test]
        fn braced_modifiers_combine_with_the_next_key() {
            let expected = vec![key(
                vk::TAB,
                Modifiers {
                    control: true,
                    shift: true,
                    ..Default::default()
                },
            )];

            assert_eq!(parse_keys("{CTRL}{SHIFT}{TAB}").unwrap(), expected);
            assert_eq!(parse_keys("{CTRL+SHIFT+TAB}").unwrap(), expected);
            assert_eq!(parse_keys("^+{TAB}").unwrap(), expected);
        }

        #[test]
        fn named_key_accepts_a_modifier_prefix() {
            assert_eq!(
                parse_keys("^{F5}").unwrap(),
                vec![key(vk::F1 + 4, controls())]
            );
        }

        #[test]
        fn unknown_named_keys_are_named_in_the_error() {
            let error = parse_keys("{NOPE}").expect_err("must reject");
            assert!(error.contains("NOPE"), "{error}");
            assert!(error.contains("unknown key name"), "{error}");
        }

        #[test]
        fn unterminated_braces_are_named_in_the_error() {
            let error = parse_keys("{ENTER").expect_err("must reject");
            assert!(error.contains("unterminated"), "{error}");
            assert!(error.contains("ENTER"), "{error}");
        }

        #[test]
        fn empty_specifications_are_rejected() {
            assert!(parse_keys("").expect_err("must reject").contains("empty"));
            assert!(parse_keys("{}").expect_err("must reject").contains("empty"));
        }

        #[test]
        fn modifiers_without_a_key_are_rejected() {
            for spec in ["^", "^!", "{CTRL}", "{SHIFT}", "{WIN}"] {
                assert!(parse_keys(spec).is_err(), "{spec}");
            }
        }

        #[test]
        fn malformed_combinations_are_rejected() {
            for spec in ["{CTRL+}", "{+T}", "{CTRL+NOPE}", "{ENTER+}"] {
                assert!(parse_keys(spec).is_err(), "{spec}");
            }
        }

        #[test]
        fn literal_modifier_characters_need_braces() {
            assert_eq!(parse_keys("{+}").unwrap(), vec![character('+')]);
            assert!(parse_keys("+").is_err());
        }

        #[test]
        fn unicode_characters_are_text_steps() {
            assert_eq!(parse_keys("é").unwrap(), vec![character('é')]);
        }

        #[test]
        fn control_uppercase_letters_drop_the_implicit_shift() {
            let steps = parse_keys("^A").unwrap();
            let base = &steps[0].base;

            assert_eq!(base, &KeyBase::Character('A'));
            assert_eq!(effective_character('A', steps[0].modifiers), 'a');
            assert_eq!(effective_character('A', Modifiers::default()), 'A');
        }
    }
}

#[cfg(windows)]
mod platform {
    use std::mem::size_of;
    use std::thread::sleep;
    use std::time::{Duration, Instant};

    use windows::Win32::Foundation::{HWND, POINT};
    use windows::Win32::UI::Accessibility::SELFLAG_TAKEFOCUS;
    use windows::Win32::UI::Input::KeyboardAndMouse::{
        IsWindowEnabled, MapVirtualKeyW, SendInput, VkKeyScanW, INPUT, INPUT_0, INPUT_KEYBOARD,
        INPUT_MOUSE, KEYBDINPUT, KEYBD_EVENT_FLAGS, KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP,
        KEYEVENTF_SCANCODE, KEYEVENTF_UNICODE, MAPVK_VK_TO_VSC, MOUSEEVENTF_HWHEEL,
        MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP,
        MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_WHEEL, MOUSEINPUT,
        MOUSE_EVENT_FLAGS, VIRTUAL_KEY,
    };
    use windows::Win32::UI::WindowsAndMessaging::{
        GetAncestor, GetCursorPos, GetForegroundWindow, GetWindowThreadProcessId, IsIconic,
        IsWindow, SetCursorPos, SetForegroundWindow, ShowWindow, GA_ROOT, SW_MINIMIZE, SW_RESTORE,
    };

    use super::parse::{self, KeyBase, KeyStep, Modifiers};
    use crate::protocol::{
        error_kind, outcome, ActionRequest, ActionResult, ErrorInfo, Point, PointerButton,
        WindowInfo,
    };
    use crate::windows::{enumerate, uia, WindowsBackend};

    const FOCUS_TIMEOUT: Duration = Duration::from_millis(300);
    const FOCUS_POLL: Duration = Duration::from_millis(15);
    const SEND_INPUT_CHUNK: usize = 64;
    const WHEEL_DELTA: i32 = 120;
    const DEFAULT_SCROLL_AMOUNT: i32 = 3;
    const MAX_SCROLL_AMOUNT: i32 = 20;

    /// Perform a synthetic-input action against the resolved window.
    pub fn perform(
        backend: &WindowsBackend,
        request: &ActionRequest,
    ) -> Result<ActionResult, ErrorInfo> {
        match request.action.as_str() {
            "activate" => activate(backend, request),
            "keys" => keys(backend, request),
            "click" => click(backend, request),
            "double_click" => double_click(backend, request),
            "right_click" => right_click(backend, request),
            "hover" => hover(backend, request),
            "drag" => drag(backend, request),
            "scroll" => scroll(backend, request),
            "focus" => focus(backend, request),
            action => Err(ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                format!("unsupported input action {action:?}"),
            )),
        }
    }
    /// Raise the window and confirm it owns the foreground.
    fn activate(
        backend: &WindowsBackend,
        request: &ActionRequest,
    ) -> Result<ActionResult, ErrorInfo> {
        let window = enumerate::resolve_window(&request.window)?;
        let prepared = prepare_window(backend, request, &window, false)?;

        focus_window(&window, prepared.hwnd)?;

        Ok(ActionResult {
            action: "activate".to_string(),
            delivered: true,
            verified: is_foreground(prepared.hwnd),
            uncertain: false,
            value: None,
            message: Some(format!("activated {:?}", window.title)),
            outcome: Some(outcome::NONE.to_string()),
        })
    }

    fn keys(backend: &WindowsBackend, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let specification = request.args.keys.as_deref().unwrap_or_default();
        let steps = parse::parse_keys(specification)
            .map_err(|message| ErrorInfo::new(error_kind::INVALID_REQUEST, message))?;

        let window = enumerate::resolve_window(&request.window)?;
        let prepared = prepare_window(backend, request, &window, true)?;
        focus_window(&window, prepared.hwnd)?;

        let mut inputs = Vec::new();

        for step in &steps {
            push_step(&mut inputs, step)?;
        }

        let sent = send(&window, &inputs)?;

        Ok(ActionResult {
            action: "keys".to_string(),
            delivered: true,
            verified: false,
            uncertain: false,
            value: Some(sent.to_string()),
            message: Some(
                "synthetic keystrokes are not verifiable; confirm the effect with a snapshot"
                    .to_string(),
            ),
            outcome: Some(outcome::KEYSTROKE.to_string()),
        })
    }

    fn click(backend: &WindowsBackend, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        pointer_click(backend, request, PointerButton::Left, 1)
    }

    fn double_click(
        backend: &WindowsBackend,
        request: &ActionRequest,
    ) -> Result<ActionResult, ErrorInfo> {
        pointer_click(backend, request, PointerButton::Left, 2)
    }

    fn right_click(
        backend: &WindowsBackend,
        request: &ActionRequest,
    ) -> Result<ActionResult, ErrorInfo> {
        pointer_click(backend, request, PointerButton::Right, 1)
    }

    fn hover(backend: &WindowsBackend, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let point = require_point(request, "hover")?;
        let window = enumerate::resolve_window(&request.window)?;
        let _ = prepare_window(backend, request, &window, false)?;
        let mut pointer = PointerGuard::capture();

        move_pointer(point.x, point.y)?;
        pointer.expect(point.x, point.y);

        let mut result = ActionResult {
            action: request.action.clone(),
            delivered: true,
            verified: false,
            uncertain: false,
            value: None,
            message: Some(format!(
                "pointer moved to ({}, {}); hover is not verifiable",
                point.x, point.y
            )),
            outcome: Some(outcome::POINTER.to_string()),
        };

        if !pointer.finish() {
            append_note(&mut result, "the pointer could not be restored");
        }

        Ok(result)
    }

    fn drag(backend: &WindowsBackend, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let from = require_point(request, "drag")?;
        let Some(to) = request.args.to_point else {
            return Err(ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                "drag requires args.to_point for the destination",
            ));
        };
        let button = requested_button(request, PointerButton::Left)?;
        let duration = request.args.drag_duration();

        let window = enumerate::resolve_window(&request.window)?;
        let prepared = prepare_window(backend, request, &window, false)?;
        let mut pointer = PointerGuard::capture();
        focus_window(&window, prepared.hwnd)?;
        move_pointer(from.x, from.y)?;
        pointer.expect(from.x, from.y);

        let (down, up) = button_flags(button);
        send(&window, &[mouse_input(down, 0)])?;

        let mut move_error = None;
        let steps = (duration / 16).clamp(1, 60);
        let pause = Duration::from_millis(duration / steps);

        for step in 1..=steps {
            let x = from.x as i64 + (to.x as i64 - from.x as i64) * step as i64 / steps as i64;
            let y = from.y as i64 + (to.y as i64 - from.y as i64) * step as i64 / steps as i64;

            if let Err(error) = move_pointer(x as i32, y as i32) {
                move_error = Some(error);
                break;
            }

            pointer.expect(x as i32, y as i32);
            sleep(pause);
        }

        let released = send(&window, &[mouse_input(up, 0)]);
        if let Some(error) = move_error {
            return Err(error);
        }
        released?;

        if !is_foreground(prepared.hwnd) {
            let mut result = ActionResult::uncertain(
                request.action.as_str(),
                "the target window lost the foreground after the drag; the input may have gone elsewhere",
            );
            result.outcome = Some(outcome::POINTER.to_string());

            if !pointer.finish() {
                append_note(&mut result, "the pointer could not be restored");
            }

            return Ok(result);
        }

        let mut result = ActionResult {
            action: request.action.clone(),
            delivered: true,
            verified: false,
            uncertain: false,
            value: None,
            message: Some(format!(
                "dragged {} from ({}, {}) to ({}, {}) in {duration} ms; synthetic pointer input is not verifiable",
                button.as_str(),
                from.x,
                from.y,
                to.x,
                to.y
            )),
            outcome: Some(outcome::POINTER.to_string()),
        };

        if !pointer.finish() {
            append_note(&mut result, "the pointer could not be restored");
        }

        Ok(result)
    }

    /// Centre of an element's recorded bounds, when the snapshot captured them.
    fn element_centre(handle: &uia::ElementHandle) -> Option<Point> {
        // The snapshot record is the only reliable source: asking the element
        // for a live rectangle can block inside UIA on some providers.
        let bounds = handle.record().bounds?;

        (bounds.width > 0 && bounds.height > 0).then(|| Point {
            x: bounds.left + bounds.width / 2,
            y: bounds.top + bounds.height / 2,
        })
    }

    /// Invoke fallback for elements that expose no invoke pattern: click the
    /// element centre, or the explicit point the caller supplied.
    pub fn click_element_fallback(
        backend: &WindowsBackend,
        request: &ActionRequest,
        handle: &uia::ElementHandle,
        action: &str,
    ) -> Result<ActionResult, ErrorInfo> {
        let point = request
            .args
            .point
            .or_else(|| element_centre(handle))
            .ok_or_else(|| {
                ErrorInfo::new(
                    error_kind::INVALID_REQUEST,
                    "the element exposes no invoke pattern and has no bounds to click",
                )
            })?;

        let mut fallback = request.clone();
        fallback.action = action.to_string();
        fallback.args.point = Some(point);

        let mut result = pointer_click(backend, &fallback, PointerButton::Left, 1)?;
        append_note(
            &mut result,
            "the element exposes no invoke pattern; the fallback clicked it instead",
        );

        Ok(result)
    }

    fn pointer_click(
        backend: &WindowsBackend,
        request: &ActionRequest,
        default_button: PointerButton,
        default_count: u32,
    ) -> Result<ActionResult, ErrorInfo> {
        let point = require_point(request, &request.action)?;
        let button = requested_button(request, default_button)?;
        let count = request.args.click_count(default_count);

        let window = enumerate::resolve_window(&request.window)?;
        let prepared = prepare_window(backend, request, &window, false)?;
        let mut pointer = PointerGuard::capture();
        focus_window(&window, prepared.hwnd)?;
        move_pointer(point.x, point.y)?;
        pointer.expect(point.x, point.y);

        let (down, up) = button_flags(button);
        let mut inputs = Vec::with_capacity(count as usize * 2);

        for _ in 0..count {
            inputs.push(mouse_input(down, 0));
            inputs.push(mouse_input(up, 0));
        }

        send(&window, &inputs)?;

        if !is_foreground(prepared.hwnd) {
            let mut result = ActionResult::uncertain(
                request.action.as_str(),
                "the target window lost the foreground after the click; the click may have opened another window",
            );
            result.outcome = Some(outcome::POINTER.to_string());

            if !pointer.finish() {
                append_note(&mut result, "the pointer could not be restored");
            }

            return Ok(result);
        }

        let mut result = ActionResult {
            action: request.action.clone(),
            delivered: true,
            verified: false,
            uncertain: false,
            value: None,
            message: Some(format!(
                "posted {count} {} click(s) at ({}, {}); synthetic pointer input is not verifiable",
                button.as_str(),
                point.x,
                point.y
            )),
            outcome: Some(outcome::POINTER.to_string()),
        };

        if !pointer.finish() {
            append_note(&mut result, "the pointer could not be restored");
        }

        Ok(result)
    }

    fn scroll(
        backend: &WindowsBackend,
        request: &ActionRequest,
    ) -> Result<ActionResult, ErrorInfo> {
        let window = enumerate::resolve_window(&request.window)?;
        let prepared = prepare_window(backend, request, &window, false)?;
        let direction = request.args.direction.as_deref().unwrap_or_default();
        let amount = request
            .args
            .amount
            .unwrap_or(DEFAULT_SCROLL_AMOUNT)
            .clamp(1, MAX_SCROLL_AMOUNT);
        let input = wheel_input(direction, amount)?;

        focus_window(&window, prepared.hwnd)?;
        // The wheel goes to whatever window sits under the physical pointer,
        // so anchor it on the requested point or the target element.
        let anchor = request
            .args
            .point
            .or_else(|| prepared.target.as_ref().and_then(element_centre));

        if let Some(anchor) = anchor {
            let mut pointer = PointerGuard::capture();
            move_pointer(anchor.x, anchor.y)?;
            pointer.expect(anchor.x, anchor.y);

            let sent = send(&window, &[input]);
            let _ = pointer.finish();
            sent?;
        } else {
            send(&window, &[input])?;
        }

        if !is_foreground(prepared.hwnd) {
            let mut result = ActionResult::uncertain(
                "scroll",
                "the target window lost the foreground after the scroll; the wheel events may have gone elsewhere",
            );
            result.outcome = Some(outcome::POINTER.to_string());

            return Ok(result);
        }

        Ok(ActionResult {
            action: "scroll".to_string(),
            delivered: true,
            verified: false,
            uncertain: false,
            value: None,
            message: Some("wheel scroll sent; synthetic input is not verifiable".to_string()),
            outcome: Some(outcome::POINTER.to_string()),
        })
    }

    fn focus(backend: &WindowsBackend, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let window = enumerate::resolve_window(&request.window)?;
        let prepared = prepare_window(backend, request, &window, false)?;

        focus_window(&window, prepared.hwnd)?;

        let message = if let Some(handle) = prepared.target {
            unsafe { handle.select_pattern()?.Select(SELFLAG_TAKEFOCUS as i32) }.map_err(
                |error| {
                    ErrorInfo::new(
                        error_kind::INPUT_BLOCKED,
                        format!("LegacyIAccessible Select failed: {error}"),
                    )
                },
            )?;

            "window is in the foreground and the element was selected".to_string()
        } else {
            "window is in the foreground".to_string()
        };

        Ok(ActionResult {
            action: "focus".to_string(),
            delivered: true,
            verified: true,
            uncertain: false,
            value: None,
            message: Some(message),
            outcome: Some(outcome::ACCESSIBILITY.to_string()),
        })
    }

    /// Raise the target window for an explicit foreground action.
    pub(crate) fn bring_to_front(window: &WindowInfo) -> bool {
        let Ok(hwnd) = live_handle(window) else {
            return false;
        };

        focus_window(window, hwnd).is_ok()
    }

    /// Window resolved, integrity-checked, and with element guards applied.
    struct Prepared {
        hwnd: HWND,
        target: Option<uia::ElementHandle>,
    }

    fn prepare_window(
        backend: &WindowsBackend,
        request: &ActionRequest,
        window: &WindowInfo,
        reject_password: bool,
    ) -> Result<Prepared, ErrorInfo> {
        let hwnd = live_handle(window)?;
        enumerate::check_integrity(window)?;

        if !unsafe { IsWindowEnabled(hwnd) }.as_bool() {
            return Err(ErrorInfo::new(
                error_kind::INPUT_BLOCKED,
                format!(
                    "window {:?} is disabled; input would be ignored",
                    window.title
                ),
            ));
        }

        let target = element_target(backend, request, window)?;

        if let Some(handle) = &target {
            if !handle.is_enabled_fresh()? {
                return Err(ErrorInfo::new(
                    error_kind::INPUT_BLOCKED,
                    format!(
                        "element {} is disabled; input would be ignored",
                        handle.runtime_id()
                    ),
                ));
            }

            if reject_password && handle.is_password() {
                return Err(ErrorInfo::new(
                    error_kind::INPUT_BLOCKED,
                    "refusing to send keys to a password element",
                ));
            }
        }

        Ok(Prepared { hwnd, target })
    }

    fn element_target(
        backend: &WindowsBackend,
        request: &ActionRequest,
        window: &WindowInfo,
    ) -> Result<Option<uia::ElementHandle>, ErrorInfo> {
        let Some(reference) = request
            .target
            .as_ref()
            .filter(|reference| !reference.is_empty())
        else {
            return Ok(None);
        };

        let cache = backend
            .snapshot_cache
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let Some(cache) = cache.as_ref() else {
            return Err(ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                "no snapshot is cached; take a snapshot before targeting an element",
            ));
        };

        if cache.window().handle != window.handle || cache.window().pid != window.pid {
            return Err(ErrorInfo::new(
                error_kind::STALE_TARGET,
                "the cached snapshot belongs to a different window; re-snapshot the target",
            ));
        }

        cache.resolve_target(reference).map(Some)
    }

    fn live_handle(window: &WindowInfo) -> Result<HWND, ErrorInfo> {
        if !enumerate::is_same_window(&window.handle, window.pid) {
            return Err(ErrorInfo::new(
                error_kind::STALE_TARGET,
                "target window closed or its handle was reused; re-enumerate windows",
            ));
        }

        enumerate::parse_handle(&window.handle).ok_or_else(|| {
            ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                format!("invalid window handle {:?}", window.handle),
            )
        })
    }

    fn focus_window(window: &WindowInfo, hwnd: HWND) -> Result<(), ErrorInfo> {
        let reported = unsafe {
            if IsIconic(hwnd).as_bool() {
                // The return value reports the previous visibility, not success.
                let _ = ShowWindow(hwnd, SW_RESTORE);
            }

            SetForegroundWindow(hwnd).as_bool()
        };

        let deadline = Instant::now() + FOCUS_TIMEOUT;

        loop {
            if is_foreground(hwnd) {
                return Ok(());
            }

            if Instant::now() >= deadline {
                break;
            }

            sleep(FOCUS_POLL);
        }

        Err(ErrorInfo::new(
            error_kind::INPUT_BLOCKED,
            format!(
                "focus failed: could not bring window {:?} to the foreground within {} ms (SetForegroundWindow reported {reported}); it stayed in the background",
                window.title,
                FOCUS_TIMEOUT.as_millis()
            ),
        ))
    }

    fn is_foreground(hwnd: HWND) -> bool {
        unsafe {
            let foreground = GetForegroundWindow();

            if foreground == hwnd {
                return true;
            }

            if foreground.is_invalid() || hwnd.is_invalid() {
                return false;
            }

            let target_root = GetAncestor(hwnd, GA_ROOT);
            let foreground_root = GetAncestor(foreground, GA_ROOT);

            !target_root.is_invalid() && target_root == foreground_root
        }
    }

    /// Restore the user's foreground window after a background-intent action.
    ///
    /// The guard restores only while the target still owns the foreground, so a
    /// user who switches apps while the action runs keeps their choice. A
    /// window that was minimized before the action is minimized again, and the
    /// restore is best-effort because Windows can deny `SetForegroundWindow`.
    pub(crate) struct ForegroundGuard {
        previous: HWND,
        target: HWND,
        target_pid: u32,
        was_iconic: bool,
        finished: bool,
        restored: bool,
    }

    impl ForegroundGuard {
        pub(crate) fn capture(window: Option<&WindowInfo>) -> Self {
            let previous = unsafe { GetForegroundWindow() };
            let target = window
                .and_then(|window| enumerate::parse_handle(&window.handle))
                .unwrap_or_default();
            let target_pid = window.map(|window| window.pid).unwrap_or_default();
            let was_iconic = !target.is_invalid() && unsafe { IsIconic(target) }.as_bool();

            Self {
                previous,
                target,
                target_pid,
                was_iconic,
                finished: false,
                restored: true,
            }
        }

        pub(crate) fn finish(&mut self) -> bool {
            if self.finished {
                return self.restored;
            }

            self.finished = true;

            if self.previous.is_invalid()
                || self.target.is_invalid()
                || self.previous == self.target
                || !self.target_owns_foreground()
            {
                return self.restored;
            }

            if self.was_iconic && !unsafe { IsIconic(self.target) }.as_bool() {
                let _ = unsafe { ShowWindow(self.target, SW_MINIMIZE) };
            }

            self.restored = restore_foreground(self.previous);
            self.restored
        }

        fn target_owns_foreground(&self) -> bool {
            if is_foreground(self.target) {
                return true;
            }

            if self.target_pid == 0 {
                return false;
            }

            let foreground = unsafe { GetForegroundWindow() };

            if foreground.is_invalid() {
                return false;
            }

            let mut pid = 0u32;
            unsafe { GetWindowThreadProcessId(foreground, Some(&mut pid)) };

            pid != 0 && pid == self.target_pid
        }
    }

    impl Drop for ForegroundGuard {
        fn drop(&mut self) {
            self.finish();
        }
    }

    /// Remember the real pointer position and put it back after a synthetic
    /// pointer action. The pointer is restored only when it is still where the
    /// action left it, so a user who grabs the mouse keeps control.
    struct PointerGuard {
        origin: Option<POINT>,
        expected: Option<POINT>,
        finished: bool,
        restored: bool,
    }

    impl PointerGuard {
        fn capture() -> Self {
            let mut origin = POINT::default();
            let origin = unsafe { GetCursorPos(&mut origin) }
                .is_ok()
                .then_some(origin);

            Self {
                origin,
                expected: None,
                finished: false,
                restored: true,
            }
        }

        fn expect(&mut self, x: i32, y: i32) {
            self.expected = Some(POINT { x, y });
        }

        fn finish(&mut self) -> bool {
            if self.finished {
                return self.restored;
            }

            self.finished = true;
            let (Some(origin), Some(expected)) = (self.origin, self.expected) else {
                return self.restored;
            };
            let mut current = POINT::default();

            if unsafe { GetCursorPos(&mut current) }.is_err() {
                self.restored = false;
                return self.restored;
            }

            if current == origin || current != expected {
                return self.restored;
            }

            self.restored = unsafe { SetCursorPos(origin.x, origin.y) }.is_ok();
            self.restored
        }
    }

    impl Drop for PointerGuard {
        fn drop(&mut self) {
            self.finish();
        }
    }

    fn restore_foreground(previous: HWND) -> bool {
        if is_foreground(previous) {
            return true;
        }

        if !unsafe { IsWindow(Some(previous)) }.as_bool() {
            return true;
        }

        let _ = unsafe { SetForegroundWindow(previous) };
        let deadline = Instant::now() + FOCUS_TIMEOUT;

        loop {
            if is_foreground(previous) {
                return true;
            }

            if Instant::now() >= deadline {
                return false;
            }

            sleep(FOCUS_POLL);
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

    fn send(window: &WindowInfo, inputs: &[INPUT]) -> Result<usize, ErrorInfo> {
        if inputs.is_empty() {
            return Err(ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                "the keys specification produced no key events",
            ));
        }

        for chunk in inputs.chunks(SEND_INPUT_CHUNK) {
            if !enumerate::is_same_window(&window.handle, window.pid) {
                return Err(ErrorInfo::new(
                    error_kind::STALE_TARGET,
                    "target window changed before SendInput; nothing further was sent",
                ));
            }

            let sent = unsafe { SendInput(chunk, size_of::<INPUT>() as i32) };

            if sent as usize != chunk.len() {
                return Err(ErrorInfo::new(
                    error_kind::INPUT_BLOCKED,
                    format!(
                        "SendInput delivered {sent} of {} events; the input desktop or target integrity blocked the rest",
                        chunk.len()
                    ),
                ));
            }
        }

        Ok(inputs.len())
    }

    fn push_step(inputs: &mut Vec<INPUT>, step: &KeyStep) -> Result<(), ErrorInfo> {
        let held = held_modifiers(step.modifiers);

        for key in &held {
            push_virtual_key(inputs, *key, false)?;
        }

        match &step.base {
            KeyBase::Virtual(key) => {
                push_virtual_key(inputs, *key, false)?;
                push_virtual_key(inputs, *key, true)?;
            }
            KeyBase::Character(character) => {
                push_character(inputs, *character, step.modifiers)?;
            }
        }

        for key in held.iter().rev() {
            push_virtual_key(inputs, *key, true)?;
        }

        Ok(())
    }

    fn held_modifiers(modifiers: Modifiers) -> Vec<u16> {
        let mut held = Vec::new();

        if modifiers.control {
            held.push(parse::vk::CONTROL);
        }

        if modifiers.alt {
            held.push(parse::vk::ALT);
        }

        if modifiers.shift {
            held.push(parse::vk::SHIFT);
        }

        if modifiers.win {
            held.push(parse::vk::WIN);
        }

        held
    }

    fn push_character(
        inputs: &mut Vec<INPUT>,
        character: char,
        modifiers: Modifiers,
    ) -> Result<(), ErrorInfo> {
        let character = parse::effective_character(character, modifiers);

        if let Some((key, needs_shift)) = character_key(character) {
            let implicit_shift = needs_shift && !modifiers.shift;

            if implicit_shift {
                push_virtual_key(inputs, parse::vk::SHIFT, false)?;
            }

            push_virtual_key(inputs, key, false)?;
            push_virtual_key(inputs, key, true)?;

            if implicit_shift {
                push_virtual_key(inputs, parse::vk::SHIFT, true)?;
            }

            return Ok(());
        }

        let mut buffer = [0u16; 2];

        for unit in character.encode_utf16(&mut buffer).iter().copied() {
            push_unicode(inputs, unit, false);
            push_unicode(inputs, unit, true);
        }

        Ok(())
    }

    fn character_key(character: char) -> Option<(u16, bool)> {
        let code = u16::try_from(u32::from(character)).ok()?;
        let scan = unsafe { VkKeyScanW(code) };

        if scan < 0 {
            return None;
        }

        let value = scan as u16;
        let key = value & 0x00FF;
        let state = value >> 8;

        // Ctrl/Alt bits mean the character needs a layout-specific chord such
        // as AltGr, which the committed-text path cannot express as one key.
        if key == 0 || state & 0x06 != 0 {
            return None;
        }

        Some((key, state & 0x01 != 0))
    }

    fn push_virtual_key(inputs: &mut Vec<INPUT>, key: u16, up: bool) -> Result<(), ErrorInfo> {
        let scan = unsafe { MapVirtualKeyW(u32::from(key), MAPVK_VK_TO_VSC) };
        let scan = u16::try_from(scan)
            .ok()
            .filter(|scan| *scan != 0)
            .ok_or_else(|| {
                ErrorInfo::new(
                    error_kind::BACKEND_ERROR,
                    format!("no scan code for virtual key {key:#04X}"),
                )
            })?;
        let mut flags = KEYEVENTF_SCANCODE.0;

        if is_extended_key(key) {
            flags |= KEYEVENTF_EXTENDEDKEY.0;
        }

        if up {
            flags |= KEYEVENTF_KEYUP.0;
        }

        inputs.push(keyboard_input(scan, flags));

        Ok(())
    }

    fn push_unicode(inputs: &mut Vec<INPUT>, unit: u16, up: bool) {
        let mut flags = KEYEVENTF_UNICODE.0;

        if up {
            flags |= KEYEVENTF_KEYUP.0;
        }

        inputs.push(keyboard_input(unit, flags));
    }

    fn keyboard_input(scan: u16, flags: u32) -> INPUT {
        INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT {
                    wVk: VIRTUAL_KEY(0),
                    wScan: scan,
                    dwFlags: KEYBD_EVENT_FLAGS(flags),
                    time: 0,
                    dwExtraInfo: 0,
                },
            },
        }
    }

    fn mouse_input(flags: MOUSE_EVENT_FLAGS, data: u32) -> INPUT {
        INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dx: 0,
                    dy: 0,
                    mouseData: data,
                    dwFlags: flags,
                    time: 0,
                    dwExtraInfo: 0,
                },
            },
        }
    }

    fn wheel_input(direction: &str, amount: i32) -> Result<INPUT, ErrorInfo> {
        let delta = WHEEL_DELTA * amount.clamp(1, MAX_SCROLL_AMOUNT);
        let (flags, value) = match direction.trim().to_ascii_lowercase().as_str() {
            "up" => (MOUSEEVENTF_WHEEL, delta),
            "down" => (MOUSEEVENTF_WHEEL, -delta),
            "right" => (MOUSEEVENTF_HWHEEL, delta),
            "left" => (MOUSEEVENTF_HWHEEL, -delta),
            other => {
                return Err(ErrorInfo::new(
                    error_kind::INVALID_REQUEST,
                    format!("unsupported scroll direction {other:?}; use up, down, left, or right"),
                ));
            }
        };

        // mouseData is an unsigned field carrying a signed wheel delta.
        Ok(mouse_input(flags, value as u32))
    }

    fn require_point(request: &ActionRequest, action: &str) -> Result<Point, ErrorInfo> {
        request.args.point.ok_or_else(|| {
            ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                format!("{action} requires args.point for a coordinate action"),
            )
        })
    }

    fn requested_button(
        request: &ActionRequest,
        default: PointerButton,
    ) -> Result<PointerButton, ErrorInfo> {
        match request
            .args
            .button
            .as_deref()
            .map(str::trim)
            .filter(|name| !name.is_empty())
        {
            Some(_) => request.args.pointer_button(),
            None => Ok(default),
        }
    }

    fn move_pointer(x: i32, y: i32) -> Result<(), ErrorInfo> {
        unsafe { SetCursorPos(x, y) }.map_err(|error| {
            ErrorInfo::new(
                error_kind::BACKEND_ERROR,
                format!("SetCursorPos({x}, {y}) failed: {error}"),
            )
        })
    }

    fn button_flags(button: PointerButton) -> (MOUSE_EVENT_FLAGS, MOUSE_EVENT_FLAGS) {
        match button {
            PointerButton::Left => (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            PointerButton::Right => (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
            PointerButton::Middle => (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
        }
    }

    fn is_extended_key(key: u16) -> bool {
        matches!(
            key,
            0x21..=0x28 | 0x2D | 0x2E | 0x5B | 0x5C | 0x6F | 0xA3 | 0xA5
        )
    }
}

#[cfg(windows)]
pub use platform::perform;
#[cfg(windows)]
pub(crate) use platform::{bring_to_front, click_element_fallback, ForegroundGuard};
