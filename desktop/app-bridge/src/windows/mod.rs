//! Windows backend: window enumeration, UI Automation, input, and screenshots.
//!
//! Owned by the Windows team. T5 implements enumeration, state, windows, and
//! doctor. UIA snapshots, actions, input, and screenshots land in later tasks.

#[cfg(windows)]
pub mod actions;
#[cfg(windows)]
pub mod element;
#[cfg(windows)]
pub mod enumerate;
#[cfg(windows)]
pub mod input;
#[cfg(windows)]
pub mod screenshot;
#[cfg(windows)]
pub mod uia;

use crate::protocol::{
    ActionRequest, ActionResult, DoctorReport, ErrorInfo, Health, ScreenshotRequest, Snapshot,
    SnapshotRequest, WindowInfo,
};
use std::sync::Mutex;

use crate::Backend;

/// Windows backend handle.
#[derive(Debug, Default)]
pub struct WindowsBackend {
    snapshot_cache: Mutex<Option<uia::UiaSnapshotCache>>,
}

impl WindowsBackend {
    /// Create a backend bound to this process.
    pub fn new() -> Self {
        Self {
            snapshot_cache: Mutex::new(None),
        }
    }
}

impl Backend for WindowsBackend {
    fn name(&self) -> &'static str {
        "windows-uia"
    }

    fn platform(&self) -> &'static str {
        "windows"
    }

    fn capabilities(&self) -> Vec<String> {
        [
            "windows",
            "snapshot",
            "action",
            "screenshot",
            "doctor",
            "uia",
            "cell_at",
            "scroll_to",
            "dialogs",
        ]
        .iter()
        .map(|value| (*value).to_string())
        .collect()
    }

    fn health(&self) -> Health {
        if enumerate::probe_enumeration() {
            Health::Ready
        } else {
            Health::Degraded
        }
    }

    fn doctor(&self) -> DoctorReport {
        DoctorReport {
            platform: self.platform().to_string(),
            backend: self.name().to_string(),
            health: self.health(),
            checks: {
                let mut checks = enumerate::doctor_checks();
                checks.push(uia::doctor_check());
                checks
            },
            notes: vec![
                "Windows needs no accessibility or screen-recording grant for this backend."
                    .to_string(),
            ],
            ..Default::default()
        }
    }

    fn windows(&self) -> Result<Vec<WindowInfo>, ErrorInfo> {
        enumerate::enumerate_windows()
    }

    fn snapshot(&self, request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo> {
        let window = enumerate::resolve_window(&request.window)?;
        let outcome = uia::snapshot_with_cache(&window, request)?;
        *self
            .snapshot_cache
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(outcome.cache);
        Ok(outcome.snapshot)
    }
    fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        let action = request.action.as_str();
        let explicit = matches!(action, "activate" | "focus");
        let foreground = request.args.delivery_mode.is_foreground();
        let target = enumerate::resolve_window(&request.window).ok();
        let mut front_failed = false;

        if foreground && !explicit {
            front_failed = !target.as_ref().is_some_and(input::bring_to_front);
        }

        let background = if explicit || foreground {
            None
        } else {
            Some(input::ForegroundGuard::capture(target.as_ref()))
        };

        let mut result = match action {
            "keys" | "scroll" | "focus" | "activate" => input::perform(self, request),
            "click" | "double_click" | "right_click" | "hover" if request.args.point.is_some() => {
                input::perform(self, request)
            }
            "drag" => input::perform(self, request),
            _ => actions::perform(self, request),
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
                        "the previous foreground window could not be restored",
                    );
                }
            }
        }

        result
    }

    fn screenshot(&self, request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
        let window = enumerate::resolve_window(&request.window)?;
        screenshot::capture(&window)
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
