//! Connection-scoped observation helpers.
//!
//! Snapshots and element references are valid only for the run that produced
//! them. This module holds the small amount of bookkeeping the server needs to
//! resolve an action target against the latest snapshot without turning it into
//! a cross-run session store.

use std::collections::HashMap;

use crate::protocol::{error_kind, ElementRecord, ElementRef, ErrorDetails, ErrorInfo, Snapshot};

/// A snapshot plus the window it came from, discarded when the run ends.
#[derive(Debug, Default)]
pub struct Observation {
    pub snapshot: Option<Snapshot>,
}

impl Observation {
    /// Record a fresh snapshot, replacing the previous one.
    pub fn record(&mut self, mut snapshot: Snapshot) {
        annotate_paths(&mut snapshot);
        self.snapshot = Some(snapshot);
    }

    /// Drop the recorded snapshot when the bridge shuts down.
    pub fn clear(&mut self) {
        self.snapshot = None;
    }

    /// True when no snapshot has been recorded for this bridge.
    pub fn is_empty(&self) -> bool {
        self.snapshot.is_none()
    }

    /// Find an element by connection-scoped reference.
    ///
    /// Selectors are tried in order of strength: `id`, `runtime_id`,
    /// `automation_id`, then `name` (optionally narrowed by `role`). A selector
    /// that fails to match falls through to the next one, so a stale `id` does
    /// not hide a usable name.
    pub fn find(&self, target: &ElementRef) -> Option<&ElementRecord> {
        let snapshot = self.snapshot.as_ref()?;

        if let Some(id) = target.id {
            if let Some(record) = snapshot.elements.iter().find(|element| element.id == id) {
                return Some(record);
            }
        }

        if let Some(runtime_id) = target.runtime_id.as_deref() {
            if let Some(record) = snapshot
                .elements
                .iter()
                .find(|element| element.runtime_id == runtime_id)
            {
                return Some(record);
            }
        }

        if let Some(automation_id) = target.automation_id.as_deref() {
            if let Some(record) = snapshot
                .elements
                .iter()
                .find(|element| element.automation_id.as_deref() == Some(automation_id))
            {
                return Some(record);
            }
        }

        if let Some(path) = target.path.as_deref() {
            if let Some(record) = snapshot
                .elements
                .iter()
                .find(|element| element.path.as_deref() == Some(path))
            {
                return Some(record);
            }
        }

        if let Some(name) = target.name.as_deref() {
            let role = target.role.as_deref();
            let is_match = |element: &ElementRecord| {
                element.name.as_deref() == Some(name)
                    && role
                        .map(|role| element.control_type.eq_ignore_ascii_case(role))
                        .unwrap_or(true)
            };

            // Fail closed: a name shared with a sensitive control resolves to
            // that control so the password guard applies instead of a label.
            if let Some(record) = snapshot
                .elements
                .iter()
                .find(|element| is_match(element) && element.sensitive)
            {
                return Some(record);
            }

            if let Some(record) = snapshot.elements.iter().find(|element| is_match(element)) {
                return Some(record);
            }

            return None;
        }

        // A role-only selector is the weakest form and is allowed only when
        // nothing stronger was supplied.
        let role = target.role.as_deref()?;

        snapshot
            .elements
            .iter()
            .find(|element| element.control_type.eq_ignore_ascii_case(role))
    }

    /// Resolve a reference to a concrete element for this run.
    ///
    /// The returned reference always carries an `id`, the platform runtime id,
    /// and the remaining selectors so a backend does not have to re-resolve it.
    pub fn resolve(&self, target: &ElementRef) -> Result<ElementRef, ErrorInfo> {
        let record = self.find(target).ok_or_else(|| self.not_found(target))?;

        if let Some(expected) = target
            .runtime_id
            .as_deref()
            .filter(|value| !value.is_empty())
        {
            if record.runtime_id != expected {
                return Err(identity_mismatch("runtime_id", expected, record));
            }
        }

        if let Some(expected) = target.path.as_deref().filter(|value| !value.is_empty()) {
            if record.path.as_deref() != Some(expected) {
                return Err(identity_mismatch("path", expected, record));
            }
        }

        Ok(ElementRef {
            id: Some(record.id),
            runtime_id: non_empty(target.runtime_id.clone())
                .or_else(|| non_empty(Some(record.runtime_id.clone()))),
            name: non_empty(target.name.clone()).or_else(|| non_empty(record.name.clone())),
            role: non_empty(target.role.clone())
                .or_else(|| non_empty(Some(record.control_type.clone()))),
            automation_id: non_empty(target.automation_id.clone())
                .or_else(|| non_empty(record.automation_id.clone())),
            path: non_empty(target.path.clone()).or_else(|| non_empty(record.path.clone())),
        })
    }

    fn not_found(&self, target: &ElementRef) -> ErrorInfo {
        let pinned = target.id.is_some()
            || target.runtime_id.is_some()
            || target.automation_id.is_some()
            || target.path.is_some();
        let details = self
            .snapshot
            .as_ref()
            .map(|snapshot| failure_details(snapshot, target))
            .unwrap_or_default();

        let error = if pinned {
            ErrorInfo::new(
                error_kind::STALE_TARGET,
                "target not present in the latest snapshot; take a fresh snapshot",
            )
        } else {
            ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                "no element matches the given name/role; take a fresh snapshot or widen the selector",
            )
        };

        error.with_details(details)
    }
}

fn identity_mismatch(field: &str, expected: &str, record: &ElementRecord) -> ErrorInfo {
    ErrorInfo::new(
        error_kind::STALE_TARGET,
        format!(
            "the {field} selector {expected:?} no longer matches the resolved element; take a fresh snapshot"
        ),
    )
    .with_details(ErrorDetails {
        candidates: Vec::new(),
        last_observed: Some(describe_element(record)),
        scope: Some("resolved element from the latest snapshot".to_string()),
    })
}

fn non_empty(value: Option<String>) -> Option<String> {
    value.filter(|value| !value.is_empty())
}

/// Fill `path` for every element from its parent chain.
///
/// The path is a role/name chain from the window root, so a caller can reuse it
/// across snapshots and across CLI invocations.
pub fn annotate_paths(snapshot: &mut Snapshot) {
    let mut paths: Vec<String> = Vec::with_capacity(snapshot.elements.len());

    for element in &snapshot.elements {
        let segment = match element.name.as_deref() {
            Some(name) if !name.is_empty() => format!("{}[{}]", element.control_type, name),
            _ => element.control_type.clone(),
        };

        let path = match element.parent.and_then(|parent| paths.get(parent as usize)) {
            Some(parent_path) => format!("{parent_path}/{segment}"),
            None => segment,
        };

        paths.push(path);
    }

    for (element, path) in snapshot.elements.iter_mut().zip(paths) {
        element.path = Some(path);
    }
}

/// Human-readable one-line description of an element.
pub fn describe_element(element: &ElementRecord) -> String {
    let mut description = format!("id={} {}", element.id, element.control_type);

    if let Some(name) = element
        .name
        .as_deref()
        .filter(|name| !name.trim().is_empty())
    {
        description.push_str(&format!(" \"{name}\""));
    }

    if let Some(path) = element.path.as_deref().filter(|path| !path.is_empty()) {
        description.push_str(&format!(" path={path}"));
    }

    description
}

/// Near-miss elements whose names share a prefix with the requested name.
///
/// Candidates are ordered by shared prefix length, then snapshot order, and
/// capped at `limit` so an error stays readable.
pub fn near_miss_candidates(
    elements: &[ElementRecord],
    target: &ElementRef,
    limit: usize,
) -> Vec<String> {
    let Some(query) = target
        .name
        .as_deref()
        .filter(|name| !name.trim().is_empty())
    else {
        return Vec::new();
    };
    if limit == 0 {
        return Vec::new();
    }

    let query = query.to_lowercase();
    let threshold = query.chars().count().clamp(1, 3);
    let role = target.role.as_deref();

    let mut scored: Vec<(usize, String)> = elements
        .iter()
        .filter_map(|element| {
            if let Some(role) = role {
                if !element.control_type.eq_ignore_ascii_case(role) {
                    return None;
                }
            }

            let name = element.name.as_deref()?;
            if name.trim().is_empty() {
                return None;
            }

            let score = common_prefix_len(&query, &name.to_lowercase());
            if score < threshold {
                return None;
            }

            Some((score, describe_element(element)))
        })
        .collect();

    scored.sort_by_key(|entry| std::cmp::Reverse(entry.0));
    scored
        .into_iter()
        .take(limit)
        .map(|(_, description)| description)
        .collect()
}

/// Build the diagnosis attached to a failed selector lookup.
pub fn failure_details(snapshot: &Snapshot, target: &ElementRef) -> ErrorDetails {
    ErrorDetails {
        candidates: near_miss_candidates(&snapshot.elements, target, 5),
        last_observed: snapshot.elements.last().map(describe_element),
        scope: Some(scope_note(snapshot)),
    }
}

/// Describe the snapshot a diagnosis ran against and why it was truncated.
pub fn scope_note(snapshot: &Snapshot) -> String {
    let total = snapshot.total_elements.max(snapshot.elements.len() as u32);
    let mut note = format!(
        "latest snapshot holds {} of {} elements",
        snapshot.elements.len(),
        total
    );

    if let Some(reason) = snapshot.truncated_by.as_deref() {
        note.push_str(&format!(", truncated_by={reason}"));
    } else if snapshot.truncated {
        note.push_str(", truncated");
    }

    note
}

/// Prune a snapshot in place to actionable, landmark, and informative nodes.
///
/// Returns the number of nodes removed. When pruning is the only reason the
/// payload differs, `truncated_by` becomes `actionable`; an already truncated
/// snapshot keeps its original reason.
pub fn apply_actionable(snapshot: &mut Snapshot) -> usize {
    let prune = prune_actionable(std::mem::take(&mut snapshot.elements));
    snapshot.elements = prune.elements;

    if prune.removed > 0 && !snapshot.truncated {
        snapshot.truncated = true;
        snapshot.truncated_by = Some("actionable".to_string());
    }

    prune.removed
}

/// Pure actionable-tree post-processing over a preorder element list.
///
/// Drops anonymous containers while reparenting kept descendants to the nearest
/// kept ancestor, then renumbers ids and depths contiguously.
pub fn prune_actionable(elements: Vec<ElementRecord>) -> ActionablePrune {
    let mut kept: Vec<ElementRecord> = Vec::with_capacity(elements.len());
    let mut lineage: HashMap<u32, Option<(u32, u32)>> = HashMap::new();
    let mut removed = 0usize;

    for element in elements {
        let ancestor = element
            .parent
            .and_then(|parent| lineage.get(&parent).copied())
            .flatten();
        let has_name = element
            .name
            .as_deref()
            .is_some_and(|name| !name.trim().is_empty());
        let has_value = element
            .value
            .as_deref()
            .is_some_and(|value| !value.trim().is_empty());

        if !keep_in_actionable(&element, has_name, has_value) {
            removed += 1;
            lineage.insert(element.id, ancestor);
            continue;
        }

        let new_id = kept.len() as u32;
        let depth = ancestor.map(|(_, depth)| depth + 1).unwrap_or(0);
        lineage.insert(element.id, Some((new_id, depth)));

        let mut record = element;
        record.id = new_id;
        record.parent = ancestor.map(|(id, _)| id);
        record.depth = depth;
        kept.push(record);
    }

    ActionablePrune {
        elements: kept,
        removed,
    }
}

/// Result of [`prune_actionable`].
#[derive(Debug, Default)]
pub struct ActionablePrune {
    pub elements: Vec<ElementRecord>,
    pub removed: usize,
}

fn keep_in_actionable(element: &ElementRecord, has_name: bool, has_value: bool) -> bool {
    let role = normalize_role(&element.control_type);

    if is_actionable_role(&role, &element.patterns) {
        return true;
    }

    if is_landmark_role(&role, has_name) {
        return true;
    }

    if is_anonymous_container(&role) {
        return false;
    }

    has_name || has_value
}

fn is_actionable_role(role: &str, patterns: &[String]) -> bool {
    match role {
        "button" | "push button" | "toggle button" | "check box" | "checkbox" | "radio button"
        | "radiobutton" | "combo box" | "combobox" | "entry" | "text entry" | "edit"
        | "text field" | "text box" | "tab" | "page tab" | "tree item" | "menu item" | "link"
        | "hyperlink" | "slider" | "spin button" | "spinner" | "number spinner"
        | "document text" => true,
        "section" => is_clickable(patterns),
        _ => false,
    }
}

fn is_landmark_role(role: &str, has_name: bool) -> bool {
    matches!(
        role,
        "window"
            | "frame"
            | "dialog"
            | "menu bar"
            | "toolbar"
            | "tool bar"
            | "table"
            | "tree"
            | "list"
    ) || (role == "group" && has_name)
}

fn is_anonymous_container(role: &str) -> bool {
    matches!(
        role,
        "panel" | "pane" | "filler" | "viewport" | "scroll pane" | "scrollpane" | "separator"
    )
}

fn is_clickable(patterns: &[String]) -> bool {
    patterns.iter().any(|pattern| {
        let pattern = pattern.to_ascii_lowercase();
        ["click", "invoke", "action", "press"]
            .iter()
            .any(|verb| pattern.contains(verb))
    })
}

fn normalize_role(role: &str) -> String {
    role.chars()
        .map(|character| match character {
            '_' | '-' => ' ',
            other => other,
        })
        .collect::<String>()
        .split_whitespace()
        .map(str::to_lowercase)
        .collect::<Vec<String>>()
        .join(" ")
}

fn common_prefix_len(left: &str, right: &str) -> usize {
    left.chars()
        .zip(right.chars())
        .take_while(|(left, right)| left == right)
        .count()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::ElementRecord;

    fn observation() -> Observation {
        let mut observation = Observation::default();
        observation.record(Snapshot {
            elements: vec![
                ElementRecord {
                    id: 3,
                    runtime_id: "runtime:3".to_string(),
                    control_type: "Button".to_string(),
                    name: Some("Save".to_string()),
                    automation_id: Some("save".to_string()),
                    ..Default::default()
                },
                ElementRecord {
                    id: 7,
                    runtime_id: "runtime:7".to_string(),
                    control_type: "Edit".to_string(),
                    name: Some("Save".to_string()),
                    ..Default::default()
                },
            ],
            ..Default::default()
        });
        observation
    }

    #[test]
    fn prefers_strong_selectors() {
        let observation = observation();
        let target = ElementRef {
            runtime_id: Some("runtime:7".to_string()),
            name: Some("Save".to_string()),
            ..Default::default()
        };

        let resolved = observation.resolve(&target).expect("resolved");
        assert_eq!(resolved.id, Some(7));
        assert_eq!(resolved.runtime_id.as_deref(), Some("runtime:7"));
    }

    #[test]
    fn narrows_name_matches_by_role() {
        let observation = observation();
        let target = ElementRef {
            name: Some("Save".to_string()),
            role: Some("Edit".to_string()),
            ..Default::default()
        };

        let resolved = observation.resolve(&target).expect("resolved");
        assert_eq!(resolved.id, Some(7));
    }

    #[test]
    fn annotates_paths_along_the_parent_chain() {
        let mut observation = Observation::default();
        observation.record(Snapshot {
            elements: vec![
                ElementRecord {
                    id: 0,
                    control_type: "Window".to_string(),
                    name: Some("Graph view".to_string()),
                    ..Default::default()
                },
                ElementRecord {
                    id: 1,
                    parent: Some(0),
                    depth: 1,
                    control_type: "Panel".to_string(),
                    ..Default::default()
                },
                ElementRecord {
                    id: 2,
                    parent: Some(1),
                    depth: 2,
                    control_type: "Button".to_string(),
                    name: Some("Open".to_string()),
                    ..Default::default()
                },
            ],
            ..Default::default()
        });

        let snapshot = observation.snapshot.as_ref().expect("snapshot");
        let leaf_path = snapshot.elements[2].path.clone();
        assert_eq!(
            leaf_path.as_deref(),
            Some("Window[Graph view]/Panel/Button[Open]")
        );

        let resolved = observation
            .resolve(&ElementRef {
                path: leaf_path,
                ..Default::default()
            })
            .expect("resolved by path");
        assert_eq!(resolved.id, Some(2));
    }

    #[test]
    fn unknown_target_is_not_found() {
        let observation = observation();
        assert!(observation
            .resolve(&ElementRef {
                name: Some("Missing".to_string()),
                ..Default::default()
            })
            .is_err());
    }

    #[test]
    fn mismatched_path_is_stale_instead_of_rematching_by_name() {
        let observation = observation();
        let error = observation
            .resolve(&ElementRef {
                name: Some("Save".to_string()),
                path: Some("Button[Other]".to_string()),
                ..Default::default()
            })
            .expect_err("mismatched path must be stale");

        assert_eq!(error.kind, error_kind::STALE_TARGET);
        let details = error.details.expect("diagnosis details");
        assert!(details
            .last_observed
            .as_deref()
            .is_some_and(|value| value.contains("Save")));
    }
    #[test]
    fn name_shared_with_sensitive_resolves_to_sensitive() {
        let mut observation = Observation::default();
        observation.record(Snapshot {
            elements: vec![
                ElementRecord {
                    id: 1,
                    control_type: "Text".to_string(),
                    name: Some("Password".to_string()),
                    ..Default::default()
                },
                ElementRecord {
                    id: 2,
                    control_type: "Edit".to_string(),
                    name: Some("Password".to_string()),
                    sensitive: true,
                    ..Default::default()
                },
            ],
            ..Default::default()
        });

        let resolved = observation
            .resolve(&ElementRef {
                name: Some("Password".to_string()),
                ..Default::default()
            })
            .expect("resolved");

        assert_eq!(resolved.id, Some(2));
    }
    #[test]
    fn near_miss_candidates_share_a_prefix_and_respect_the_cap() {
        let elements = vec![
            named(0, None, 0, "Button", Some("Save")),
            named(1, None, 0, "Menu Item", Some("Save As")),
            named(2, None, 0, "Button", Some("Submit")),
            named(3, None, 0, "Button", Some("Delete")),
            named(4, None, 0, "Button", Some("Settings")),
        ];
        let target = ElementRef {
            name: Some("Sav".to_string()),
            ..Default::default()
        };

        let candidates = near_miss_candidates(&elements, &target, 5);

        assert_eq!(candidates.len(), 2);
        assert!(candidates[0].contains("Save") && !candidates[0].contains("Save As"));
        assert!(candidates[1].contains("Save As"));
        assert!(candidates
            .iter()
            .all(|candidate| !candidate.contains("Submit")));

        let by_role = near_miss_candidates(
            &elements,
            &ElementRef {
                name: Some("Sav".to_string()),
                role: Some("Button".to_string()),
                ..Default::default()
            },
            5,
        );
        assert_eq!(by_role.len(), 1);
        assert!(by_role[0].contains("Save"));

        let many: Vec<ElementRecord> = (0..8)
            .map(|id| named(id, None, 0, "Button", Some("Save copy")))
            .collect();
        assert_eq!(near_miss_candidates(&many, &target, 5).len(), 5);
        assert!(near_miss_candidates(&many, &target, 0).is_empty());
    }

    #[test]
    fn actionable_prune_keeps_roles_drops_containers_and_reparents_children() {
        let elements = vec![
            named(0, None, 0, "Window", Some("Main")),
            named(1, Some(0), 1, "Panel", Some("Editor Pane")),
            named(2, Some(1), 2, "Button", Some("Save")),
            named(3, Some(1), 2, "Filler", None),
            value_record(4, Some(3), 3, "Edit", Some("Name"), Some("Ada")),
            named(5, Some(0), 1, "Text", None),
            named(6, Some(0), 1, "Group", None),
            named(7, Some(0), 1, "Group", Some("Options")),
            named(8, Some(0), 1, "Separator", Some("sep")),
            value_record(9, Some(0), 1, "Slider", None, Some("50")),
        ];

        let prune = prune_actionable(elements);
        let kept = prune.elements;

        assert_eq!(prune.removed, 5);
        assert_eq!(kept.len(), 5);
        assert_eq!(
            kept.iter()
                .map(|element| element.name.as_deref().unwrap_or(""))
                .collect::<Vec<_>>(),
            vec!["Main", "Save", "Name", "Options", ""]
        );

        for (index, element) in kept.iter().enumerate() {
            assert_eq!(element.id, index as u32);
            assert!(element
                .parent
                .map(|parent| parent < element.id)
                .unwrap_or(true));
        }

        assert_eq!(kept[0].depth, 0);
        assert_eq!(kept[1].parent, Some(0));
        assert_eq!(kept[1].depth, 1);
        assert_eq!(kept[2].parent, Some(0));
        assert_eq!(kept[2].depth, 1);
        assert_eq!(kept[2].value.as_deref(), Some("Ada"));
        assert_eq!(kept[4].parent, Some(0));
        assert_eq!(kept[4].depth, 1);
    }

    #[test]
    fn actionable_prune_marks_truncation_only_when_it_is_the_sole_reason() {
        let mut complete = Snapshot {
            elements: vec![
                named(0, None, 0, "Window", Some("Main")),
                named(1, Some(0), 1, "Panel", None),
                value_record(2, Some(1), 2, "Slider", None, Some("10")),
            ],
            total_elements: 3,
            ..Default::default()
        };

        assert_eq!(apply_actionable(&mut complete), 1);
        assert_eq!(complete.elements.len(), 2);
        assert!(complete.truncated);
        assert_eq!(complete.truncated_by.as_deref(), Some("actionable"));

        let mut partial = Snapshot {
            elements: vec![
                named(0, None, 0, "Window", Some("Main")),
                named(1, Some(0), 1, "Panel", None),
            ],
            truncated: true,
            truncated_by: Some("max_elements".to_string()),
            ..Default::default()
        };

        apply_actionable(&mut partial);
        assert_eq!(partial.truncated_by.as_deref(), Some("max_elements"));
    }

    #[test]
    fn failure_details_report_scope_and_last_observed() {
        let target = ElementRef {
            name: Some("Sav".to_string()),
            ..Default::default()
        };
        let snapshot = Snapshot {
            elements: vec![
                named(0, None, 0, "Window", Some("Main")),
                named(1, Some(0), 1, "Button", Some("Save")),
            ],
            truncated: true,
            truncated_by: Some("max_depth".to_string()),
            total_elements: 9,
            ..Default::default()
        };

        let details = failure_details(&snapshot, &target);

        assert_eq!(details.candidates.len(), 1);
        assert!(details.candidates[0].contains("Save"));
        assert_eq!(
            details.last_observed.as_deref(),
            Some("id=1 Button \"Save\"")
        );
        assert_eq!(
            details.scope.as_deref(),
            Some("latest snapshot holds 2 of 9 elements, truncated_by=max_depth")
        );
    }

    fn named(
        id: u32,
        parent: Option<u32>,
        depth: u32,
        control_type: &str,
        name: Option<&str>,
    ) -> ElementRecord {
        value_record(id, parent, depth, control_type, name, None)
    }

    fn value_record(
        id: u32,
        parent: Option<u32>,
        depth: u32,
        control_type: &str,
        name: Option<&str>,
        value: Option<&str>,
    ) -> ElementRecord {
        ElementRecord {
            id,
            parent,
            depth,
            runtime_id: format!("runtime:{id}"),
            control_type: control_type.to_string(),
            name: name.map(str::to_string),
            value: value.map(str::to_string),
            ..Default::default()
        }
    }
}
