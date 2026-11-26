//! Deterministic backend for protocol, discovery, and CLI tests.
//!
//! Owned by T4. The fake models one primary window, one offscreen window, and
//! one disabled window plus a small accessibility tree. State lives behind a
//! `Mutex`, so `set_value` round-trips inside one process while every process
//! starts from the same defaults.
//!
//! Integration tests should target [`WINDOW_TITLE`] and the element names
//! `Text Editor`, `Save`, `Delete`, `Password`, `Agree`, and `Offscreen Label`.

use std::collections::BTreeMap;
use std::sync::{Mutex, MutexGuard};

use crate::protocol::{
    error_kind, outcome, ActionResult, Bounds, CheckResult, DoctorReport, ElementRecord,
    ElementRef, ErrorInfo, Health, ScreenshotRequest, ScrollState, Snapshot, SnapshotRequest,
    WindowInfo,
};
use crate::{ActionRequest, Backend};

/// Handle of the primary fake window.
pub const WINDOW_HANDLE: &str = "0x1";
/// Process id of the primary fake window.
pub const WINDOW_PID: u32 = 4242;
/// Title of the primary fake window.
pub const WINDOW_TITLE: &str = "Fake Window";
/// Process name of the primary fake window.
pub const WINDOW_PROCESS: &str = "fake.exe";
/// Window class of the primary fake window.
pub const WINDOW_CLASS: &str = "FakeWindow";

/// Handle of the hidden window that lives offscreen.
pub const HIDDEN_WINDOW_HANDLE: &str = "0x2";
/// Title of the hidden window.
pub const HIDDEN_WINDOW_TITLE: &str = "Fake Hidden Window";
/// Process name of the hidden window.
pub const HIDDEN_WINDOW_PROCESS: &str = "fake-hidden.exe";

/// Handle of the disabled window.
pub const DISABLED_WINDOW_HANDLE: &str = "0x3";
/// Title of the disabled window.
pub const DISABLED_WINDOW_TITLE: &str = "Fake Disabled Window";
/// Process name of the disabled window.
pub const DISABLED_WINDOW_PROCESS: &str = "fake-disabled.exe";

/// Root window element id.
pub const ROOT_ELEMENT_ID: u32 = 0;
/// Editor pane element id.
pub const EDITOR_PANE_ID: u32 = 1;
/// Editable text field element id.
pub const TEXT_EDITOR_ID: u32 = 2;
/// Save button element id.
pub const SAVE_BUTTON_ID: u32 = 3;
/// Disabled delete button element id.
pub const DELETE_BUTTON_ID: u32 = 4;
/// Password field element id.
pub const PASSWORD_EDIT_ID: u32 = 5;
/// Checkbox element id.
pub const AGREE_CHECKBOX_ID: u32 = 6;
/// Offscreen label element id.
pub const OFFSCREEN_LABEL_ID: u32 = 7;

/// Number of elements in an untruncated snapshot.
pub const ELEMENT_COUNT: u32 = 8;
/// Default depth budget.
pub const DEFAULT_MAX_DEPTH: u32 = 10;
/// Default element budget.
pub const DEFAULT_MAX_ELEMENTS: u32 = 1000;
/// Secret held by the password field; it is never exposed through the protocol.
pub const PASSWORD_SECRET: &str = "correct horse battery staple";

/// Mutable state of the fake desktop.
#[derive(Debug, Clone)]
pub struct FakeState {
    /// Values held by controls that expose a Value or Text pattern.
    pub values: BTreeMap<u32, String>,
    /// Per-element enabled overrides; absent means enabled.
    pub enabled: BTreeMap<u32, bool>,
    /// Per-element toggle state.
    pub toggled: BTreeMap<u32, bool>,
    /// Element that last received a click or a selection change.
    pub selection: Option<u32>,
    /// Element that currently owns keyboard focus.
    pub focused: Option<u32>,
    /// Element that was invoked last.
    pub last_invoked: Option<u32>,
    /// Number of invoke or button click calls.
    pub invoke_count: u32,
    /// Number of click calls, including coordinate clicks.
    pub click_count: u32,
    /// Last keys payload sent by the caller.
    pub last_keys: Option<String>,
    /// Scroll calls recorded as `(direction, amount)`.
    pub scrolls: Vec<(String, i32)>,
    /// Absolute scroll targets recorded as `(element id, horizontal, vertical)`.
    pub scroll_positions: Vec<(u32, Option<f64>, Option<f64>)>,
    /// Title of the window raised by the last activate call.
    pub activated: Option<String>,
}

impl Default for FakeState {
    fn default() -> Self {
        let mut values = BTreeMap::new();
        values.insert(TEXT_EDITOR_ID, String::new());
        values.insert(PASSWORD_EDIT_ID, PASSWORD_SECRET.to_string());

        let mut enabled = BTreeMap::new();
        enabled.insert(DELETE_BUTTON_ID, false);

        let mut toggled = BTreeMap::new();
        toggled.insert(AGREE_CHECKBOX_ID, false);

        Self {
            values,
            enabled,
            toggled,
            selection: None,
            focused: None,
            last_invoked: None,
            invoke_count: 0,
            click_count: 0,
            last_keys: None,
            scrolls: Vec::new(),
            scroll_positions: Vec::new(),
            activated: None,
        }
    }
}

/// A deterministic but stateful backend with a stable window and element tree.
#[derive(Debug)]
pub struct FakeBackend {
    pub health: Health,
    state: Mutex<FakeState>,
}

impl Default for FakeBackend {
    fn default() -> Self {
        Self::ready()
    }
}

impl FakeBackend {
    /// Ready fake backend.
    pub fn ready() -> Self {
        Self {
            health: Health::Ready,
            state: Mutex::new(FakeState::default()),
        }
    }

    /// Backend that reports degraded health but still serves requests.
    pub fn degraded() -> Self {
        Self {
            health: Health::Degraded,
            state: Mutex::new(FakeState::default()),
        }
    }

    /// Mutable state, for tests that need to arrange a scenario.
    pub fn state(&self) -> MutexGuard<'_, FakeState> {
        self.lock_state()
    }
}

impl Backend for FakeBackend {
    fn name(&self) -> &'static str {
        "fake"
    }

    fn platform(&self) -> &'static str {
        "fake"
    }

    fn capabilities(&self) -> Vec<String> {
        ["windows", "snapshot", "action", "screenshot", "dialogs"]
            .iter()
            .map(|value| (*value).to_string())
            .collect()
    }

    fn health(&self) -> Health {
        self.health
    }

    fn doctor(&self) -> DoctorReport {
        let health = self.health();
        let backend_ok = health != Health::Unavailable;
        let input_ok = health == Health::Ready;

        DoctorReport {
            platform: self.platform().to_string(),
            backend: self.name().to_string(),
            health,
            permissions: BTreeMap::from([
                ("accessibility".to_string(), "granted".to_string()),
                ("screen_recording".to_string(), "granted".to_string()),
            ]),
            checks: vec![
                CheckResult::new("backend", backend_ok, "fake backend module loaded"),
                CheckResult::new(
                    "loopback",
                    true,
                    "loopback bind and token discovery available",
                ),
                CheckResult::new("input", input_ok, "synthetic input path available"),
            ],
            notes: vec!["fake backend controls no native application".to_string()],
        }
    }

    fn windows(&self) -> Result<Vec<WindowInfo>, ErrorInfo> {
        Ok(vec![
            WindowInfo {
                handle: WINDOW_HANDLE.to_string(),
                dialog: false,
                pid: WINDOW_PID,
                process_name: Some(WINDOW_PROCESS.to_string()),
                title: WINDOW_TITLE.to_string(),
                class_name: Some(WINDOW_CLASS.to_string()),
                bounds: Bounds {
                    left: 10,
                    top: 20,
                    width: 400,
                    height: 300,
                },
                foreground: true,
                enabled: true,
                offscreen: false,
            },
            WindowInfo {
                handle: HIDDEN_WINDOW_HANDLE.to_string(),
                dialog: true,
                pid: WINDOW_PID + 1,
                process_name: Some(HIDDEN_WINDOW_PROCESS.to_string()),
                title: HIDDEN_WINDOW_TITLE.to_string(),
                class_name: Some(WINDOW_CLASS.to_string()),
                bounds: Bounds {
                    left: 0,
                    top: 0,
                    width: 0,
                    height: 0,
                },
                foreground: false,
                enabled: true,
                offscreen: true,
            },
            WindowInfo {
                handle: DISABLED_WINDOW_HANDLE.to_string(),
                dialog: false,
                pid: WINDOW_PID + 2,
                process_name: Some(DISABLED_WINDOW_PROCESS.to_string()),
                title: DISABLED_WINDOW_TITLE.to_string(),
                class_name: Some(WINDOW_CLASS.to_string()),
                bounds: Bounds {
                    left: 500,
                    top: 20,
                    width: 200,
                    height: 100,
                },
                foreground: false,
                enabled: false,
                offscreen: false,
            },
        ])
    }

    fn snapshot(&self, request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo> {
        let window = self.resolve_window(&request.window)?;
        let max_depth = request.max_depth.unwrap_or(DEFAULT_MAX_DEPTH);
        let max_elements = request.max_elements.unwrap_or(DEFAULT_MAX_ELEMENTS);
        let state = self.lock_state();
        let elements = Self::element_templates(&window, &state);

        let mut snapshot = build_snapshot(window, elements, max_depth, max_elements);

        if request.actionable {
            crate::observe::apply_actionable(&mut snapshot);
        }

        Ok(snapshot)
    }

    fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let window = self.resolve_window(&request.window)?;

        if !window.enabled {
            return Err(ErrorInfo::new(
                error_kind::INPUT_BLOCKED,
                format!("window '{}' is disabled", window.title),
            ));
        }

        let mut state = self.lock_state();
        let elements = Self::element_templates(&window, &state);

        match request.action.as_str() {
            "get_value" => {
                let element = find_element(&elements, request.target.as_ref())?;
                ensure_not_sensitive(element)?;
                ensure_value_pattern(element)?;

                Ok(ActionResult {
                    action: request.action.clone(),
                    delivered: true,
                    verified: true,
                    uncertain: false,
                    value: element.value.clone(),
                    message: None,
                    outcome: Some(outcome::ACCESSIBILITY.to_string()),
                })
            }
            "set_value" => {
                let element = find_element(&elements, request.target.as_ref())?;
                ensure_not_sensitive(element)?;
                ensure_enabled(element)?;
                ensure_value_pattern(element)?;

                let value = request
                    .args
                    .value
                    .clone()
                    .ok_or_else(|| ErrorInfo::invalid("set_value requires args.value"))?;

                state.values.insert(element.id, value.clone());

                let read_back = state.values.get(&element.id).cloned();
                if read_back.as_deref() != Some(value.as_str()) {
                    return Err(ErrorInfo::backend("set_value read-back mismatch"));
                }

                Ok(ActionResult {
                    action: request.action.clone(),
                    delivered: true,
                    verified: true,
                    uncertain: false,
                    value: Some(value),
                    message: None,
                    outcome: Some(outcome::ACCESSIBILITY.to_string()),
                })
            }
            "invoke" => {
                if let Some(target) = request.target.as_ref().filter(|target| !target.is_empty()) {
                    let element = find_element(&elements, Some(target))?;
                    ensure_enabled(element)?;
                    ensure_pattern(element, "Invoke")?;

                    state.invoke_count += 1;
                    state.last_invoked = Some(element.id);
                    state.selection = Some(element.id);
                }

                Ok(ActionResult::delivered_with(
                    request.action.clone(),
                    outcome::ACCESSIBILITY,
                ))
            }
            "toggle" => {
                let mut value = None;

                if let Some(target) = request.target.as_ref().filter(|target| !target.is_empty()) {
                    let element = find_element(&elements, Some(target))?;
                    ensure_enabled(element)?;
                    ensure_pattern(element, "Toggle")?;

                    let current = state.toggled.get(&element.id).copied().unwrap_or(false);
                    let checked = !current;
                    state.toggled.insert(element.id, checked);

                    let read_back = state.toggled.get(&element.id).copied().unwrap_or(false);
                    if read_back != checked {
                        return Err(ErrorInfo::backend("toggle read-back mismatch"));
                    }

                    value = Some(checked.to_string());
                }

                Ok(ActionResult {
                    action: request.action.clone(),
                    delivered: true,
                    verified: true,
                    uncertain: false,
                    value,
                    message: None,
                    outcome: Some(outcome::ACCESSIBILITY.to_string()),
                })
            }
            "click" => {
                let mut click_outcome = outcome::POINTER;

                if let Some(target) = request.target.as_ref().filter(|target| !target.is_empty()) {
                    let element = find_element(&elements, Some(target))?;
                    ensure_enabled(element)?;

                    state.click_count += 1;
                    state.selection = Some(element.id);

                    if element.patterns.iter().any(|pattern| pattern == "Invoke") {
                        state.invoke_count += 1;
                        state.last_invoked = Some(element.id);
                    }

                    if element.patterns.iter().any(|pattern| pattern == "Toggle") {
                        let entry = state.toggled.entry(element.id).or_insert(false);
                        *entry = !*entry;
                    }

                    click_outcome = outcome::ACCESSIBILITY;
                } else {
                    state.click_count += 1;
                }

                Ok(ActionResult::delivered_with(
                    request.action.clone(),
                    click_outcome,
                ))
            }
            "keys" => {
                if let Some(target) = request.target.as_ref().filter(|target| !target.is_empty()) {
                    let element = find_element(&elements, Some(target))?;
                    ensure_enabled(element)?;
                }

                let keys = request
                    .args
                    .keys
                    .clone()
                    .ok_or_else(|| ErrorInfo::invalid("keys requires args.keys"))?;
                state.last_keys = Some(keys);

                Ok(ActionResult {
                    action: request.action.clone(),
                    delivered: true,
                    verified: false,
                    uncertain: false,
                    value: None,
                    message: None,
                    outcome: Some(outcome::KEYSTROKE.to_string()),
                })
            }
            "focus" => {
                let element = find_element(&elements, request.target.as_ref())?;
                ensure_enabled(element)?;

                state.focused = Some(element.id);

                Ok(ActionResult::delivered_with(
                    request.action.clone(),
                    outcome::ACCESSIBILITY,
                ))
            }
            "scroll_to" => {
                let (horizontal, vertical) =
                    request.args.scroll_target().map_err(ErrorInfo::invalid)?;
                let element = find_element(&elements, request.target.as_ref())?;
                ensure_enabled(element)?;
                state
                    .scroll_positions
                    .push((element.id, horizontal, vertical));

                Ok(ActionResult {
                    action: request.action.clone(),
                    delivered: true,
                    verified: true,
                    uncertain: false,
                    value: None,
                    message: None,
                    outcome: Some(outcome::ACCESSIBILITY.to_string()),
                })
            }
            "scroll" => {
                if let Some(target) = request.target.as_ref().filter(|target| !target.is_empty()) {
                    let element = find_element(&elements, Some(target))?;
                    ensure_enabled(element)?;
                }

                let direction = request
                    .args
                    .direction
                    .clone()
                    .unwrap_or_else(|| "down".to_string());
                let amount = request.args.amount.unwrap_or(3);
                state.scrolls.push((direction, amount));

                Ok(ActionResult {
                    action: request.action.clone(),
                    delivered: true,
                    verified: false,
                    uncertain: false,
                    value: None,
                    message: None,
                    outcome: Some(outcome::POINTER.to_string()),
                })
            }
            "activate" => {
                state.activated = Some(window.title.clone());

                Ok(ActionResult::delivered_with(
                    request.action.clone(),
                    outcome::NONE,
                ))
            }
            other => Err(ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                format!("unknown action: {other}"),
            )),
        }
    }

    fn screenshot(&self, request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
        let window = self.resolve_window(&request.window)?;

        Ok(encode_png_ihdr(
            window.bounds.width.max(1) as u32,
            window.bounds.height.max(1) as u32,
        ))
    }
}

impl FakeBackend {
    fn lock_state(&self) -> MutexGuard<'_, FakeState> {
        self.state.lock().unwrap_or_else(|error| error.into_inner())
    }

    fn resolve_window(&self, query: &str) -> Result<WindowInfo, ErrorInfo> {
        let query = query.trim();
        let windows = self.windows()?;

        let candidate = windows
            .iter()
            .find(|window| !query.is_empty() && window.title == query)
            .or_else(|| {
                windows
                    .iter()
                    .find(|window| window.handle.eq_ignore_ascii_case(query))
            })
            .or_else(|| {
                windows.iter().find(|window| {
                    window
                        .process_name
                        .as_deref()
                        .map(|name| process_matches(name, query))
                        .unwrap_or(false)
                })
            })
            .or_else(|| {
                windows.iter().find(|window| {
                    window.enabled
                        && !window.offscreen
                        && !query.is_empty()
                        && window.title.to_lowercase().contains(&query.to_lowercase())
                })
            });

        candidate.cloned().ok_or_else(|| {
            ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                format!("no window matching '{query}'"),
            )
        })
    }

    fn element_templates(window: &WindowInfo, state: &FakeState) -> Vec<ElementRecord> {
        let is_enabled = |id: u32| state.enabled.get(&id).copied().unwrap_or(true);
        let runtime_id = |id: u32| format!("fake:{id}");

        vec![
            ElementRecord {
                id: ROOT_ELEMENT_ID,
                parent: None,
                depth: 0,
                runtime_id: runtime_id(ROOT_ELEMENT_ID),
                control_type: "Window".to_string(),
                name: Some(WINDOW_TITLE.to_string()),
                automation_id: Some("window".to_string()),
                class_name: Some(WINDOW_CLASS.to_string()),
                value: None,
                enabled: true,
                offscreen: window.offscreen,
                bounds: Some(window.bounds),
                patterns: Vec::new(),
                sensitive: false,
                path: None,
                scroll: None,
            },
            ElementRecord {
                id: EDITOR_PANE_ID,
                parent: Some(ROOT_ELEMENT_ID),
                depth: 1,
                runtime_id: runtime_id(EDITOR_PANE_ID),
                control_type: "Pane".to_string(),
                name: Some("Editor Pane".to_string()),
                automation_id: Some("editor-pane".to_string()),
                class_name: Some(WINDOW_CLASS.to_string()),
                value: None,
                enabled: true,
                offscreen: false,
                bounds: Some(Bounds {
                    left: window.bounds.left,
                    top: window.bounds.top,
                    width: window.bounds.width,
                    height: 200,
                }),
                patterns: vec!["Scroll".to_string()],
                sensitive: false,
                path: None,
                scroll: Some(ScrollState {
                    horizontal_percent: Some(0.0),
                    vertical_percent: Some(0.0),
                    horizontal_view_percent: Some(100.0),
                    vertical_view_percent: Some(50.0),
                    horizontal: false,
                    vertical: true,
                }),
            },
            ElementRecord {
                id: TEXT_EDITOR_ID,
                parent: Some(EDITOR_PANE_ID),
                depth: 2,
                runtime_id: runtime_id(TEXT_EDITOR_ID),
                control_type: "Edit".to_string(),
                name: Some("Text Editor".to_string()),
                automation_id: Some("edit".to_string()),
                class_name: Some("Edit".to_string()),
                value: state.values.get(&TEXT_EDITOR_ID).cloned(),
                enabled: is_enabled(TEXT_EDITOR_ID),
                offscreen: false,
                bounds: Some(Bounds {
                    left: window.bounds.left + 8,
                    top: window.bounds.top + 8,
                    width: window.bounds.width - 16,
                    height: 160,
                }),
                patterns: vec![
                    "Value".to_string(),
                    "Text".to_string(),
                    "LegacyIAccessible".to_string(),
                ],
                sensitive: false,
                path: None,
                scroll: None,
            },
            ElementRecord {
                id: SAVE_BUTTON_ID,
                parent: Some(ROOT_ELEMENT_ID),
                depth: 1,
                runtime_id: runtime_id(SAVE_BUTTON_ID),
                control_type: "Button".to_string(),
                name: Some("Save".to_string()),
                automation_id: Some("save".to_string()),
                class_name: Some("Button".to_string()),
                value: None,
                enabled: is_enabled(SAVE_BUTTON_ID),
                offscreen: false,
                bounds: Some(Bounds {
                    left: window.bounds.left + 300,
                    top: window.bounds.top + 220,
                    width: 80,
                    height: 28,
                }),
                patterns: vec!["Invoke".to_string()],
                sensitive: false,
                path: None,
                scroll: None,
            },
            ElementRecord {
                id: DELETE_BUTTON_ID,
                parent: Some(ROOT_ELEMENT_ID),
                depth: 1,
                runtime_id: runtime_id(DELETE_BUTTON_ID),
                control_type: "Button".to_string(),
                name: Some("Delete".to_string()),
                automation_id: Some("delete".to_string()),
                class_name: Some("Button".to_string()),
                value: None,
                enabled: is_enabled(DELETE_BUTTON_ID),
                offscreen: false,
                bounds: Some(Bounds {
                    left: window.bounds.left + 210,
                    top: window.bounds.top + 220,
                    width: 80,
                    height: 28,
                }),
                patterns: vec!["Invoke".to_string()],
                sensitive: false,
                path: None,
                scroll: None,
            },
            ElementRecord {
                id: PASSWORD_EDIT_ID,
                parent: Some(ROOT_ELEMENT_ID),
                depth: 1,
                runtime_id: runtime_id(PASSWORD_EDIT_ID),
                control_type: "Edit".to_string(),
                name: Some("Password".to_string()),
                automation_id: Some("password".to_string()),
                class_name: Some("Edit".to_string()),
                value: None,
                enabled: is_enabled(PASSWORD_EDIT_ID),
                offscreen: false,
                bounds: Some(Bounds {
                    left: window.bounds.left + 8,
                    top: window.bounds.top + 250,
                    width: 180,
                    height: 24,
                }),
                patterns: vec!["Text".to_string()],
                sensitive: true,
                path: None,
                scroll: None,
            },
            ElementRecord {
                id: AGREE_CHECKBOX_ID,
                parent: Some(ROOT_ELEMENT_ID),
                depth: 1,
                runtime_id: runtime_id(AGREE_CHECKBOX_ID),
                control_type: "CheckBox".to_string(),
                name: Some("Agree".to_string()),
                automation_id: Some("agree".to_string()),
                class_name: Some("CheckBox".to_string()),
                value: Some(
                    state
                        .toggled
                        .get(&AGREE_CHECKBOX_ID)
                        .copied()
                        .unwrap_or(false)
                        .to_string(),
                ),
                enabled: is_enabled(AGREE_CHECKBOX_ID),
                offscreen: false,
                bounds: Some(Bounds {
                    left: window.bounds.left + 8,
                    top: window.bounds.top + 280,
                    width: 120,
                    height: 16,
                }),
                patterns: vec!["Toggle".to_string()],
                sensitive: false,
                path: None,
                scroll: None,
            },
            ElementRecord {
                id: OFFSCREEN_LABEL_ID,
                parent: Some(ROOT_ELEMENT_ID),
                depth: 1,
                runtime_id: runtime_id(OFFSCREEN_LABEL_ID),
                control_type: "Text".to_string(),
                name: Some("Offscreen Label".to_string()),
                automation_id: Some("offscreen-label".to_string()),
                class_name: Some("Text".to_string()),
                value: None,
                enabled: true,
                offscreen: true,
                bounds: None,
                patterns: Vec::new(),
                sensitive: false,
                path: None,
                scroll: None,
            },
        ]
    }
}

fn build_snapshot(
    window: WindowInfo,
    elements: Vec<ElementRecord>,
    max_depth: u32,
    max_elements: u32,
) -> Snapshot {
    let total_elements = elements.len() as u32;
    let mut kept: Vec<ElementRecord> = elements
        .into_iter()
        .filter(|element| element.depth <= max_depth)
        .collect();
    let depth_kept = kept.len();

    kept.truncate(max_elements as usize);

    let mut remap = BTreeMap::new();
    for (index, element) in kept.iter().enumerate() {
        remap.insert(element.id, index as u32);
    }

    for (index, element) in kept.iter_mut().enumerate() {
        element.parent = element
            .parent
            .and_then(|parent| remap.get(&parent).copied());
        element.id = index as u32;
    }

    let truncated = depth_kept < total_elements as usize || kept.len() < depth_kept;

    Snapshot {
        window,
        elements: kept,
        truncated,
        truncated_by: None,
        children_cut: 0,
        max_depth,
        max_elements,
        total_elements,
    }
}

fn find_element<'a>(
    elements: &'a [ElementRecord],
    target: Option<&ElementRef>,
) -> Result<&'a ElementRecord, ErrorInfo> {
    let target = target
        .filter(|reference| !reference.is_empty())
        .ok_or_else(|| ErrorInfo::invalid("action requires a target element"))?;

    let found = elements
        .iter()
        .find(|element| target.id.is_some_and(|id| element.id == id))
        .or_else(|| {
            elements.iter().find(|element| {
                target
                    .runtime_id
                    .as_deref()
                    .is_some_and(|id| element.runtime_id == id)
            })
        })
        .or_else(|| {
            elements.iter().find(|element| {
                target
                    .automation_id
                    .as_deref()
                    .is_some_and(|id| element.automation_id.as_deref() == Some(id))
            })
        })
        .or_else(|| {
            elements.iter().find(|element| {
                target.name.as_deref().is_some_and(|name| {
                    element.name.as_deref() == Some(name)
                        && target
                            .role
                            .as_deref()
                            .map_or(true, |role| element.control_type.eq_ignore_ascii_case(role))
                })
            })
        })
        .or_else(|| {
            elements.iter().find(|element| {
                target
                    .role
                    .as_deref()
                    .is_some_and(|role| element.control_type.eq_ignore_ascii_case(role))
            })
        });

    found.ok_or_else(|| {
        ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            "no element matches the target reference",
        )
    })
}

fn ensure_not_sensitive(element: &ElementRecord) -> Result<(), ErrorInfo> {
    if element.sensitive {
        return Err(ErrorInfo::new(
            error_kind::INPUT_BLOCKED,
            format!(
                "element '{}' is sensitive; its value is never exposed",
                element.name.as_deref().unwrap_or("<unnamed>")
            ),
        ));
    }

    Ok(())
}

fn ensure_enabled(element: &ElementRecord) -> Result<(), ErrorInfo> {
    if !element.enabled {
        return Err(ErrorInfo::new(
            error_kind::INPUT_BLOCKED,
            format!(
                "element '{}' is disabled",
                element.name.as_deref().unwrap_or("<unnamed>")
            ),
        ));
    }

    Ok(())
}

fn ensure_value_pattern(element: &ElementRecord) -> Result<(), ErrorInfo> {
    let has_value = element
        .patterns
        .iter()
        .any(|pattern| pattern == "Value" || pattern == "Text");

    if !has_value {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!(
                "element '{}' exposes neither Value nor Text",
                element.name.as_deref().unwrap_or("<unnamed>")
            ),
        ));
    }

    Ok(())
}

fn ensure_pattern(element: &ElementRecord, pattern: &str) -> Result<(), ErrorInfo> {
    if !element
        .patterns
        .iter()
        .any(|candidate| candidate == pattern)
    {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!(
                "element '{}' does not support {pattern}",
                element.name.as_deref().unwrap_or("<unnamed>")
            ),
        ));
    }

    Ok(())
}

fn process_matches(process_name: &str, query: &str) -> bool {
    if process_name.eq_ignore_ascii_case(query) {
        return true;
    }

    let stem = process_name
        .strip_suffix(".exe")
        .or_else(|| process_name.strip_suffix(".EXE"))
        .unwrap_or(process_name);

    stem.eq_ignore_ascii_case(query)
}

fn encode_png_ihdr(width: u32, height: u32) -> Vec<u8> {
    let mut header = Vec::with_capacity(13);
    header.extend_from_slice(&width.to_be_bytes());
    header.extend_from_slice(&height.to_be_bytes());
    header.extend_from_slice(&[8, 2, 0, 0, 0]);

    let mut chunk = Vec::with_capacity(4 + header.len());
    chunk.extend_from_slice(b"IHDR");
    chunk.extend_from_slice(&header);

    let mut png = Vec::with_capacity(8 + 4 + chunk.len() + 4);
    png.extend_from_slice(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]);
    png.extend_from_slice(&(header.len() as u32).to_be_bytes());
    png.extend_from_slice(&chunk);
    png.extend_from_slice(&crc32(&chunk).to_be_bytes());

    png
}

fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;

    for byte in bytes {
        crc ^= u32::from(*byte);

        for _ in 0..8 {
            let mask = (crc & 1).wrapping_neg();
            crc = (crc >> 1) ^ (0xEDB8_8320 & mask);
        }
    }

    !crc
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::{ActionArgs, Point};

    fn element_ref(id: u32) -> Option<ElementRef> {
        Some(ElementRef {
            id: Some(id),
            ..Default::default()
        })
    }

    fn action_request(action: &str, id: Option<u32>) -> ActionRequest {
        ActionRequest {
            window: WINDOW_TITLE.to_string(),
            action: action.to_string(),
            target: id.and_then(element_ref),
            args: ActionArgs::default(),
        }
    }

    fn snapshot_request() -> SnapshotRequest {
        SnapshotRequest {
            window: WINDOW_TITLE.to_string(),
            max_depth: None,
            max_elements: None,
            exclude_roles: Vec::new(),
            actionable: false,
        }
    }

    #[test]
    fn default_backend_is_ready_and_degraded_is_degraded() {
        assert_eq!(FakeBackend::default().health(), Health::Ready);
        assert_eq!(FakeBackend::ready().health(), Health::Ready);
        assert_eq!(FakeBackend::degraded().health(), Health::Degraded);
    }

    #[test]
    fn windows_include_primary_hidden_and_disabled() {
        let windows = FakeBackend::ready().windows().unwrap();

        assert_eq!(windows.len(), 3);
        assert_eq!(windows[0].handle, WINDOW_HANDLE);
        assert_eq!(windows[0].pid, WINDOW_PID);
        assert_eq!(windows[0].title, WINDOW_TITLE);
        assert_eq!(windows[0].process_name.as_deref(), Some(WINDOW_PROCESS));
        assert_eq!(windows[0].class_name.as_deref(), Some(WINDOW_CLASS));
        assert!(windows[0].foreground);
        assert!(windows[1].offscreen);
        assert!(windows[1].dialog);
        assert!(!windows[0].dialog);
        assert!(!windows[2].enabled);
    }

    #[test]
    fn window_matching_accepts_title_handle_and_process() {
        let backend = FakeBackend::ready();

        for query in [
            WINDOW_TITLE,
            "fake window",
            "Window",
            WINDOW_HANDLE,
            "0x1",
            WINDOW_PROCESS,
            "fake",
        ] {
            let snapshot = backend
                .snapshot(&SnapshotRequest {
                    window: query.to_string(),
                    max_depth: None,
                    max_elements: None,
                    exclude_roles: Vec::new(),
                    actionable: false,
                })
                .unwrap_or_else(|error| panic!("query '{query}' failed: {error}"));

            assert_eq!(snapshot.window.handle, WINDOW_HANDLE, "query '{query}'");
        }
    }

    #[test]
    fn hidden_and_disabled_windows_are_addressable_by_title() {
        let backend = FakeBackend::ready();

        let hidden = backend
            .snapshot(&SnapshotRequest {
                window: HIDDEN_WINDOW_TITLE.to_string(),
                max_depth: None,
                max_elements: None,
                exclude_roles: Vec::new(),
                actionable: false,
            })
            .unwrap();
        assert!(hidden.window.offscreen);

        let disabled = backend
            .snapshot(&SnapshotRequest {
                window: DISABLED_WINDOW_TITLE.to_string(),
                max_depth: None,
                max_elements: None,
                exclude_roles: Vec::new(),
                actionable: false,
            })
            .unwrap();
        assert!(!disabled.window.enabled);
    }

    #[test]
    fn unknown_window_is_target_not_found() {
        let backend = FakeBackend::ready();
        let error = backend
            .snapshot(&SnapshotRequest {
                window: "No Such Window".to_string(),
                max_depth: None,
                max_elements: None,
                exclude_roles: Vec::new(),
                actionable: false,
            })
            .unwrap_err();

        assert_eq!(error.kind, error_kind::TARGET_NOT_FOUND);
    }

    #[test]
    fn snapshot_has_all_elements_with_stable_ids() {
        let snapshot = FakeBackend::ready().snapshot(&snapshot_request()).unwrap();

        assert_eq!(snapshot.total_elements, ELEMENT_COUNT);
        assert_eq!(snapshot.elements.len() as u32, ELEMENT_COUNT);
        assert!(!snapshot.truncated);

        for (index, element) in snapshot.elements.iter().enumerate() {
            assert_eq!(element.id, index as u32);
            assert_eq!(element.runtime_id, format!("fake:{index}"));
            assert!(element
                .parent
                .map(|parent| parent < element.id)
                .unwrap_or(true));
        }

        assert_eq!(snapshot.elements[TEXT_EDITOR_ID as usize].depth, 2);
        assert_eq!(
            snapshot.elements[TEXT_EDITOR_ID as usize].parent,
            Some(EDITOR_PANE_ID)
        );
    }

    #[test]
    fn snapshot_truncates_by_depth_and_element_budget() {
        let backend = FakeBackend::ready();

        let by_depth = backend
            .snapshot(&SnapshotRequest {
                window: WINDOW_TITLE.to_string(),
                max_depth: Some(1),
                max_elements: None,
                exclude_roles: Vec::new(),
                actionable: false,
            })
            .unwrap();

        assert!(by_depth.truncated);
        assert_eq!(by_depth.total_elements, ELEMENT_COUNT);
        assert_eq!(by_depth.max_depth, 1);
        assert!(by_depth.elements.iter().all(|element| element.depth <= 1));

        let by_elements = backend
            .snapshot(&SnapshotRequest {
                window: WINDOW_TITLE.to_string(),
                max_depth: None,
                max_elements: Some(2),
                exclude_roles: Vec::new(),
                actionable: false,
            })
            .unwrap();

        assert!(by_elements.truncated);
        assert_eq!(by_elements.total_elements, ELEMENT_COUNT);
        assert_eq!(by_elements.elements.len(), 2);
        assert_eq!(by_elements.max_elements, 2);
        assert_eq!(by_elements.elements[0].id, 0);
        assert_eq!(by_elements.elements[1].id, 1);
    }

    #[test]
    fn set_value_round_trips_and_updates_snapshot() {
        let backend = FakeBackend::ready();
        let mut request = action_request("set_value", Some(TEXT_EDITOR_ID));
        request.args.value = Some("hello bridge".to_string());

        let result = backend.action(&request).unwrap();
        assert!(result.delivered);
        assert!(result.verified);
        assert_eq!(result.value.as_deref(), Some("hello bridge"));
        assert_eq!(
            backend
                .state()
                .values
                .get(&TEXT_EDITOR_ID)
                .map(String::as_str),
            Some("hello bridge")
        );

        let read = backend
            .action(&action_request("get_value", Some(TEXT_EDITOR_ID)))
            .unwrap();
        assert_eq!(read.value.as_deref(), Some("hello bridge"));

        let snapshot = backend.snapshot(&snapshot_request()).unwrap();
        assert_eq!(
            snapshot.elements[TEXT_EDITOR_ID as usize].value.as_deref(),
            Some("hello bridge")
        );
    }

    #[test]
    fn get_value_on_non_value_control_is_unsupported() {
        let error = FakeBackend::ready()
            .action(&action_request("get_value", Some(SAVE_BUTTON_ID)))
            .unwrap_err();

        assert_eq!(error.kind, error_kind::UNSUPPORTED);
    }

    #[test]
    fn sensitive_value_is_never_exposed() {
        let backend = FakeBackend::ready();

        let snapshot = backend.snapshot(&snapshot_request()).unwrap();
        let password = &snapshot.elements[PASSWORD_EDIT_ID as usize];
        assert!(password.sensitive);
        assert!(password.value.is_none());

        let error = backend
            .action(&action_request("get_value", Some(PASSWORD_EDIT_ID)))
            .unwrap_err();
        assert_eq!(error.kind, error_kind::INPUT_BLOCKED);

        let mut request = action_request("set_value", Some(PASSWORD_EDIT_ID));
        request.args.value = Some("guess".to_string());

        let error = backend.action(&request).unwrap_err();
        assert_eq!(error.kind, error_kind::INPUT_BLOCKED);
        assert_eq!(
            backend
                .state()
                .values
                .get(&PASSWORD_EDIT_ID)
                .map(String::as_str),
            Some(PASSWORD_SECRET)
        );
    }

    #[test]
    fn disabled_and_sensitive_actions_are_refused() {
        let backend = FakeBackend::ready();

        let invoke_error = backend
            .action(&action_request("invoke", Some(DELETE_BUTTON_ID)))
            .unwrap_err();
        assert_eq!(invoke_error.kind, error_kind::INPUT_BLOCKED);

        let mut request = action_request("set_value", Some(DELETE_BUTTON_ID));
        request.args.value = Some("x".to_string());
        let error = backend.action(&request).unwrap_err();
        assert_eq!(error.kind, error_kind::INPUT_BLOCKED);

        let mut window_request = action_request("click", None);
        window_request.window = DISABLED_WINDOW_TITLE.to_string();
        let window_error = backend.action(&window_request).unwrap_err();
        assert_eq!(window_error.kind, error_kind::INPUT_BLOCKED);
    }

    #[test]
    fn invoke_toggle_and_click_flip_state() {
        let backend = FakeBackend::ready();

        let invoke = backend
            .action(&action_request("invoke", Some(SAVE_BUTTON_ID)))
            .unwrap();
        assert!(invoke.delivered && invoke.verified);
        assert_eq!(backend.state().invoke_count, 1);
        assert_eq!(backend.state().last_invoked, Some(SAVE_BUTTON_ID));

        let toggle = backend
            .action(&action_request("toggle", Some(AGREE_CHECKBOX_ID)))
            .unwrap();
        assert!(toggle.verified);
        assert_eq!(toggle.value.as_deref(), Some("true"));
        assert_eq!(
            backend.state().toggled.get(&AGREE_CHECKBOX_ID).copied(),
            Some(true)
        );

        let click = backend
            .action(&action_request("click", Some(AGREE_CHECKBOX_ID)))
            .unwrap();
        assert!(click.delivered);
        assert_eq!(
            backend.state().toggled.get(&AGREE_CHECKBOX_ID).copied(),
            Some(false)
        );
        assert_eq!(backend.state().click_count, 1);
    }

    #[test]
    fn strong_selectors_win_over_a_shared_role() {
        let backend = FakeBackend::ready();
        let mut request = action_request("invoke", Some(DELETE_BUTTON_ID));
        let target = request.target.clone().expect("target");
        request.target = Some(ElementRef {
            name: target.name,
            role: Some("Button".to_string()),
            ..target
        });

        let error = backend.action(&request).expect_err("refused");

        assert_eq!(error.kind, error_kind::INPUT_BLOCKED);
        assert!(error.message.contains("Delete"));
    }

    #[test]
    fn activate_records_the_window() {
        let backend = FakeBackend::ready();

        let result = backend.action(&action_request("activate", None)).unwrap();

        assert!(result.delivered);
        assert_eq!(backend.state().activated.as_deref(), Some(WINDOW_TITLE));
    }

    #[test]
    fn keys_focus_and_scroll_are_delivered() {
        let backend = FakeBackend::ready();

        let mut keys = action_request("keys", Some(TEXT_EDITOR_ID));
        keys.args.keys = Some("^s".to_string());
        assert!(backend.action(&keys).unwrap().delivered);
        assert_eq!(backend.state().last_keys.as_deref(), Some("^s"));

        let focus = backend
            .action(&action_request("focus", Some(TEXT_EDITOR_ID)))
            .unwrap();
        assert!(focus.delivered && focus.verified);
        assert_eq!(backend.state().focused, Some(TEXT_EDITOR_ID));

        let mut scroll = action_request("scroll", Some(TEXT_EDITOR_ID));
        scroll.args.direction = Some("down".to_string());
        scroll.args.amount = Some(5);
        assert!(backend.action(&scroll).unwrap().delivered);
        assert_eq!(backend.state().scrolls, vec![("down".to_string(), 5)]);
    }

    #[test]
    fn click_with_point_is_delivered_without_target() {
        let backend = FakeBackend::ready();
        let mut request = action_request("click", None);
        request.args.point = Some(Point { x: 30, y: 40 });

        assert!(backend.action(&request).unwrap().delivered);
        assert_eq!(backend.state().click_count, 1);
    }

    #[test]
    fn unknown_action_and_target_are_rejected() {
        let backend = FakeBackend::ready();

        let action_error = backend
            .action(&action_request("levitate", Some(TEXT_EDITOR_ID)))
            .unwrap_err();
        assert_eq!(action_error.kind, error_kind::INVALID_REQUEST);

        let target_error = backend
            .action(&action_request("get_value", Some(999)))
            .unwrap_err();
        assert_eq!(target_error.kind, error_kind::TARGET_NOT_FOUND);

        let missing_target = backend
            .action(&action_request("get_value", None))
            .unwrap_err();
        assert_eq!(missing_target.kind, error_kind::INVALID_REQUEST);

        let by_name = backend
            .action(&ActionRequest {
                window: WINDOW_TITLE.to_string(),
                action: "invoke".to_string(),
                target: Some(ElementRef {
                    name: Some("Save".to_string()),
                    ..Default::default()
                }),
                args: ActionArgs::default(),
            })
            .unwrap();
        assert!(by_name.delivered);
    }

    #[test]
    fn screenshot_is_png_with_ihdr() {
        let png = FakeBackend::ready()
            .screenshot(&ScreenshotRequest {
                window: WINDOW_TITLE.to_string(),
            })
            .unwrap();

        assert_eq!(&png[..8], &[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]);
        assert_eq!(&png[12..16], b"IHDR");
        assert_eq!(u32::from_be_bytes(png[16..20].try_into().unwrap()), 400);
        assert_eq!(u32::from_be_bytes(png[20..24].try_into().unwrap()), 300);
        assert_eq!(u32::from_be_bytes(png[8..12].try_into().unwrap()), 13);

        let expected_crc = crc32(&png[12..29]);
        assert_eq!(
            u32::from_be_bytes(png[29..33].try_into().unwrap()),
            expected_crc
        );
    }

    #[test]
    fn png_crc_matches_known_vector() {
        assert_eq!(crc32(b"123456789"), 0xCBF4_3926);
    }

    #[test]
    fn doctor_reports_backend_loopback_and_input() {
        let ready = FakeBackend::ready().doctor();
        assert_eq!(ready.health, Health::Ready);
        assert!(ready.checks.iter().all(|check| check.ok));
        assert!(ready
            .checks
            .iter()
            .any(|check| check.name == "loopback" && check.ok));

        let degraded = FakeBackend::degraded().doctor();
        assert_eq!(degraded.health, Health::Degraded);
        assert!(degraded
            .checks
            .iter()
            .any(|check| check.name == "input" && !check.ok));
        assert!(degraded
            .checks
            .iter()
            .any(|check| check.name == "backend" && check.ok));
    }

    #[test]
    fn capabilities_cover_the_protocol_surface() {
        let capabilities = FakeBackend::ready().capabilities();
        for expected in ["windows", "snapshot", "action", "screenshot", "dialogs"] {
            assert!(capabilities.iter().any(|value| value == expected));
        }
    }
}
