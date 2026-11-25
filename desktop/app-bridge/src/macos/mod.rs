//! macOS backend: Accessibility tree, window enumeration, and TCC checks.
//!
//! The backend dispatches structure and semantics to [`ax`], input events to
//! [`input`], and mirrors TCC state through [`permissions`]. It holds no AX
//! state between
//! calls: every request re-enumerates windows and re-resolves its target, which
//! keeps the bridge's zero-state contract intact.

pub mod ax;
pub mod input;
pub mod permissions;

use std::collections::BTreeMap;

use crate::protocol::error_kind::{self, INPUT_BLOCKED, NO_PERMISSION, UNSUPPORTED};
use crate::protocol::{
    outcome, ActionRequest, ActionResult, CheckResult, DoctorReport, ElementRef, ErrorInfo, Health,
    Point, PointerButton, ScreenshotRequest, Snapshot, SnapshotRequest, WindowInfo,
};
use crate::Backend;

use self::ax::{AppElement, AxError};

/// macOS backend handle.
#[derive(Debug, Default)]
pub struct MacBackend;

impl MacBackend {
    /// Create a backend bound to this process.
    pub fn new() -> Self {
        Self
    }
}

impl Backend for MacBackend {
    fn name(&self) -> &'static str {
        "macos-ax"
    }

    fn platform(&self) -> &'static str {
        "macos"
    }

    fn capabilities(&self) -> Vec<String> {
        [
            "windows",
            "snapshot",
            "action",
            "invoke",
            "click",
            "keys",
            "get_value",
            "set_value",
            "focus",
            "scroll",
            "scroll_to",
            "cell_at",
            "dialogs",
        ]
        .iter()
        .map(|name| name.to_string())
        .collect()
    }

    fn health(&self) -> Health {
        if permissions::accessibility_trusted() {
            Health::Ready
        } else {
            Health::Degraded
        }
    }

    fn doctor(&self) -> DoctorReport {
        let current = permissions::Permissions::current();
        let trusted = current.accessibility;
        let screen = current.screen_recording;
        let mut entries = BTreeMap::new();
        entries.insert(
            "accessibility".to_string(),
            permissions::word(trusted).to_string(),
        );
        entries.insert(
            "screen_recording".to_string(),
            permissions::word(screen).to_string(),
        );

        DoctorReport {
            platform: self.platform().to_string(),
            backend: self.name().to_string(),
            health: if current.ready() {
                Health::Ready
            } else {
                Health::Degraded
            },
            permissions: entries,
            checks: vec![
                CheckResult::new(
                    "accessibility-trusted",
                    trusted,
                    if trusted {
                        "AXUIElement calls and CGEventPostToPid are permitted"
                    } else {
                        "grant Accessibility in System Settings > Privacy & Security"
                    },
                ),
                CheckResult::new(
                    "cg-event-access",
                    trusted,
                    if trusted {
                        "keys, coordinate clicks, and the scroll fallback can post events"
                    } else {
                        "CGEventPostToPid needs the Accessibility grant"
                    },
                ),
                CheckResult::new("ax-backend", true, "AXUIElement and AXValue are available"),
                CheckResult::new(
                    "background-input",
                    true,
                    "keys, coordinate clicks, and the scroll fallback post to the target process without activating it; a self-activation is reverted",
                ),
                CheckResult::new(
                    "screen-recording",
                    screen,
                    if screen {
                        "screen capture is permitted"
                    } else {
                        "screenshots need Screen Recording; the prompt is shown on first use"
                    },
                ),
            ],
            notes: vec![
                "window and element bounds are AX screen points, not backing pixels".to_string(),
                "keys, click with a point, and the scroll fallback post through CGEventPostToPid without activating the target; if the app brings itself forward, the prior frontmost app is restored"
                    .to_string(),
                "invoke, click by element, focus, and scroll with an AX action do not need the target frontmost"
                    .to_string(),
                "window capture lands with the capture plane; screenshot reports unsupported until then"
                    .to_string(),
            ],
        }
    }

    fn windows(&self) -> Result<Vec<WindowInfo>, ErrorInfo> {
        ax::ensure_trusted()?;
        Ok(ax::enumerate_windows())
    }

    fn snapshot(&self, request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo> {
        ax::ensure_trusted()?;
        let window = ax::find_window(&request.window)?;
        ax::snapshot_window(window.pid, window.index, request)
    }

    fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        ax::ensure_trusted()?;

        let action = request.action.to_ascii_lowercase();
        let window = ax::find_window(&request.window)?;
        let explicit = action == "focus";
        let foreground = request.args.delivery_mode.is_foreground();
        let mut front_failed = false;

        if foreground && !explicit {
            front_failed = !input::activate_target(window.pid);
        }

        let background =
            (!explicit && !foreground).then(|| input::FrontmostGuard::capture(window.pid));
        let app = AppElement::application(window.pid).map_err(ax_error)?;
        let _ = app.set_messaging_timeout(ax::MESSAGING_TIMEOUT_SECS);
        let windows = ax::window_elements(&app);
        let root = windows
            .get(window.index)
            .cloned()
            .ok_or_else(|| ErrorInfo::new(error_kind::STALE_TARGET, "the window disappeared"))?;

        let element = match request.target.as_ref() {
            Some(target) if action != "cell_at" => {
                ax::resolve_element(window.pid, window.index, &root, target)?
            }
            _ => root.clone(),
        };

        if matches!(
            action.as_str(),
            "invoke"
                | "click"
                | "double_click"
                | "right_click"
                | "hover"
                | "drag"
                | "set_value"
                | "keys"
                | "scroll"
                | "select"
                | "scroll_into_view"
                | "scroll_to"
        ) {
            ensure_actionable(&element)?;
        }

        let mut result = match action.as_str() {
            "invoke" => {
                ax::press(&element).map_err(ax_error)?;
                Ok(completed(
                    &request.action,
                    outcome::ACCESSIBILITY,
                    true,
                    None,
                    None,
                ))
            }
            "click" | "double_click" | "right_click" | "hover" | "drag" => {
                match request.args.point {
                    Some(point) => pointer_action(request, window.pid, point),
                    None if matches!(action.as_str(), "double_click" | "right_click") => {
                        ax::press(&element).map_err(ax_error)?;
                        Ok(completed(
                            &request.action,
                            outcome::ACCESSIBILITY,
                            true,
                            None,
                            None,
                        ))
                    }
                    None => Err(ErrorInfo::new(
                        UNSUPPORTED,
                        format!(
                            "macos {} needs args.point; pass a screen coordinate to post a CGEvent",
                            request.action
                        ),
                    )),
                }
            }
            "get_value" => {
                if is_sensitive(&element) {
                    return Err(ErrorInfo::new(
                        INPUT_BLOCKED,
                        "password fields never return their value",
                    ));
                }

                let value = ax::value_string(&element);
                let verified = value.is_some();
                Ok(completed(
                    &request.action,
                    outcome::ACCESSIBILITY,
                    verified,
                    value,
                    if verified {
                        None
                    } else {
                        Some("the element has no readable value".to_string())
                    },
                ))
            }
            "set_value" => {
                if is_sensitive(&element) {
                    return Err(ErrorInfo::new(
                        INPUT_BLOCKED,
                        "password fields are not writable through the bridge",
                    ));
                }

                let value = request.args.value.as_deref().ok_or_else(|| {
                    ErrorInfo::new(error_kind::INVALID_REQUEST, "set_value needs args.value")
                })?;
                let write = ax::set_value(&element, value).map_err(ax_error)?;
                Ok(completed(
                    &request.action,
                    outcome::ACCESSIBILITY,
                    write.verified,
                    write.value,
                    if write.verified {
                        None
                    } else {
                        Some("the value read back did not match; not retried".to_string())
                    },
                ))
            }
            "select" => match ax::select(&element) {
                Ok(()) => {
                    let verified = ax::attribute_bool(&element, "AXSelected").unwrap_or(false);
                    Ok(completed(
                        &request.action,
                        outcome::ACCESSIBILITY,
                        verified,
                        None,
                        (!verified).then(|| {
                            "AXSelected did not read back as true; confirm with a fresh snapshot"
                                .to_string()
                        }),
                    ))
                }
                Err(error) if error.kind() == UNSUPPORTED => Err(ErrorInfo::new(
                    UNSUPPORTED,
                    "macos select: the element exposes neither a settable AXSelected attribute nor AXPress; click it, or pass args.point",
                )),
                Err(error) => Err(ax_error(error)),
            },
            "scroll_into_view" => match ax::scroll_into_view(&element) {
                Ok(()) => Ok(completed(
                    &request.action,
                    outcome::ACCESSIBILITY,
                    false,
                    None,
                    Some(
                        "AXScrollToVisible returned; confirm visibility with a fresh snapshot"
                            .to_string(),
                    ),
                )),
                Err(error) if error.kind() == UNSUPPORTED => Err(ErrorInfo::new(
                    UNSUPPORTED,
                    "macos scroll_into_view: the element exposes no AXScrollToVisible action; pass args.point to click or scroll",
                )),
                Err(error) => Err(ax_error(error)),
            },
            "scroll_to" => {
                let (horizontal, vertical) = request
                    .args
                    .scroll_target()
                    .map_err(ErrorInfo::invalid)?;
                let write = ax::scroll_to(&element, horizontal, vertical).map_err(|error| {
                    if error.kind() == UNSUPPORTED {
                        ErrorInfo::new(
                            UNSUPPORTED,
                            "macos scroll_to: the element exposes no settable AXVerticalScrollBar or AXHorizontalScrollBar; target the scroll area or a scrollbar",
                        )
                    } else {
                        ax_error(error)
                    }
                })?;
                let verified = scroll_axis_matches(write.horizontal, horizontal)
                    && scroll_axis_matches(write.vertical, vertical);

                Ok(completed(
                    &request.action,
                    outcome::ACCESSIBILITY,
                    verified,
                    None,
                    (!verified).then(|| {
                        "the scrollbar value read back did not match; not retried".to_string()
                    }),
                ))
            }
            "focus" => {
                ax::focus(&element).map_err(ax_error)?;
                Ok(completed(
                    &request.action,
                    outcome::ACCESSIBILITY,
                    true,
                    None,
                    None,
                ))
            }
            "cell_at" => cell_at(request, &root, window.pid, window.index),
            "scroll" => {
                let direction = request.args.direction.as_deref().ok_or_else(|| {
                    ErrorInfo::new(error_kind::INVALID_REQUEST, "scroll needs args.direction")
                })?;
                let amount = request.args.amount.unwrap_or(1);

                match ax::scroll(&element, direction, amount) {
                    Ok(steps) => Ok(completed(
                        &request.action,
                        outcome::ACCESSIBILITY,
                        true,
                        None,
                        Some(format!("performed {steps} AX scroll step(s)")),
                    )),
                    Err(error) if error.kind() == UNSUPPORTED => {
                        let bounds = ax::frame(&element)
                            .or_else(|| ax::frame(&root))
                            .ok_or_else(|| {
                                ErrorInfo::new(
                                    error_kind::STALE_TARGET,
                                    "the element has no on-screen bounds for a scroll fallback",
                                )
                            })?;
                        let center_x = bounds.left + bounds.width / 2;
                        let center_y = bounds.top + bounds.height / 2;
                        let posted =
                            input::scroll_wheel(window.pid, center_x, center_y, direction, amount)?;

                        Ok(completed(
                            &request.action,
                            outcome::POINTER,
                            false,
                            None,
                            Some(format!(
                                "the element has no AX scroll action; posted {posted} scroll wheel event(s) at ({center_x}, {center_y}); not verified"
                            )),
                        ))
                    }
                    Err(error) => Err(ax_error(error)),
                }
            }
            "keys" => {
                let keys = request.args.keys.as_deref().ok_or_else(|| {
                    ErrorInfo::new(error_kind::INVALID_REQUEST, "keys needs args.keys")
                })?;

                if is_sensitive(&element) {
                    return Err(ErrorInfo::new(
                        INPUT_BLOCKED,
                        "password fields are not writable through the bridge",
                    ));
                }

                let posted = input::post_key_events(window.pid, keys)?;

                Ok(completed(
                    &request.action,
                    outcome::KEYSTROKE,
                    false,
                    None,
                    Some(format!(
                        "posted {posted} key event(s) to pid {}; not verified",
                        window.pid
                    )),
                ))
            }
            other => Err(ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                format!("unknown action {other:?}"),
            )),
        };

        if foreground && !explicit && front_failed {
            if let Ok(action_result) = result.as_mut() {
                append_note(action_result, "could not bring the target app to the front");
            }
        }
        if let Some(mut guard) = background {
            if !guard.finish() {
                if let Ok(action_result) = result.as_mut() {
                    append_note(
                        action_result,
                        "the previous frontmost app could not be restored",
                    );
                }
            }
        }

        result
    }

    fn screenshot(&self, _request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
        if !permissions::screen_recording_granted() {
            let _ = permissions::request_screen_recording();
            return Err(ErrorInfo::new(
                NO_PERMISSION,
                "Screen Recording is required for screenshots; grant it in System Settings > Privacy & Security > Screen & System Audio Recording",
            ));
        }

        Err(ErrorInfo::new(
            UNSUPPORTED,
            "window capture is not implemented in the AX backend; the capture plane will supply PNG bytes",
        ))
    }
}

fn ax_error(error: AxError) -> ErrorInfo {
    ax::to_error(error)
}

fn ensure_actionable(element: &AppElement) -> Result<(), ErrorInfo> {
    if ax::is_enabled(element) {
        Ok(())
    } else {
        Err(ErrorInfo::new(
            INPUT_BLOCKED,
            "the target control is disabled",
        ))
    }
}

fn is_sensitive(element: &AppElement) -> bool {
    ax::is_sensitive(
        ax::role(element).as_deref(),
        ax::subrole(element).as_deref(),
    )
}

fn pointer_action(
    request: &ActionRequest,
    pid: i32,
    point: Point,
) -> Result<ActionResult, ErrorInfo> {
    let action = request.action.to_ascii_lowercase();

    match action.as_str() {
        "hover" => {
            input::move_to(pid, point.x, point.y)?;

            Ok(completed(
                &request.action,
                outcome::POINTER,
                false,
                None,
                Some(format!(
                    "moved the pointer to ({}, {}) on pid {pid}; not verified",
                    point.x, point.y
                )),
            ))
        }
        "drag" => {
            let to = request.args.to_point.ok_or_else(|| {
                ErrorInfo::new(
                    UNSUPPORTED,
                    "macos drag needs args.to_point; pass a screen coordinate to post a CGEvent",
                )
            })?;
            let button = requested_button(request, PointerButton::Left)?;

            let posted = input::drag(pid, point, to, button, request.args.drag_duration())?;

            Ok(completed(
                &request.action,
                outcome::POINTER,
                false,
                None,
                Some(format!(
                    "posted {posted} drag event(s) from ({}, {}) to ({}, {}); not verified",
                    point.x, point.y, to.x, to.y
                )),
            ))
        }
        _ => {
            let default_button = if action == "right_click" {
                PointerButton::Right
            } else {
                PointerButton::Left
            };
            let default_count = if action == "double_click" { 2 } else { 1 };
            let button = requested_button(request, default_button)?;
            let count = request.args.click_count(default_count);

            let posted = input::click_at(pid, point.x, point.y, button, count)?;

            Ok(completed(
                &request.action,
                outcome::POINTER,
                false,
                None,
                Some(format!(
                    "posted {posted} {} click event(s) at ({}, {}) to pid {pid}; not verified",
                    button.as_str(),
                    point.x,
                    point.y
                )),
            ))
        }
    }
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

fn append_note(result: &mut ActionResult, note: &str) {
    match result.message.as_mut() {
        Some(message) => {
            message.push_str("; ");
            message.push_str(note);
        }
        None => result.message = Some(note.to_string()),
    }
}

fn scroll_axis_matches(current: Option<f64>, requested: Option<f64>) -> bool {
    match requested {
        None => true,
        Some(target) => current.is_some_and(|value| (value - target).abs() <= 2.0),
    }
}

fn completed(
    action: &str,
    outcome: &str,
    verified: bool,
    value: Option<String>,
    message: Option<String>,
) -> ActionResult {
    ActionResult {
        action: action.to_string(),
        delivered: true,
        verified,
        uncertain: false,
        value,
        message,
        outcome: Some(outcome.to_string()),
    }
}

/// Depth and node caps for the table search.
const MAX_TABLE_DEPTH: usize = 12;
const MAX_TABLE_NODES: usize = 2_000;

/// Resolve a spreadsheet cell by one-based row and column.
///
/// Without a target the search starts at the window root and takes the first
/// table. With a target the search starts at the resolved element, so a
/// multi-sheet workbook addresses the sheet the caller selected.
fn cell_at(
    request: &ActionRequest,
    root: &AppElement,
    app_pid: i32,
    window_index: usize,
) -> Result<ActionResult, ErrorInfo> {
    let row = request
        .args
        .row
        .ok_or_else(|| ErrorInfo::invalid("cell_at requires args.row"))?;
    let column = request
        .args
        .column
        .ok_or_else(|| ErrorInfo::invalid("cell_at requires args.column"))?;

    let target = request.target.as_ref().filter(|target| !target.is_empty());
    let subject = match target {
        Some(target) => {
            ax::resolve_element(app_pid, window_index, root, target).map_err(|error| {
                ErrorInfo::new(
                    error_kind::STALE_TARGET,
                    format!(
                        "the cell_at target {} no longer resolves ({}); take a fresh snapshot",
                        describe_target(target),
                        error.message
                    ),
                )
            })?
        }
        None => root.clone(),
    };

    let table = find_table(&subject).ok_or_else(|| match target {
        Some(target) => ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            format!(
                "the targeted element {} exposes no AX table or grid under it",
                describe_target(target)
            ),
        ),
        None => ErrorInfo::new(
            UNSUPPORTED,
            "the window exposes no AX table or grid; target the cell by name, e.g. 'B2'",
        ),
    })?;
    let (cell, actual_row, actual_column) = resolve_cell(&table, row, column)?;
    let (verified, reason) = cell_verification(row, column, actual_row, actual_column);

    Ok(ActionResult {
        action: "cell_at".to_string(),
        delivered: true,
        verified,
        uncertain: false,
        value: Some(cell_name(&cell, row, column)),
        message: Some(cell_message(row, column, &table, reason.as_deref())),
        outcome: Some(outcome::ACCESSIBILITY.to_string()),
    })
}

/// Depth-first search for the first table-like element in the window.
fn find_table(root: &AppElement) -> Option<AppElement> {
    let mut stack: Vec<(AppElement, usize)> = vec![(root.clone(), 0)];
    let mut visited = 0usize;

    while let Some((element, depth)) = stack.pop() {
        visited += 1;

        if visited > MAX_TABLE_NODES {
            break;
        }

        if is_table_role(ax::role(&element).as_deref()) || has_row_attribute(&element) {
            return Some(element);
        }

        if depth >= MAX_TABLE_DEPTH {
            continue;
        }

        let mut children = ax::children(&element);
        children.reverse();

        for child in children {
            stack.push((child, depth + 1));
        }
    }

    None
}

/// Resolve the cell element and the position attributes it reports.
fn resolve_cell(
    table: &AppElement,
    row: u32,
    column: u32,
) -> Result<(AppElement, Option<i64>, Option<i64>), ErrorInfo> {
    let rows = table_rows(table);

    if rows.is_empty() {
        return Err(ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            format!("the table exposes no rows; cannot address row {row}, column {column}"),
        ));
    }

    let row_index = checked_offset(row, rows.len()).ok_or_else(|| {
        ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            format!("row {row} is outside the {}-row table", rows.len()),
        )
    })?;
    let cells = ax::children(&rows[row_index]);

    let column_index = checked_offset(column, cells.len()).ok_or_else(|| {
        ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            format!(
                "column {column} is outside row {row}'s {}-column width",
                cells.len()
            ),
        )
    })?;
    let cell = cells[column_index].clone();
    let actual_row = ax::attribute_i64(&cell, "AXRowIndex");
    let actual_column = ax::attribute_i64(&cell, "AXColumnIndex");

    Ok((cell, actual_row, actual_column))
}

/// Collect the table's rows, preferring row arrays over direct children.
fn table_rows(table: &AppElement) -> Vec<AppElement> {
    for key in ["AXRows", "AXVisibleRows", "AXSelectedRows"] {
        let rows = ax::element_array_attribute(table, key);

        if !rows.is_empty() {
            return rows;
        }
    }

    let children = ax::children(table);

    if !children.is_empty() && children.iter().all(looks_like_row) {
        return children;
    }

    Vec::new()
}

fn looks_like_row(element: &AppElement) -> bool {
    ax::role(element)
        .as_deref()
        .is_some_and(|role| role.eq_ignore_ascii_case("AXRow"))
        || ax::copy_attribute(element, "AXRowIndex").is_some()
}

fn has_row_attribute(element: &AppElement) -> bool {
    ["AXRows", "AXVisibleRows"]
        .iter()
        .any(|key| ax::copy_attribute(element, key).is_some())
}

fn is_table_role(role: Option<&str>) -> bool {
    let role = match role {
        Some(role) => role,
        None => return false,
    };

    ["AXTable", "AXGrid", "AXOutline"]
        .iter()
        .any(|expected| role.eq_ignore_ascii_case(expected))
}

/// Convert a one-based coordinate into a zero-based index within `len`.
fn checked_offset(one_based: u32, len: usize) -> Option<usize> {
    let index = one_based.checked_sub(1)? as usize;

    (index < len).then_some(index)
}

fn cell_verification(
    row: u32,
    column: u32,
    actual_row: Option<i64>,
    actual_column: Option<i64>,
) -> (bool, Option<String>) {
    if actual_row.is_none() && actual_column.is_none() {
        return (
            false,
            Some(
                "the cell exposes neither AXRowIndex nor AXColumnIndex; addressed by position but not verified"
                    .to_string(),
            ),
        );
    }

    let expected_row = row.saturating_sub(1) as i64;
    let expected_column = column.saturating_sub(1) as i64;
    let row_matches = match actual_row {
        Some(value) => value == expected_row,
        None => true,
    };
    let column_matches = match actual_column {
        Some(value) => value == expected_column,
        None => true,
    };

    if row_matches && column_matches {
        return (true, None);
    }

    (
        false,
        Some(format!(
            "the cell reports row {}, column {}, expected row {expected_row}, column {expected_column}",
            describe_index(actual_row),
            describe_index(actual_column),
        )),
    )
}

fn describe_index(value: Option<i64>) -> String {
    value
        .map(|value| value.to_string())
        .unwrap_or_else(|| "unknown".to_string())
}

fn cell_name(cell: &AppElement, row: u32, column: u32) -> String {
    ax::title(cell)
        .or_else(|| ax::description(cell))
        .or_else(|| ax::value_string(cell))
        .unwrap_or_else(|| format!("R{row}C{column}"))
}

fn cell_message(row: u32, column: u32, table: &AppElement, reason: Option<&str>) -> String {
    let mut message = format!("row {row}, column {column}");

    if let Some(name) = table_name(table) {
        message.push_str(&format!(" in table {name:?}"));
    }

    if let Some(reason) = reason {
        message.push_str(&format!("; {reason}"));
    }

    message
}

fn table_name(table: &AppElement) -> Option<String> {
    ax::title(table).or_else(|| ax::description(table))
}

/// Short label for a target reference, used in error messages.
fn describe_target(target: &ElementRef) -> String {
    if let Some(name) = target.name.as_deref() {
        return format!("{name:?}");
    }

    if let Some(automation_id) = target.automation_id.as_deref() {
        return format!("automation id {automation_id:?}");
    }

    if let Some(role) = target.role.as_deref() {
        return format!("{role:?}");
    }

    if let Some(runtime_id) = target.runtime_id.as_deref() {
        return format!("runtime id {runtime_id:?}");
    }

    if let Some(id) = target.id {
        return format!("id {id}");
    }

    "the target".to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn table_roles_match_table_grid_and_outline() {
        assert!(is_table_role(Some("AXTable")));
        assert!(is_table_role(Some("AXGrid")));
        assert!(is_table_role(Some("AXOutline")));
        assert!(is_table_role(Some("axtable")));
        assert!(!is_table_role(Some("AXGroup")));
        assert!(!is_table_role(None));
    }

    #[test]
    fn one_based_coordinates_convert_to_zero_based() {
        assert_eq!(checked_offset(1, 4), Some(0));
        assert_eq!(checked_offset(2, 4), Some(1));
        assert_eq!(checked_offset(4, 4), Some(3));
    }

    #[test]
    fn coordinates_reject_zero_and_out_of_range() {
        assert_eq!(checked_offset(0, 4), None);
        assert_eq!(checked_offset(5, 4), None);
        assert_eq!(checked_offset(1, 0), None);
    }

    #[test]
    fn target_descriptions_prefer_name_then_fall_back_to_role() {
        let named = ElementRef {
            name: Some("Sheet2".to_string()),
            role: Some("AXTable".to_string()),
            ..Default::default()
        };
        assert_eq!(describe_target(&named), "\"Sheet2\"");

        let by_role = ElementRef {
            role: Some("AXTable".to_string()),
            ..Default::default()
        };
        assert_eq!(describe_target(&by_role), "\"AXTable\"");
    }
}
