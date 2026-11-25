//! Protocol conformance and fake-backend behavior tests owned by T4.
//!
//! These tests pin the wire contract the Python client and the platform
//! backends must keep: stable error identifiers, redaction of sensitive values,
//! explicit truncation budgets, refusal of blocked input, value round-trips,
//! PNG screenshots, and observable timeouts.

use ce_app_bridge::backend::fake::{
    FakeBackend, AGREE_CHECKBOX_ID, DELETE_BUTTON_ID, DISABLED_WINDOW_TITLE, EDITOR_PANE_ID,
    ELEMENT_COUNT, PASSWORD_EDIT_ID, PASSWORD_SECRET, SAVE_BUTTON_ID, TEXT_EDITOR_ID,
    WINDOW_HANDLE, WINDOW_PID, WINDOW_PROCESS, WINDOW_TITLE,
};
use ce_app_bridge::protocol::error_kind;
use ce_app_bridge::{
    ActionArgs, ActionRequest, ActionResult, Backend, DoctorReport, ElementRef, Envelope,
    ErrorInfo, Health, ScreenshotRequest, Snapshot, SnapshotRequest, WindowInfo,
};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

const ERROR_KINDS: &[&str] = &[
    error_kind::BRIDGE_UNAVAILABLE,
    error_kind::VERSION_MISMATCH,
    error_kind::NO_PERMISSION,
    error_kind::ELEVATED_TARGET,
    error_kind::CAPTURE_EXCLUDED,
    error_kind::UNCERTAIN,
    error_kind::INPUT_BLOCKED,
    error_kind::TARGET_NOT_FOUND,
    error_kind::STALE_TARGET,
    error_kind::INVALID_REQUEST,
    error_kind::BACKEND_ERROR,
    error_kind::TIMEOUT,
    error_kind::UNSUPPORTED,
    error_kind::UNAUTHORIZED,
    error_kind::NOT_FOUND,
];

#[test]
fn error_kinds_are_stable_and_serialize_as_type() {
    assert_eq!(ERROR_KINDS.len(), 15);

    for kind in ERROR_KINDS {
        let envelope = Envelope::fail("action", ErrorInfo::new(*kind, "detail"), Health::Degraded);
        let encoded = envelope.to_json();
        let value: serde_json::Value = serde_json::from_str(&encoded).unwrap();

        assert_eq!(value["error"]["type"], *kind);
        assert!(value["error"].get("kind").is_none());
        assert_eq!(value["error"]["message"], "detail");
        assert_eq!(value["health"], "degraded");
    }
}

#[test]
fn fake_windows_expose_a_stable_integration_target() {
    let backend = FakeBackend::ready();
    let windows = backend.windows().unwrap();

    let primary = windows
        .iter()
        .find(|window| window.handle == WINDOW_HANDLE)
        .expect("primary fake window missing");

    assert_eq!(primary.pid, WINDOW_PID);
    assert_eq!(primary.title, WINDOW_TITLE);
    assert_eq!(primary.process_name.as_deref(), Some(WINDOW_PROCESS));
    assert!(primary.foreground);
    assert!(primary.enabled);
    assert!(!primary.offscreen);

    assert!(windows.iter().any(|window| window.offscreen));
    assert!(windows.iter().any(|window| !window.enabled));
}

#[test]
fn element_records_never_carry_a_value_for_sensitive_controls() {
    let backend = FakeBackend::ready();
    let snapshot = backend.snapshot(&snapshot_request()).unwrap();

    for element in &snapshot.elements {
        if element.sensitive {
            assert!(element.value.is_none(), "sensitive element leaked a value");
        }

        let encoded = serde_json::to_string(element).unwrap();
        assert!(
            !encoded.contains(PASSWORD_SECRET),
            "snapshot leaked the password secret"
        );
    }

    let password = &snapshot.elements[PASSWORD_EDIT_ID as usize];
    assert_eq!(password.name.as_deref(), Some("Password"));
    assert!(password.sensitive);
    assert!(password.value.is_none());

    let encoded = serde_json::to_string(&snapshot).unwrap();
    assert!(!encoded.contains(PASSWORD_SECRET));
    assert!(!encoded.contains("correct horse"));
}

#[test]
fn truncation_budgets_are_explicit_and_total_elements_is_accurate() {
    let backend = FakeBackend::ready();

    let full = backend.snapshot(&snapshot_request()).unwrap();
    assert_eq!(full.total_elements, ELEMENT_COUNT);
    assert_eq!(full.max_depth, 10);
    assert_eq!(full.max_elements, 1000);
    assert!(!full.truncated);

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
    assert!(by_depth.elements.len() < ELEMENT_COUNT as usize);
    assert!(by_depth.elements.iter().all(|element| element.depth <= 1));
    assert_ids_are_sequential(&by_depth);

    let by_elements = backend
        .snapshot(&SnapshotRequest {
            window: WINDOW_TITLE.to_string(),
            max_depth: None,
            max_elements: Some(3),
            exclude_roles: Vec::new(),
            actionable: false,
        })
        .unwrap();

    assert!(by_elements.truncated);
    assert_eq!(by_elements.total_elements, ELEMENT_COUNT);
    assert_eq!(by_elements.max_elements, 3);
    assert_eq!(by_elements.elements.len(), 3);
    assert_ids_are_sequential(&by_elements);

    let both = backend
        .snapshot(&SnapshotRequest {
            window: WINDOW_TITLE.to_string(),
            max_depth: Some(1),
            max_elements: Some(2),
            exclude_roles: Vec::new(),
            actionable: false,
        })
        .unwrap();

    assert!(both.truncated);
    assert_eq!(both.total_elements, ELEMENT_COUNT);
    assert_eq!(both.elements.len(), 2);
    assert_ids_are_sequential(&both);

    let zero = backend
        .snapshot(&SnapshotRequest {
            window: WINDOW_TITLE.to_string(),
            max_depth: None,
            max_elements: Some(0),
            exclude_roles: Vec::new(),
            actionable: false,
        })
        .unwrap();

    assert!(zero.truncated);
    assert!(zero.elements.is_empty());
    assert_eq!(zero.total_elements, ELEMENT_COUNT);
}

#[test]
fn disabled_and_sensitive_actions_are_refused() {
    let backend = FakeBackend::ready();

    let disabled = backend
        .action(&action_request("invoke", Some(DELETE_BUTTON_ID)))
        .unwrap_err();
    assert_eq!(disabled.kind, error_kind::INPUT_BLOCKED);

    let sensitive_read = backend
        .action(&action_request("get_value", Some(PASSWORD_EDIT_ID)))
        .unwrap_err();
    assert_eq!(sensitive_read.kind, error_kind::INPUT_BLOCKED);

    let mut write = action_request("set_value", Some(PASSWORD_EDIT_ID));
    write.args.value = Some("letmein".to_string());

    let sensitive_write = backend.action(&write).unwrap_err();
    assert_eq!(sensitive_write.kind, error_kind::INPUT_BLOCKED);
    assert_eq!(
        backend
            .state()
            .values
            .get(&PASSWORD_EDIT_ID)
            .map(String::as_str),
        Some(PASSWORD_SECRET)
    );

    let mut disabled_window = action_request("click", None);
    disabled_window.window = DISABLED_WINDOW_TITLE.to_string();
    let window_error = backend.action(&disabled_window).unwrap_err();
    assert_eq!(window_error.kind, error_kind::INPUT_BLOCKED);
}

#[test]
fn get_value_and_set_value_round_trip() {
    let backend = FakeBackend::ready();

    let mut write = action_request("set_value", Some(TEXT_EDITOR_ID));
    write.args.value = Some("round trip".to_string());

    let written = backend.action(&write).unwrap();
    assert!(written.delivered);
    assert!(written.verified);
    assert_eq!(written.value.as_deref(), Some("round trip"));

    let read = backend
        .action(&action_request("get_value", Some(TEXT_EDITOR_ID)))
        .unwrap();
    assert!(read.delivered);
    assert!(read.verified);
    assert_eq!(read.value.as_deref(), Some("round trip"));

    let snapshot = backend.snapshot(&snapshot_request()).unwrap();
    assert_eq!(
        snapshot.elements[TEXT_EDITOR_ID as usize].value.as_deref(),
        Some("round trip")
    );

    let toggle = backend
        .action(&action_request("toggle", Some(AGREE_CHECKBOX_ID)))
        .unwrap();
    assert_eq!(toggle.value.as_deref(), Some("true"));
    assert_eq!(
        backend.state().toggled.get(&AGREE_CHECKBOX_ID).copied(),
        Some(true)
    );

    let invoke = backend
        .action(&action_request("invoke", Some(SAVE_BUTTON_ID)))
        .unwrap();
    assert!(invoke.delivered && invoke.verified);
    assert_eq!(backend.state().invoke_count, 1);
}

#[test]
fn scroll_to_records_absolute_position() {
    let backend = FakeBackend::ready();

    let mut request = action_request("scroll_to", Some(EDITOR_PANE_ID));
    request.args.vertical_percent = Some(50.0);

    let result = backend.action(&request).unwrap();

    assert!(result.delivered);
    assert!(result.verified);
    assert_eq!(
        backend.state().scroll_positions,
        vec![(EDITOR_PANE_ID, None, Some(50.0))]
    );

    let invalid = action_request("scroll_to", Some(EDITOR_PANE_ID));
    assert_eq!(
        backend.action(&invalid).unwrap_err().kind,
        error_kind::INVALID_REQUEST
    );
}

#[test]
fn unknown_targets_return_target_not_found() {
    let backend = FakeBackend::ready();

    let window_error = backend
        .snapshot(&SnapshotRequest {
            window: "No Such Window".to_string(),
            max_depth: None,
            max_elements: None,
            exclude_roles: Vec::new(),
            actionable: false,
        })
        .unwrap_err();
    assert_eq!(window_error.kind, error_kind::TARGET_NOT_FOUND);

    let element_error = backend
        .action(&action_request("get_value", Some(999)))
        .unwrap_err();
    assert_eq!(element_error.kind, error_kind::TARGET_NOT_FOUND);

    let by_runtime_id = backend
        .action(&ActionRequest {
            window: WINDOW_TITLE.to_string(),
            action: "get_value".to_string(),
            target: Some(ElementRef {
                runtime_id: Some("fake:2".to_string()),
                ..Default::default()
            }),
            args: ActionArgs::default(),
        })
        .unwrap();
    assert!(by_runtime_id.delivered);
}

#[test]
fn unknown_action_is_invalid_request() {
    let backend = FakeBackend::ready();
    let error = backend
        .action(&action_request("teleport", Some(TEXT_EDITOR_ID)))
        .unwrap_err();

    assert_eq!(error.kind, error_kind::INVALID_REQUEST);
}

#[test]
fn screenshot_starts_with_the_png_signature() {
    let png = FakeBackend::ready()
        .screenshot(&ScreenshotRequest {
            window: WINDOW_TITLE.to_string(),
        })
        .unwrap();

    assert!(png.len() >= 33);
    assert_eq!(&png[..8], &[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]);
    assert_eq!(&png[12..16], b"IHDR");
    assert_eq!(u32::from_be_bytes(png[8..12].try_into().unwrap()), 13);
    assert_eq!(u32::from_be_bytes(png[16..20].try_into().unwrap()), 400);
    assert_eq!(u32::from_be_bytes(png[20..24].try_into().unwrap()), 300);
}

#[test]
fn doctor_reports_health_and_capability_checks() {
    let ready = FakeBackend::ready().doctor();
    assert_eq!(ready.health, Health::Ready);

    for name in ["backend", "loopback", "input"] {
        assert!(
            ready
                .checks
                .iter()
                .any(|check| check.name == name && check.ok),
            "missing ready check '{name}'"
        );
    }

    let degraded = FakeBackend::degraded().doctor();
    assert_eq!(degraded.health, Health::Degraded);
    assert!(degraded
        .checks
        .iter()
        .any(|check| check.name == "input" && !check.ok));
}

#[test]
fn slow_backend_timeout_is_observable() {
    let backend = Arc::new(SlowBackend::new(Duration::from_secs(2)));
    let (sender, receiver) = mpsc::channel();

    let worker = {
        let backend = Arc::clone(&backend);
        thread::spawn(move || {
            let mut request = action_request("keys", Some(TEXT_EDITOR_ID));
            request.args.keys = Some("^s".to_string());
            let result = backend.action(&request);
            let _ = sender.send(result);
        })
    };

    assert!(
        matches!(
            receiver.recv_timeout(Duration::from_millis(250)),
            Err(RecvTimeoutError::Timeout)
        ),
        "caller must be able to observe a timeout"
    );

    let result = receiver
        .recv_timeout(Duration::from_secs(5))
        .expect("slow backend never produced a result");
    assert!(result.is_ok());

    worker.join().unwrap();
}

#[test]
fn find_defaults_to_unsupported_on_backends_that_do_not_stream() {
    let request = ce_app_bridge::FindRequest {
        window: WINDOW_TITLE.to_string(),
        ..Default::default()
    };

    let error = FakeBackend::ready().find(&request).unwrap_err();

    assert_eq!(error.kind, error_kind::UNSUPPORTED);
    assert!(error.message.contains("not implemented"));
}

#[test]
fn actionable_snapshot_prunes_anonymous_containers_and_renumbers() {
    let backend = FakeBackend::ready();
    let snapshot = backend
        .snapshot(&SnapshotRequest {
            window: WINDOW_TITLE.to_string(),
            max_depth: None,
            max_elements: None,
            exclude_roles: Vec::new(),
            actionable: true,
        })
        .unwrap();

    assert_eq!(snapshot.total_elements, ELEMENT_COUNT);
    assert!(snapshot.truncated);
    assert_eq!(snapshot.truncated_by.as_deref(), Some("actionable"));
    assert_eq!(snapshot.elements.len(), ELEMENT_COUNT as usize - 1);
    assert!(snapshot
        .elements
        .iter()
        .all(|element| element.control_type != "Pane"));

    for (index, element) in snapshot.elements.iter().enumerate() {
        assert_eq!(element.id, index as u32);
    }

    let editor = &snapshot.elements[1];
    assert_eq!(editor.name.as_deref(), Some("Text Editor"));
    assert_eq!(editor.parent, Some(0));
    assert_eq!(editor.depth, 1);
}

#[test]
fn actionable_false_keeps_the_complete_tree() {
    let snapshot = FakeBackend::ready().snapshot(&snapshot_request()).unwrap();

    assert_eq!(snapshot.elements.len() as u32, ELEMENT_COUNT);
    assert!(!snapshot.truncated);
    assert!(snapshot.truncated_by.is_none());
    assert!(snapshot
        .elements
        .iter()
        .any(|element| element.control_type == "Pane"));
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

fn action_request(action: &str, element_id: Option<u32>) -> ActionRequest {
    ActionRequest {
        window: WINDOW_TITLE.to_string(),
        action: action.to_string(),
        target: element_id.map(|id| ElementRef {
            id: Some(id),
            ..Default::default()
        }),
        args: ActionArgs::default(),
    }
}

fn assert_ids_are_sequential(snapshot: &Snapshot) {
    for (index, element) in snapshot.elements.iter().enumerate() {
        assert_eq!(element.id, index as u32);
        assert!(element
            .parent
            .map(|parent| parent < element.id)
            .unwrap_or(true));
    }

    if let Some(pane) = snapshot
        .elements
        .iter()
        .find(|element| element.id == EDITOR_PANE_ID)
    {
        assert_eq!(pane.parent, Some(0));
    }
}

/// Backend that sleeps before every action so callers can prove a timeout.
struct SlowBackend {
    inner: FakeBackend,
    delay: Duration,
}

impl SlowBackend {
    fn new(delay: Duration) -> Self {
        Self {
            inner: FakeBackend::ready(),
            delay,
        }
    }
}

impl Backend for SlowBackend {
    fn name(&self) -> &'static str {
        "slow-fake"
    }

    fn platform(&self) -> &'static str {
        "fake"
    }

    fn capabilities(&self) -> Vec<String> {
        self.inner.capabilities()
    }

    fn health(&self) -> Health {
        self.inner.health()
    }

    fn doctor(&self) -> DoctorReport {
        self.inner.doctor()
    }

    fn windows(&self) -> Result<Vec<WindowInfo>, ErrorInfo> {
        self.inner.windows()
    }

    fn snapshot(&self, request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo> {
        self.inner.snapshot(request)
    }

    fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        thread::sleep(self.delay);
        self.inner.action(request)
    }

    fn screenshot(&self, request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
        self.inner.screenshot(request)
    }
}
