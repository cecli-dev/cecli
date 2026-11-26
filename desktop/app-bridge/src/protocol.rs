//! Wire protocol types shared by the bridge server, platform backends, and the
//! Python client.
//!
//! Every HTTP response is a JSON envelope:
//!
//! ```json
//! {"ok": true, "action": "snapshot", "data": {}, "error": null, "health": "ready"}
//! ```
//!
//! Errors use a stable `type` string so clients can branch on the failure kind
//! instead of parsing messages. See [`ErrorKind`] for the full set.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Version of this crate, reported in `bridge.json` and `/api/app/state`.
pub const BRIDGE_VERSION: &str = env!("CARGO_PKG_VERSION");

/// Minimum bridge version the Python client accepts.
pub const MIN_COMPATIBLE_VERSION: &str = BRIDGE_VERSION;

/// Health of the bridge or a single backend call.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Health {
    /// Everything the backend needs is available.
    Ready,
    /// The backend works but a capability or permission is missing.
    Degraded,
    /// The backend cannot serve requests at all.
    #[default]
    Unavailable,
}

impl Health {
    /// Lowercase wire representation.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Ready => "ready",
            Self::Degraded => "degraded",
            Self::Unavailable => "unavailable",
        }
    }
}

/// Stable error identifiers used by the client and the tests.
pub mod error_kind {
    pub const BRIDGE_UNAVAILABLE: &str = "bridge_unavailable";
    pub const VERSION_MISMATCH: &str = "version_mismatch";
    pub const NO_PERMISSION: &str = "no_permission";
    pub const ELEVATED_TARGET: &str = "elevated_target";
    pub const CAPTURE_EXCLUDED: &str = "capture_excluded";
    pub const UNCERTAIN: &str = "uncertain";
    pub const INPUT_BLOCKED: &str = "input_blocked";
    pub const TARGET_NOT_FOUND: &str = "target_not_found";
    pub const STALE_TARGET: &str = "stale_target";
    pub const INVALID_REQUEST: &str = "invalid_request";
    pub const BACKEND_ERROR: &str = "backend_error";
    pub const TIMEOUT: &str = "timeout";
    pub const UNSUPPORTED: &str = "unsupported";
    pub const UNAUTHORIZED: &str = "unauthorized";
    pub const NOT_FOUND: &str = "not_found";
}

/// Path that actually delivered an action.
pub mod outcome {
    pub const ACCESSIBILITY: &str = "accessibility";
    pub const POINTER: &str = "pointer";
    pub const KEYSTROKE: &str = "keystroke";
    pub const NONE: &str = "none";
}

/// How an action should treat the user's foreground window.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum DeliveryMode {
    /// Restore the previous foreground window after the action.
    #[default]
    Background,
    /// Leave the target in front after the action.
    Foreground,
}

impl DeliveryMode {
    /// True when the caller explicitly wants visible foreground control.
    pub fn is_foreground(self) -> bool {
        self == Self::Foreground
    }
}

/// Structured diagnosis attached to a failed selector lookup.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ErrorDetails {
    /// Human-readable near-miss elements, most similar first.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub candidates: Vec<String>,
    /// Description of the last element observed in the searched snapshot.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_observed: Option<String>,
    /// Snapshot or search scope the diagnosis ran against.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scope: Option<String>,
}

/// A structured bridge failure.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ErrorInfo {
    /// Stable machine-readable kind, e.g. `input_blocked`.
    #[serde(rename = "type")]
    pub kind: String,
    /// Human-readable detail.
    pub message: String,
    /// Optional structured diagnosis for selector and lookup failures.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub details: Option<ErrorDetails>,
}

impl ErrorInfo {
    /// Build an error from a stable kind and a message.
    pub fn new(kind: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            kind: kind.into(),
            message: message.into(),
            details: None,
        }
    }

    /// Wrap a backend or transport error as `backend_error`.
    pub fn backend(message: impl Into<String>) -> Self {
        Self::new(error_kind::BACKEND_ERROR, message)
    }

    /// Invalid request payloads.
    pub fn invalid(message: impl Into<String>) -> Self {
        Self::new(error_kind::INVALID_REQUEST, message)
    }

    /// Attach structured diagnosis, replacing any earlier details.
    pub fn with_details(mut self, details: ErrorDetails) -> Self {
        self.details = Some(details);
        self
    }
}

impl std::fmt::Display for ErrorInfo {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.kind, self.message)
    }
}

impl std::error::Error for ErrorInfo {}

/// Response envelope used by every JSON endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Envelope {
    pub ok: bool,
    pub action: String,
    pub data: Value,
    pub error: Option<ErrorInfo>,
    pub health: Health,
    /// Non-fatal degradations, e.g. a cached screenshot or a cut walk.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub notes: Vec<String>,
}

impl Envelope {
    /// Successful envelope with a JSON payload.
    pub fn ok(action: impl Into<String>, data: Value, health: Health) -> Self {
        Self {
            ok: true,
            action: action.into(),
            data,
            error: None,
            health,
            notes: Vec::new(),
        }
    }

    /// Successful envelope that also reports non-fatal notes.
    pub fn ok_with_notes(
        action: impl Into<String>,
        data: Value,
        health: Health,
        notes: Vec<String>,
    ) -> Self {
        Self {
            notes,
            ..Self::ok(action, data, health)
        }
    }

    /// Append non-fatal notes to this envelope.
    pub fn with_notes(mut self, notes: impl IntoIterator<Item = String>) -> Self {
        self.notes.extend(notes);
        self
    }

    /// Failure envelope. `data` stays an empty object.
    pub fn fail(action: impl Into<String>, error: ErrorInfo, health: Health) -> Self {
        Self {
            ok: false,
            action: action.into(),
            data: Value::Object(serde_json::Map::new()),
            error: Some(error),
            health,
            notes: Vec::new(),
        }
    }

    /// Encode with a trailing newline so line-oriented tools stay happy.
    pub fn to_json(&self) -> String {
        let mut encoded = serde_json::to_string(self).unwrap_or_else(|_| {
            "{\"ok\":false,\"action\":\"internal\",\"data\":{},\"error\":{\"type\":\"backend_error\",\"message\":\"encoding failed\"},\"health\":\"unavailable\"}".to_string()
        });
        encoded.push('\n');
        encoded
    }
}

/// Screen-space rectangle in physical pixels.
#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct Bounds {
    pub left: i32,
    pub top: i32,
    pub width: i32,
    pub height: i32,
}

/// A point in screen coordinates.
#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct Point {
    pub x: i32,
    pub y: i32,
}

/// Pointer button used by click and drag actions.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum PointerButton {
    #[default]
    Left,
    Right,
    Middle,
}

impl PointerButton {
    /// Parse a wire button name; an absent or empty value means left.
    pub fn parse(value: Option<&str>) -> Result<Self, String> {
        let Some(name) = value.map(str::trim).filter(|name| !name.is_empty()) else {
            return Ok(Self::Left);
        };

        match name.to_ascii_lowercase().as_str() {
            "left" => Ok(Self::Left),
            "right" => Ok(Self::Right),
            "middle" => Ok(Self::Middle),
            other => Err(format!(
                "unsupported button '{other}'; expected left, right, or middle"
            )),
        }
    }

    /// Lowercase wire name.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Left => "left",
            Self::Right => "right",
            Self::Middle => "middle",
        }
    }

    /// X11 button number (1 left, 2 middle, 3 right).
    pub fn x11_button(self) -> u8 {
        match self {
            Self::Left => 1,
            Self::Middle => 2,
            Self::Right => 3,
        }
    }

    /// CoreGraphics mouse button number (0 left, 1 right, 2 middle).
    pub fn macos_button(self) -> u32 {
        match self {
            Self::Left => 0,
            Self::Right => 1,
            Self::Middle => 2,
        }
    }
}

/// Visible top-level window reported by the backend.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct WindowInfo {
    /// Platform handle encoded as a string: HWND, AX identifier, or X11 id.
    pub handle: String,
    pub pid: u32,
    pub process_name: Option<String>,
    pub title: String,
    pub class_name: Option<String>,
    pub bounds: Bounds,
    pub foreground: bool,
    pub enabled: bool,
    pub offscreen: bool,
    /// True when the window looks like a modal dialog or an owned popup.
    #[serde(default)]
    pub dialog: bool,
}

/// Snapshot request body.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SnapshotRequest {
    /// Window title, process name, or handle.
    pub window: String,
    #[serde(default)]
    pub max_depth: Option<u32>,
    #[serde(default)]
    pub max_elements: Option<u32>,
    /// Roles whose subtrees are skipped entirely (e.g. `Menu`, `Separator`).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub exclude_roles: Vec<String>,
    /// Keep only actionable, landmark, and informative nodes.
    #[serde(default)]
    pub actionable: bool,
}

/// Scroll offsets and viewport share for a scrollable control.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ScrollState {
    /// Horizontal offset as a percentage of the scrollable range.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub horizontal_percent: Option<f64>,
    /// Vertical offset as a percentage of the scrollable range.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub vertical_percent: Option<f64>,
    /// Share of the content visible horizontally, as a percentage.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub horizontal_view_percent: Option<f64>,
    /// Share of the content visible vertically, as a percentage.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub vertical_view_percent: Option<f64>,
    /// True when the control can scroll horizontally.
    #[serde(default, skip_serializing_if = "is_false")]
    pub horizontal: bool,
    /// True when the control can scroll vertically.
    #[serde(default, skip_serializing_if = "is_false")]
    pub vertical: bool,
}

fn is_false(value: &bool) -> bool {
    !*value
}
/// One accessibility node inside a snapshot.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct ElementRecord {
    /// Connection-scoped index used by actions in this run.
    pub id: u32,
    /// Parent index inside the same snapshot, if any.
    pub parent: Option<u32>,
    pub depth: u32,
    /// Platform runtime identifier (UIA runtime id, AX path, AT-SPI path).
    pub runtime_id: String,
    pub control_type: String,
    pub name: Option<String>,
    pub automation_id: Option<String>,
    pub class_name: Option<String>,
    /// Value is omitted for password and otherwise sensitive controls.
    pub value: Option<String>,
    pub enabled: bool,
    pub offscreen: bool,
    pub bounds: Option<Bounds>,
    pub patterns: Vec<String>,
    /// True when the control holds secret text; `value` is always `None`.
    pub sensitive: bool,
    /// Stable role/name path from the window root; survives across runs.
    #[serde(default)]
    pub path: Option<String>,
    /// Scroll offsets and viewport share when the control scrolls.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub scroll: Option<ScrollState>,
}

/// Snapshot response payload.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Snapshot {
    pub window: WindowInfo,
    pub elements: Vec<ElementRecord>,
    /// True when any budget, child cap, or deadline cut the walk short.
    pub truncated: bool,
    /// Dominant reason the walk stopped: `max_elements`, `max_depth`,
    /// `max_children`, or `time`. Absent when the snapshot is complete.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub truncated_by: Option<String>,
    /// Children dropped by the per-node child cap, summed over all nodes.
    #[serde(default)]
    pub children_cut: u32,
    pub max_depth: u32,
    pub max_elements: u32,
    /// Total nodes observed before truncation.
    pub total_elements: u32,
}

/// Structured accessibility query evaluated during the tree walk.
///
/// The walk stops as soon as `limit` matches have been stored, so callers can
/// search a huge subtree (for example a spreadsheet grid) without reading the
/// whole thing. `max_depth`, `max_elements`, `exclude_roles`, and the per-node
/// child cap apply exactly as they do for [`SnapshotRequest`].
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FindRequest {
    /// Window title, process name, or handle.
    pub window: String,
    #[serde(default)]
    pub max_depth: Option<u32>,
    #[serde(default)]
    pub max_elements: Option<u32>,
    /// Roles whose subtrees are skipped entirely.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub exclude_roles: Vec<String>,
    /// Stop after this many stored matches. `0` is treated as unset.
    #[serde(default)]
    pub limit: Option<u32>,
    pub r#match: MatchSpec,
}

/// Node predicates for [`FindRequest`]. Every present field must match.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct MatchSpec {
    /// Role names matched case-insensitively against the control type or the
    /// platform role name. Empty means any role.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub roles: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<StringMatch>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value: Option<StringMatch>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sensitive: Option<bool>,
}

/// Case-insensitive string predicate used by [`MatchSpec`].
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct StringMatch {
    /// `eq`, `contains`, `prefix`, or `suffix`; anything else is treated as `eq`.
    #[serde(default = "default_match_op")]
    pub op: String,
    pub value: String,
}

impl Default for StringMatch {
    fn default() -> Self {
        Self {
            op: default_match_op(),
            value: String::new(),
        }
    }
}

/// Default [`StringMatch`] operator.
pub fn default_match_op() -> String {
    "eq".to_string()
}

/// Result of [`crate::Backend::find`].
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FindResult {
    /// Stored matches, at most `limit` when one was supplied.
    pub matches: Vec<ElementRecord>,
    /// Every match seen, including any beyond `limit`.
    pub match_count: u32,
    /// True when a limit, budget, child cap, depth cap, or deadline cut the walk.
    pub truncated: bool,
    /// Dominant reason: `limit`, `time`, `max_elements`, `max_children`, or
    /// `max_depth`. Absent when the result is complete.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub truncated_by: Option<String>,
}

/// Reference to an element, valid only inside one connection/run.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ElementRef {
    #[serde(default)]
    pub id: Option<u32>,
    #[serde(default)]
    pub runtime_id: Option<String>,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub automation_id: Option<String>,
    /// Stable role/name path from the window root, e.g. `Frame[Title]/Panel/Button[Save]`.
    #[serde(default)]
    pub path: Option<String>,
}

impl ElementRef {
    /// True when the reference carries no selector at all.
    pub fn is_empty(&self) -> bool {
        self.id.is_none()
            && self.runtime_id.is_none()
            && self.name.is_none()
            && self.role.is_none()
            && self.automation_id.is_none()
            && self.path.is_none()
    }
}

/// Action request body.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActionRequest {
    /// Window title, process name, or handle.
    pub window: String,
    /// `invoke`, `set_value`, `get_value`, `click`, `keys`, `focus`, `scroll`,
    /// `scroll_to`, or another backend action.
    pub action: String,
    #[serde(default)]
    pub target: Option<ElementRef>,
    #[serde(default)]
    pub args: ActionArgs,
}

/// Optional arguments for every action. Unknown keys are preserved in `extra`.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct ActionArgs {
    /// Text for `set_value`; never written for password controls.
    pub value: Option<String>,
    /// Keystroke specification for `keys`, e.g. `^s` or `{ENTER}`.
    pub keys: Option<String>,
    /// Absolute screen point for an explicit global click.
    pub point: Option<Point>,
    /// Scroll direction: `up`, `down`, `left`, `right`.
    pub direction: Option<String>,
    /// Scroll amount in wheel notches or pixels, backend defined.
    pub amount: Option<i32>,
    /// Absolute horizontal scroll target as a percentage (0-100).
    pub horizontal_percent: Option<f64>,
    /// Absolute vertical scroll target as a percentage (0-100).
    pub vertical_percent: Option<f64>,
    /// Zero-based row for `cell_at`.
    #[serde(default)]
    pub row: Option<u32>,
    /// Zero-based column for `cell_at`.
    #[serde(default)]
    pub column: Option<u32>,
    /// Pointer button: `left`, `right`, or `middle`; defaults to left.
    #[serde(default)]
    pub button: Option<String>,
    /// Click repeat count; `2` is a double click. Defaults to one.
    #[serde(default)]
    pub count: Option<u32>,
    /// Literal text for text-entry helpers.
    #[serde(default)]
    pub text: Option<String>,
    /// Absolute destination for `drag`.
    #[serde(default)]
    pub to_point: Option<Point>,
    /// Drag duration in milliseconds.
    #[serde(default)]
    pub duration_ms: Option<u32>,
    /// Restore the previous foreground window (`background`, default) or
    /// leave the target in front (`foreground`).
    #[serde(default)]
    pub delivery_mode: DeliveryMode,
    /// Extra backend-specific options.
    pub extra: BTreeMap<String, Value>,
}

impl ActionArgs {
    /// Parsed pointer button, defaulting to left.
    pub fn pointer_button(&self) -> Result<PointerButton, ErrorInfo> {
        PointerButton::parse(self.button.as_deref()).map_err(ErrorInfo::invalid)
    }

    /// Repeat count for a click, defaulting to `default` and never below one.
    pub fn click_count(&self, default: u32) -> u32 {
        self.count.unwrap_or(default).max(1)
    }

    /// Drag duration bounded so a bad payload cannot stall the bridge.
    pub fn drag_duration(&self) -> u64 {
        u64::from(self.duration_ms.unwrap_or(250).min(10_000))
    }
    /// Requested absolute scroll position, rejecting out-of-range percentages.
    pub fn scroll_target(&self) -> Result<(Option<f64>, Option<f64>), String> {
        if self.horizontal_percent.is_none() && self.vertical_percent.is_none() {
            return Err(
                "scroll_to needs args.horizontal_percent or args.vertical_percent".to_string(),
            );
        }

        for (name, value) in [
            ("horizontal_percent", self.horizontal_percent),
            ("vertical_percent", self.vertical_percent),
        ] {
            if let Some(value) = value {
                if !(0.0..=100.0).contains(&value) {
                    return Err(format!("{name} must be between 0 and 100, not {value}"));
                }
            }
        }

        Ok((self.horizontal_percent, self.vertical_percent))
    }
}

/// Action response payload.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ActionResult {
    pub action: String,
    /// True when the input reached the target or the pattern call returned.
    pub delivered: bool,
    /// True when a follow-up observation confirmed the effect.
    pub verified: bool,
    /// True when a timeout leaves the outcome unknown. Never auto-retried.
    pub uncertain: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    /// Path that actually delivered the action: `accessibility`, `pointer`,
    /// `keystroke`, or `none`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub outcome: Option<String>,
}

impl ActionResult {
    /// Pattern call that succeeded and needs no read-back.
    pub fn delivered(action: impl Into<String>) -> Self {
        Self {
            action: action.into(),
            delivered: true,
            verified: true,
            uncertain: false,
            ..Default::default()
        }
    }

    /// Pattern call that succeeded, tagged with the delivery path that fired.
    pub fn delivered_with(action: impl Into<String>, outcome: &str) -> Self {
        Self {
            outcome: Some(outcome.to_string()),
            ..Self::delivered(action)
        }
    }

    /// A timed-out send: delivered, unverified, uncertain.
    pub fn uncertain(action: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            action: action.into(),
            delivered: true,
            verified: false,
            uncertain: true,
            value: None,
            message: Some(message.into()),
            outcome: None,
        }
    }
}

/// Screenshot request body.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScreenshotRequest {
    pub window: String,
}

/// `/api/app/state` payload.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct StateInfo {
    pub platform: String,
    pub version: String,
    pub backend: String,
    pub capabilities: Vec<String>,
    pub health: Health,
    pub pid: u32,
    pub mode: String,
    pub protocol_version: String,
}

/// Result of one diagnostic check.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CheckResult {
    pub name: String,
    pub ok: bool,
    pub detail: String,
}

impl CheckResult {
    pub fn new(name: impl Into<String>, ok: bool, detail: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            ok,
            detail: detail.into(),
        }
    }
}

/// `/api/app/doctor` payload.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DoctorReport {
    pub platform: String,
    pub backend: String,
    pub health: Health,
    /// Permission name to state, e.g. `accessibility` -> `granted`.
    pub permissions: BTreeMap<String, String>,
    pub checks: Vec<CheckResult>,
    pub notes: Vec<String>,
}

/// Contents of `bridge.json`, used by clients to find the loopback server.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BridgeFile {
    pub version: String,
    pub platform: String,
    pub host: String,
    pub port: u16,
    pub token: String,
    pub pid: u32,
    pub mode: String,
    #[serde(default)]
    pub started_at: String,
}

impl BridgeFile {
    /// Base URL for requests.
    pub fn base_url(&self) -> String {
        format!("http://{}:{}", self.host, self.port)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn envelope_round_trips() {
        let envelope = Envelope::ok("state", serde_json::json!({"a": 1}), Health::Ready);
        let decoded: Envelope = serde_json::from_str(&envelope.to_json()).unwrap();
        assert!(decoded.ok);
        assert_eq!(decoded.action, "state");
        assert_eq!(decoded.health, Health::Ready);
        assert!(decoded.error.is_none());
    }

    #[test]
    fn failures_encode_type_not_kind() {
        let envelope = Envelope::fail(
            "action",
            ErrorInfo::new(error_kind::INPUT_BLOCKED, "disabled"),
            Health::Degraded,
        );
        let value: Value = serde_json::from_str(&envelope.to_json()).unwrap();
        assert_eq!(value["error"]["type"], "input_blocked");
        assert!(value["error"].get("kind").is_none());
    }

    #[test]
    fn element_ref_empty_detection() {
        assert!(ElementRef::default().is_empty());
        assert!(!ElementRef {
            name: Some("Save".into()),
            ..Default::default()
        }
        .is_empty());
    }

    #[test]
    fn snapshot_truncation_fields_are_optional_on_the_wire() {
        let value = serde_json::to_value(Snapshot::default()).unwrap();

        assert!(value.get("truncated_by").is_none());
        assert_eq!(value["children_cut"], 0);
    }

    #[test]
    fn snapshot_truncation_fields_round_trip_when_set() {
        let snapshot = Snapshot {
            truncated: true,
            truncated_by: Some("max_children".to_string()),
            children_cut: 42,
            ..Default::default()
        };
        let value = serde_json::to_value(&snapshot).unwrap();

        assert_eq!(value["truncated"], true);
        assert_eq!(value["truncated_by"], "max_children");
        assert_eq!(value["children_cut"], 42);
    }

    #[test]
    fn legacy_snapshots_without_truncation_fields_still_decode() {
        let mut value = serde_json::to_value(Snapshot::default()).unwrap();
        let object = value.as_object_mut().unwrap();
        object.remove("truncated_by");
        object.remove("children_cut");

        let decoded: Snapshot = serde_json::from_value(value).unwrap();

        assert!(decoded.truncated_by.is_none());
        assert_eq!(decoded.children_cut, 0);
    }

    #[test]
    fn find_request_defaults_when_only_window_and_match_are_given() {
        let request: FindRequest =
            serde_json::from_str(r#"{"window":"Sheet","match":{}}"#).unwrap();

        assert_eq!(request.window, "Sheet");
        assert!(request.max_depth.is_none());
        assert!(request.max_elements.is_none());
        assert!(request.exclude_roles.is_empty());
        assert!(request.limit.is_none());
        assert!(request.r#match.roles.is_empty());
        assert!(request.r#match.name.is_none());
        assert!(request.r#match.value.is_none());
        assert!(request.r#match.enabled.is_none());
        assert!(request.r#match.sensitive.is_none());
    }

    #[test]
    fn string_match_defaults_to_eq_and_applies_no_op_to_missing_field() {
        let matcher: StringMatch = serde_json::from_str(r#"{"value":"Save"}"#).unwrap();
        assert_eq!(matcher.op, "eq");
        assert_eq!(StringMatch::default().op, "eq");

        let request: FindRequest = serde_json::from_str(
            r#"{"window":"W","match":{"name":{"value":"Save"},"enabled":true}}"#,
        )
        .unwrap();
        let name = request.r#match.name.expect("name matcher");
        assert_eq!(name.op, "eq");
        assert_eq!(name.value, "Save");
        assert_eq!(request.r#match.enabled, Some(true));
    }

    #[test]
    fn find_result_omits_absent_truncation_reason() {
        let value = serde_json::to_value(FindResult::default()).unwrap();

        assert!(value.get("truncated_by").is_none());
        assert_eq!(value["match_count"], 0);
        assert_eq!(value["truncated"], false);

        let truncated = FindResult {
            match_count: 7,
            truncated: true,
            truncated_by: Some("limit".to_string()),
            ..Default::default()
        };
        let value = serde_json::to_value(truncated).unwrap();
        assert_eq!(value["truncated_by"], "limit");
        assert_eq!(value["match_count"], 7);
    }

    #[test]
    fn cell_at_args_default_to_none() {
        let args: ActionArgs = serde_json::from_str("{\"value\":\"x\"}").unwrap();
        assert!(args.row.is_none());
        assert!(args.column.is_none());

        let args: ActionArgs = serde_json::from_str(r#"{"row":3,"column":2}"#).unwrap();
        assert_eq!(args.row, Some(3));
        assert_eq!(args.column, Some(2));
    }
    #[test]
    fn error_details_are_omitted_when_absent_and_round_trip_when_set() {
        let plain = ErrorInfo::new(error_kind::TARGET_NOT_FOUND, "missing");
        let value = serde_json::to_value(&plain).unwrap();

        assert!(value.get("details").is_none());
        assert_eq!(value["type"], "target_not_found");
        assert_eq!(value["message"], "missing");

        let detailed = plain.with_details(ErrorDetails {
            candidates: vec!["id=1 Button \"Save\"".to_string()],
            last_observed: Some("id=4 Text \"Status\"".to_string()),
            scope: Some("latest snapshot holds 4 of 4 elements".to_string()),
        });
        let value = serde_json::to_value(&detailed).unwrap();

        assert_eq!(value["details"]["candidates"][0], "id=1 Button \"Save\"");
        assert_eq!(value["details"]["last_observed"], "id=4 Text \"Status\"");
        assert_eq!(
            value["details"]["scope"],
            "latest snapshot holds 4 of 4 elements"
        );
    }

    #[test]
    fn snapshot_request_actionable_defaults_to_false() {
        let request: SnapshotRequest = serde_json::from_str(r#"{"window":"W"}"#).unwrap();
        assert!(!request.actionable);

        let enabled: SnapshotRequest =
            serde_json::from_str(r#"{"window":"W","actionable":true}"#).unwrap();
        assert!(enabled.actionable);
    }
    #[test]
    fn envelope_notes_are_absent_when_empty_and_present_when_set() {
        let plain = Envelope::ok("state", serde_json::json!({}), Health::Ready);
        let value = serde_json::to_value(&plain).unwrap();
        assert!(value.get("notes").is_none());

        let noted = Envelope::ok("state", serde_json::json!({}), Health::Ready)
            .with_notes(["served from cache".to_string()]);
        let value = serde_json::to_value(&noted).unwrap();
        assert_eq!(value["notes"][0], "served from cache");
    }

    #[test]
    fn ok_with_notes_round_trips() {
        let envelope = Envelope::ok_with_notes(
            "snapshot",
            serde_json::json!({}),
            Health::Ready,
            vec!["snapshot cut by max_elements (kept 10)".to_string()],
        );
        let decoded: Envelope = serde_json::from_str(&envelope.to_json()).unwrap();

        assert_eq!(decoded.notes, envelope.notes);
    }

    #[test]
    fn action_outcome_is_optional_on_the_wire() {
        let plain = ActionResult::delivered("invoke");
        let value = serde_json::to_value(&plain).unwrap();
        assert!(value.get("outcome").is_none());

        let tagged = ActionResult::delivered_with("invoke", outcome::ACCESSIBILITY);
        let value = serde_json::to_value(&tagged).unwrap();
        assert_eq!(value["outcome"], "accessibility");
    }
    #[test]
    fn pointer_button_parses_names_and_defaults_to_left() {
        assert_eq!(PointerButton::parse(None), Ok(PointerButton::Left));
        assert_eq!(PointerButton::parse(Some("  ")), Ok(PointerButton::Left));
        assert_eq!(
            PointerButton::parse(Some("RIGHT")),
            Ok(PointerButton::Right)
        );
        assert_eq!(
            PointerButton::parse(Some("middle")),
            Ok(PointerButton::Middle)
        );
        assert!(PointerButton::parse(Some("thumb")).is_err());
        assert_eq!(PointerButton::Right.x11_button(), 3);
        assert_eq!(PointerButton::Middle.macos_button(), 2);
    }

    #[test]
    fn action_args_click_and_drag_fields_default_for_old_payloads() {
        let args: ActionArgs = serde_json::from_str(r#"{"value":"x"}"#).unwrap();
        assert!(args.button.is_none());
        assert_eq!(args.click_count(1), 1);
        assert_eq!(args.pointer_button().unwrap(), PointerButton::Left);
        assert_eq!(args.drag_duration(), 250);
        assert!(args.to_point.is_none());
        assert!(args.text.is_none());

        let args: ActionArgs = serde_json::from_str(
            r#"{"button":"right","count":2,"to_point":{"x":3,"y":4},"duration_ms":80}"#,
        )
        .unwrap();
        assert_eq!(args.pointer_button().unwrap(), PointerButton::Right);
        assert_eq!(args.click_count(1), 2);
        assert_eq!(args.to_point, Some(Point { x: 3, y: 4 }));
        assert_eq!(args.drag_duration(), 80);
    }

    #[test]
    fn window_dialog_defaults_to_false_and_round_trips() {
        let mut value = serde_json::to_value(WindowInfo::default()).unwrap();
        value.as_object_mut().unwrap().remove("dialog");
        let decoded: WindowInfo = serde_json::from_value(value).unwrap();
        assert!(!decoded.dialog);

        let window = WindowInfo {
            dialog: true,
            ..Default::default()
        };
        assert_eq!(serde_json::to_value(window).unwrap()["dialog"], true);
    }
    #[test]
    fn delivery_mode_defaults_to_background_and_parses_foreground() {
        assert_eq!(
            ActionArgs::default().delivery_mode,
            DeliveryMode::Background
        );

        let args: ActionArgs = serde_json::from_str(r#"{"delivery_mode":"foreground"}"#).unwrap();
        assert_eq!(args.delivery_mode, DeliveryMode::Foreground);

        let args: ActionArgs = serde_json::from_str(r#"{"value":"x"}"#).unwrap();
        assert_eq!(args.delivery_mode, DeliveryMode::Background);
    }

    #[test]
    fn delivery_mode_rejects_unknown_values() {
        assert!(serde_json::from_str::<ActionArgs>(r#"{"delivery_mode":"front"}"#).is_err());
    }

    #[test]
    fn scroll_target_requires_and_parses_percentages() {
        assert!(ActionArgs::default().scroll_target().is_err());

        let args = ActionArgs {
            vertical_percent: Some(50.0),
            ..Default::default()
        };
        assert_eq!(args.scroll_target().unwrap(), (None, Some(50.0)));

        let args = ActionArgs {
            horizontal_percent: Some(0.0),
            vertical_percent: Some(100.0),
            ..Default::default()
        };
        assert_eq!(args.scroll_target().unwrap(), (Some(0.0), Some(100.0)));

        for invalid in [-1.0, 101.0] {
            let args = ActionArgs {
                horizontal_percent: Some(invalid),
                ..Default::default()
            };
            assert!(args.scroll_target().is_err(), "{invalid} must be refused");
        }
    }

    #[test]
    fn scroll_state_round_trips_and_skips_unset_axes() {
        let state = ScrollState {
            vertical_percent: Some(25.0),
            vertical: true,
            ..Default::default()
        };
        let value = serde_json::to_value(&state).unwrap();

        assert_eq!(
            value,
            serde_json::json!({"vertical_percent": 25.0, "vertical": true})
        );
        assert_eq!(serde_json::from_value::<ScrollState>(value).unwrap(), state);
    }
}
