//! Platform-free element mapping and tree helpers for the Windows UIA snapshot.
//!
//! This module deliberately depends on nothing from the crate so the pure helpers
//! can be compiled and tested on a non-Windows host:
//!
//! ```text
//! rustc --edition 2021 --test desktop/app-bridge/src/windows/element.rs -o /tmp/element-tests
//! ```
//!
//! [`uia`](super::uia) converts [`ElementSeed`] values into protocol records and
//! attaches platform handles. The budget rules mirror the fake backend so both
//! implementations produce the same `truncated`/`total_elements` semantics.

use std::collections::HashMap;

/// UIA does not expose a password control type; password edits are reported as
/// `Edit` with `IsPassword` set. The name is still recognized for robustness.
pub const PASSWORD_CONTROL_TYPE: &str = "Password";

/// Prefix for elements whose provider did not return a runtime id. These ids are
/// not stable across calls and must not be used for identity checks.
pub const UNSTABLE_RUNTIME_ID_PREFIX: &str = "uia-index:";

/// Patterns probed for each element, in record order. Ids match the UIA
/// `UIA_*PatternId` values.
pub const PATTERN_PROBES: [(&str, i32); 10] = [
    ("Value", 10002),
    ("Invoke", 10000),
    ("Toggle", 10015),
    ("SelectionItem", 10010),
    ("ExpandCollapse", 10005),
    ("RangeValue", 10003),
    ("Scroll", 10004),
    ("Text", 10014),
    ("LegacyIAccessible", 10018),
    ("ScrollItem", 10017),
];

/// Control type ids in the subset the bridge reports. Everything else maps to
/// `Custom` so clients see a stable, documented vocabulary.
pub mod control_type_id {
    pub const BUTTON: i32 = 50000;
    pub const CHECK_BOX: i32 = 50002;
    pub const COMBO_BOX: i32 = 50003;
    pub const EDIT: i32 = 50004;
    pub const HYPERLINK: i32 = 50005;
    pub const IMAGE: i32 = 50006;
    pub const LIST_ITEM: i32 = 50007;
    pub const LIST: i32 = 50008;
    pub const MENU_ITEM: i32 = 50011;
    pub const RADIO_BUTTON: i32 = 50013;
    pub const SCROLL_BAR: i32 = 50014;
    pub const SLIDER: i32 = 50015;
    pub const SPINNER: i32 = 50016;
    pub const TAB: i32 = 50018;
    pub const TAB_ITEM: i32 = 50019;
    pub const TEXT: i32 = 50020;
    pub const TOOL_BAR: i32 = 50021;
    pub const TREE: i32 = 50023;
    pub const TREE_ITEM: i32 = 50024;
    pub const CUSTOM: i32 = 50025;
    pub const DOCUMENT: i32 = 50030;
    pub const WINDOW: i32 = 50032;
    pub const PANE: i32 = 50033;
    pub const TABLE: i32 = 50036;
}

/// Screen-space rectangle used while building records.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ElementBounds {
    pub left: i32,
    pub top: i32,
    pub width: i32,
    pub height: i32,
}

/// Scroll offsets and viewport share read from the UIA Scroll pattern.
#[derive(Debug, Clone, PartialEq)]
pub struct ElementScroll {
    pub horizontal_percent: Option<f64>,
    pub vertical_percent: Option<f64>,
    pub horizontal_view_percent: Option<f64>,
    pub vertical_view_percent: Option<f64>,
    pub horizontal: bool,
    pub vertical: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ElementSeed {
    pub runtime_id: String,
    pub parent_runtime_id: Option<String>,
    pub control_type: String,
    pub name: Option<String>,
    pub automation_id: Option<String>,
    pub class_name: Option<String>,
    pub value: Option<String>,
    pub enabled: bool,
    pub offscreen: bool,
    pub bounds: Option<ElementBounds>,
    pub patterns: Vec<String>,
    pub sensitive: bool,
    pub scroll: Option<ElementScroll>,
}

impl ElementSeed {
    /// Seed with the fields every element carries; the caller fills the rest.
    pub fn new(runtime_id: impl Into<String>, control_type: impl Into<String>) -> Self {
        Self {
            runtime_id: runtime_id.into(),
            parent_runtime_id: None,
            control_type: control_type.into(),
            name: None,
            automation_id: None,
            class_name: None,
            value: None,
            enabled: true,
            offscreen: false,
            bounds: None,
            patterns: Vec::new(),
            sensitive: false,
            scroll: None,
        }
    }

    /// True when the element holds secret text.
    pub fn is_sensitive(&self) -> bool {
        self.sensitive || self.control_type == PASSWORD_CONTROL_TYPE
    }
}

/// Final element node with visit-order ids and parent indexes.
#[derive(Debug, Clone, PartialEq)]
pub struct ElementNode {
    pub id: u32,
    pub parent: Option<u32>,
    pub depth: u32,
    pub runtime_id: String,
    pub control_type: String,
    pub name: Option<String>,
    pub automation_id: Option<String>,
    pub class_name: Option<String>,
    pub value: Option<String>,
    pub enabled: bool,
    pub offscreen: bool,
    pub bounds: Option<ElementBounds>,
    pub patterns: Vec<String>,
    pub sensitive: bool,
    pub scroll: Option<ElementScroll>,
}

/// Result of [`build_snapshot`].
#[derive(Debug, Clone, PartialEq)]
pub struct SnapshotBuild {
    pub nodes: Vec<ElementNode>,
    pub truncated: bool,
    pub total_elements: u32,
}

/// Map a UIA control type id to the documented name.
pub fn control_type_name(control_type: i32) -> &'static str {
    use control_type_id as ct;

    match control_type {
        ct::BUTTON => "Button",
        ct::CHECK_BOX => "CheckBox",
        ct::COMBO_BOX => "ComboBox",
        ct::EDIT => "Edit",
        ct::HYPERLINK => "Hyperlink",
        ct::IMAGE => "Image",
        ct::LIST_ITEM => "ListItem",
        ct::LIST => "List",
        ct::MENU_ITEM => "MenuItem",
        ct::RADIO_BUTTON => "RadioButton",
        ct::SCROLL_BAR => "ScrollBar",
        ct::SLIDER => "Slider",
        ct::SPINNER => "Spinner",
        ct::TAB => "Tab",
        ct::TAB_ITEM => "TabItem",
        ct::TEXT => "Text",
        ct::TOOL_BAR => "ToolBar",
        ct::TREE => "Tree",
        ct::TREE_ITEM => "TreeItem",
        ct::DOCUMENT => "Document",
        ct::WINDOW => "Window",
        ct::PANE => "Pane",
        ct::TABLE => "Table",
        _ => "Custom",
    }
}

/// Join a UIA runtime id array with `.` so the value stays a stable string for
/// the lifetime of the window.
pub fn format_runtime_id(ids: &[i32]) -> String {
    ids.iter().map(i32::to_string).collect::<Vec<_>>().join(".")
}

/// Synthetic id used when a provider returns no runtime id.
pub fn unstable_runtime_id(index: u32) -> String {
    format!("{UNSTABLE_RUNTIME_ID_PREFIX}{index}")
}

/// True when an id cannot be used to re-fetch and identity-check an element.
pub fn is_unstable_runtime_id(runtime_id: &str) -> bool {
    runtime_id.starts_with(UNSTABLE_RUNTIME_ID_PREFIX)
}

/// Never expose a value for a sensitive element.
pub fn enforce_password_guard(node: &mut ElementNode) {
    if node.sensitive {
        node.value = None;
    }
}

/// Build the pre-order element list and apply the depth and element budgets.
///
/// `root` is the window element (id 0). `descendants` are in UIA document order,
/// which is already pre-order. A descendant whose parent is unknown becomes a
/// child of the root at depth 1, which is the documented flat fallback when the
/// provider does not answer parent queries.
pub fn build_snapshot(
    root: ElementSeed,
    descendants: Vec<ElementSeed>,
    max_depth: u32,
    max_elements: u32,
) -> SnapshotBuild {
    let mut nodes = Vec::with_capacity(descendants.len() + 1);
    let mut index: HashMap<String, u32> = HashMap::new();

    let root_id = root.runtime_id.clone();
    nodes.push(node_from(root, 0, None, 0));
    if !root_id.is_empty() {
        index.insert(root_id, 0);
    }

    for seed in descendants {
        if seed.runtime_id.is_empty() || index.contains_key(&seed.runtime_id) {
            continue;
        }

        let parent = seed
            .parent_runtime_id
            .as_ref()
            .and_then(|parent| index.get(parent).copied());
        let (parent_index, depth) = match parent {
            Some(parent_index) => (parent_index, nodes[parent_index as usize].depth + 1),
            None => (0, 1),
        };

        let id = nodes.len() as u32;
        let runtime_id = seed.runtime_id.clone();
        nodes.push(node_from(seed, id, Some(parent_index), depth));
        index.insert(runtime_id, id);
    }

    let total_elements = nodes.len() as u32;
    let mut truncated = false;

    if max_elements == 0 {
        return SnapshotBuild {
            nodes: Vec::new(),
            truncated: total_elements > 0,
            total_elements,
        };
    }

    nodes.retain(|node| {
        if node.depth > max_depth {
            truncated = true;
            false
        } else {
            true
        }
    });

    if nodes.len() > max_elements as usize {
        nodes.truncate(max_elements as usize);
        truncated = true;
    }

    remap_ids(&mut nodes);

    SnapshotBuild {
        nodes,
        truncated,
        total_elements,
    }
}

fn node_from(seed: ElementSeed, id: u32, parent: Option<u32>, depth: u32) -> ElementNode {
    let sensitive = seed.is_sensitive();
    let mut node = ElementNode {
        id,
        parent,
        depth,
        runtime_id: seed.runtime_id,
        control_type: seed.control_type,
        name: seed.name,
        automation_id: seed.automation_id,
        class_name: seed.class_name,
        value: seed.value,
        enabled: seed.enabled,
        offscreen: seed.offscreen,
        bounds: seed.bounds,
        patterns: seed.patterns,
        scroll: seed.scroll,
        sensitive,
    };
    enforce_password_guard(&mut node);
    node
}

fn remap_ids(nodes: &mut [ElementNode]) {
    let mut remap: HashMap<u32, u32> = HashMap::with_capacity(nodes.len());
    for (new_id, node) in nodes.iter().enumerate() {
        remap.insert(node.id, new_id as u32);
    }

    for (new_id, node) in nodes.iter_mut().enumerate() {
        node.parent = node.parent.and_then(|parent| remap.get(&parent).copied());
        node.id = new_id as u32;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seed(runtime_id: &str, parent: Option<&str>, control_type: &str) -> ElementSeed {
        let mut seed = ElementSeed::new(runtime_id, control_type);
        seed.parent_runtime_id = parent.map(str::to_string);
        seed
    }

    #[test]
    fn control_type_names_cover_the_documented_set() {
        assert_eq!(control_type_name(50032), "Window");
        assert_eq!(control_type_name(50033), "Pane");
        assert_eq!(control_type_name(50004), "Edit");
        assert_eq!(control_type_name(50000), "Button");
        assert_eq!(control_type_name(50002), "CheckBox");
        assert_eq!(control_type_name(50003), "ComboBox");
        assert_eq!(control_type_name(50013), "RadioButton");
        assert_eq!(control_type_name(50020), "Text");
        assert_eq!(control_type_name(50008), "List");
        assert_eq!(control_type_name(50007), "ListItem");
        assert_eq!(control_type_name(50011), "MenuItem");
        assert_eq!(control_type_name(50018), "Tab");
        assert_eq!(control_type_name(50019), "TabItem");
        assert_eq!(control_type_name(50021), "ToolBar");
        assert_eq!(control_type_name(50030), "Document");
        assert_eq!(control_type_name(50005), "Hyperlink");
        assert_eq!(control_type_name(50006), "Image");
        assert_eq!(control_type_name(50014), "ScrollBar");
        assert_eq!(control_type_name(50015), "Slider");
        assert_eq!(control_type_name(50016), "Spinner");
        assert_eq!(control_type_name(50036), "Table");
        assert_eq!(control_type_name(50023), "Tree");
        assert_eq!(control_type_name(50024), "TreeItem");
        assert_eq!(control_type_name(50025), "Custom");
        assert_eq!(control_type_name(99999), "Custom");
    }

    #[test]
    fn runtime_ids_join_with_dots() {
        assert_eq!(format_runtime_id(&[42, 100, 3]), "42.100.3");
        assert_eq!(format_runtime_id(&[-1]), "-1");
        assert_eq!(format_runtime_id(&[]), "");
    }

    #[test]
    fn unstable_ids_are_flagged() {
        let id = unstable_runtime_id(7);
        assert_eq!(id, "uia-index:7");
        assert!(is_unstable_runtime_id(&id));
        assert!(!is_unstable_runtime_id("42.100.3"));
    }

    #[test]
    fn pre_order_numbering_and_parents() {
        let root = seed("1", None, "Window");
        let descendants = vec![
            seed("2", Some("1"), "Pane"),
            seed("3", Some("2"), "Edit"),
            seed("4", Some("1"), "Button"),
        ];

        let built = build_snapshot(root, descendants, 10, 100);
        assert_eq!(built.total_elements, 4);
        assert!(!built.truncated);
        let ids: Vec<u32> = built.nodes.iter().map(|node| node.id).collect();
        assert_eq!(ids, vec![0, 1, 2, 3]);
        let parents: Vec<Option<u32>> = built.nodes.iter().map(|node| node.parent).collect();
        assert_eq!(parents, vec![None, Some(0), Some(1), Some(0)]);
        let depths: Vec<u32> = built.nodes.iter().map(|node| node.depth).collect();
        assert_eq!(depths, vec![0, 1, 2, 1]);
    }

    #[test]
    fn missing_parents_produce_a_flat_fallback() {
        let root = seed("1", None, "Window");
        let descendants = vec![seed("2", Some("missing"), "Pane"), seed("3", None, "Edit")];

        let built = build_snapshot(root, descendants, 10, 100);
        assert_eq!(built.nodes[1].parent, Some(0));
        assert_eq!(built.nodes[1].depth, 1);
        assert_eq!(built.nodes[2].parent, Some(0));
        assert_eq!(built.nodes[2].depth, 1);
    }

    #[test]
    fn duplicate_runtime_ids_are_dropped() {
        let root = seed("1", None, "Window");
        let descendants = vec![
            seed("1", None, "Window"),
            seed("2", Some("1"), "Pane"),
            seed("2", Some("1"), "Pane"),
        ];

        let built = build_snapshot(root, descendants, 10, 100);
        assert_eq!(built.nodes.len(), 2);
        assert_eq!(built.total_elements, 2);
    }

    #[test]
    fn depth_budget_truncates_and_reports_total() {
        let root = seed("1", None, "Window");
        let descendants = vec![seed("2", Some("1"), "Pane"), seed("3", Some("2"), "Edit")];

        let built = build_snapshot(root, descendants, 1, 100);
        assert!(built.truncated);
        assert_eq!(built.total_elements, 3);
        assert_eq!(built.nodes.len(), 2);
        assert_eq!(built.nodes[1].depth, 1);
    }

    #[test]
    fn element_budget_truncates_and_remaps_parents() {
        let root = seed("1", None, "Window");
        let descendants = vec![
            seed("2", Some("1"), "Pane"),
            seed("3", Some("1"), "Button"),
            seed("4", Some("3"), "Text"),
        ];

        let built = build_snapshot(root, descendants, 10, 3);
        assert!(built.truncated);
        assert_eq!(built.total_elements, 4);
        assert_eq!(built.nodes.len(), 3);
        let ids: Vec<u32> = built.nodes.iter().map(|node| node.id).collect();
        assert_eq!(ids, vec![0, 1, 2]);
        let parents: Vec<Option<u32>> = built.nodes.iter().map(|node| node.parent).collect();
        assert_eq!(parents, vec![None, Some(0), Some(0)]);
    }

    #[test]
    fn zero_element_budget_returns_empty() {
        let root = seed("1", None, "Window");
        let built = build_snapshot(root, vec![seed("2", Some("1"), "Pane")], 10, 0);
        assert!(built.nodes.is_empty());
        assert!(built.truncated);
        assert_eq!(built.total_elements, 2);
    }

    #[test]
    fn sensitive_values_are_never_kept() {
        let mut root = seed("1", None, "Window");
        root.value = Some("not-secret".to_string());
        let mut password = seed("2", Some("1"), "Edit");
        password.sensitive = true;
        password.value = Some("correct horse battery staple".to_string());

        let built = build_snapshot(root, vec![password], 10, 100);
        assert_eq!(built.nodes[0].value.as_deref(), Some("not-secret"));
        assert!(built.nodes[1].sensitive);
        assert_eq!(built.nodes[1].value, None);
    }

    #[test]
    fn password_control_type_forces_sensitivity() {
        let root = seed("1", None, "Window");
        let mut password = seed("2", Some("1"), PASSWORD_CONTROL_TYPE);
        password.value = Some("secret".to_string());

        let built = build_snapshot(root, vec![password], 10, 100);
        assert!(built.nodes[1].sensitive);
        assert_eq!(built.nodes[1].value, None);
    }

    #[test]
    fn pattern_probe_names_are_unique() {
        let mut names: Vec<&str> = PATTERN_PROBES.iter().map(|(name, _)| *name).collect();
        names.sort_unstable();
        names.dedup();
        assert_eq!(names.len(), PATTERN_PROBES.len());
    }
}
