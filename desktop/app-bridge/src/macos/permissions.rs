//! macOS TCC permission probes shared by the backend and the doctor report.
//!
//! Probing never prompts. Prompts are separate calls used only by the doctor's
//! explicit ensure flow and by the first screenshot attempt.

use core_foundation::base::TCFType;
use core_foundation::boolean::CFBoolean;
use core_foundation::dictionary::{CFDictionary, CFDictionaryRef};
use core_foundation::string::{CFString, CFStringRef};
use core_graphics::access::ScreenCaptureAccess;

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXIsProcessTrustedWithOptions(options: CFDictionaryRef) -> u8;

    static kAXTrustedCheckOptionPrompt: CFStringRef;
}

/// True when this process holds the Accessibility grant. Never prompts.
pub fn accessibility_trusted() -> bool {
    is_accessibility_trusted(false)
}

/// Ask the system to show the Accessibility prompt. Only call from an explicit
/// user-initiated flow (doctor or `--ensure`), never on every request.
pub fn request_accessibility() -> bool {
    is_accessibility_trusted(true)
}

/// Screen Recording status without prompting.
pub fn screen_recording_granted() -> bool {
    ScreenCaptureAccess.preflight()
}

/// Ask for Screen Recording. The system usually requires a process restart
/// before the grant takes effect, so call this only when a screenshot is first
/// attempted.
pub fn request_screen_recording() -> bool {
    ScreenCaptureAccess.request()
}

/// Snapshot of the permissions a macOS backend cares about.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Permissions {
    pub accessibility: bool,
    pub screen_recording: bool,
}

impl Permissions {
    /// Probe every permission without prompting.
    pub fn current() -> Self {
        Self {
            accessibility: accessibility_trusted(),
            screen_recording: screen_recording_granted(),
        }
    }

    /// Health is ready only when AX and event posting are allowed.
    pub fn ready(&self) -> bool {
        self.accessibility
    }
}

/// `granted`/`denied` word used by the doctor permission map.
pub fn word(granted: bool) -> &'static str {
    if granted {
        "granted"
    } else {
        "denied"
    }
}

fn is_accessibility_trusted(prompt: bool) -> bool {
    let key = unsafe { CFString::wrap_under_get_rule(kAXTrustedCheckOptionPrompt) };
    let value = if prompt {
        CFBoolean::true_value()
    } else {
        CFBoolean::false_value()
    };
    let options = CFDictionary::from_CFType_pairs(&[(key, value)]);

    unsafe { AXIsProcessTrustedWithOptions(options.as_concrete_TypeRef()) != 0 }
}
