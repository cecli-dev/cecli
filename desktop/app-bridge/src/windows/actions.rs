//! Windows semantic actions owned by T7.
//!
//! `perform` is wired from [`super::WindowsBackend::action`] for every
//! element-scoped verb: `get_value`, `set_value`, `invoke`, element `click`, and
//! the UIA state patterns `toggle`, `select`, `expand`, and `collapse`. `cell_at`
//! resolves a grid cell by one-based row and column, optionally targeting a grid
//! element from the current snapshot instead of the window's first grid. `scroll_to`
//! sets the UIA ScrollPattern percentages on an element.
//! Relative wheel input (`keys`, `focus`, point clicks, `scroll`) and `range_value`
//! belong to other layers and are rejected here.
//!
//! Delivery, verification, and uncertainty are reported separately. A pattern
//! call that returned is delivered; a post-state read inside the poll budget
//! decides verification; a timeout is uncertain and is never retried. Every send
//! is preceded by a fresh enabled read and T6 re-checks element identity when the
//! handle is resolved from the snapshot cache.

use std::time::{Duration, Instant};

use windows::core::{Error as ComError, IUnknown, Interface, BSTR};
use windows::Win32::Foundation::E_INVALIDARG;
use windows::Win32::System::Com::{CoCreateInstance, CLSCTX_INPROC_SERVER};
use windows::Win32::System::Variant::{VARIANT, VARIANT_0, VARIANT_0_0, VARIANT_0_0_0, VT_I4};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, ExpandCollapseState, ExpandCollapseState_Collapsed,
    ExpandCollapseState_Expanded, ExpandCollapseState_PartiallyExpanded, IUIAutomation,
    IUIAutomationCondition, IUIAutomationElement, IUIAutomationGridItemPattern,
    IUIAutomationGridPattern, IUIAutomationTablePattern, IUIAutomationValuePattern, ToggleState,
    ToggleState_Off, ToggleState_On, TreeScope_Descendants, UIA_ControlTypePropertyId,
    UIA_DataGridControlTypeId, UIA_GridItemPatternId, UIA_GridPatternId, UIA_TableControlTypeId,
    UIA_TablePatternId, UIA_ValuePatternId, UIA_E_ELEMENTNOTAVAILABLE, UIA_E_ELEMENTNOTENABLED,
    UIA_E_TIMEOUT,
};

use crate::protocol::{
    error_kind, outcome, ActionArgs, ActionRequest, ActionResult, ElementRef, ErrorInfo, WindowInfo,
};

use super::element;
use super::enumerate;
use super::input;
use super::uia::{ElementHandle, UiaSnapshotCache};

/// Total time a read-back or post-state may take before reporting unverified.
const VERIFY_BUDGET: Duration = Duration::from_millis(600);
/// Delay between fresh read-back attempts.
const VERIFY_STEP: Duration = Duration::from_millis(50);
/// UIA sentinel that leaves one scroll axis untouched.
const NO_SCROLL: f64 = -1.0;
/// Percentage tolerance when confirming an absolute scroll position.
const SCROLL_TOLERANCE: f64 = 2.0;
/// Control types whose text may sit behind TextPattern or LegacyIAccessible.
const TEXTUAL_CONTROL_TYPES: [&str; 3] = ["Edit", "Document", "Text"];

/// Perform an element-scoped action (`invoke`, `set_value`, `get_value`,
/// `toggle`, `select`, `expand`, `collapse`, element clicks).
pub fn perform(
    backend: &super::WindowsBackend,
    request: &ActionRequest,
) -> Result<ActionResult, ErrorInfo> {
    let verb = ActionVerb::parse(&request.action)?;
    let window = enumerate::resolve_window(&request.window)?;
    enumerate::check_integrity(&window)?;

    if verb == ActionVerb::CellAt {
        return cell_at(backend, &window, request.target.as_ref(), &request.args);
    }

    // Resolve the target while holding the snapshot cache, then release it
    // before the action runs. Pointer actions re-resolve the element through
    // `input::element_target`, which takes this same mutex; holding it across
    // the dispatch would deadlock the backend thread.
    let handle = {
        let cache_guard = backend
            .snapshot_cache
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let Some(cache) = cache_guard.as_ref() else {
            return Err(ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                "no snapshot is cached for this connection; take a snapshot before acting",
            ));
        };

        if !same_window(cache.window(), &window) {
            return Err(ErrorInfo::new(
                error_kind::STALE_TARGET,
                "the cached snapshot belongs to a different window; take a snapshot of this window first",
            ));
        }

        let target = request
            .target
            .as_ref()
            .filter(|target| !target.is_empty())
            .ok_or_else(|| {
                ErrorInfo::new(
                    error_kind::TARGET_NOT_FOUND,
                    format!(
                        "action '{}' requires a target element from the current snapshot",
                        verb.as_str()
                    ),
                )
            })?;

        cache.resolve_target(target)?
    };

    match verb {
        ActionVerb::GetValue => get_value(&handle, &request.action),
        ActionVerb::SetValue => set_value(&handle, &request.action, request.args.value.as_deref()),
        ActionVerb::Invoke => invoke_or_click(backend, request, &handle, &request.action),
        ActionVerb::Click
        | ActionVerb::DoubleClick
        | ActionVerb::RightClick
        | ActionVerb::Hover => invoke(&handle, &request.action),
        ActionVerb::Toggle => toggle(&handle, &request.action),
        ActionVerb::Select => select(&handle, &request.action),
        ActionVerb::ScrollIntoView => scroll_into_view(&handle, &request.action),
        ActionVerb::ScrollTo => match scroll_to(&handle, &request.action, &request.args) {
            // Many grids and panes expose no Scroll pattern at all, and some - such
            // as Notepad's text editor - expose one whose SetScrollPercent call fails
            // outright. Rather than failing the verb, anchor a wheel scroll on the
            // element centre and report the position as unconfirmed.
            Err(error) if scroll_falls_back(&error) => {
                input::scroll_at_element(backend, request, &handle, &scroll_fallback_reason(&error))
            }
            result => result,
        },
        ActionVerb::Expand => expand_collapse(&handle, &request.action, true),
        ActionVerb::Collapse => expand_collapse(&handle, &request.action, false),
        ActionVerb::CellAt => cell_at(backend, &window, request.target.as_ref(), &request.args),
    }
}

fn get_value(handle: &ElementHandle, action: &str) -> Result<ActionResult, ErrorInfo> {
    ensure_not_password(handle)?;
    let value = read_value(handle)?;

    Ok(ActionResult {
        action: action.to_string(),
        delivered: true,
        verified: true,
        uncertain: false,
        value: Some(value),
        message: None,
        outcome: Some(outcome::ACCESSIBILITY.to_string()),
    })
}

fn set_value(
    handle: &ElementHandle,
    action: &str,
    value: Option<&str>,
) -> Result<ActionResult, ErrorInfo> {
    let Some(value) = value else {
        return Err(ErrorInfo::invalid("set_value requires args.value"));
    };

    ensure_not_password(handle)?;
    ensure_enabled(handle)?;

    let wide = BSTR::from(value);

    if let Ok(pattern) = handle.value_pattern() {
        if let Some(result) =
            send_result(action, "Value.SetValue", unsafe { pattern.SetValue(&wide) })?
        {
            return Ok(result);
        }
    } else if is_edit(handle) {
        let pattern = handle.select_pattern()?;
        if let Some(result) = send_result(action, "LegacyIAccessible.SetValue", unsafe {
            pattern.SetValue(&wide)
        })? {
            return Ok(result);
        }
    } else {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!(
                "element '{}' does not support Value.SetValue or LegacyIAccessible.SetValue",
                label(handle)
            ),
        ));
    }

    let verified = poll_until(
        VERIFY_BUDGET,
        VERIFY_STEP,
        || read_value(handle).ok(),
        |current| current == value,
    );

    Ok(state_result(
        action,
        verified,
        Some(value.to_string()),
        "the target accepted the write but the read-back did not match within 600 ms",
    ))
}

/// Invoke an element, falling back to a pointer click when no invoke pattern
/// works: legacy dialog controls often expose none, and a pattern that exists
/// can still fail at call time (a broken `LegacyIAccessible`).
fn invoke_or_click(
    backend: &super::WindowsBackend,
    request: &ActionRequest,
    handle: &ElementHandle,
    action: &str,
) -> Result<ActionResult, ErrorInfo> {
    ensure_enabled(handle)?;

    let mut pattern_error: Option<ErrorInfo> = None;

    if let Ok(pattern) = handle.invoke_pattern() {
        match send_result(action, "Invoke.Invoke", unsafe { pattern.Invoke() }) {
            Ok(Some(result)) => return Ok(result),
            Ok(None) => return Ok(async_result(action, invocation_message(handle))),
            Err(error) => pattern_error = Some(error),
        }
    } else if let Ok(pattern) = handle.select_pattern() {
        match send_result(action, "LegacyIAccessible.DoDefaultAction", unsafe {
            pattern.DoDefaultAction()
        }) {
            Ok(Some(result)) => return Ok(result),
            Ok(None) => return Ok(async_result(action, invocation_message(handle))),
            Err(error) => pattern_error = Some(error),
        }
    }

    match input::click_element_fallback(backend, request, handle, action) {
        Ok(result) => Ok(result),
        Err(error) => Err(match pattern_error {
            Some(pattern) => ErrorInfo::new(
                error.kind.clone(),
                format!(
                    "{} (the pointer fallback also failed: {})",
                    pattern.message, error.message
                ),
            ),
            None => error,
        }),
    }
}

/// Describe a completed pattern call without claiming verification.
fn invocation_message(handle: &ElementHandle) -> &'static str {
    if handle.is_enabled_fresh().is_ok() {
        "the pattern call returned; invocation is asynchronous, so confirm the effect with a fresh snapshot"
    } else {
        "the pattern call returned, but the element is no longer readable; confirm the effect with a fresh snapshot"
    }
}

fn invoke(handle: &ElementHandle, action: &str) -> Result<ActionResult, ErrorInfo> {
    ensure_enabled(handle)?;

    if let Ok(pattern) = handle.invoke_pattern() {
        if let Some(result) = send_result(action, "Invoke.Invoke", unsafe { pattern.Invoke() })? {
            return Ok(result);
        }
    } else {
        let pattern = handle.select_pattern()?;
        if let Some(result) = send_result(action, "LegacyIAccessible.DoDefaultAction", unsafe {
            pattern.DoDefaultAction()
        })? {
            return Ok(result);
        }
    }

    let identity_ok = handle.is_enabled_fresh().is_ok();
    let message = if identity_ok {
        "the pattern call returned; invocation is asynchronous, so confirm the effect with a fresh snapshot"
    } else {
        "the pattern call returned, but the element is no longer readable; confirm the effect with a fresh snapshot"
    };

    Ok(async_result(action, message))
}

fn toggle(handle: &ElementHandle, action: &str) -> Result<ActionResult, ErrorInfo> {
    ensure_enabled(handle)?;

    let pattern = handle.toggle_pattern()?;
    let before = unsafe { pattern.CurrentToggleState() }.ok();

    if let Some(result) = send_result(action, "Toggle.Toggle", unsafe { pattern.Toggle() })? {
        return Ok(result);
    }

    let verified = poll_until(
        VERIFY_BUDGET,
        VERIFY_STEP,
        || unsafe { pattern.CurrentToggleState() }.ok(),
        |state| toggle_state_changed(before, *state),
    );

    let value = unsafe { pattern.CurrentToggleState() }
        .ok()
        .and_then(toggle_state_text);

    Ok(state_result(
        action,
        verified,
        value,
        "the toggle call returned but the state did not change within 600 ms",
    ))
}

fn select(handle: &ElementHandle, action: &str) -> Result<ActionResult, ErrorInfo> {
    ensure_enabled(handle)?;

    let pattern = handle.selection_item_pattern()?;
    if let Some(result) = send_result(action, "SelectionItem.Select", unsafe { pattern.Select() })?
    {
        return Ok(result);
    }

    let verified = poll_until(
        VERIFY_BUDGET,
        VERIFY_STEP,
        || unsafe { pattern.CurrentIsSelected() }.ok(),
        |selected| selected.as_bool(),
    );

    Ok(state_result(
        action,
        verified,
        None,
        "the select call returned but the element did not report itself selected within 600 ms",
    ))
}

fn scroll_into_view(handle: &ElementHandle, action: &str) -> Result<ActionResult, ErrorInfo> {
    ensure_enabled(handle)?;

    let message = if let Ok(pattern) = handle.scroll_item_pattern() {
        if let Some(result) = send_result(action, "ScrollItem.ScrollIntoView", unsafe {
            pattern.ScrollIntoView()
        })? {
            return Ok(result);
        }

        "ScrollIntoView returned; confirm the element is on screen with a fresh snapshot"
    } else {
        unsafe { handle.raw_element().SetFocus() }
            .map_err(|error| send_failure("Element.SetFocus", error))?;

        "the element exposes no ScrollItem pattern; focused it so its container may reveal it"
    };

    Ok(async_result(action, message))
}

/// Whether a failed `scroll_to` should degrade to a wheel scroll.
///
/// `unsupported` means the element exposes no Scroll pattern; `backend_error`
/// means the pattern exists but the provider refused `SetScrollPercent` (Notepad
/// answers `E_FAIL`). A disabled or stale element is a real failure and is not
/// retried as pointer input.
fn scroll_falls_back(error: &ErrorInfo) -> bool {
    error.kind == error_kind::UNSUPPORTED || error.kind == error_kind::BACKEND_ERROR
}

/// Human-readable reason recorded on a wheel-fallback result.
fn scroll_fallback_reason(error: &ErrorInfo) -> String {
    if error.kind == error_kind::UNSUPPORTED {
        "the element has no Scroll pattern".to_string()
    } else {
        format!(
            "the Scroll pattern could not set the position ({})",
            error.message
        )
    }
}
fn scroll_to(
    handle: &ElementHandle,
    action: &str,
    args: &ActionArgs,
) -> Result<ActionResult, ErrorInfo> {
    ensure_enabled(handle)?;

    let (horizontal, vertical) = args.scroll_target().map_err(ErrorInfo::invalid)?;
    let pattern = handle.scroll_pattern()?;
    let sent = unsafe {
        pattern.SetScrollPercent(
            horizontal.unwrap_or(NO_SCROLL),
            vertical.unwrap_or(NO_SCROLL),
        )
    };

    if let Some(result) = send_result(action, "ScrollPattern.SetScrollPercent", sent)? {
        return Ok(result);
    }

    let verified = poll_until(
        VERIFY_BUDGET,
        VERIFY_STEP,
        || {
            let horizontal = unsafe { pattern.CurrentHorizontalScrollPercent() }.ok();
            let vertical = unsafe { pattern.CurrentVerticalScrollPercent() }.ok();

            Some((horizontal, vertical))
        },
        |(current_horizontal, current_vertical)| {
            scroll_axis_matches(*current_horizontal, horizontal)
                && scroll_axis_matches(*current_vertical, vertical)
        },
    );

    Ok(state_result(
        action,
        verified,
        None,
        "the scroll call returned but the requested position was not reached within 600 ms",
    ))
}

fn scroll_axis_matches(current: Option<f64>, requested: Option<f64>) -> bool {
    match requested {
        None => true,
        Some(target) => current.is_some_and(|value| (value - target).abs() <= SCROLL_TOLERANCE),
    }
}

fn expand_collapse(
    handle: &ElementHandle,
    action: &str,
    expand: bool,
) -> Result<ActionResult, ErrorInfo> {
    ensure_enabled(handle)?;

    let pattern = handle.expand_collapse_pattern()?;
    let sent = if expand {
        unsafe { pattern.Expand() }
    } else {
        unsafe { pattern.Collapse() }
    };
    let call = if expand {
        "ExpandCollapse.Expand"
    } else {
        "ExpandCollapse.Collapse"
    };

    if let Some(result) = send_result(action, call, sent)? {
        return Ok(result);
    }

    let verified = poll_until(
        VERIFY_BUDGET,
        VERIFY_STEP,
        || unsafe { pattern.CurrentExpandCollapseState() }.ok(),
        |state| expand_collapse_satisfied(expand, *state),
    );

    Ok(state_result(
        action,
        verified,
        None,
        if expand {
            "the expand call returned but the state did not reach expanded within 600 ms"
        } else {
            "the collapse call returned but the state did not reach collapsed within 600 ms"
        },
    ))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ActionVerb {
    GetValue,
    SetValue,
    Invoke,
    Click,
    DoubleClick,
    RightClick,
    Hover,
    Toggle,
    Select,
    ScrollIntoView,
    ScrollTo,
    Expand,
    Collapse,
    CellAt,
}

impl ActionVerb {
    fn parse(action: &str) -> Result<Self, ErrorInfo> {
        let normalized = normalize_verb(action);

        match normalized.as_str() {
            "get_value" => Ok(Self::GetValue),
            "set_value" => Ok(Self::SetValue),
            "invoke" => Ok(Self::Invoke),
            "click" => Ok(Self::Click),
            "double_click" => Ok(Self::DoubleClick),
            "right_click" => Ok(Self::RightClick),
            "hover" => Ok(Self::Hover),
            "toggle" => Ok(Self::Toggle),
            "select" => Ok(Self::Select),
            "scroll_into_view" => Ok(Self::ScrollIntoView),
            "scroll_to" => Ok(Self::ScrollTo),
            "expand" => Ok(Self::Expand),
            "collapse" => Ok(Self::Collapse),
            "cell_at" => Ok(Self::CellAt),
            "range_value" | "scroll" => Err(ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                format!(
                    "action '{normalized}' is not handled by the Windows semantic action layer"
                ),
            )),
            other => Err(ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                format!("unknown action '{other}' for the Windows UIA backend"),
            )),
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::GetValue => "get_value",
            Self::SetValue => "set_value",
            Self::Invoke => "invoke",
            Self::Click => "click",
            Self::DoubleClick => "double_click",
            Self::RightClick => "right_click",
            Self::Hover => "hover",
            Self::Toggle => "toggle",
            Self::Select => "select",
            Self::ScrollIntoView => "scroll_into_view",
            Self::ScrollTo => "scroll_to",
            Self::Expand => "expand",
            Self::Collapse => "collapse",
            Self::CellAt => "cell_at",
        }
    }
}

fn normalize_verb(action: &str) -> String {
    action.trim().to_ascii_lowercase().replace('-', "_")
}

fn same_window(cached: &WindowInfo, requested: &WindowInfo) -> bool {
    cached.handle == requested.handle && cached.pid == requested.pid
}

fn label(handle: &ElementHandle) -> &str {
    handle.record().name.as_deref().unwrap_or("<unnamed>")
}

fn is_edit(handle: &ElementHandle) -> bool {
    handle.record().control_type.eq_ignore_ascii_case("Edit")
}

fn is_textual(handle: &ElementHandle) -> bool {
    let control_type = handle.record().control_type.as_str();

    TEXTUAL_CONTROL_TYPES
        .iter()
        .any(|candidate| control_type.eq_ignore_ascii_case(candidate))
}

fn ensure_not_password(handle: &ElementHandle) -> Result<(), ErrorInfo> {
    if handle.is_password() {
        return Err(ErrorInfo::new(
            error_kind::INPUT_BLOCKED,
            format!(
                "element '{}' is a password or otherwise sensitive control; its value is never read or written",
                label(handle)
            ),
        ));
    }

    Ok(())
}

fn ensure_enabled(handle: &ElementHandle) -> Result<(), ErrorInfo> {
    if handle.is_enabled_fresh()? {
        return Ok(());
    }

    Err(ErrorInfo::new(
        error_kind::INPUT_BLOCKED,
        format!("element '{}' is disabled; nothing was sent", label(handle)),
    ))
}

fn read_value(handle: &ElementHandle) -> Result<String, ErrorInfo> {
    if let Ok(pattern) = handle.value_pattern() {
        match unsafe { pattern.CurrentValue() } {
            Ok(value) => return Ok(value.to_string()),
            Err(error) => {
                if let Some(stale) = stale_error(error) {
                    return Err(stale);
                }
            }
        }
    }

    if is_textual(handle) {
        if let Ok(pattern) = handle.select_pattern() {
            match unsafe { pattern.CurrentValue() } {
                Ok(value) => return Ok(value.to_string()),
                Err(error) => {
                    if let Some(stale) = stale_error(error) {
                        return Err(stale);
                    }
                }
            }
        }
    }

    Err(ErrorInfo::new(
        error_kind::UNSUPPORTED,
        format!(
            "element '{}' exposes no readable value through Value, Text, or LegacyIAccessible",
            label(handle)
        ),
    ))
}

fn send_result(
    action: &str,
    call: &str,
    result: windows::core::Result<()>,
) -> Result<Option<ActionResult>, ErrorInfo> {
    match result {
        Ok(()) => Ok(None),
        Err(error) => {
            if error.code().0 as u32 == UIA_E_TIMEOUT {
                let mut result = ActionResult::uncertain(
                    action,
                    format!("{call} timed out; the outcome is unknown and it was not retried"),
                );
                result.outcome = Some(outcome::ACCESSIBILITY.to_string());

                return Ok(Some(result));
            }

            Err(send_failure(call, error))
        }
    }
}

fn send_failure(call: &str, error: ComError) -> ErrorInfo {
    let code = error.code().0 as u32;

    if code == UIA_E_ELEMENTNOTENABLED {
        return ErrorInfo::new(
            error_kind::INPUT_BLOCKED,
            format!("{call} failed because the element is disabled: {error}"),
        );
    }

    if code == UIA_E_ELEMENTNOTAVAILABLE {
        return ErrorInfo::new(
            error_kind::STALE_TARGET,
            format!("{call} failed because the element is no longer available: {error}"),
        );
    }

    ErrorInfo::backend(format!("{call} failed: {error}"))
}

fn stale_error(error: ComError) -> Option<ErrorInfo> {
    let code = error.code().0 as u32;

    if code == UIA_E_ELEMENTNOTAVAILABLE || code == UIA_E_ELEMENTNOTENABLED {
        return Some(ErrorInfo::new(
            error_kind::STALE_TARGET,
            format!("the element is no longer available: {error}"),
        ));
    }

    None
}

fn toggle_state_changed(before: Option<ToggleState>, after: ToggleState) -> bool {
    before != Some(after)
}

fn toggle_state_text(state: ToggleState) -> Option<String> {
    let text = if state == ToggleState_On {
        "true"
    } else if state == ToggleState_Off {
        "false"
    } else {
        "indeterminate"
    };

    Some(text.to_string())
}

fn expand_collapse_satisfied(expand: bool, state: ExpandCollapseState) -> bool {
    if expand {
        state == ExpandCollapseState_Expanded || state == ExpandCollapseState_PartiallyExpanded
    } else {
        state == ExpandCollapseState_Collapsed
    }
}

fn state_result(
    action: &str,
    verified: bool,
    value: Option<String>,
    mismatch: &str,
) -> ActionResult {
    ActionResult {
        action: action.to_string(),
        delivered: true,
        verified,
        uncertain: false,
        value,
        message: (!verified).then(|| mismatch.to_string()),
        outcome: Some(outcome::ACCESSIBILITY.to_string()),
    }
}

fn async_result(action: &str, message: &str) -> ActionResult {
    ActionResult {
        action: action.to_string(),
        delivered: true,
        verified: false,
        uncertain: false,
        value: None,
        message: Some(message.to_string()),
        outcome: Some(outcome::ACCESSIBILITY.to_string()),
    }
}

fn poll_until<T>(
    budget: Duration,
    step: Duration,
    mut read: impl FnMut() -> Option<T>,
    accept: impl Fn(&T) -> bool,
) -> bool {
    let deadline = Instant::now() + budget;
    let step = if step.is_zero() {
        Duration::from_millis(1)
    } else {
        step
    };

    loop {
        if read().as_ref().is_some_and(&accept) {
            return true;
        }

        let now = Instant::now();
        if now >= deadline {
            return false;
        }

        std::thread::sleep(step.min(deadline - now));
    }
}

/// Number of descendants inspected before the grid search gives up.
const CELL_SCAN_LIMIT: usize = 2000;

/// Resolve the one-based `row` and `column` arguments for `cell_at`.
fn cell_arguments(args: &ActionArgs) -> Result<(u32, u32), ErrorInfo> {
    let row = args
        .row
        .ok_or_else(|| ErrorInfo::invalid("cell_at requires args.row"))?;
    let column = args
        .column
        .ok_or_else(|| ErrorInfo::invalid("cell_at requires args.column"))?;

    Ok((row, column))
}

/// Subtract one from one-based cell coordinates to get the zero-based UIA pair.
fn zero_based_cell(row: u32, column: u32) -> Result<(i32, i32), ErrorInfo> {
    let zero_row = row
        .checked_sub(1)
        .ok_or_else(|| cell_not_found(row, column))?;
    let zero_column = column
        .checked_sub(1)
        .ok_or_else(|| cell_not_found(row, column))?;
    let zero_row = i32::try_from(zero_row).map_err(|_| cell_not_found(row, column))?;
    let zero_column = i32::try_from(zero_column).map_err(|_| cell_not_found(row, column))?;

    Ok((zero_row, zero_column))
}

fn cell_not_found(row: u32, column: u32) -> ErrorInfo {
    ErrorInfo::new(
        error_kind::TARGET_NOT_FOUND,
        format!("no cell at row {row}, column {column}"),
    )
}

/// Resolve an optional grid target against the connection's cached snapshot.
///
/// `Ok(None)` means no target was supplied, so the window's first grid is used.
/// A target that cannot be resolved is reported as stale instead of quietly
/// falling back to another sheet.
fn resolve_grid_target(
    cache: Option<&UiaSnapshotCache>,
    window: &WindowInfo,
    target: Option<&ElementRef>,
) -> Result<Option<ElementHandle>, ErrorInfo> {
    let Some(target) = target.filter(|target| !target.is_empty()) else {
        return Ok(None);
    };
    let Some(cache) = cache else {
        return Err(ErrorInfo::new(
            error_kind::STALE_TARGET,
            "no snapshot is cached for this connection; take a fresh snapshot and retry",
        ));
    };

    if !same_window(cache.window(), window) {
        return Err(ErrorInfo::new(
            error_kind::STALE_TARGET,
            "the cached snapshot belongs to a different window; take a fresh snapshot of this window and retry",
        ));
    }

    cache.resolve_target(target).map(Some).map_err(|error| {
        ErrorInfo::new(
            error_kind::STALE_TARGET,
            format!(
                "cannot resolve the grid target in the cached snapshot; take a fresh snapshot and retry: {}",
                error.message
            ),
        )
    })
}

/// Address one cell in the window's first grid, or in a target grid, by
/// one-based row and column.
fn cell_at(
    backend: &super::WindowsBackend,
    window: &WindowInfo,
    target: Option<&ElementRef>,
    args: &ActionArgs,
) -> Result<ActionResult, ErrorInfo> {
    let (row, column) = cell_arguments(args)?;
    let (zero_row, zero_column) = zero_based_cell(row, column)?;

    std::thread::scope(|scope| {
        std::thread::Builder::new()
            .name("ce-app-bridge-cell".to_string())
            .spawn_scoped(scope, || {
                cell_at_on_mta(backend, window, target, row, column, zero_row, zero_column)
            })
            .map_err(|error| {
                ErrorInfo::backend(format!("cannot start the cell lookup thread: {error}"))
            })?
            .join()
            .map_err(|_| ErrorInfo::backend("the cell lookup thread panicked"))?
    })
}

fn cell_at_on_mta(
    backend: &super::WindowsBackend,
    window: &WindowInfo,
    target: Option<&ElementRef>,
    row: u32,
    column: u32,
    zero_row: i32,
    zero_column: i32,
) -> Result<ActionResult, ErrorInfo> {
    let hwnd = enumerate::parse_handle(&window.handle).ok_or_else(|| {
        ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            format!("invalid window handle {:?}", window.handle),
        )
    })?;

    enumerate::ensure_mta()?;
    let automation: IUIAutomation =
        unsafe { CoCreateInstance(&CUIAutomation, None::<&IUnknown>, CLSCTX_INPROC_SERVER) }
            .map_err(|error| {
                ErrorInfo::new(
                    error_kind::UNSUPPORTED,
                    format!("CoCreateInstance(CUIAutomation) failed: {error}"),
                )
            })?;
    let root = unsafe { automation.ElementFromHandle(hwnd) }
        .map_err(|error| lookup_failure("ElementFromHandle", error))?;
    let target = {
        let cache = backend
            .snapshot_cache
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        resolve_grid_target(cache.as_ref(), window, target)?
    };
    let grid = find_grid(&automation, &root, target.as_ref())?;
    let (cell, expected) = grid.cell(row, column, zero_row, zero_column)?;

    Ok(cell_result(&cell, row, column, expected, grid.label()))
}

fn cell_result(
    cell: &IUIAutomationElement,
    row: u32,
    column: u32,
    expected: (i32, i32),
    label: Option<&str>,
) -> ActionResult {
    let name = unsafe { cell.CurrentName() }
        .ok()
        .map(|name| name.to_string())
        .filter(|name| !name.trim().is_empty());
    let value = element_value(cell)
        .or(name)
        .unwrap_or_else(|| format!("row {row}, column {column}"));
    let scope = label
        .map(|label| format!(" on '{label}'"))
        .unwrap_or_default();
    let (verified, reason) = match cell_position(cell) {
        Some((actual_row, actual_column)) if (actual_row, actual_column) == expected => {
            (true, None)
        }
        Some((actual_row, actual_column)) => (
            false,
            Some(format!(
                "the cell reports row {}, column {}",
                actual_row + 1,
                actual_column + 1
            )),
        ),
        None => (
            false,
            Some("the cell exposes no GridItem position, so the lookup is unverified".to_string()),
        ),
    };
    let cell_name = unsafe { cell.CurrentName() }
        .ok()
        .map(|name| name.to_string())
        .filter(|name| !name.trim().is_empty())
        .map(|name| format!(" (cell {name})"))
        .unwrap_or_default();
    let message = match reason {
        Some(reason) => format!("row {row}, column {column}{scope}{cell_name} ({reason})"),
        None => format!("row {row}, column {column}{scope}{cell_name}"),
    };

    ActionResult {
        action: "cell_at".to_string(),
        delivered: true,
        verified,
        uncertain: false,
        value: Some(value),
        message: Some(message),
        outcome: Some(outcome::ACCESSIBILITY.to_string()),
    }
}

/// Read the cell's own zero-based position, when it exposes a GridItem pattern.
fn cell_position(cell: &IUIAutomationElement) -> Option<(i32, i32)> {
    let pattern =
        unsafe { cell.GetCurrentPatternAs::<IUIAutomationGridItemPattern>(UIA_GridItemPatternId) }
            .ok()?;
    let row = unsafe { pattern.CurrentRow() }.ok()?;
    let column = unsafe { pattern.CurrentColumn() }.ok()?;

    Some((row, column))
}

/// Locate a grid in the window, or at or below a resolved target element.
fn find_grid(
    automation: &IUIAutomation,
    window_root: &IUIAutomationElement,
    target: Option<&ElementHandle>,
) -> Result<GridHandle, ErrorInfo> {
    let root = target.map_or(window_root, |handle| handle.raw_element());
    let mut table = None;

    match target {
        Some(handle) => {
            if let Ok(grid) = handle.grid_pattern() {
                return Ok(GridHandle::new(automation, root, Some(grid), None));
            }
        }
        None => {
            if let Some(grid) = probe_grid(automation, root) {
                return Ok(grid);
            }

            table = probe_table(automation, root);
        }
    }

    let candidates = grid_candidate_condition(automation)?;
    let (grid, _) = scan_candidates(automation, root, &candidates, &mut table)?;
    if let Some(grid) = grid {
        return Ok(grid);
    }

    let all = unsafe { automation.CreateTrueCondition() }
        .map_err(|error| ErrorInfo::backend(format!("CreateTrueCondition failed: {error}")))?;
    let (grid, inspected) = scan_candidates(automation, root, &all, &mut table)?;
    if let Some(grid) = grid {
        return Ok(grid);
    }

    if let Some(handle) = target {
        return Err(target_grid_error(handle));
    }

    if let Some(table) = table {
        return Ok(table);
    }

    if inspected > CELL_SCAN_LIMIT {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!(
                "the window has more than {CELL_SCAN_LIMIT} descendants and none in that range exposes a UIA grid pattern; target the cell by name, e.g. 'B2'"
            ),
        ));
    }

    Err(no_grid_error())
}

fn scan_candidates(
    automation: &IUIAutomation,
    root: &IUIAutomationElement,
    condition: &IUIAutomationCondition,
    table: &mut Option<GridHandle>,
) -> Result<(Option<GridHandle>, usize), ErrorInfo> {
    let elements = unsafe { root.FindAll(TreeScope_Descendants, condition) }
        .map_err(|error| lookup_failure("Element.FindAll", error))?;
    let total = unsafe { elements.Length() }.unwrap_or(0).max(0) as usize;
    let inspected = total.min(CELL_SCAN_LIMIT);

    for index in 0..inspected {
        let Ok(element) = (unsafe { elements.GetElement(index as i32) }) else {
            continue;
        };

        if let Some(grid) = probe_grid(automation, &element) {
            return Ok((Some(grid), total));
        }

        if table.is_none() {
            *table = probe_table(automation, &element);
        }
    }

    Ok((None, total))
}

fn probe_grid(automation: &IUIAutomation, element: &IUIAutomationElement) -> Option<GridHandle> {
    let grid =
        unsafe { element.GetCurrentPatternAs::<IUIAutomationGridPattern>(UIA_GridPatternId) }
            .ok()?;

    Some(GridHandle::new(automation, element, Some(grid), None))
}

fn probe_table(automation: &IUIAutomation, element: &IUIAutomationElement) -> Option<GridHandle> {
    let table =
        unsafe { element.GetCurrentPatternAs::<IUIAutomationTablePattern>(UIA_TablePatternId) }
            .ok()?;

    Some(GridHandle::new(automation, element, None, Some(table)))
}

fn grid_candidate_condition(
    automation: &IUIAutomation,
) -> Result<IUIAutomationCondition, ErrorInfo> {
    let mut condition = control_type_condition(automation, UIA_TableControlTypeId.0)?;

    for control_type in [
        UIA_DataGridControlTypeId.0,
        element::control_type_id::CUSTOM,
        element::control_type_id::PANE,
    ] {
        let next = control_type_condition(automation, control_type)?;
        condition = unsafe { automation.CreateOrCondition(&condition, &next) }
            .map_err(|error| ErrorInfo::backend(format!("CreateOrCondition failed: {error}")))?;
    }

    Ok(condition)
}

fn control_type_condition(
    automation: &IUIAutomation,
    control_type: i32,
) -> Result<IUIAutomationCondition, ErrorInfo> {
    use std::mem::ManuallyDrop;

    let value = VARIANT {
        Anonymous: VARIANT_0 {
            Anonymous: ManuallyDrop::new(VARIANT_0_0 {
                vt: VT_I4,
                wReserved1: 0,
                wReserved2: 0,
                wReserved3: 0,
                Anonymous: VARIANT_0_0_0 { lVal: control_type },
            }),
        },
    };

    unsafe { automation.CreatePropertyCondition(UIA_ControlTypePropertyId, &value) }
        .map_err(|error| ErrorInfo::backend(format!("CreatePropertyCondition failed: {error}")))
}

/// Address one cell and return it with the position its GridItem pattern should
/// report.
///
/// Excel numbers its grid from the header corner, so index `(1, 1)` is cell `A1`
/// rather than the top-left data cell. That offset is detected from the A1-style
/// name the grid reports, then the shifted index is confirmed by name before use.
fn grid_cell(
    grid: &IUIAutomationGridPattern,
    row: u32,
    column: u32,
    zero_row: i32,
    zero_column: i32,
) -> Result<(IUIAutomationElement, (i32, i32)), ErrorInfo> {
    // `CurrentRowCount` is the realized window for a virtualized grid (Excel
    // reports the visible rows), so it cannot bound the lookup. GetItem realizes
    // the cell on demand and answers E_INVALIDARG past the sheet edge.
    let cell = unsafe { grid.GetItem(zero_row, zero_column) }
        .map_err(|error| grid_lookup_failure(error, row, column))?;

    if cell.as_raw().is_null() {
        return Err(cell_not_found(row, column));
    }

    if a1_position(&cell_name(&cell)) != Some((row, column)) {
        let shifted_row = zero_row + 1;
        let shifted_column = zero_column + 1;

        if let Ok(shifted) = unsafe { grid.GetItem(shifted_row, shifted_column) } {
            if !shifted.as_raw().is_null()
                && a1_position(&cell_name(&shifted)) == Some((row, column))
            {
                return Ok((shifted, (shifted_row, shifted_column)));
            }
        }
    }

    Ok((cell, (zero_row, zero_column)))
}

/// Read a cell's Value pattern, which is where grids keep the cell content.
fn element_value(cell: &IUIAutomationElement) -> Option<String> {
    let pattern: IUIAutomationValuePattern =
        unsafe { cell.GetCurrentPatternAs::<IUIAutomationValuePattern>(UIA_ValuePatternId) }
            .ok()?;
    let value = unsafe { pattern.CurrentValue() }.ok()?.to_string();

    (!value.is_empty()).then_some(value)
}

fn cell_name(cell: &IUIAutomationElement) -> String {
    unsafe { cell.CurrentName() }
        .ok()
        .map(|name| name.to_string())
        .unwrap_or_default()
}

/// Parse an A1-style cell name such as `B2` into one-based row and column.
fn a1_position(name: &str) -> Option<(u32, u32)> {
    let name = name.trim();
    let split = name.find(|character: char| character.is_ascii_digit())?;
    let (letters, digits) = name.split_at(split);

    if letters.is_empty() || digits.is_empty() {
        return None;
    }

    let mut column = 0u32;

    for letter in letters.chars() {
        if !letter.is_ascii_alphabetic() {
            return None;
        }

        column = column
            .checked_mul(26)?
            .checked_add(letter.to_ascii_uppercase() as u32 - 64)?;
    }

    let row = digits.parse::<u32>().ok()?;

    (row > 0 && column > 0).then_some((row, column))
}

fn grid_lookup_failure(error: ComError, row: u32, column: u32) -> ErrorInfo {
    if error.code() == E_INVALIDARG {
        return cell_not_found(row, column);
    }

    lookup_failure("GridPattern.GetItem", error)
}

fn lookup_failure(call: &str, error: ComError) -> ErrorInfo {
    if error.code().0 as u32 == UIA_E_ELEMENTNOTAVAILABLE {
        return ErrorInfo::new(
            error_kind::STALE_TARGET,
            format!("the element is no longer available: {error}"),
        );
    }

    send_failure(call, error)
}

fn target_grid_error(handle: &ElementHandle) -> ErrorInfo {
    ErrorInfo::new(
        error_kind::TARGET_NOT_FOUND,
        format!(
            "element '{}' (runtime id {}) exposes no UIA grid pattern at or below it; target the grid itself or the cell by name, e.g. 'B2'",
            label(handle),
            handle.runtime_id()
        ),
    )
}

fn no_grid_error() -> ErrorInfo {
    ErrorInfo::new(
        error_kind::UNSUPPORTED,
        "the window exposes no UIA grid pattern; target the cell by name, e.g. 'B2'",
    )
}

/// Walk up a few ancestors so the sheet name scopes the reported cell.
fn grid_label(automation: &IUIAutomation, grid: &IUIAutomationElement) -> Option<String> {
    let walker = unsafe { automation.ControlViewWalker() }.ok()?;
    let mut current = grid.clone();

    for _ in 0..4 {
        let name = unsafe { current.CurrentName() }
            .ok()
            .map(|name| name.to_string())
            .unwrap_or_default();
        let name = name.trim();

        if !name.is_empty() && !name.eq_ignore_ascii_case("grid") {
            return Some(name.to_string());
        }

        current = unsafe { walker.GetParentElement(&current) }.ok()?;
    }

    None
}

/// A located grid and the pattern used to address its cells.
struct GridHandle {
    automation: IUIAutomation,
    element: IUIAutomationElement,
    grid: Option<IUIAutomationGridPattern>,
    table: Option<IUIAutomationTablePattern>,
    label: Option<String>,
}

impl GridHandle {
    fn new(
        automation: &IUIAutomation,
        element: &IUIAutomationElement,
        grid: Option<IUIAutomationGridPattern>,
        table: Option<IUIAutomationTablePattern>,
    ) -> Self {
        let label = grid_label(automation, element);

        Self {
            automation: automation.clone(),
            element: element.clone(),
            grid,
            table,
            label,
        }
    }

    fn label(&self) -> Option<&str> {
        self.label.as_deref()
    }

    fn cell(
        &self,
        row: u32,
        column: u32,
        zero_row: i32,
        zero_column: i32,
    ) -> Result<(IUIAutomationElement, (i32, i32)), ErrorInfo> {
        if let Some(grid) = &self.grid {
            return grid_cell(grid, row, column, zero_row, zero_column);
        }

        if self.table.is_some() {
            return self.table_cell(row, column, zero_row, zero_column);
        }

        Err(no_grid_error())
    }

    fn table_cell(
        &self,
        row: u32,
        column: u32,
        zero_row: i32,
        zero_column: i32,
    ) -> Result<(IUIAutomationElement, (i32, i32)), ErrorInfo> {
        let condition = unsafe { self.automation.CreateTrueCondition() }
            .map_err(|error| ErrorInfo::backend(format!("CreateTrueCondition failed: {error}")))?;
        let elements = unsafe { self.element.FindAll(TreeScope_Descendants, &condition) }
            .map_err(|error| lookup_failure("Table.FindAll", error))?;
        let total = unsafe { elements.Length() }.unwrap_or(0).max(0) as usize;

        for index in 0..total.min(CELL_SCAN_LIMIT) {
            let Ok(cell) = (unsafe { elements.GetElement(index as i32) }) else {
                continue;
            };

            if cell_position(&cell) == Some((zero_row, zero_column)) {
                return Ok((cell, (zero_row, zero_column)));
            }
        }

        Err(cell_not_found(row, column))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cell_at_is_a_recognized_verb() {
        assert_eq!(ActionVerb::parse(" Cell-At ").unwrap(), ActionVerb::CellAt);
        assert_eq!(ActionVerb::CellAt.as_str(), "cell_at");
    }

    #[test]
    fn cell_arguments_require_row_and_column() {
        let error = cell_arguments(&ActionArgs::default()).unwrap_err();
        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
        assert_eq!(error.message, "cell_at requires args.row");

        let args = ActionArgs {
            row: Some(2),
            ..Default::default()
        };
        let error = cell_arguments(&args).unwrap_err();
        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
        assert_eq!(error.message, "cell_at requires args.column");
    }

    #[test]
    fn cell_positions_are_one_based() {
        assert_eq!(zero_based_cell(1, 1).unwrap(), (0, 0));
        assert_eq!(zero_based_cell(3, 2).unwrap(), (2, 1));

        let error = zero_based_cell(0, 1).unwrap_err();
        assert_eq!(error.kind, error_kind::TARGET_NOT_FOUND);
        assert!(error.message.contains("row 0"));

        let error = zero_based_cell(1, 0).unwrap_err();
        assert_eq!(error.kind, error_kind::TARGET_NOT_FOUND);
        assert!(error.message.contains("column 0"));
    }

    #[test]
    fn a1_names_parse_to_one_based_positions() {
        assert_eq!(a1_position("B2"), Some((2, 2)));
        assert_eq!(a1_position("a1"), Some((1, 1)));
        assert_eq!(a1_position("AA10"), Some((10, 27)));
        assert_eq!(a1_position("Select All"), None);
        assert_eq!(a1_position(""), None);
    }

    fn window(handle: &str, pid: u32) -> WindowInfo {
        WindowInfo {
            handle: handle.to_string(),
            pid,
            ..Default::default()
        }
    }

    fn com_error(code: u32) -> ComError {
        ComError::from_hresult(windows::core::HRESULT(code as i32))
    }

    #[test]
    fn verbs_normalize_case_whitespace_and_separators() {
        assert_eq!(
            ActionVerb::parse(" Get-Value ").unwrap(),
            ActionVerb::GetValue
        );
        assert_eq!(
            ActionVerb::parse("SET_VALUE").unwrap(),
            ActionVerb::SetValue
        );
        assert_eq!(ActionVerb::parse("click").unwrap(), ActionVerb::Click);
        assert_eq!(
            ActionVerb::parse("Double-Click").unwrap(),
            ActionVerb::DoubleClick
        );
        assert_eq!(
            ActionVerb::parse("right_click").unwrap(),
            ActionVerb::RightClick
        );
        assert_eq!(ActionVerb::parse("hover").unwrap(), ActionVerb::Hover);
        assert_eq!(
            ActionVerb::parse("Scroll-Into-View").unwrap(),
            ActionVerb::ScrollIntoView
        );
        assert_eq!(ActionVerb::parse("select").unwrap(), ActionVerb::Select);
        assert_eq!(ActionVerb::parse("Expand").unwrap(), ActionVerb::Expand);
    }

    #[test]
    fn delegated_and_unknown_verbs_are_invalid_requests() {
        for verb in ["range_value", "range-value", "scroll"] {
            let error = ActionVerb::parse(verb).unwrap_err();
            assert_eq!(error.kind, error_kind::INVALID_REQUEST);
            assert!(error.message.contains(&normalize_verb(verb)));
        }

        let error = ActionVerb::parse("levitate").unwrap_err();
        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
        assert!(error.message.contains("levitate"));
    }

    #[test]
    fn cached_window_must_match_handle_and_pid() {
        assert!(same_window(&window("0x10", 7), &window("0x10", 7)));
        assert!(!same_window(&window("0x10", 7), &window("0x11", 7)));
        assert!(!same_window(&window("0x10", 7), &window("0x10", 8)));
    }

    #[test]
    fn poll_matches_immediately_without_waiting() {
        let started = Instant::now();
        let matched = poll_until(
            VERIFY_BUDGET,
            VERIFY_STEP,
            || Some(2u32),
            |value| *value == 2,
        );

        assert!(matched);
        assert!(started.elapsed() < Duration::from_millis(100));
    }

    #[test]
    fn poll_accepts_a_late_match() {
        let mut attempts = 0u32;
        let matched = poll_until(
            Duration::from_millis(200),
            Duration::from_millis(5),
            || {
                attempts += 1;
                Some(attempts)
            },
            |value| *value >= 3,
        );

        assert!(matched);
        assert!(attempts >= 3);
    }

    #[test]
    fn poll_gives_up_within_the_budget() {
        let started = Instant::now();
        let matched = poll_until(
            Duration::from_millis(60),
            Duration::from_millis(10),
            || Some(0u32),
            |_| false,
        );

        assert!(!matched);
        assert!(started.elapsed() < Duration::from_millis(500));
    }

    #[test]
    fn verified_write_construction_reports_delivery_and_mismatch() {
        let result = state_result("set_value", false, Some("x".into()), "did not match");

        assert!(result.delivered);
        assert!(!result.verified);
        assert!(!result.uncertain);
        assert_eq!(result.value.as_deref(), Some("x"));
        assert_eq!(result.message.as_deref(), Some("did not match"));

        let verified = state_result("expand", true, None, "did not match");
        assert!(verified.delivered && verified.verified);
        assert!(verified.message.is_none());
    }

    #[test]
    fn asynchronous_result_is_unverified_and_explains_why() {
        let result = async_result("invoke", "confirm with a snapshot");

        assert!(result.delivered);
        assert!(!result.verified);
        assert!(!result.uncertain);
        assert!(result.value.is_none());
        assert_eq!(result.message.as_deref(), Some("confirm with a snapshot"));
    }

    #[test]
    fn toggle_and_expand_expectations_track_the_requested_state() {
        assert!(toggle_state_changed(Some(ToggleState_Off), ToggleState_On));
        assert!(!toggle_state_changed(Some(ToggleState_On), ToggleState_On));
        assert!(toggle_state_changed(None, ToggleState_On));

        assert_eq!(toggle_state_text(ToggleState_On).as_deref(), Some("true"));
        assert_eq!(toggle_state_text(ToggleState_Off).as_deref(), Some("false"));

        assert!(expand_collapse_satisfied(
            true,
            ExpandCollapseState_Expanded
        ));
        assert!(expand_collapse_satisfied(
            true,
            ExpandCollapseState_PartiallyExpanded
        ));
        assert!(!expand_collapse_satisfied(
            true,
            ExpandCollapseState_Collapsed
        ));
        assert!(expand_collapse_satisfied(
            false,
            ExpandCollapseState_Collapsed
        ));
        assert!(!expand_collapse_satisfied(
            false,
            ExpandCollapseState_Expanded
        ));
    }

    #[test]
    fn uia_timeouts_are_uncertain_not_errors() {
        let result = send_result("invoke", "Invoke.Invoke", Err(com_error(UIA_E_TIMEOUT)))
            .unwrap()
            .unwrap();

        assert!(result.delivered);
        assert!(!result.verified);
        assert!(result.uncertain);
    }

    #[test]
    fn a_successful_send_has_no_early_result() {
        assert!(send_result("invoke", "Invoke.Invoke", Ok(()))
            .unwrap()
            .is_none());
    }

    #[test]
    fn element_state_errors_map_to_stable_kinds() {
        let error = send_result(
            "toggle",
            "Toggle.Toggle",
            Err(com_error(UIA_E_ELEMENTNOTENABLED)),
        )
        .unwrap_err();
        assert_eq!(error.kind, error_kind::INPUT_BLOCKED);

        let error = send_result(
            "toggle",
            "Toggle.Toggle",
            Err(com_error(UIA_E_ELEMENTNOTAVAILABLE)),
        )
        .unwrap_err();
        assert_eq!(error.kind, error_kind::STALE_TARGET);
    }

    #[test]
    fn an_empty_cell_target_matches_no_target() {
        let window = window("0x10", 7);
        let empty = ElementRef::default();

        assert!(resolve_grid_target(None, &window, None).unwrap().is_none());
        assert!(resolve_grid_target(None, &window, Some(&empty))
            .unwrap()
            .is_none());
    }

    #[test]
    fn an_unresolvable_cell_target_is_stale() {
        let window = window("0x10", 7);
        let target = ElementRef {
            id: Some(4),
            ..Default::default()
        };

        let error = resolve_grid_target(None, &window, Some(&target)).unwrap_err();

        assert_eq!(error.kind, error_kind::STALE_TARGET);
        assert!(error.message.contains("snapshot"));
        assert!(error.message.contains("retry"));
    }

    #[test]
    fn a_missing_scroll_pattern_falls_back_to_the_wheel() {
        let error = ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "element does not support the Scroll pattern",
        );

        assert!(scroll_falls_back(&error));
        assert_eq!(
            scroll_fallback_reason(&error),
            "the element has no Scroll pattern"
        );
    }

    #[test]
    fn a_refused_set_scroll_percent_falls_back_to_the_wheel() {
        let error = ErrorInfo::backend("ScrollPattern.SetScrollPercent failed: 0x80131509");

        assert!(scroll_falls_back(&error));

        let reason = scroll_fallback_reason(&error);

        assert!(reason.starts_with("the Scroll pattern could not set the position"));
        assert!(reason.contains("0x80131509"));
    }

    #[test]
    fn a_blocked_or_stale_element_is_not_retried_as_a_wheel() {
        for kind in [error_kind::INPUT_BLOCKED, error_kind::STALE_TARGET] {
            let error = ErrorInfo::new(kind, "blocked");

            assert!(!scroll_falls_back(&error), "{kind} must not fall back");
        }
    }
}
