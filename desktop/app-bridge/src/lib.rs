//! Loopback bridge for native application control.
//!
//! The crate is shared by two transports: the Tauri desktop app calls the
//! [`Backend`] in-process, and the `app-harness` CLI talks HTTP to the same
//! server. The bridge is a mode of the signed `ce-underscore` binary; it is
//! never a separate executable.
//!
//! Contract highlights:
//!
//! - Zero state per invocation: a CLI run re-enumerates windows and element
//!   references only live for the duration of that run.
//! - One bridge per user, discovered through `bridge.json`.
//! - Platform calls are serialized; a timed-out call is reported as
//!   `delivered: true, verified: false, uncertain: true` and is never retried.
//!
//! Platform backends implement [`Backend`] in their own module and are selected
//! by [`default_backend`].

use std::sync::Arc;

pub mod dialog;
pub mod observe;
pub mod protocol;
pub mod server;

pub mod backend;

#[cfg(target_os = "linux")]
pub mod linux;
#[cfg(target_os = "macos")]
pub mod macos;
#[cfg(target_os = "windows")]
pub mod windows;

pub use protocol::{
    ActionArgs, ActionRequest, ActionResult, Bounds, BridgeFile, CheckResult, DoctorReport,
    ElementRecord, ElementRef, Envelope, ErrorDetails, ErrorInfo, FindRequest, FindResult, Health,
    MatchSpec, Point, PointerButton, ScreenshotRequest, Snapshot, SnapshotRequest, StateInfo,
    StringMatch, WindowInfo,
};

use protocol::error_kind;

/// Platform operations the bridge exposes.
///
/// Implementations must be safe to share across threads. The server serializes
/// calls behind one queue, but a platform backend may still be probed from
/// status endpoints concurrently, so every method takes `&self`.
pub trait Backend: Send + Sync {
    /// Short backend name, e.g. `windows-uia`.
    fn name(&self) -> &'static str;

    /// Platform identifier reported in `bridge.json` and state.
    fn platform(&self) -> &'static str;

    /// Capabilities this backend supports, e.g. `snapshot`, `screenshot`.
    fn capabilities(&self) -> Vec<String>;

    /// Cheap health probe; must not block on the target application.
    fn health(&self) -> Health;

    /// Backend diagnostics without touching any target application.
    fn doctor(&self) -> DoctorReport;

    /// Visible top-level windows, freshly enumerated on every call.
    fn windows(&self) -> Result<Vec<WindowInfo>, ErrorInfo>;

    /// Accessibility snapshot for one window.
    fn snapshot(&self, request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo>;

    /// Structured search evaluated during the accessibility walk.
    ///
    /// Backends that cannot stream the tree may keep this default; clients then
    /// receive an `unsupported` error instead of a partial result.
    fn find(&self, _request: &FindRequest) -> Result<FindResult, ErrorInfo> {
        Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "find is not implemented for this backend",
        ))
    }

    /// Run one semantic action or input operation.
    fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo>;

    /// PNG bytes for one window.
    fn screenshot(&self, request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo>;
}

/// Backend used when the bridge runs in this process.
pub fn default_backend() -> Arc<dyn Backend> {
    if std::env::var("CECLI_BRIDGE_BACKEND")
        .map(|value| value.eq_ignore_ascii_case("fake"))
        .unwrap_or(false)
    {
        return Arc::new(backend::fake::FakeBackend::ready());
    }
    #[cfg(target_os = "windows")]
    {
        Arc::new(windows::WindowsBackend::new())
    }

    #[cfg(target_os = "macos")]
    {
        Arc::new(macos::MacBackend::new())
    }

    #[cfg(target_os = "linux")]
    {
        Arc::new(linux::LinuxBackend::new())
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
    {
        Arc::new(UnsupportedBackend)
    }
}

/// Backend stub used on platforms without a native implementation.
#[derive(Debug, Default)]
pub struct UnsupportedBackend;

impl Backend for UnsupportedBackend {
    fn name(&self) -> &'static str {
        "unsupported"
    }

    fn platform(&self) -> &'static str {
        std::env::consts::OS
    }

    fn capabilities(&self) -> Vec<String> {
        Vec::new()
    }

    fn health(&self) -> Health {
        Health::Unavailable
    }

    fn doctor(&self) -> DoctorReport {
        DoctorReport {
            platform: self.platform().to_string(),
            backend: self.name().to_string(),
            health: Health::Unavailable,
            notes: vec!["no native backend for this platform".to_string()],
            ..Default::default()
        }
    }

    fn windows(&self) -> Result<Vec<WindowInfo>, ErrorInfo> {
        Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "no native backend for this platform",
        ))
    }

    fn snapshot(&self, _request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo> {
        Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "no native backend for this platform",
        ))
    }

    fn action(&self, _request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "no native backend for this platform",
        ))
    }

    fn screenshot(&self, _request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
        Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "no native backend for this platform",
        ))
    }
}

/// Run the bridge in the foreground. Returns a process exit code.
pub fn run_bridge(foreground: bool) -> i32 {
    server::run_foreground(foreground)
}

/// Start the bridge if no healthy one is running. Returns a process exit code.
pub fn ensure_bridge() -> i32 {
    server::ensure_bridge()
}

/// Print bridge status as JSON. Returns a process exit code.
pub fn bridge_status() -> i32 {
    server::status()
}

/// Stop the running bridge. Returns a process exit code.
pub fn stop_bridge() -> i32 {
    server::stop()
}

/// Build a state payload from a backend.
pub fn state_for(backend: &dyn Backend) -> StateInfo {
    StateInfo {
        platform: backend.platform().to_string(),
        version: protocol::BRIDGE_VERSION.to_string(),
        backend: backend.name().to_string(),
        capabilities: backend.capabilities(),
        health: backend.health(),
        pid: std::process::id(),
        mode: "bridge".to_string(),
        protocol_version: protocol::BRIDGE_VERSION.to_string(),
    }
}
