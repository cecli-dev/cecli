//! Safe wrappers over the macOS Accessibility (AXUIElement) API.
//!
//! The wrappers own every Core Foundation object they create: values copied from
//! the AX API use the copy rule, values borrowed from arrays are retained on
//! wrap, and all of them release on drop. Unsafe blocks are limited to the C
//! calls themselves; everything else works with [`AppElement`] and plain Rust
//! values.
//!
//! Coordinates follow the AX API: screen points with a top-left origin. The
//! protocol calls its rectangles "physical pixels"; on macOS the values are
//! points, which is the unit AX reports and the unit CGEvent consumes.

use std::collections::VecDeque;
use std::ffi::c_void;
use std::ptr;

use core_foundation::array::{CFArray, CFArrayGetCount, CFArrayGetValueAtIndex, CFArrayRef};
use core_foundation::base::{CFEqual, CFGetTypeID, CFRange, CFType, CFTypeID, CFTypeRef, TCFType};
use core_foundation::boolean::CFBoolean;
use core_foundation::dictionary::{CFDictionary, CFDictionaryRef};
use core_foundation::number::CFNumber;
use core_foundation::string::{CFString, CFStringRef};
use core_graphics::access::ScreenCaptureAccess;
use core_graphics::geometry::{CGPoint, CGSize};
use objc2::rc::autoreleasepool;
use objc2_app_kit::{NSApplicationActivationPolicy, NSWorkspace};

use crate::protocol::error_kind::{
    BACKEND_ERROR, INVALID_REQUEST, NO_PERMISSION, STALE_TARGET, TARGET_NOT_FOUND, UNCERTAIN,
    UNSUPPORTED,
};
use crate::protocol::{
    Bounds, ElementRecord, ElementRef, ErrorInfo, ScrollState, Snapshot, SnapshotRequest,
    WindowInfo,
};

/// Default snapshot depth when the request leaves it unset.
pub const DEFAULT_MAX_DEPTH: u32 = 10;
/// Default snapshot element budget when the request leaves it unset.
pub const DEFAULT_MAX_ELEMENTS: u32 = 1_000;
/// Upper bounds that keep a hostile request from walking forever.
pub const HARD_MAX_DEPTH: u32 = 64;
/// Element cap for one snapshot.
pub const HARD_MAX_ELEMENTS: u32 = 20_000;
/// How long one AX message may take before the API reports `cannotComplete`.
pub const MESSAGING_TIMEOUT_SECS: f32 = 0.5;

const AX_ERROR_SUCCESS: i32 = 0;
const AX_ERROR_FAILURE: i32 = -25200;
const AX_ERROR_ILLEGAL_ARGUMENT: i32 = -25201;
const AX_ERROR_INVALID_UI_ELEMENT: i32 = -25202;
const AX_ERROR_CANNOT_COMPLETE: i32 = -25204;
const AX_ERROR_ATTRIBUTE_UNSUPPORTED: i32 = -25205;
const AX_ERROR_ACTION_UNSUPPORTED: i32 = -25206;
const AX_ERROR_NOT_IMPLEMENTED: i32 = -25208;
const AX_ERROR_API_DISABLED: i32 = -25211;
const AX_ERROR_NO_VALUE: i32 = -25212;

const AX_VALUE_CGPOINT: u32 = 1;
const AX_VALUE_CGSIZE: u32 = 2;
const AX_VALUE_CFRANGE: u32 = 4;

const AX_PRESS: &str = "AXPress";
const AX_CONFIRM: &str = "AXConfirm";
const AX_RAISE: &str = "AXRaise";
const AX_INCREMENT: &str = "AXIncrement";
const AX_DECREMENT: &str = "AXDecrement";

const AX_ROLE_SECURE_TEXT_FIELD: &str = "AXSecureTextField";

const MAX_SEARCH_ELEMENTS: usize = 20_000;

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXUIElementCreateApplication(pid: i32) -> AXUIElementRef;
    fn AXUIElementCreateSystemWide() -> AXUIElementRef;
    fn AXUIElementGetTypeID() -> CFTypeID;
    fn AXUIElementCopyAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: *mut CFTypeRef,
    ) -> i32;
    fn AXUIElementSetAttributeValue(
        element: AXUIElementRef,
        attribute: CFStringRef,
        value: CFTypeRef,
    ) -> i32;
    fn AXUIElementIsAttributeSettable(
        element: AXUIElementRef,
        attribute: CFStringRef,
        settable: *mut u8,
    ) -> i32;
    fn AXUIElementCopyActionNames(element: AXUIElementRef, names: *mut CFArrayRef) -> i32;
    fn AXUIElementPerformAction(element: AXUIElementRef, action: CFStringRef) -> i32;
    fn AXUIElementSetMessagingTimeout(element: AXUIElementRef, timeout: f32) -> i32;

    fn AXValueGetTypeID() -> CFTypeID;
    fn AXValueGetValue(value: AXValueRef, the_type: u32, out: *mut c_void) -> u8;
    fn AXValueCreate(the_type: u32, value: *const c_void) -> AXValueRef;

    fn AXIsProcessTrusted() -> u8;
    fn AXIsProcessTrustedWithOptions(options: CFDictionaryRef) -> u8;

    static kAXTrustedCheckOptionPrompt: CFStringRef;
}

type AXUIElementRef = *const c_void;
type AXValueRef = *const c_void;

/// One AX error code. Use [`AxError::kind`] to map it onto the wire contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AxError {
    pub code: i32,
}

impl AxError {
    pub fn new(code: i32) -> Self {
        Self { code }
    }

    /// Stable protocol error kind for this code.
    pub fn kind(self) -> &'static str {
        match self.code {
            AX_ERROR_API_DISABLED => NO_PERMISSION,
            AX_ERROR_INVALID_UI_ELEMENT => STALE_TARGET,
            AX_ERROR_CANNOT_COMPLETE => UNCERTAIN,
            AX_ERROR_ATTRIBUTE_UNSUPPORTED
            | AX_ERROR_ACTION_UNSUPPORTED
            | AX_ERROR_NOT_IMPLEMENTED => UNSUPPORTED,
            AX_ERROR_ILLEGAL_ARGUMENT => INVALID_REQUEST,
            _ => BACKEND_ERROR,
        }
    }

    /// Human-readable detail for logs and the doctor report.
    pub fn message(self) -> String {
        match self.code {
            AX_ERROR_API_DISABLED => {
                "Accessibility permission is not granted to this process".to_string()
            }
            AX_ERROR_INVALID_UI_ELEMENT => {
                "the accessibility element is no longer valid".to_string()
            }
            AX_ERROR_ATTRIBUTE_UNSUPPORTED => {
                "the element does not support the attribute".to_string()
            }
            AX_ERROR_ACTION_UNSUPPORTED => "the element does not support the action".to_string(),
            AX_ERROR_NOT_IMPLEMENTED => {
                "the application does not implement the accessibility API".to_string()
            }
            AX_ERROR_CANNOT_COMPLETE => {
                "the accessibility call could not complete in time".to_string()
            }
            AX_ERROR_NO_VALUE => "the attribute has no value".to_string(),
            AX_ERROR_ILLEGAL_ARGUMENT => "illegal accessibility argument".to_string(),
            AX_ERROR_FAILURE => "the accessibility call failed".to_string(),
            other => format!("accessibility error {other}"),
        }
    }
}

impl std::fmt::Display for AxError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{} ({})", self.message(), self.code)
    }
}

impl std::error::Error for AxError {}

/// Convert an AX failure into the protocol error envelope.
pub fn to_error(error: AxError) -> ErrorInfo {
    ErrorInfo::new(error.kind(), error.message())
}

/// A retained `AXUIElementRef`.
///
/// Cloning retains; dropping releases. Instances are intentionally neither
/// `Send` nor `Sync`: the backend creates them per call and never stores them.
#[derive(Debug, Clone)]
pub struct AppElement {
    inner: CFType,
}

impl AppElement {
    /// Create the application element for a process.
    pub fn application(pid: i32) -> Result<Self, AxError> {
        let raw = unsafe { AXUIElementCreateApplication(pid) };
        Self::from_create_rule(raw)
    }

    /// Create the system-wide element, used for frontmost-application queries.
    pub fn system_wide() -> Result<Self, AxError> {
        let raw = unsafe { AXUIElementCreateSystemWide() };
        Self::from_create_rule(raw)
    }

    pub fn set_messaging_timeout(&self, seconds: f32) -> Result<(), AxError> {
        check_error(unsafe { AXUIElementSetMessagingTimeout(self.raw(), seconds) })
    }

    fn raw(&self) -> AXUIElementRef {
        self.inner.as_concrete_TypeRef()
    }

    fn from_create_rule(raw: AXUIElementRef) -> Result<Self, AxError> {
        if raw.is_null() {
            return Err(AxError::new(AX_ERROR_FAILURE));
        }

        Ok(Self {
            inner: unsafe { CFType::wrap_under_create_rule(raw) },
        })
    }

    fn from_get_rule(raw: CFTypeRef) -> Option<Self> {
        if raw.is_null() {
            return None;
        }

        Some(Self {
            inner: unsafe { CFType::wrap_under_get_rule(raw) },
        })
    }
}

/// True when this process currently holds the Accessibility grant.
pub fn accessibility_trusted() -> bool {
    unsafe { AXIsProcessTrusted() != 0 }
}

/// Ask the system to show the Accessibility prompt. Only call from an explicit
/// user-initiated flow; never from `doctor` or startup.
pub fn request_accessibility_trust() -> bool {
    let key = unsafe { CFString::wrap_under_get_rule(kAXTrustedCheckOptionPrompt) };
    let options = CFDictionary::from_CFType_pairs(&[(key, CFBoolean::true_value())]);

    unsafe { AXIsProcessTrustedWithOptions(options.as_concrete_TypeRef()) != 0 }
}

/// Screen Recording status without prompting.
pub fn screen_recording_granted() -> bool {
    ScreenCaptureAccess.preflight()
}

/// Ask for Screen Recording. The system may require a process restart.
pub fn request_screen_recording() -> bool {
    ScreenCaptureAccess.request()
}

/// Return a permission error unless Accessibility is granted.
pub fn ensure_trusted() -> Result<(), ErrorInfo> {
    if accessibility_trusted() {
        return Ok(());
    }

    Err(ErrorInfo::new(
        NO_PERMISSION,
        "Accessibility permission is required; grant it in System Settings > Privacy & Security > Accessibility",
    ))
}

/// Copy one attribute and own the returned value.
///
/// The AX API returns a `+1` reference; the [`CFType`] wrapper releases it. An
/// unsupported attribute or an attribute with no value yields `None`.
pub fn copy_attribute(element: &AppElement, key: &str) -> Option<CFType> {
    let attribute = CFString::new(key);
    let mut value: CFTypeRef = ptr::null();
    let status = unsafe {
        AXUIElementCopyAttributeValue(element.raw(), attribute.as_concrete_TypeRef(), &mut value)
    };

    if status != AX_ERROR_SUCCESS {
        return None;
    }

    if value.is_null() {
        return None;
    }

    Some(unsafe { CFType::wrap_under_create_rule(value) })
}

pub fn attribute_string(element: &AppElement, key: &str) -> Option<String> {
    let value = copy_attribute(element, key)?;
    if !value.instance_of::<CFString>() {
        return None;
    }

    value.downcast::<CFString>().map(|text| text.to_string())
}

pub fn attribute_bool(element: &AppElement, key: &str) -> Option<bool> {
    let value = copy_attribute(element, key)?;
    if !value.instance_of::<CFBoolean>() {
        return None;
    }

    value.downcast::<CFBoolean>().map(bool::from)
}

pub fn attribute_i64(element: &AppElement, key: &str) -> Option<i64> {
    let value = copy_attribute(element, key)?;
    if !value.instance_of::<CFNumber>() {
        return None;
    }

    value
        .downcast::<CFNumber>()
        .and_then(|number| number.to_i64())
}

pub fn attribute_f64(element: &AppElement, key: &str) -> Option<f64> {
    let value = copy_attribute(element, key)?;
    if !value.instance_of::<CFNumber>() {
        return None;
    }

    value
        .downcast::<CFNumber>()
        .and_then(|number| number.to_f64())
}
pub fn element_attribute(element: &AppElement, key: &str) -> Option<AppElement> {
    let value = copy_attribute(element, key)?;
    if cf_type_id(&value) != unsafe { AXUIElementGetTypeID() } {
        return None;
    }

    AppElement::from_get_rule(value.as_CFTypeRef())
}

pub fn element_array_attribute(element: &AppElement, key: &str) -> Vec<AppElement> {
    let value = match copy_attribute(element, key) {
        Some(value) => value,
        None => return Vec::new(),
    };

    if !value.instance_of::<core_foundation::array::CFArray<CFType>>() {
        return Vec::new();
    }

    let array = value.as_CFTypeRef() as CFArrayRef;
    array_values(array)
        .into_iter()
        .filter_map(AppElement::from_get_rule)
        .collect()
}

pub fn children(element: &AppElement) -> Vec<AppElement> {
    element_array_attribute(element, "AXChildren")
}

pub fn role(element: &AppElement) -> Option<String> {
    attribute_string(element, "AXRole")
}

pub fn subrole(element: &AppElement) -> Option<String> {
    attribute_string(element, "AXSubrole")
}

pub fn title(element: &AppElement) -> Option<String> {
    attribute_string(element, "AXTitle")
}

pub fn description(element: &AppElement) -> Option<String> {
    attribute_string(element, "AXDescription")
}

pub fn automation_id(element: &AppElement) -> Option<String> {
    attribute_string(element, "AXIdentifier")
}

pub fn value_string(element: &AppElement) -> Option<String> {
    let value = copy_attribute(element, "AXValue")?;

    if value.instance_of::<CFString>() {
        return value.downcast::<CFString>().map(|text| text.to_string());
    }

    if value.instance_of::<CFNumber>() {
        return value
            .downcast::<CFNumber>()
            .and_then(|number| number.to_i64())
            .map(|number| number.to_string());
    }

    if value.instance_of::<CFBoolean>() {
        return value
            .downcast::<CFBoolean>()
            .map(|flag| if bool::from(flag) { "true" } else { "false" }.to_string());
    }

    None
}

pub fn is_enabled(element: &AppElement) -> bool {
    attribute_bool(element, "AXEnabled").unwrap_or(true)
}

pub fn is_focused(element: &AppElement) -> bool {
    attribute_bool(element, "AXFocused").unwrap_or(false)
}

pub fn position(element: &AppElement) -> Option<CGPoint> {
    let value = copy_attribute(element, "AXPosition")?;
    let raw = ax_value_ref(&value)?;
    let mut point = CGPoint::new(0.0, 0.0);
    let ok = unsafe {
        AXValueGetValue(
            raw,
            AX_VALUE_CGPOINT,
            &mut point as *mut CGPoint as *mut c_void,
        )
    };

    if ok == 0 {
        return None;
    }

    Some(point)
}

pub fn size(element: &AppElement) -> Option<CGSize> {
    let value = copy_attribute(element, "AXSize")?;
    let raw = ax_value_ref(&value)?;
    let mut size = CGSize::new(0.0, 0.0);
    let ok = unsafe {
        AXValueGetValue(
            raw,
            AX_VALUE_CGSIZE,
            &mut size as *mut CGSize as *mut c_void,
        )
    };

    if ok == 0 {
        return None;
    }

    Some(size)
}

pub fn frame(element: &AppElement) -> Option<Bounds> {
    let position = position(element)?;
    let size = size(element)?;
    Some(bounds_from_point_size(position, size))
}

pub fn is_attribute_settable(element: &AppElement, key: &str) -> Option<bool> {
    let attribute = CFString::new(key);
    let mut settable: u8 = 0;
    let status = unsafe {
        AXUIElementIsAttributeSettable(
            element.raw(),
            attribute.as_concrete_TypeRef(),
            &mut settable,
        )
    };

    if status != AX_ERROR_SUCCESS {
        return None;
    }

    Some(settable != 0)
}

fn set_attribute_ref(element: &AppElement, key: &str, value: CFTypeRef) -> Result<(), AxError> {
    let attribute = CFString::new(key);
    check_error(unsafe {
        AXUIElementSetAttributeValue(element.raw(), attribute.as_concrete_TypeRef(), value)
    })
}

pub fn action_names(element: &AppElement) -> Vec<String> {
    let mut names: CFArrayRef = ptr::null();
    let status = unsafe { AXUIElementCopyActionNames(element.raw(), &mut names) };

    if status != AX_ERROR_SUCCESS || names.is_null() {
        return Vec::new();
    }

    let array = unsafe { CFArray::<CFString>::wrap_under_create_rule(names) };
    array.iter().map(|name| name.to_string()).collect()
}

pub fn supports_action(element: &AppElement, action: &str) -> bool {
    action_names(element)
        .iter()
        .any(|name| name.eq_ignore_ascii_case(action))
}

pub fn perform_action(element: &AppElement, action: &str) -> Result<(), AxError> {
    let name = CFString::new(action);
    check_error(unsafe { AXUIElementPerformAction(element.raw(), name.as_concrete_TypeRef()) })
}

/// Press a control, preferring `AXPress` and falling back to `AXConfirm`.
pub fn press(element: &AppElement) -> Result<(), AxError> {
    let names = action_names(element);

    if names.iter().any(|name| name.eq_ignore_ascii_case(AX_PRESS)) {
        return perform_action(element, AX_PRESS);
    }

    if names
        .iter()
        .any(|name| name.eq_ignore_ascii_case(AX_CONFIRM))
    {
        return perform_action(element, AX_CONFIRM);
    }

    Err(AxError::new(AX_ERROR_ACTION_UNSUPPORTED))
}

/// Mark an element selected through `AXSelected`, falling back to `AXPress`.
pub fn select(element: &AppElement) -> Result<(), AxError> {
    if is_attribute_settable(element, "AXSelected") == Some(true) {
        let flag = CFBoolean::true_value();
        return set_attribute_ref(element, "AXSelected", flag.as_CFTypeRef());
    }

    if supports_action(element, AX_PRESS) {
        return perform_action(element, AX_PRESS);
    }

    Err(AxError::new(AX_ERROR_ACTION_UNSUPPORTED))
}

/// Ask an element to reveal itself through `AXScrollToVisible`.
pub fn scroll_into_view(element: &AppElement) -> Result<(), AxError> {
    if supports_action(element, "AXScrollToVisible") {
        return perform_action(element, "AXScrollToVisible");
    }

    Err(AxError::new(AX_ERROR_ACTION_UNSUPPORTED))
}

/// Move focus to an element, falling back to raising its window.
pub fn focus(element: &AppElement) -> Result<(), AxError> {
    if is_attribute_settable(element, "AXFocused").unwrap_or(false) {
        let flag = CFBoolean::true_value();
        return set_attribute_ref(element, "AXFocused", flag.as_CFTypeRef());
    }

    if supports_action(element, AX_RAISE) {
        return perform_action(element, AX_RAISE);
    }

    Err(AxError::new(AX_ERROR_ACTION_UNSUPPORTED))
}

/// Write `AXValue` and read it back. Never retries.
pub fn set_value(element: &AppElement, text: &str) -> Result<ValueWrite, AxError> {
    if is_attribute_settable(element, "AXValue") == Some(false) {
        return Err(AxError::new(AX_ERROR_ATTRIBUTE_UNSUPPORTED));
    }

    let value = CFString::new(text);
    set_attribute_ref(element, "AXValue", value.as_CFTypeRef())?;

    let readback = value_string(element);
    Ok(ValueWrite {
        verified: readback.as_deref() == Some(text),
        value: readback,
    })
}

/// Insert text at the current selection using `AXSelectedTextRange` plus
/// `AXValue`, then verify by reading the value back.
pub fn insert_text(element: &AppElement, text: &str) -> Result<ValueWrite, AxError> {
    if is_attribute_settable(element, "AXValue") != Some(true) {
        return Err(AxError::new(AX_ERROR_ATTRIBUTE_UNSUPPORTED));
    }

    let existing = value_string(element).unwrap_or_default();
    let (location, length) = selected_range(element).unwrap_or_else(|| {
        let end = existing.encode_utf16().count();
        (end, 0)
    });

    let (updated, caret) = insert_utf16(&existing, location, length, text)
        .ok_or_else(|| AxError::new(AX_ERROR_FAILURE))?;

    let value = CFString::new(&updated);
    set_attribute_ref(element, "AXValue", value.as_CFTypeRef())?;
    let _ = set_selected_range(element, caret, 0);

    let readback = value_string(element);
    Ok(ValueWrite {
        verified: readback.as_deref() == Some(updated.as_str()),
        value: readback,
    })
}

/// Scroll by performing `AXIncrement`/`AXDecrement` where the element supports
/// it. Returns the number of steps performed.
pub fn scroll(element: &AppElement, direction: &str, amount: i32) -> Result<u32, AxError> {
    let primary =
        scroll_action_for(direction).ok_or_else(|| AxError::new(AX_ERROR_ILLEGAL_ARGUMENT))?;
    let names = action_names(element);
    let fallback = scroll_fallback_action(direction);

    let action = if names.iter().any(|name| name.eq_ignore_ascii_case(primary)) {
        primary
    } else if let Some(fallback) = fallback {
        if names.iter().any(|name| name.eq_ignore_ascii_case(fallback)) {
            fallback
        } else {
            return Err(AxError::new(AX_ERROR_ACTION_UNSUPPORTED));
        }
    } else {
        return Err(AxError::new(AX_ERROR_ACTION_UNSUPPORTED));
    };

    let steps = amount.unsigned_abs().clamp(1, 10);
    for _ in 0..steps {
        perform_action(element, action)?;
    }

    Ok(steps)
}

/// One scrollbar write and the value read back from it.
pub struct ScrollWrite {
    pub horizontal: Option<f64>,
    pub vertical: Option<f64>,
}

/// Read the scrollbar values for a scroll area or scrollbar element.
pub fn scroll_state(element: &AppElement, role: Option<&str>) -> Option<ScrollState> {
    let role = role.unwrap_or_default();

    if role.eq_ignore_ascii_case("AXScrollBar") {
        let value = attribute_f64(element, "AXValue")? * 100.0;
        let vertical = attribute_string(element, "AXOrientation")
            .is_some_and(|value| value.eq_ignore_ascii_case("AXVerticalOrientation"));

        return Some(ScrollState {
            horizontal_percent: (!vertical).then_some(value),
            vertical_percent: vertical.then_some(value),
            horizontal: !vertical,
            vertical,
            ..Default::default()
        });
    }

    if !role.eq_ignore_ascii_case("AXScrollArea") {
        return None;
    }

    let horizontal_bar = scroll_bar(element, Some(role), false);
    let vertical_bar = scroll_bar(element, Some(role), true);
    let horizontal = horizontal_bar
        .as_ref()
        .and_then(|bar| attribute_f64(bar, "AXValue"));
    let vertical = vertical_bar
        .as_ref()
        .and_then(|bar| attribute_f64(bar, "AXValue"));

    if horizontal.is_none() && vertical.is_none() {
        return None;
    }

    Some(ScrollState {
        horizontal_percent: horizontal.map(|value| value * 100.0),
        vertical_percent: vertical.map(|value| value * 100.0),
        horizontal: horizontal_bar.is_some(),
        vertical: vertical_bar.is_some(),
        ..Default::default()
    })
}

/// Set one or both scrollbar values as percentages.
pub fn scroll_to(
    element: &AppElement,
    horizontal: Option<f64>,
    vertical: Option<f64>,
) -> Result<ScrollWrite, AxError> {
    let role = role(element);
    let horizontal_bar = if horizontal.is_some() {
        scroll_bar(element, role.as_deref(), false)
    } else {
        None
    };
    let vertical_bar = if vertical.is_some() {
        scroll_bar(element, role.as_deref(), true)
    } else {
        None
    };

    if horizontal.is_some() && horizontal_bar.is_none() {
        return Err(AxError::new(AX_ERROR_ACTION_UNSUPPORTED));
    }

    if vertical.is_some() && vertical_bar.is_none() {
        return Err(AxError::new(AX_ERROR_ACTION_UNSUPPORTED));
    }

    if let (Some(bar), Some(percent)) = (horizontal_bar.as_ref(), horizontal) {
        write_scroll_percent(bar, percent)?;
    }

    if let (Some(bar), Some(percent)) = (vertical_bar.as_ref(), vertical) {
        write_scroll_percent(bar, percent)?;
    }

    Ok(ScrollWrite {
        horizontal: horizontal_bar
            .as_ref()
            .and_then(|bar| attribute_f64(bar, "AXValue"))
            .map(|value| value * 100.0),
        vertical: vertical_bar
            .as_ref()
            .and_then(|bar| attribute_f64(bar, "AXValue"))
            .map(|value| value * 100.0),
    })
}

fn scroll_bar(element: &AppElement, role_name: Option<&str>, vertical: bool) -> Option<AppElement> {
    let key = if vertical {
        "AXVerticalScrollBar"
    } else {
        "AXHorizontalScrollBar"
    };

    if let Some(bar) = element_attribute(element, key) {
        return Some(bar);
    }

    if role_name.is_some_and(|value| value.eq_ignore_ascii_case("AXScrollBar")) {
        return Some(element.clone());
    }

    children(element).into_iter().find(|child| {
        let is_bar = role(child)
            .as_deref()
            .is_some_and(|role| role.eq_ignore_ascii_case("AXScrollBar"));
        let orientation = attribute_string(child, "AXOrientation")
            .is_some_and(|value| value.eq_ignore_ascii_case("AXVerticalOrientation"));

        is_bar && orientation == vertical
    })
}

fn write_scroll_percent(bar: &AppElement, percent: f64) -> Result<(), AxError> {
    if is_attribute_settable(bar, "AXValue") == Some(false) {
        return Err(AxError::new(AX_ERROR_ATTRIBUTE_UNSUPPORTED));
    }

    let value = CFNumber::from(percent / 100.0);
    set_attribute_ref(bar, "AXValue", value.as_CFTypeRef())
}

/// Write one element snapshot for one window.
pub fn snapshot(app_pid: i32, request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo> {
    ensure_trusted()?;
    let target = find_window_for_pid(app_pid, &request.window)?;
    snapshot_window(app_pid, target.index, request)
}

/// Snapshot the window at `window_index` for `app_pid`.
pub fn snapshot_window(
    app_pid: i32,
    window_index: usize,
    request: &SnapshotRequest,
) -> Result<Snapshot, ErrorInfo> {
    ensure_trusted()?;

    let app = AppElement::application(app_pid).map_err(to_error)?;
    let _ = app.set_messaging_timeout(MESSAGING_TIMEOUT_SECS);
    let windows = window_elements(&app);
    let window = windows
        .get(window_index)
        .cloned()
        .ok_or_else(stale_window)?;

    let frontmost = frontmost_pid();
    let focused = element_attribute(&app, "AXFocusedWindow");
    let process_name = process_name_for(app_pid);
    let info = window_info_for(
        app_pid,
        window_index,
        &window,
        frontmost,
        focused.as_ref(),
        process_name,
    );

    let max_depth = clamp_depth(request.max_depth.unwrap_or(DEFAULT_MAX_DEPTH));
    let max_elements = clamp_elements(request.max_elements.unwrap_or(DEFAULT_MAX_ELEMENTS));

    let mut state = WalkState {
        records: Vec::new(),
        truncated: false,
    };
    walk(
        &window,
        "",
        0,
        None,
        app_pid,
        window_index,
        max_depth,
        max_elements,
        &mut state,
    );

    Ok(Snapshot {
        window: info,
        total_elements: state.records.len() as u32,
        elements: state.records,
        truncated: state.truncated,
        truncated_by: None,
        children_cut: 0,
        max_depth,
        max_elements,
    })
}

/// Resolve an action target inside a window. Only runtime ids and name/role
/// selectors are resolvable: numeric ids are connection-scoped and therefore
/// stale by the time a stateless backend sees them.
pub fn resolve_element(
    app_pid: i32,
    window_index: usize,
    window: &AppElement,
    target: &ElementRef,
) -> Result<AppElement, ErrorInfo> {
    if let Some(runtime_id) = target.runtime_id.as_deref() {
        return resolve_runtime_id(app_pid, window_index, window, runtime_id);
    }

    if target.name.is_some() || target.role.is_some() || target.automation_id.is_some() {
        let spec = ElementSpec::from_ref(target);
        return find_element(window, &spec).ok_or_else(|| {
            ErrorInfo::new(
                TARGET_NOT_FOUND,
                "no element in the window matches the selector",
            )
        });
    }

    if target.id.is_some() {
        return Err(ErrorInfo::new(
            STALE_TARGET,
            "numeric element ids are connection-scoped; pass runtime_id or a name selector",
        ));
    }

    Err(ErrorInfo::new(
        TARGET_NOT_FOUND,
        "the action target is empty",
    ))
}

/// All visible top-level windows, freshly enumerated.
pub fn enumerate_windows() -> Vec<WindowInfo> {
    let frontmost = frontmost_pid();
    let mut windows = Vec::new();

    for app in running_apps() {
        let element = match AppElement::application(app.pid) {
            Ok(element) => element,
            Err(_) => continue,
        };

        let _ = element.set_messaging_timeout(MESSAGING_TIMEOUT_SECS);
        let focused = element_attribute(&element, "AXFocusedWindow");

        for (index, window) in window_elements(&element).iter().enumerate() {
            if !role_matches("AXWindow", role(window).as_deref()) {
                continue;
            }

            windows.push(window_info_for(
                app.pid,
                index,
                window,
                frontmost,
                focused.as_ref(),
                app.name.clone(),
            ));
        }
    }

    windows.sort_by(|left, right| {
        right
            .foreground
            .cmp(&left.foreground)
            .then_with(|| left.process_name.cmp(&right.process_name))
            .then_with(|| left.title.cmp(&right.title))
    });
    windows
}

/// Find the window that matches a title, process name, or handle.
pub fn find_window(selector: &str) -> Result<WindowTarget, ErrorInfo> {
    ensure_trusted()?;
    let windows = enumerate_windows();
    select_window(&windows, selector).ok_or_else(|| {
        ErrorInfo::new(
            TARGET_NOT_FOUND,
            format!("no window matches {:?}", selector),
        )
    })
}

/// Window elements for one application element.
pub fn window_elements(app: &AppElement) -> Vec<AppElement> {
    element_array_attribute(app, "AXWindows")
}

/// A resolved window: pid, index into `AXWindows`, and its public record.
#[derive(Debug, Clone)]
pub struct WindowTarget {
    pub pid: i32,
    pub index: usize,
    pub info: WindowInfo,
}

/// Result of a value write: the value read back plus whether it matched.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValueWrite {
    pub verified: bool,
    pub value: Option<String>,
}

/// Runtime id decoded back into a resolvable path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimePath {
    pub pid: i32,
    pub window_index: usize,
    pub path: Vec<usize>,
    pub role: Option<String>,
    pub title: Option<String>,
}

/// Snapshot role check used for password fields. The value is never returned.
pub fn is_sensitive(role: Option<&str>, subrole: Option<&str>) -> bool {
    matches_role(role, AX_ROLE_SECURE_TEXT_FIELD)
        || matches_role(subrole, AX_ROLE_SECURE_TEXT_FIELD)
}

fn matches_role(value: Option<&str>, expected: &str) -> bool {
    value
        .map(|value| value.eq_ignore_ascii_case(expected))
        .unwrap_or(false)
}

fn check_error(code: i32) -> Result<(), AxError> {
    if code == AX_ERROR_SUCCESS {
        Ok(())
    } else {
        Err(AxError::new(code))
    }
}

fn cf_type_id(value: &CFType) -> CFTypeID {
    unsafe { CFGetTypeID(value.as_CFTypeRef()) }
}

fn ax_value_ref(value: &CFType) -> Option<AXValueRef> {
    if cf_type_id(value) != unsafe { AXValueGetTypeID() } {
        return None;
    }

    Some(value.as_CFTypeRef())
}

fn array_values(array: CFArrayRef) -> Vec<CFTypeRef> {
    if array.is_null() {
        return Vec::new();
    }

    let count = unsafe { CFArrayGetCount(array) }.max(0);
    let mut values = Vec::with_capacity(count as usize);

    for index in 0..count {
        let value = unsafe { CFArrayGetValueAtIndex(array, index) };
        if !value.is_null() {
            values.push(value);
        }
    }

    values
}

fn selected_range(element: &AppElement) -> Option<(usize, usize)> {
    let value = copy_attribute(element, "AXSelectedTextRange")?;
    let raw = ax_value_ref(&value)?;
    let mut range = CFRange {
        location: 0,
        length: 0,
    };
    let ok = unsafe {
        AXValueGetValue(
            raw,
            AX_VALUE_CFRANGE,
            &mut range as *mut CFRange as *mut c_void,
        )
    };

    if ok == 0 {
        return None;
    }

    Some((range.location.max(0) as usize, range.length.max(0) as usize))
}

fn set_selected_range(element: &AppElement, location: usize, length: usize) -> Result<(), AxError> {
    let range = CFRange {
        location: location as isize,
        length: length as isize,
    };
    let raw = unsafe { AXValueCreate(AX_VALUE_CFRANGE, &range as *const CFRange as *const c_void) };

    if raw.is_null() {
        return Err(AxError::new(AX_ERROR_FAILURE));
    }

    let value = unsafe { CFType::wrap_under_create_rule(raw) };
    set_attribute_ref(element, "AXSelectedTextRange", value.as_CFTypeRef())
}

fn window_info_for(
    pid: i32,
    index: usize,
    window: &AppElement,
    frontmost: Option<i32>,
    focused_window: Option<&AppElement>,
    process_name: Option<String>,
) -> WindowInfo {
    let bounds = frame(window).unwrap_or_default();
    let minimized = attribute_bool(window, "AXMinimized").unwrap_or(false);
    let visible = attribute_bool(window, "AXVisible").unwrap_or(true);
    let focused = match focused_window {
        Some(focused) => elements_equal(focused, window),
        None => true,
    };

    WindowInfo {
        handle: build_window_handle(pid, index),
        pid: pid as u32,
        process_name,
        title: title(window).unwrap_or_default(),
        class_name: role(window),
        bounds,
        foreground: frontmost == Some(pid) && focused,
        enabled: is_enabled(window),
        offscreen: minimized || !visible || bounds.width == 0 || bounds.height == 0,
        dialog: subrole(window)
            .as_deref()
            .is_some_and(crate::dialog::subrole_is_dialog),
    }
}

fn elements_equal(left: &AppElement, right: &AppElement) -> bool {
    unsafe { CFEqual(left.raw(), right.raw()) != 0 }
}

fn find_window_for_pid(pid: i32, selector: &str) -> Result<WindowTarget, ErrorInfo> {
    let app = AppElement::application(pid).map_err(to_error)?;
    let _ = app.set_messaging_timeout(MESSAGING_TIMEOUT_SECS);
    let frontmost = frontmost_pid();
    let focused = element_attribute(&app, "AXFocusedWindow");
    let process_name = process_name_for(pid);

    let windows: Vec<WindowInfo> = window_elements(&app)
        .iter()
        .enumerate()
        .filter(|(_, window)| role_matches("AXWindow", role(window).as_deref()))
        .map(|(index, window)| {
            window_info_for(
                pid,
                index,
                window,
                frontmost,
                focused.as_ref(),
                process_name.clone(),
            )
        })
        .collect();

    select_window(&windows, selector).ok_or_else(|| {
        ErrorInfo::new(
            TARGET_NOT_FOUND,
            format!("no window matches {:?}", selector),
        )
    })
}

fn resolve_runtime_id(
    pid: i32,
    window_index: usize,
    window: &AppElement,
    runtime_id: &str,
) -> Result<AppElement, ErrorInfo> {
    let parsed = parse_runtime_id(runtime_id)
        .ok_or_else(|| ErrorInfo::new(INVALID_REQUEST, "runtime_id is not an AX element path"))?;

    if parsed.pid != pid || parsed.window_index != window_index {
        return Err(ErrorInfo::new(
            STALE_TARGET,
            "runtime_id belongs to another window; take a fresh snapshot",
        ));
    }

    let mut current = window.clone();
    for index in parsed.path.iter().copied() {
        let next = children(&current).into_iter().nth(index).ok_or_else(|| {
            ErrorInfo::new(STALE_TARGET, "the AX element path no longer resolves")
        })?;
        current = next;
    }

    if let Some(expected) = parsed.role {
        if !role_matches(&expected, role(&current).as_deref()) {
            return Err(ErrorInfo::new(
                STALE_TARGET,
                "the AX element at this path changed role; take a fresh snapshot",
            ));
        }
    }

    Ok(current)
}

fn find_element(root: &AppElement, spec: &ElementSpec) -> Option<AppElement> {
    let mut queue = VecDeque::new();
    queue.push_back(root.clone());
    let mut visited = 0;

    while let Some(node) = queue.pop_front() {
        visited += 1;
        if visited > MAX_SEARCH_ELEMENTS {
            return None;
        }

        if spec.matches(&node) {
            return Some(node);
        }

        queue.extend(children(&node));
    }

    None
}

#[allow(clippy::too_many_arguments)]
fn walk(
    element: &AppElement,
    path: &str,
    depth: u32,
    parent: Option<u32>,
    app_pid: i32,
    window_index: usize,
    max_depth: u32,
    max_elements: u32,
    state: &mut WalkState,
) {
    if state.records.len() >= max_elements as usize {
        state.truncated = true;
        return;
    }

    let role = role(element);
    let subrole = subrole(element);
    let name = title(element).or_else(|| description(element));
    let sensitive = is_sensitive(role.as_deref(), subrole.as_deref());
    let id = state.records.len() as u32;
    let mut patterns = action_names(element);

    if is_attribute_settable(element, "AXValue") == Some(true) {
        patterns.push("SetValue".to_string());
    }

    state.records.push(ElementRecord {
        id,
        parent,
        depth,
        runtime_id: build_runtime_id(
            app_pid,
            window_index,
            path,
            role.as_deref(),
            name.as_deref(),
        ),
        control_type: role.clone().unwrap_or_default(),
        name,
        automation_id: automation_id(element),
        class_name: subrole,
        value: if sensitive {
            None
        } else {
            value_string(element)
        },
        enabled: is_enabled(element),
        offscreen: !attribute_bool(element, "AXVisible").unwrap_or(true),
        bounds: frame(element),
        patterns,
        sensitive,
        scroll: scroll_state(element, role.as_deref()),
        path: None,
    });

    if depth >= max_depth {
        if !children(element).is_empty() {
            state.truncated = true;
        }
        return;
    }

    let mut descendants = children(element);
    if is_menu_role(role.as_deref()) {
        let remaining = max_elements.saturating_sub(state.records.len() as u32) as usize;
        if menu_dominates_budget(count_subtree(element, remaining / 2 + 1), remaining) {
            descendants.clear();
        }
    }

    for (index, child) in descendants.iter().enumerate() {
        let child_path = if path.is_empty() {
            index.to_string()
        } else {
            format!("{path}.{index}")
        };

        walk(
            child,
            &child_path,
            depth + 1,
            Some(id),
            app_pid,
            window_index,
            max_depth,
            max_elements,
            state,
        );

        if state.truncated && state.records.len() >= max_elements as usize {
            break;
        }
    }
}

fn count_subtree(element: &AppElement, limit: usize) -> usize {
    if limit == 0 {
        return 0;
    }

    let mut count = 1;
    let mut queue = VecDeque::new();
    queue.push_back(element.clone());

    while let Some(node) = queue.pop_front() {
        for child in children(&node) {
            count += 1;
            if count >= limit {
                return count;
            }
            queue.push_back(child);
        }
    }

    count
}

fn running_apps() -> Vec<AppTarget> {
    autoreleasepool(|_pool| {
        let workspace = NSWorkspace::sharedWorkspace();
        let frontmost = workspace
            .frontmostApplication()
            .map(|app| app.processIdentifier());
        let applications = workspace.runningApplications();
        let mut targets = Vec::new();

        for application in applications.iter() {
            if application.isTerminated() {
                continue;
            }

            let policy = application.activationPolicy();
            if policy == NSApplicationActivationPolicy::Prohibited {
                continue;
            }

            let pid = application.processIdentifier();
            let name = application.localizedName().map(|name| name.to_string());
            targets.push(AppTarget {
                pid,
                name,
                active: frontmost == Some(pid),
            });
        }

        targets
    })
}

fn frontmost_pid() -> Option<i32> {
    let apps = running_apps();
    apps.iter().find(|app| app.active).map(|app| app.pid)
}

fn process_name_for(pid: i32) -> Option<String> {
    running_apps()
        .into_iter()
        .find(|app| app.pid == pid)
        .and_then(|app| app.name)
}

fn bounds_from_point_size(point: CGPoint, size: CGSize) -> Bounds {
    Bounds {
        left: point.x.round() as i32,
        top: point.y.round() as i32,
        width: size.width.round() as i32,
        height: size.height.round() as i32,
    }
}

fn clamp_depth(depth: u32) -> u32 {
    depth.clamp(1, HARD_MAX_DEPTH)
}

fn clamp_elements(elements: u32) -> u32 {
    elements.clamp(1, HARD_MAX_ELEMENTS)
}

fn build_window_handle(pid: i32, index: usize) -> String {
    format!("ax:{pid}:{index}")
}

fn window_index_from_handle(handle: &str, pid: i32) -> Option<usize> {
    let mut parts = handle.split(':');
    if parts.next()? != "ax" {
        return None;
    }

    if parts.next()?.parse::<i32>().ok()? != pid {
        return None;
    }

    parts.next()?.parse().ok()
}

fn select_window(windows: &[WindowInfo], selector: &str) -> Option<WindowTarget> {
    let selector = selector.trim();

    if selector.is_empty() {
        return windows.first().map(window_target);
    }

    if let Some(window) = windows.iter().find(|window| window.handle == selector) {
        return Some(window_target(window));
    }

    let lower = selector.to_lowercase();

    windows
        .iter()
        .find(|window| window.title.to_lowercase() == lower)
        .or_else(|| {
            windows
                .iter()
                .find(|window| window.title.to_lowercase().contains(&lower))
        })
        .or_else(|| {
            windows.iter().find(|window| {
                window
                    .process_name
                    .as_deref()
                    .map(|name| name.to_lowercase() == lower)
                    .unwrap_or(false)
            })
        })
        .or_else(|| {
            windows.iter().find(|window| {
                window
                    .process_name
                    .as_deref()
                    .map(|name| name.to_lowercase().contains(&lower))
                    .unwrap_or(false)
            })
        })
        .map(window_target)
}

fn window_target(window: &WindowInfo) -> WindowTarget {
    let pid = window.pid as i32;
    let index = window_index_from_handle(&window.handle, pid).unwrap_or(0);

    WindowTarget {
        pid,
        index,
        info: window.clone(),
    }
}

fn build_runtime_id(
    pid: i32,
    window_index: usize,
    path: &str,
    role: Option<&str>,
    title: Option<&str>,
) -> String {
    format!(
        "ax:{}:w{}:{}|{}|{}",
        pid,
        window_index,
        path,
        sanitize_token(role.unwrap_or_default()),
        sanitize_token(title.unwrap_or_default()),
    )
}

fn parse_runtime_id(runtime_id: &str) -> Option<RuntimePath> {
    let mut fields = runtime_id.splitn(3, '|');
    let head = fields.next()?;
    let role = fields
        .next()
        .map(str::to_string)
        .filter(|value| !value.is_empty());
    let title = fields
        .next()
        .map(str::to_string)
        .filter(|value| !value.is_empty());
    let head = head.strip_prefix("ax:")?;
    let mut parts = head.split(':');
    let pid = parts.next()?.parse().ok()?;
    let window_index = parts.next()?.strip_prefix('w')?.parse().ok()?;
    let path = parts.next().unwrap_or_default();
    let path = if path.is_empty() {
        Vec::new()
    } else {
        path.split('.')
            .map(|segment| segment.parse().ok())
            .collect::<Option<Vec<usize>>>()?
    };

    Some(RuntimePath {
        pid,
        window_index,
        path,
        role,
        title,
    })
}

fn sanitize_token(value: &str) -> String {
    value
        .replace('|', "/")
        .replace(['\n', '\r', '\t'], " ")
        .trim()
        .chars()
        .take(80)
        .collect()
}

fn insert_utf16(
    existing: &str,
    location: usize,
    length: usize,
    insert: &str,
) -> Option<(String, usize)> {
    let mut units: Vec<u16> = existing.encode_utf16().collect();
    let start = location.min(units.len());
    let end = location.saturating_add(length).min(units.len());
    let inserted: Vec<u16> = insert.encode_utf16().collect();
    let caret = start + inserted.len();
    units.splice(start..end, inserted);

    String::from_utf16(&units).ok().map(|text| (text, caret))
}

fn role_matches(expected: &str, actual: Option<&str>) -> bool {
    let actual = match actual {
        Some(actual) => actual,
        None => return false,
    };

    normalize_role(expected).eq_ignore_ascii_case(normalize_role(actual))
}

fn normalize_role(role: &str) -> &str {
    role.strip_prefix("AX")
        .or_else(|| role.strip_prefix("ax"))
        .unwrap_or(role)
}

fn is_menu_role(role: Option<&str>) -> bool {
    matches!(role, Some("AXMenuBar" | "AXMenu" | "AXMenuBarItem"))
}

fn menu_dominates_budget(subtree: usize, remaining: usize) -> bool {
    remaining > 0 && subtree * 2 > remaining
}

fn scroll_action_for(direction: &str) -> Option<&'static str> {
    match direction.trim().to_ascii_lowercase().as_str() {
        "up" | "left" => Some(AX_DECREMENT),
        "down" | "right" => Some(AX_INCREMENT),
        _ => None,
    }
}

fn scroll_fallback_action(direction: &str) -> Option<&'static str> {
    match direction.trim().to_ascii_lowercase().as_str() {
        "up" => Some("AXScrollUp"),
        "down" => Some("AXScrollDown"),
        "left" => Some("AXScrollLeft"),
        "right" => Some("AXScrollRight"),
        _ => None,
    }
}

fn stale_window() -> ErrorInfo {
    ErrorInfo::new(
        STALE_TARGET,
        "the window disappeared; take a fresh window list",
    )
}

#[derive(Debug)]
struct WalkState {
    records: Vec<ElementRecord>,
    truncated: bool,
}

#[derive(Debug, Clone)]
struct AppTarget {
    pid: i32,
    name: Option<String>,
    active: bool,
}

#[derive(Debug, Clone, Default)]
struct ElementSpec {
    name: Option<String>,
    role: Option<String>,
    automation_id: Option<String>,
}

impl ElementSpec {
    fn from_ref(target: &ElementRef) -> Self {
        Self {
            name: target.name.clone(),
            role: target.role.clone(),
            automation_id: target.automation_id.clone(),
        }
    }

    fn matches(&self, element: &AppElement) -> bool {
        if let Some(role) = self.role.as_deref() {
            if !role_matches(role, role_of(element).as_deref()) {
                return false;
            }
        }

        if let Some(expected) = self.automation_id.as_deref() {
            if automation_id(element).as_deref() != Some(expected) {
                return false;
            }
        }

        if let Some(expected) = self.name.as_deref() {
            let actual = title(element).or_else(|| description(element));
            let actual = match actual {
                Some(actual) => actual,
                None => return false,
            };

            if actual != expected && !actual.to_lowercase().contains(&expected.to_lowercase()) {
                return false;
            }
        }

        self.name.is_some() || self.role.is_some() || self.automation_id.is_some()
    }
}

fn role_of(element: &AppElement) -> Option<String> {
    role(element)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::{Bounds, WindowInfo};

    fn window(
        handle: &str,
        pid: u32,
        name: Option<&str>,
        title: &str,
        foreground: bool,
    ) -> WindowInfo {
        WindowInfo {
            handle: handle.to_string(),
            pid,
            process_name: name.map(str::to_string),
            title: title.to_string(),
            foreground,
            ..Default::default()
        }
    }

    #[test]
    fn runtime_ids_round_trip() {
        let runtime_id = build_runtime_id(42, 3, "1.4", Some("AXButton"), Some("Save"));
        let parsed = parse_runtime_id(&runtime_id).expect("parse");

        assert_eq!(parsed.pid, 42);
        assert_eq!(parsed.window_index, 3);
        assert_eq!(parsed.path, vec![1, 4]);
        assert_eq!(parsed.role.as_deref(), Some("AXButton"));
        assert_eq!(parsed.title.as_deref(), Some("Save"));
    }

    #[test]
    fn root_runtime_id_parses_to_empty_path() {
        let runtime_id = build_runtime_id(7, 0, "", Some("AXWindow"), Some("Mail"));
        let parsed = parse_runtime_id(&runtime_id).expect("parse");

        assert!(parsed.path.is_empty());
        assert_eq!(parsed.title.as_deref(), Some("Mail"));
    }

    #[test]
    fn runtime_id_rejects_foreign_shapes() {
        assert!(parse_runtime_id("hwnd:123").is_none());
        assert!(parse_runtime_id("ax:not-a-pid:w0:").is_none());
        assert!(parse_runtime_id("ax:1:w0:1.x").is_none());
    }

    #[test]
    fn runtime_id_titles_are_sanitized() {
        let runtime_id = build_runtime_id(1, 0, "", Some("AXButton"), Some("a|b\nc"));
        let parsed = parse_runtime_id(&runtime_id).expect("parse");

        assert_eq!(parsed.title.as_deref(), Some("a/b c"));
    }

    #[test]
    fn handle_parsing_keeps_pid_and_index() {
        assert_eq!(window_index_from_handle("ax:99:2", 99), Some(2));
        assert_eq!(window_index_from_handle("ax:98:2", 99), None);
        assert_eq!(window_index_from_handle("hwnd:12", 99), None);
    }

    #[test]
    fn window_selection_prefers_handle_then_title_then_process() {
        let windows = vec![
            window("ax:10:0", 10, Some("Excel"), "Book1", false),
            window("ax:20:0", 20, Some("Safari"), "Apple", true),
        ];

        assert_eq!(select_window(&windows, "ax:20:0").unwrap().pid, 20);
        assert_eq!(select_window(&windows, "Book1").unwrap().pid, 10);
        assert_eq!(select_window(&windows, "safari").unwrap().pid, 20);
        assert_eq!(select_window(&windows, "apple").unwrap().pid, 20);
        assert_eq!(select_window(&windows, "").unwrap().pid, 10);
        assert!(select_window(&windows, "absent").is_none());
    }

    #[test]
    fn menu_skipping_needs_a_dominating_subtree() {
        let windows_remaining = 1_000;

        assert!(!menu_dominates_budget(10, windows_remaining));
        assert!(menu_dominates_budget(800, windows_remaining));
        assert!(!menu_dominates_budget(10, 0));
    }

    #[test]
    fn sensitive_roles_cover_role_and_subrole() {
        assert!(is_sensitive(Some("AXSecureTextField"), None));
        assert!(is_sensitive(None, Some("AXSecureTextField")));
        assert!(!is_sensitive(Some("AXTextField"), Some("AXSearchField")));
    }

    #[test]
    fn roles_match_with_and_without_prefix() {
        assert!(role_matches("button", Some("AXButton")));
        assert!(role_matches("AXButton", Some("button")));
        assert!(!role_matches("AXButton", Some("AXCheckBox")));
        assert!(!role_matches("AXButton", None));
    }

    #[test]
    fn text_insertion_uses_utf16_offsets() {
        assert_eq!(insert_utf16("hello", 5, 0, "!"), Some(("hello!".into(), 6)));
        assert_eq!(
            insert_utf16("hello", 0, 0, "oh "),
            Some(("oh hello".into(), 3))
        );
        assert_eq!(insert_utf16("hello", 1, 4, "i"), Some(("hi".into(), 2)));
    }

    #[test]
    fn text_insertion_tracks_utf16_caret() {
        assert_eq!(insert_utf16("a😀b", 3, 0, "x"), Some(("a😀xb".into(), 4)));
    }

    #[test]
    fn scroll_direction_maps_to_ax_actions() {
        assert_eq!(scroll_action_for("up"), Some("AXDecrement"));
        assert_eq!(scroll_action_for("RIGHT"), Some("AXIncrement"));
        assert_eq!(scroll_action_for("diagonal"), None);
        assert_eq!(scroll_fallback_action("down"), Some("AXScrollDown"));
    }

    #[test]
    fn bounds_round_points_to_pixels() {
        let bounds = bounds_from_point_size(CGPoint::new(-12.4, 30.6), CGSize::new(640.5, 480.4));

        assert_eq!(
            bounds,
            Bounds {
                left: -12,
                top: 31,
                width: 641,
                height: 480
            }
        );
    }

    #[test]
    fn budgets_are_clamped() {
        assert_eq!(clamp_depth(0), 1);
        assert_eq!(clamp_depth(10_000), HARD_MAX_DEPTH);
        assert_eq!(clamp_elements(0), 1);
        assert_eq!(clamp_elements(u32::MAX), HARD_MAX_ELEMENTS);
    }
}
