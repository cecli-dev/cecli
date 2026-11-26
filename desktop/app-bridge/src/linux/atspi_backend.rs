//! AT-SPI backend: window enumeration, accessibility snapshots, and semantic
//! actions over D-Bus.
//!
//! Every public method is synchronous and drives a private tokio runtime with a
//! timeout-wrapped future. The bridge server calls backends from its own worker
//! threads, so blocking here is expected; calling from inside an async context
//! is rejected instead of panicking in `Runtime::block_on`.
//!
//! Pixel capture and raw input injection are deliberately absent: screenshots
//! belong to the capture plane and `keys`/`scroll` to the XTEST driver (T14).

use std::collections::{HashMap, HashSet};
use std::future::Future;
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::time::{Duration, Instant};

use atspi::proxy::accessible::AccessibleProxy;
use atspi::proxy::action::ActionProxy;
use atspi::proxy::application::ApplicationProxy;
use atspi::proxy::collection::CollectionProxy;
use atspi::proxy::component::ComponentProxy;
use atspi::proxy::editable_text::EditableTextProxy;
use atspi::proxy::table::TableProxy;
use atspi::proxy::table_cell::TableCellProxy;
use atspi::proxy::text::TextProxy;
use atspi::proxy::value::ValueProxy;
use atspi::{
    AccessibilityConnection, CoordType, Interface, InterfaceSet, MatchType, ObjectMatchRule,
    ObjectRefOwned, ScrollType, SortOrder,
};
use atspi::{State, StateSet};

use crate::protocol::{
    error_kind, outcome, ActionArgs, ActionRequest, ActionResult, Bounds, CheckResult,
    DoctorReport, ElementRecord, ElementRef, ErrorInfo, FindRequest, FindResult, Health, MatchSpec,
    ScreenshotRequest, ScrollState, Snapshot, SnapshotRequest, StringMatch, WindowInfo,
};
use crate::Backend;

/// Default budget for AT-SPI calls; `CECLI_ATSPI_TIMEOUT_MS` overrides it.
const DEFAULT_CALL_TIMEOUT: Duration = Duration::from_secs(10);
/// Short budget used by health and registry probes.
const PROBE_TIMEOUT: Duration = Duration::from_secs(3);
/// How long a cached health answer stays fresh.
const HEALTH_TTL: Duration = Duration::from_secs(5);
/// Upper bound on waiting for a setter's read-back.
const READ_BACK_WINDOW: Duration = Duration::from_millis(600);
/// Poll interval used while waiting for a setter's read-back.
const READ_BACK_POLL: Duration = Duration::from_millis(100);
/// Default snapshot depth budget.
const DEFAULT_MAX_DEPTH: u32 = 10;
/// Default snapshot element budget.
const DEFAULT_MAX_ELEMENTS: u32 = 1000;
/// Maximum children expanded for any single node.
const MAX_CHILDREN_PER_NODE: usize = 200;
/// Hard cap on cells read by the `cell_at` enumeration fallback.
const MAX_CELLS: usize = 5000;
/// Upper bound on work spent on one application during window enumeration.
const PEER_TIMEOUT: Duration = Duration::from_secs(2);

/// AT-SPI implementation of the bridge [`Backend`] contract.
#[derive(Debug)]
pub struct AtspiBackend {
    state: Mutex<ConnectionState>,
    last_snapshot: Mutex<Option<SnapshotCache>>,
}

impl AtspiBackend {
    /// Create a backend with no connection yet; the bus is opened lazily.
    pub fn new() -> Self {
        Self {
            state: Mutex::new(ConnectionState::default()),
            last_snapshot: Mutex::new(None),
        }
    }
}

impl Default for AtspiBackend {
    fn default() -> Self {
        Self::new()
    }
}

impl Backend for AtspiBackend {
    fn name(&self) -> &'static str {
        "linux-atspi"
    }

    fn platform(&self) -> &'static str {
        "linux"
    }

    fn capabilities(&self) -> Vec<String> {
        [
            "windows",
            "snapshot",
            "action",
            "find",
            "dialogs",
            "scroll_to",
        ]
        .iter()
        .map(|value| (*value).to_string())
        .collect()
    }

    fn health(&self) -> Health {
        self.probe_health()
    }

    fn doctor(&self) -> DoctorReport {
        self.report()
    }

    fn windows(&self) -> Result<Vec<WindowInfo>, ErrorInfo> {
        let connection = self.connection()?;
        let state = &self.state;
        let candidates = match run_with_timeout("windows", call_timeout(), async move {
            window_candidates(&connection, state).await
        }) {
            Ok((candidates, _skipped)) => candidates,
            Err(error) => {
                if error.kind == error_kind::TIMEOUT {
                    reset_connection(state);
                }

                return Err(error);
            }
        };

        Ok(candidates
            .into_iter()
            .map(|candidate| candidate.info)
            .collect())
    }

    fn snapshot(&self, request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo> {
        let connection = self.connection()?;
        let query = request.window.clone();
        let max_depth = request.max_depth.unwrap_or(DEFAULT_MAX_DEPTH);
        let max_elements = request.max_elements.unwrap_or(DEFAULT_MAX_ELEMENTS);
        let exclude_roles = normalize_roles(&request.exclude_roles);
        let actionable = request.actionable;

        let budget = snapshot_budget();
        let deadline = Instant::now() + budget;
        let state = &self.state;

        let cache = match run_with_timeout("snapshot", budget, async move {
            let window = window_node(&connection, state, &query).await?;

            build_snapshot(
                &connection,
                window,
                max_depth,
                max_elements,
                &exclude_roles,
                deadline,
            )
            .await
        }) {
            Ok(cache) => cache,
            Err(error) => {
                if error.kind == error_kind::TIMEOUT {
                    reset_connection(state);
                }

                return Err(error);
            }
        };

        let mut snapshot = cache.snapshot.clone();
        *lock(&self.last_snapshot) = Some(cache);

        if actionable {
            crate::observe::apply_actionable(&mut snapshot);
        }

        Ok(snapshot)
    }

    fn find(&self, request: &FindRequest) -> Result<FindResult, ErrorInfo> {
        let connection = self.connection()?;
        let query = request.window.clone();
        let max_depth = request.max_depth.unwrap_or(DEFAULT_MAX_DEPTH);
        let max_elements = request.max_elements.unwrap_or(DEFAULT_MAX_ELEMENTS);
        let exclude_roles = normalize_roles(&request.exclude_roles);
        let limit = request.limit.filter(|value| *value > 0);
        let spec = request.r#match.clone();
        let budget = snapshot_budget();
        let deadline = Instant::now() + budget;
        let state = &self.state;

        let result = match run_with_timeout("find", budget, async move {
            let window = window_node(&connection, state, &query).await?;

            Ok(find_in_window(
                &connection,
                window.node,
                max_depth,
                max_elements,
                &exclude_roles,
                deadline,
                limit,
                &spec,
            )
            .await)
        }) {
            Ok(result) => result,
            Err(error) => {
                if error.kind == error_kind::TIMEOUT {
                    reset_connection(state);
                }

                return Err(error);
            }
        };

        Ok(result)
    }

    fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
        match request.action.as_str() {
            "invoke" | "click" | "focus" | "set_value" | "get_value" | "select"
            | "scroll_into_view" | "scroll_to" => {
                let (record, node) = self.resolve_action_target(request.target.as_ref())?;
                let connection = self.connection()?;
                let action = request.action.clone();
                let args = request.args.clone();

                run_with_timeout("action", call_timeout(), async move {
                    dispatch_action(&connection, &node, &record, &action, &args).await
                })
            }
            "cell_at" => {
                let row = request
                    .args
                    .row
                    .ok_or_else(|| ErrorInfo::invalid("cell_at requires args.row"))?;
                let column = request
                    .args
                    .column
                    .ok_or_else(|| ErrorInfo::invalid("cell_at requires args.column"))?;
                let query = request.window.clone();
                let root = self.resolve_cell_root(request.target.as_ref())?;
                let connection = self.connection()?;
                let state = &self.state;

                run_with_timeout("action", call_timeout(), async move {
                    cell_at(&connection, state, &query, root, row, column).await
                })
            }
            "keys" | "scroll" => Err(ErrorInfo::new(
                error_kind::UNSUPPORTED,
                "linux keys and scroll input require the XTEST driver (T14); the AT-SPI backend only performs semantic actions",
            )),
            other => Err(ErrorInfo::invalid(format!(
                "unknown action '{other}' for the linux-atspi backend; expected invoke, click, focus, set_value, get_value, select, scroll_into_view, scroll_to, cell_at, keys, or scroll"
            ))),
        }
    }

    fn screenshot(&self, _request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
        Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "linux pixel capture is handled by the capture plane; the AT-SPI backend does not capture screenshots",
        ))
    }
}

impl AtspiBackend {
    fn connection(&self) -> Result<AccessibilityConnection, ErrorInfo> {
        {
            let state = lock(&self.state);
            if let Some(connection) = state.connection.clone() {
                return Ok(connection);
            }
        }

        let connection = run_with_timeout("connect", call_timeout(), async {
            AccessibilityConnection::new()
                .await
                .map_err(|error| bus_unavailable(&error))
        })?;

        lock(&self.state).connection = Some(connection.clone());

        Ok(connection)
    }

    fn probe_health(&self) -> Health {
        let cached = {
            let state = lock(&self.state);
            match state.health {
                Some((at, health)) if at.elapsed() < HEALTH_TTL => return health,
                _ => state.connection.clone(),
            }
        };

        let (health, connection) = match cached {
            Some(connection) => {
                let probe = {
                    let connection = connection.clone();
                    run_with_timeout("registry", PROBE_TIMEOUT, async move {
                        registry_application_count(&connection).await
                    })
                };

                match probe {
                    Ok(0) => (Health::Degraded, Some(connection)),
                    Ok(_) => (Health::Ready, Some(connection)),
                    Err(_) => (Health::Unavailable, None),
                }
            }
            None => match run_with_timeout("connect", PROBE_TIMEOUT, async {
                AccessibilityConnection::new()
                    .await
                    .map_err(|error| bus_unavailable(&error))
            }) {
                Ok(connection) => {
                    let count = {
                        let connection = connection.clone();
                        run_with_timeout("registry", PROBE_TIMEOUT, async move {
                            registry_application_count(&connection).await
                        })
                    };

                    match count {
                        Ok(0) => (Health::Degraded, Some(connection)),
                        Ok(_) => (Health::Ready, Some(connection)),
                        Err(_) => (Health::Unavailable, None),
                    }
                }
                Err(_) => (Health::Unavailable, None),
            },
        };

        let mut state = lock(&self.state);
        state.health = Some((Instant::now(), health));
        state.connection = connection;

        health
    }

    fn report(&self) -> DoctorReport {
        let mut checks = vec![CheckResult::new("backend", true, "linux-atspi")];

        let (bus_ok, bus_detail) = match self.connection() {
            Ok(_) => (true, "accessibility bus reachable".to_string()),
            Err(error) => (false, error.message),
        };
        checks.push(CheckResult::new("session_bus", bus_ok, bus_detail));

        let (registry_ok, registry_detail, applications) = self.registry_report();
        checks.push(CheckResult::new(
            "atspi_registry",
            registry_ok,
            registry_detail,
        ));

        let accessibility = accessibility_setting();
        let enabled_ok = accessibility != "false";
        checks.push(CheckResult::new(
            "accessibility_enabled",
            enabled_ok,
            format!("org.gnome.desktop.interface toolkit-accessibility={accessibility}"),
        ));

        let health = if !bus_ok || !registry_ok {
            Health::Unavailable
        } else if applications == 0 {
            Health::Degraded
        } else {
            Health::Ready
        };

        let mut notes = Vec::new();
        if applications == 0 {
            notes.push(
                "the AT-SPI registry reports no accessible applications; enable toolkit accessibility for the target"
                    .to_string(),
            );
        }
        if accessibility == "false" {
            notes.push(
                "toolkit accessibility is disabled; run 'gsettings set org.gnome.desktop.interface toolkit-accessibility true'"
                    .to_string(),
            );
        }

        DoctorReport {
            platform: self.platform().to_string(),
            backend: self.name().to_string(),
            health,
            permissions: [(
                "accessibility".to_string(),
                match accessibility.as_str() {
                    "true" => "enabled",
                    "false" => "disabled",
                    _ => "unknown",
                }
                .to_string(),
            )]
            .into_iter()
            .collect(),
            checks,
            notes,
        }
    }

    fn registry_report(&self) -> (bool, String, u32) {
        let Ok(connection) = self.connection() else {
            return (false, "accessibility bus unavailable".to_string(), 0);
        };

        let probe = run_with_timeout("registry", PROBE_TIMEOUT, async move {
            registry_application_count(&connection).await
        });

        match probe {
            Ok(count) => (
                true,
                format!("AT-SPI registry reports {count} application(s)"),
                count,
            ),
            Err(error) => (false, error.message, 0),
        }
    }

    fn resolve_action_target(
        &self,
        target: Option<&ElementRef>,
    ) -> Result<(ElementRecord, NodeRef), ErrorInfo> {
        if target.filter(|reference| !reference.is_empty()).is_none() {
            return Err(ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                "action requires a target element from the latest snapshot",
            ));
        }
        let cache = lock(&self.last_snapshot);
        let cache = cache.as_ref().ok_or_else(|| {
            ErrorInfo::new(
                error_kind::STALE_TARGET,
                "no snapshot is available; take a snapshot before acting",
            )
        })?;
        let (record, node) = resolve_node(cache, target)?;

        Ok((record.clone(), node.clone()))
    }

    /// Resolve the optional grid target that scopes `cell_at`.
    ///
    /// `Ok(None)` keeps the window-rooted default. A present target must resolve
    /// against the latest snapshot; it is never silently replaced by the window.
    fn resolve_cell_root(
        &self,
        target: Option<&ElementRef>,
    ) -> Result<Option<(ElementRecord, NodeRef)>, ErrorInfo> {
        if target.filter(|reference| !reference.is_empty()).is_none() {
            return Ok(None);
        }

        let cache = lock(&self.last_snapshot);
        let cache = cache.as_ref().ok_or_else(|| {
            ErrorInfo::new(
                error_kind::STALE_TARGET,
                "cell_at was given a grid target but no snapshot is cached; take a snapshot before acting",
            )
        })?;

        resolve_node(cache, target)
            .map(|(record, node)| Some((record.clone(), node.clone())))
            .map_err(|_| {
                ErrorInfo::new(
                    error_kind::STALE_TARGET,
                    "the grid target no longer resolves in the latest snapshot; take a fresh snapshot",
                )
            })
    }
}

/// Reference to one accessible object on the accessibility bus.
#[derive(Debug, Clone, PartialEq, Eq)]
struct NodeRef {
    destination: String,
    path: String,
}

impl NodeRef {
    fn key(&self) -> String {
        format!("{}|{}", self.destination, self.path)
    }
}

/// A window candidate plus the bus object it came from.
#[derive(Debug)]
struct WindowCandidate {
    info: WindowInfo,
    node: NodeRef,
}

/// Snapshot plus the parallel bus references needed to act on its elements.
#[derive(Debug)]
struct SnapshotCache {
    snapshot: Snapshot,
    nodes: Vec<NodeRef>,
}

/// Cached bus connection and health answer.
#[derive(Debug, Default)]
struct ConnectionState {
    connection: Option<AccessibilityConnection>,
    health: Option<(Instant, Health)>,
}

/// Accessible application discovered on the registry.
#[derive(Debug)]
struct AppEntry {
    name: String,
    toolkit: Option<String>,
    node: NodeRef,
}

/// Facts gathered for one accessible node during a snapshot walk.
#[derive(Debug)]
struct NodeFacts {
    control_type: String,
    name: Option<String>,
    class_name: Option<String>,
    value: Option<String>,
    enabled: bool,
    offscreen: bool,
    bounds: Option<Bounds>,
    patterns: Vec<String>,
    sensitive: bool,
    scroll: Option<ScrollState>,
}

async fn window_candidates(
    connection: &AccessibilityConnection,
    state: &Mutex<ConnectionState>,
) -> Result<(Vec<WindowCandidate>, u32), ErrorInfo> {
    let applications = applications(connection).await?;
    let mut candidates = Vec::new();
    let mut skipped = 0u32;

    for application in applications {
        match tokio::time::timeout(
            peer_timeout(),
            application_candidates(connection, application),
        )
        .await
        {
            Ok(Ok(windows)) => candidates.extend(windows),
            Ok(Err(error)) => {
                skipped = skipped.saturating_add(1);

                if error.kind == error_kind::TIMEOUT {
                    reset_connection(state);
                }
            }
            Err(_) => {
                skipped = skipped.saturating_add(1);
                reset_connection(state);
            }
        }
    }

    Ok((candidates, skipped))
}

async fn window_node(
    connection: &AccessibilityConnection,
    state: &Mutex<ConnectionState>,
    query: &str,
) -> Result<WindowCandidate, ErrorInfo> {
    let (mut candidates, _skipped) = window_candidates(connection, state).await?;
    let windows: Vec<WindowInfo> = candidates
        .iter()
        .map(|candidate| candidate.info.clone())
        .collect();
    let index = select_window_index(&windows, query).ok_or_else(|| {
        ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            format!("no accessible window matches '{query}'"),
        )
    })?;

    Ok(candidates.swap_remove(index))
}

async fn application_candidates(
    connection: &AccessibilityConnection,
    application: AppEntry,
) -> Result<Vec<WindowCandidate>, ErrorInfo> {
    let pid = process_id(connection, &application.node.destination)
        .await
        .unwrap_or(0);
    let children = children_of(connection, &application.node).await?;
    let mut candidates = Vec::new();

    for child in children {
        let Ok(info) = read_window_info(
            connection,
            &child,
            &application.name,
            application.toolkit.as_deref(),
            pid,
        )
        .await
        else {
            continue;
        };

        candidates.push(WindowCandidate { info, node: child });
    }

    Ok(candidates)
}

async fn applications(connection: &AccessibilityConnection) -> Result<Vec<AppEntry>, ErrorInfo> {
    let root = connection
        .root_accessible_on_registry()
        .await
        .map_err(|error| bus_unavailable(&error))?;
    let references = root
        .get_children()
        .await
        .map_err(|error| dbus_error("registry get_children", error))?;

    let mut applications = Vec::new();

    for reference in references {
        let Some(node) = node_from_reference(&reference) else {
            continue;
        };
        let Ok(accessible) = accessible_for(connection, &node).await else {
            continue;
        };
        let name = accessible.name().await.unwrap_or_default();
        let toolkit = application_toolkit(connection, &node).await;

        applications.push(AppEntry {
            name,
            toolkit,
            node,
        });
    }

    Ok(applications)
}

async fn registry_application_count(
    connection: &AccessibilityConnection,
) -> Result<u32, ErrorInfo> {
    let root = connection
        .root_accessible_on_registry()
        .await
        .map_err(|error| bus_unavailable(&error))?;
    let references = root
        .get_children()
        .await
        .map_err(|error| dbus_error("registry get_children", error))?;

    Ok(references
        .iter()
        .filter(|reference| node_from_reference(reference).is_some())
        .count() as u32)
}

async fn application_toolkit(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Option<String> {
    let accessible = accessible_for(connection, node).await.ok()?;
    let interfaces = accessible.get_interfaces().await.ok()?;

    if !interfaces.contains(Interface::Application) {
        return None;
    }

    let application = application_for(connection, node).await.ok()?;

    application
        .toolkit_name()
        .await
        .ok()
        .filter(|name| !name.is_empty())
}

async fn process_id(connection: &AccessibilityConnection, destination: &str) -> Option<u32> {
    let reply = connection
        .connection()
        .call_method(
            Some("org.freedesktop.DBus"),
            "/org/freedesktop/DBus",
            Some("org.freedesktop.DBus"),
            "GetConnectionUnixProcessID",
            &(destination,),
        )
        .await
        .ok()?;

    reply.body().deserialize::<u32>().ok()
}

async fn read_window_info(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    application_name: &str,
    toolkit: Option<&str>,
    pid: u32,
) -> Result<WindowInfo, ErrorInfo> {
    let accessible = accessible_for(connection, node).await?;
    let role_name = role_name_of(&accessible).await;
    let states = accessible.get_state().await.ok();
    let interfaces = accessible
        .get_interfaces()
        .await
        .unwrap_or_else(|_| InterfaceSet::empty());
    let title = accessible.name().await.unwrap_or_default();
    let bounds = bounds_of(connection, node, &interfaces).await;
    let foreground = states
        .map(|states| states.contains(State::Active) || states.contains(State::Focused))
        .unwrap_or(false);
    let enabled = states
        .map(|states| {
            states.contains(State::Enabled)
                || states.contains(State::Sensitive)
                || states.contains(State::Active)
        })
        .unwrap_or(true);
    let offscreen = states
        .map(|states| !states.contains(State::Showing) && !states.contains(State::Visible))
        .unwrap_or(false);

    Ok(WindowInfo {
        handle: node.path.clone(),
        pid,
        process_name: non_empty(application_name),
        title,
        class_name: toolkit
            .map(str::to_string)
            .or_else(|| non_empty(&role_name)),
        bounds: bounds.unwrap_or_default(),
        foreground,
        enabled,
        offscreen,
        dialog: crate::dialog::atspi_role_is_dialog(&role_name),
    })
}

async fn build_snapshot(
    connection: &AccessibilityConnection,
    window: WindowCandidate,
    max_depth: u32,
    max_elements: u32,
    exclude_roles: &[String],
    deadline: Instant,
) -> Result<SnapshotCache, ErrorInfo> {
    let mut elements: Vec<ElementRecord> = Vec::new();
    let mut nodes: Vec<NodeRef> = Vec::new();

    let stats = walk_tree(
        connection,
        window.node.clone(),
        max_depth,
        max_elements,
        exclude_roles,
        deadline,
        |id, parent, depth, node, facts| {
            elements.push(element_record(id, parent, depth, node, facts));
            nodes.push(node.clone());
            WalkStep::Continue
        },
    )
    .await;

    let truncated_by = truncation_cause(
        stats.timed_out,
        stats.budget_exhausted,
        stats.children_cut,
        stats.depth_limited,
    )
    .map(str::to_string);
    let truncated = truncated_by.is_some()
        || snapshot_truncated(stats.kept, max_elements, stats.depth_limited, stats.pending);

    Ok(SnapshotCache {
        snapshot: Snapshot {
            window: window.info,
            elements,
            truncated,
            truncated_by,
            children_cut: stats.children_cut,
            max_depth,
            max_elements,
            total_elements: stats.kept,
        },
        nodes,
    })
}

#[allow(clippy::too_many_arguments)]
async fn find_in_window(
    connection: &AccessibilityConnection,
    root: NodeRef,
    max_depth: u32,
    max_elements: u32,
    exclude_roles: &[String],
    deadline: Instant,
    limit: Option<u32>,
    spec: &MatchSpec,
) -> FindResult {
    let mut collector = FindCollector::new(limit);

    let stats = walk_tree(
        connection,
        root,
        max_depth,
        max_elements,
        exclude_roles,
        deadline,
        |_id, parent, depth, node, facts| {
            if !facts_match(spec, &facts) {
                return WalkStep::Continue;
            }

            let record = element_record(0, parent, depth, node, facts);

            if collector.record(record) {
                WalkStep::Stop
            } else {
                WalkStep::Continue
            }
        },
    )
    .await;

    let truncated_by = if stats.stopped {
        Some("limit".to_string())
    } else {
        truncation_cause(
            stats.timed_out,
            stats.budget_exhausted,
            stats.children_cut,
            stats.depth_limited,
        )
        .map(str::to_string)
    };

    collector.into_result(truncated_by)
}

/// Walk the accessibility tree once, applying budgets and the child cap, and
/// hand each kept node to `visit` before descending into its children.
async fn walk_tree<F>(
    connection: &AccessibilityConnection,
    root: NodeRef,
    max_depth: u32,
    max_elements: u32,
    exclude_roles: &[String],
    deadline: Instant,
    mut visit: F,
) -> WalkStats
where
    F: FnMut(u32, Option<u32>, u32, &NodeRef, NodeFacts) -> WalkStep,
{
    let mut stats = WalkStats::default();
    let mut visited: HashSet<String> = HashSet::new();
    let mut stack = WalkStack::new(root);

    while let Some((node, parent, depth)) = stack.pop() {
        if deadline_reached(deadline) {
            stats.timed_out = true;
            break;
        }

        if stats.kept >= max_elements {
            stats.budget_exhausted = true;
            stack.put_back((node, parent, depth));
            break;
        }

        if !visited.insert(node.key()) {
            continue;
        }

        let facts = match node_facts(connection, &node).await {
            Ok(facts) => facts,
            Err(_) => {
                if deadline_reached(deadline) {
                    stats.timed_out = true;
                    break;
                }

                continue;
            }
        };
        if role_excluded(facts.class_name.as_deref(), exclude_roles) {
            continue;
        }

        let id = stats.kept;
        stats.kept = stats.kept.saturating_add(1);

        if visit(id, parent, depth, &node, facts) == WalkStep::Stop {
            stats.stopped = true;
            break;
        }

        if deadline_reached(deadline) {
            stats.timed_out = true;
            break;
        }

        if depth >= max_depth {
            stats.depth_limited |= has_children(connection, &node).await;
            continue;
        }

        if stats.kept >= max_elements {
            stats.budget_exhausted = !stack.is_empty() || has_children(connection, &node).await;
            break;
        }

        match children_of(connection, &node).await {
            Ok(children) => {
                let (children, dropped) = cap_children(children, MAX_CHILDREN_PER_NODE);
                stats.children_cut = stats.children_cut.saturating_add(dropped);
                stack.push_children(id, depth + 1, children);
            }
            Err(_) => {
                if deadline_reached(deadline) {
                    stats.timed_out = true;
                    break;
                }

                continue;
            }
        }
    }

    stats.pending = !stack.is_empty();
    stats
}

fn element_record(
    id: u32,
    parent: Option<u32>,
    depth: u32,
    node: &NodeRef,
    facts: NodeFacts,
) -> ElementRecord {
    ElementRecord {
        id,
        parent,
        depth,
        runtime_id: node.path.clone(),
        control_type: facts.control_type,
        name: facts.name,
        automation_id: None,
        class_name: facts.class_name,
        value: if facts.sensitive { None } else { facts.value },
        enabled: facts.enabled,
        offscreen: facts.offscreen,
        bounds: facts.bounds,
        patterns: facts.patterns,
        sensitive: facts.sensitive,
        scroll: facts.scroll,
        path: None,
    }
}

async fn node_facts(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Result<NodeFacts, ErrorInfo> {
    let accessible = accessible_for(connection, node).await?;
    let role_name = role_name_of(&accessible).await;
    let states = accessible.get_state().await.ok();
    let interfaces = accessible
        .get_interfaces()
        .await
        .unwrap_or_else(|_| InterfaceSet::empty());
    let name = accessible.name().await.ok().filter(|name| !name.is_empty());
    let sensitive = is_password_role(&role_name);
    let bounds = bounds_of(connection, node, &interfaces).await;

    let mut patterns: Vec<String> = interfaces
        .iter()
        .map(|interface| format!("{interface:?}"))
        .filter(|name| !name.is_empty())
        .collect();

    let mut value = None;
    if !sensitive && should_read_text_value(&role_name, &interfaces) {
        value = read_text_value(connection, node).await.ok().flatten();
    }
    if !sensitive && value.is_none() && interfaces.contains(Interface::Value) {
        value = read_numeric_value(connection, node).await;
    }
    if interfaces.contains(Interface::Action) {
        if let Ok(actions) = action_names(connection, node).await {
            patterns.extend(actions);
        }
    }

    let scroll = scroll_state(connection, node, &role_name, states.as_ref()).await;
    let enabled = states
        .map(|states| states.contains(State::Enabled))
        .unwrap_or(true);
    let offscreen = states
        .map(|states| !states.contains(State::Showing) && !states.contains(State::Visible))
        .unwrap_or(false);

    Ok(NodeFacts {
        control_type: role_to_control_type(&role_name),
        class_name: non_empty(&role_name),
        name,
        value,
        enabled,
        offscreen,
        bounds,
        patterns,
        sensitive,
        scroll,
    })
}

async fn role_name_of(accessible: &AccessibleProxy<'_>) -> String {
    if let Ok(role) = accessible.get_role().await {
        return role.name().to_string();
    }

    accessible.get_role_name().await.unwrap_or_default()
}

async fn children_of(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Result<Vec<NodeRef>, ErrorInfo> {
    let accessible = accessible_for(connection, node).await?;
    let references = accessible
        .get_children()
        .await
        .map_err(|error| dbus_error("get_children", error))?;

    Ok(references.iter().filter_map(node_from_reference).collect())
}

async fn has_children(connection: &AccessibilityConnection, node: &NodeRef) -> bool {
    let Ok(accessible) = accessible_for(connection, node).await else {
        return false;
    };

    accessible
        .child_count()
        .await
        .map(|count| count > 0)
        .unwrap_or(false)
}

async fn bounds_of(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    interfaces: &InterfaceSet,
) -> Option<Bounds> {
    if !interfaces.contains(Interface::Component) {
        return None;
    }

    let component = component_for(connection, node).await.ok()?;
    let extents = match component.get_extents(CoordType::Screen).await {
        Ok(extents) => extents,
        Err(_) => component.get_extents(CoordType::Window).await.ok()?,
    };
    let (left, top, width, height) = extents;

    if width <= 0 || height <= 0 {
        return None;
    }

    Some(Bounds {
        left,
        top,
        width,
        height,
    })
}

async fn read_text_value(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Result<Option<String>, ErrorInfo> {
    let text = text_for(connection, node).await?;
    let count = text
        .character_count()
        .await
        .map_err(|error| dbus_error("Text.CharacterCount", error))?;
    let count = count.max(0);
    let value = text
        .get_text(0, count)
        .await
        .map_err(|error| dbus_error("Text.GetText", error))?;

    Ok(Some(value))
}

async fn read_numeric_value(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Option<String> {
    let value = value_for(connection, node).await.ok()?;

    if let Ok(text) = value.text().await {
        if !text.is_empty() {
            return Some(text);
        }
    }
    if let Ok(current) = value.current_value().await {
        return Some(format_number(current));
    }

    None
}

async fn scroll_state(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    role_name: &str,
    states: Option<&StateSet>,
) -> Option<ScrollState> {
    let role = role_name.to_ascii_lowercase();

    if is_scrollbar_role(&role) {
        let percent = read_scrollbar_percent(connection, node).await?;
        let (horizontal, vertical) = scrollbar_axes(states);

        return Some(ScrollState {
            horizontal_percent: horizontal.then_some(percent),
            vertical_percent: vertical.then_some(percent),
            horizontal,
            vertical,
            ..Default::default()
        });
    }

    if !is_scroll_container_role(&role) {
        return None;
    }

    let children = children_of(connection, node).await.ok()?;
    let mut horizontal = None;
    let mut vertical = None;

    for child in children {
        let Ok(accessible) = accessible_for(connection, &child).await else {
            continue;
        };
        let child_role = role_name_of(&accessible).await.to_ascii_lowercase();

        if !is_scrollbar_role(&child_role) {
            continue;
        }

        let Some(percent) = read_scrollbar_percent(connection, &child).await else {
            continue;
        };
        let child_states = accessible.get_state().await.ok();
        let (child_horizontal, child_vertical) = scrollbar_axes(child_states.as_ref());

        if child_horizontal && horizontal.is_none() {
            horizontal = Some(percent);
        }

        if child_vertical && vertical.is_none() {
            vertical = Some(percent);
        }
    }

    if horizontal.is_none() && vertical.is_none() {
        return None;
    }

    Some(ScrollState {
        horizontal_percent: horizontal,
        vertical_percent: vertical,
        horizontal: horizontal.is_some(),
        vertical: vertical.is_some(),
        ..Default::default()
    })
}

async fn scroll_to_element(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    action: &str,
    args: &ActionArgs,
) -> Result<ActionResult, ErrorInfo> {
    let (horizontal, vertical) = args.scroll_target().map_err(ErrorInfo::invalid)?;
    let accessible = accessible_for(connection, node)
        .await
        .map_err(|error| stale_target(&error.message))?;
    let role = role_name_of(&accessible).await.to_ascii_lowercase();
    let states = accessible.get_state().await.ok();
    let scrollbars = scrollbar_targets(connection, node, &role, states).await?;

    if scrollbars.is_empty() {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "linux scroll_to: the element exposes no AT-SPI scrollbar; target a scroll pane or scroll bar",
        ));
    }

    let mut reached_horizontal = false;
    let mut reached_vertical = false;
    let mut horizontal_readback = None;
    let mut vertical_readback = None;

    for (bar, bar_states) in scrollbars {
        let (bar_horizontal, bar_vertical) = scrollbar_axes(bar_states.as_ref());

        if let (Some(percent), true) = (horizontal, bar_horizontal) {
            horizontal_readback = set_scrollbar_percent(connection, &bar, percent).await?;
            reached_horizontal = horizontal_readback.is_some();
        }

        if let (Some(percent), true) = (vertical, bar_vertical) {
            vertical_readback = set_scrollbar_percent(connection, &bar, percent).await?;
            reached_vertical = vertical_readback.is_some();
        }
    }

    if horizontal.is_some() && !reached_horizontal {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "linux scroll_to: the target exposes no horizontal scrollbar",
        ));
    }

    if vertical.is_some() && !reached_vertical {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "linux scroll_to: the target exposes no vertical scrollbar",
        ));
    }

    let verified = scroll_axis_matches(horizontal_readback, horizontal)
        && scroll_axis_matches(vertical_readback, vertical);

    Ok(ActionResult {
        action: action.to_string(),
        delivered: true,
        verified,
        uncertain: false,
        value: None,
        message: (!verified)
            .then(|| "the scrollbar value read back did not match; not retried".to_string()),
        outcome: Some(outcome::ACCESSIBILITY.to_string()),
    })
}

async fn scrollbar_targets(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    role: &str,
    states: Option<StateSet>,
) -> Result<Vec<(NodeRef, Option<StateSet>)>, ErrorInfo> {
    if is_scrollbar_role(role) {
        return Ok(vec![(node.clone(), states)]);
    }

    if !is_scroll_container_role(role) {
        return Ok(Vec::new());
    }

    let mut bars = Vec::new();

    for child in children_of(connection, node).await? {
        let Ok(accessible) = accessible_for(connection, &child).await else {
            continue;
        };
        let child_role = role_name_of(&accessible).await.to_ascii_lowercase();

        if is_scrollbar_role(&child_role) {
            let child_states = accessible.get_state().await.ok();
            bars.push((child, child_states));
        }
    }

    Ok(bars)
}

async fn read_scrollbar_percent(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Option<f64> {
    let value = value_for(connection, node).await.ok()?;
    let current = value.current_value().await.ok()?;
    let minimum = value.minimum_value().await.ok()?;
    let maximum = value.maximum_value().await.ok()?;

    scroll_percent_of(current, minimum, maximum)
}

async fn set_scrollbar_percent(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    percent: f64,
) -> Result<Option<f64>, ErrorInfo> {
    let value = value_for(connection, node)
        .await
        .map_err(|error| stale_target(&error.message))?;
    let minimum = value
        .minimum_value()
        .await
        .map_err(|error| dbus_error("Value.MinimumValue", error))?;
    let maximum = value
        .maximum_value()
        .await
        .map_err(|error| dbus_error("Value.MaximumValue", error))?;

    if maximum <= minimum {
        return Ok(None);
    }

    let target = minimum + (maximum - minimum) * percent / 100.0;
    value
        .set_current_value(target)
        .await
        .map_err(|error| dbus_error("Value.SetCurrentValue", error))?;
    let current = value.current_value().await.ok();

    Ok(current.and_then(|current| scroll_percent_of(current, minimum, maximum)))
}

fn scroll_percent_of(current: f64, minimum: f64, maximum: f64) -> Option<f64> {
    (maximum > minimum)
        .then(|| ((current - minimum) / (maximum - minimum) * 100.0).clamp(0.0, 100.0))
}

fn scrollbar_axes(states: Option<&StateSet>) -> (bool, bool) {
    let horizontal = states.is_some_and(|states| states.contains(State::Horizontal));
    let vertical = states.is_some_and(|states| states.contains(State::Vertical));

    if horizontal || vertical {
        (horizontal, vertical)
    } else {
        (false, true)
    }
}

fn is_scrollbar_role(role: &str) -> bool {
    role == "scroll bar" || role == "scrollbar"
}

fn is_scroll_container_role(role: &str) -> bool {
    matches!(
        role,
        "scroll pane" | "scrollpane" | "viewport" | "document frame" | "document web"
    )
}

fn scroll_axis_matches(current: Option<f64>, requested: Option<f64>) -> bool {
    match requested {
        None => true,
        Some(target) => current.is_some_and(|value| (value - target).abs() <= 2.0),
    }
}

async fn read_value(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Result<Option<String>, ErrorInfo> {
    let interfaces = interfaces_of(connection, node).await?;

    if interfaces.contains(Interface::EditableText) || interfaces.contains(Interface::Text) {
        if let Ok(Some(value)) = read_text_value(connection, node).await {
            return Ok(Some(value));
        }
    }
    if interfaces.contains(Interface::Value) {
        return Ok(read_numeric_value(connection, node).await);
    }

    Ok(None)
}

async fn interfaces_of(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Result<InterfaceSet, ErrorInfo> {
    let accessible = accessible_for(connection, node).await?;

    accessible
        .get_interfaces()
        .await
        .map_err(|error| dbus_error("get_interfaces", error))
}

async fn action_names(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Result<Vec<String>, ErrorInfo> {
    let action = action_for(connection, node).await?;
    let actions = action
        .get_actions()
        .await
        .map_err(|error| dbus_error("Action.GetActions", error))?;

    Ok(actions
        .into_iter()
        .map(|action| action.name)
        .filter(|name| !name.is_empty())
        .collect())
}

async fn dispatch_action(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    record: &ElementRecord,
    action: &str,
    args: &ActionArgs,
) -> Result<ActionResult, ErrorInfo> {
    if record.sensitive && matches!(action, "set_value" | "get_value") {
        return Err(ErrorInfo::new(
            error_kind::INPUT_BLOCKED,
            format!(
                "element '{}' is sensitive; its value is never read or written",
                record.name.as_deref().unwrap_or("<unnamed>")
            ),
        ));
    }

    let states = refresh_states(connection, node).await?;

    if action != "get_value" {
        if let Some(states) = states {
            if !states.contains(State::Enabled) {
                return Err(ErrorInfo::new(
                    error_kind::INPUT_BLOCKED,
                    format!(
                        "element '{}' is disabled",
                        record.name.as_deref().unwrap_or("<unnamed>")
                    ),
                ));
            }
        }
    }

    match action {
        "get_value" => {
            let value = read_value(connection, node).await?;
            let Some(value) = value else {
                return Err(ErrorInfo::new(
                    error_kind::UNSUPPORTED,
                    format!(
                        "element '{}' does not expose EditableText, Text, or Value",
                        record.name.as_deref().unwrap_or("<unnamed>")
                    ),
                ));
            };

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
        "set_value" => {
            let value = args
                .value
                .clone()
                .ok_or_else(|| ErrorInfo::invalid("set_value requires args.value"))?;

            write_value(connection, node, &value).await
        }
        "invoke" => invoke(connection, node, action, false).await,
        "select" => select_element(connection, node, action).await,
        "scroll_into_view" => scroll_into_view_element(connection, node, action).await,
        "scroll_to" => scroll_to_element(connection, node, action, args).await,
        "click" => invoke(connection, node, action, true).await,
        "focus" => focus(connection, node, action, states).await,
        other => Err(ErrorInfo::invalid(format!("unknown action '{other}'"))),
    }
}

async fn refresh_states(
    connection: &AccessibilityConnection,
    node: &NodeRef,
) -> Result<Option<StateSet>, ErrorInfo> {
    let accessible = accessible_for(connection, node)
        .await
        .map_err(|error| stale_target(&error.message))?;

    match accessible.get_state().await {
        Ok(states) => Ok(Some(states)),
        Err(error) => Err(stale_target(&format!(
            "target state is no longer readable: {error}"
        ))),
    }
}

async fn write_value(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    value: &str,
) -> Result<ActionResult, ErrorInfo> {
    let interfaces = interfaces_of(connection, node).await?;

    if interfaces.contains(Interface::EditableText) {
        let editable = editable_for(connection, node).await?;
        let written = editable
            .set_text_contents(value)
            .await
            .map_err(|error| dbus_error("EditableText.SetTextContents", error))?;

        if !written {
            return Err(ErrorInfo::backend(
                "EditableText.SetTextContents was refused by the target",
            ));
        }

        let verified = verify_text(connection, node, value).await;

        return Ok(ActionResult {
            action: "set_value".to_string(),
            delivered: true,
            verified,
            uncertain: false,
            value: Some(value.to_string()),
            message: (!verified).then(|| {
                "the target accepted the write but the read-back did not match within 600 ms"
                    .to_string()
            }),
            outcome: Some(outcome::ACCESSIBILITY.to_string()),
        });
    }

    if interfaces.contains(Interface::Value) {
        let numeric = value.trim().parse::<f64>().map_err(|_| {
            ErrorInfo::invalid(format!(
                "set_value expects a numeric value for this control, got '{value}'"
            ))
        })?;
        let value_proxy = value_for(connection, node).await?;
        value_proxy
            .set_current_value(numeric)
            .await
            .map_err(|error| dbus_error("Value.SetCurrentValue", error))?;

        let verified = verify_number(connection, node, numeric, value).await;

        return Ok(ActionResult {
            action: "set_value".to_string(),
            delivered: true,
            verified,
            uncertain: false,
            value: Some(value.to_string()),
            message: (!verified).then(|| {
                "the target accepted the write but the read-back did not match within 600 ms"
                    .to_string()
            }),
            outcome: Some(outcome::ACCESSIBILITY.to_string()),
        });
    }

    Err(ErrorInfo::new(
        error_kind::UNSUPPORTED,
        "target does not support EditableText or Value",
    ))
}

async fn verify_text(connection: &AccessibilityConnection, node: &NodeRef, expected: &str) -> bool {
    let deadline = Instant::now() + READ_BACK_WINDOW;

    loop {
        tokio::time::sleep(READ_BACK_POLL).await;

        if let Ok(Some(value)) = read_text_value(connection, node).await {
            if value == expected {
                return true;
            }
        }
        if Instant::now() >= deadline {
            return false;
        }
    }
}

async fn verify_number(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    expected: f64,
    rendered: &str,
) -> bool {
    let deadline = Instant::now() + READ_BACK_WINDOW;

    loop {
        tokio::time::sleep(READ_BACK_POLL).await;

        if let Ok(value) = value_for(connection, node).await {
            if let Ok(text) = value.text().await {
                if text == rendered {
                    return true;
                }
            }
            if let Ok(current) = value.current_value().await {
                if (current - expected).abs() <= 1e-6 {
                    return true;
                }
            }
        }
        if Instant::now() >= deadline {
            return false;
        }
    }
}

async fn invoke(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    action: &str,
    click: bool,
) -> Result<ActionResult, ErrorInfo> {
    let interfaces = interfaces_of(connection, node).await?;

    if !interfaces.contains(Interface::Action) {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "target does not implement the AT-SPI Action interface",
        ));
    }

    let proxy = action_for(connection, node).await?;
    let actions = proxy
        .get_actions()
        .await
        .map_err(|error| dbus_error("Action.GetActions", error))?;
    let preferred: &[&str] = if click {
        &["click", "press"]
    } else {
        &["click", "press", "invoke", "activate"]
    };
    let named = actions.iter().position(|candidate| {
        preferred
            .iter()
            .any(|name| candidate.name.eq_ignore_ascii_case(name))
    });
    // Electron and GTK widgets often expose unnamed actions; index 0 is the
    // default action a pointer click would trigger.
    let index = named.or(if actions.is_empty() { None } else { Some(0) });
    let Some(index) = index else {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "target exposes no AT-SPI actions",
        ));
    };

    let performed = proxy
        .do_action(index as i32)
        .await
        .map_err(|error| dbus_error("Action.DoAction", error))?;

    if !performed {
        return Err(ErrorInfo::new(
            error_kind::INPUT_BLOCKED,
            format!(
                "AT-SPI action '{}' was refused by the target",
                actions[index].name
            ),
        ));
    }

    Ok(ActionResult {
        action: action.to_string(),
        delivered: true,
        verified: false,
        uncertain: false,
        value: None,
        message: Some(format!(
            "invoked AT-SPI action '{}' (index {index})",
            actions[index].name
        )),
        outcome: Some(outcome::ACCESSIBILITY.to_string()),
    })
}

async fn select_element(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    action: &str,
) -> Result<ActionResult, ErrorInfo> {
    let states = refresh_states(connection, node).await?;

    if states.is_some_and(|states| states.contains(State::Selected)) {
        return Ok(ActionResult::delivered_with(action, outcome::ACCESSIBILITY));
    }

    let interfaces = interfaces_of(connection, node).await?;

    if !interfaces.contains(Interface::Action) {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "linux select: the target exposes no AT-SPI Action interface; click it, or pass args.point to click by coordinate",
        ));
    }

    let proxy = action_for(connection, node).await?;
    let actions = proxy
        .get_actions()
        .await
        .map_err(|error| dbus_error("Action.GetActions", error))?;
    let index = actions.iter().position(|candidate| {
        candidate.name.eq_ignore_ascii_case("select")
            || candidate.name.eq_ignore_ascii_case("select item")
    });
    let Some(index) = index else {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "linux select: the target exposes no AT-SPI 'select' action; click it, or pass args.point to click by coordinate",
        ));
    };

    let performed = proxy
        .do_action(index as i32)
        .await
        .map_err(|error| dbus_error("Action.DoAction", error))?;

    if !performed {
        return Err(ErrorInfo::new(
            error_kind::INPUT_BLOCKED,
            format!(
                "AT-SPI action '{}' was refused by the target",
                actions[index].name
            ),
        ));
    }

    Ok(ActionResult {
        action: action.to_string(),
        delivered: true,
        verified: false,
        uncertain: false,
        value: None,
        message: Some(format!(
            "invoked AT-SPI action '{}'; confirm selection with a fresh snapshot",
            actions[index].name
        )),
        outcome: Some(outcome::ACCESSIBILITY.to_string()),
    })
}

async fn scroll_into_view_element(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    action: &str,
) -> Result<ActionResult, ErrorInfo> {
    let interfaces = interfaces_of(connection, node).await?;

    if !interfaces.contains(Interface::Component) {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "linux scroll_into_view: the target exposes no AT-SPI Component interface; pass its center as args.point to click or scroll",
        ));
    }

    let component = component_for(connection, node).await?;
    let scrolled = component
        .scroll_to(ScrollType::Anywhere)
        .await
        .map_err(|error| dbus_error("Component.ScrollTo", error))?;

    if scrolled {
        return Ok(ActionResult {
            action: action.to_string(),
            delivered: true,
            verified: false,
            uncertain: false,
            value: None,
            message: Some(
                "Component.ScrollTo reported success; confirm visibility with a fresh snapshot"
                    .to_string(),
            ),
            outcome: Some(outcome::ACCESSIBILITY.to_string()),
        });
    }

    let focused = component.grab_focus().await.unwrap_or(false);

    if focused {
        return Ok(ActionResult {
            action: action.to_string(),
            delivered: true,
            verified: false,
            uncertain: false,
            value: None,
            message: Some(
                "ScrollTo was refused; focused the element so its container may reveal it"
                    .to_string(),
            ),
            outcome: Some(outcome::ACCESSIBILITY.to_string()),
        });
    }

    Err(ErrorInfo::new(
        error_kind::UNSUPPORTED,
        "linux scroll_into_view: the target refused both ScrollTo and focus; pass its center as args.point to click or scroll",
    ))
}

async fn focus(
    connection: &AccessibilityConnection,
    node: &NodeRef,
    action: &str,
    states: Option<StateSet>,
) -> Result<ActionResult, ErrorInfo> {
    let interfaces = interfaces_of(connection, node).await?;
    let already_focused = states
        .map(|states| states.contains(State::Focused))
        .unwrap_or(false);

    if !interfaces.contains(Interface::Component) {
        if already_focused {
            return Ok(ActionResult::delivered_with(action, outcome::ACCESSIBILITY));
        }

        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            "target does not implement the AT-SPI Component interface",
        ));
    }

    let component = component_for(connection, node).await?;
    let focused = component
        .grab_focus()
        .await
        .map_err(|error| dbus_error("Component.GrabFocus", error))?;

    if !focused {
        return Err(ErrorInfo::new(
            error_kind::INPUT_BLOCKED,
            "the target refused focus",
        ));
    }

    Ok(ActionResult::delivered_with(action, outcome::ACCESSIBILITY))
}

async fn accessible_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<AccessibleProxy<'a>, ErrorInfo> {
    AccessibleProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("Accessible destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("Accessible path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("Accessible proxy", error))
}

async fn application_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<ApplicationProxy<'a>, ErrorInfo> {
    ApplicationProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("Application destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("Application path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("Application proxy", error))
}

async fn action_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<ActionProxy<'a>, ErrorInfo> {
    ActionProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("Action destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("Action path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("Action proxy", error))
}

async fn component_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<ComponentProxy<'a>, ErrorInfo> {
    ComponentProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("Component destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("Component path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("Component proxy", error))
}

async fn text_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<TextProxy<'a>, ErrorInfo> {
    TextProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("Text destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("Text path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("Text proxy", error))
}

async fn editable_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<EditableTextProxy<'a>, ErrorInfo> {
    EditableTextProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("EditableText destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("EditableText path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("EditableText proxy", error))
}

async fn value_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<ValueProxy<'a>, ErrorInfo> {
    ValueProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("Value destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("Value path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("Value proxy", error))
}

async fn collection_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<CollectionProxy<'a>, ErrorInfo> {
    CollectionProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("Collection destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("Collection path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("Collection proxy", error))
}

async fn table_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<TableProxy<'a>, ErrorInfo> {
    TableProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("Table destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("Table path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("Table proxy", error))
}

async fn table_cell_for<'a>(
    connection: &'a AccessibilityConnection,
    node: &NodeRef,
) -> Result<TableCellProxy<'a>, ErrorInfo> {
    TableCellProxy::builder(connection.connection())
        .destination(node.destination.clone())
        .map_err(|error| dbus_error("TableCell destination", error))?
        .path(node.path.clone())
        .map_err(|error| dbus_error("TableCell path", error))?
        .build()
        .await
        .map_err(|error| dbus_error("TableCell proxy", error))
}

fn node_from_reference(reference: &ObjectRefOwned) -> Option<NodeRef> {
    if reference.is_null() {
        return None;
    }

    let destination = reference.name_as_str()?.to_string();
    let path = reference.path_as_str().to_string();

    if destination.is_empty() || path.is_empty() || path == "/org/a11y/atspi/null" {
        return None;
    }

    Some(NodeRef { destination, path })
}

fn call_timeout() -> Duration {
    static TIMEOUT: OnceLock<Duration> = OnceLock::new();

    *TIMEOUT.get_or_init(|| {
        std::env::var("CECLI_ATSPI_TIMEOUT_MS")
            .ok()
            .and_then(|value| value.trim().parse::<u64>().ok())
            .filter(|value| *value > 0)
            .map(Duration::from_millis)
            .unwrap_or(DEFAULT_CALL_TIMEOUT)
    })
}

fn runtime() -> &'static tokio::runtime::Runtime {
    static RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();

    RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .thread_name("ce-app-bridge-atspi")
            .enable_all()
            .build()
            .expect("AT-SPI runtime")
    })
}

fn run_with_timeout<F, T>(label: &'static str, timeout: Duration, future: F) -> Result<T, ErrorInfo>
where
    F: Future<Output = Result<T, ErrorInfo>>,
{
    if tokio::runtime::Handle::try_current().is_ok() {
        return Err(ErrorInfo::backend(
            "the AT-SPI backend cannot block inside an async runtime; call it from a worker thread",
        ));
    }

    runtime().block_on(async move {
        match tokio::time::timeout(timeout, future).await {
            Ok(result) => result,
            Err(_) => Err(ErrorInfo::new(
                error_kind::TIMEOUT,
                format!("AT-SPI {label} exceeded {} ms", timeout.as_millis()),
            )),
        }
    })
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn bus_unavailable(error: impl std::fmt::Display) -> ErrorInfo {
    ErrorInfo::new(
        error_kind::UNSUPPORTED,
        format!(
            "the AT-SPI accessibility bus is not available: {error}; start a desktop session with toolkit accessibility enabled"
        ),
    )
}

fn dbus_error(context: &str, error: impl std::fmt::Display) -> ErrorInfo {
    ErrorInfo::backend(format!("{context}: {error}"))
}

fn stale_target(detail: &str) -> ErrorInfo {
    ErrorInfo::new(
        error_kind::STALE_TARGET,
        format!("{detail}; take a fresh snapshot"),
    )
}

/// Lowercase and trim role names once per request.
fn normalize_roles(roles: &[String]) -> Vec<String> {
    roles
        .iter()
        .map(|role| role.trim().to_ascii_lowercase())
        .filter(|role| !role.is_empty())
        .collect()
}

/// Apply every present [`MatchSpec`] predicate to one node's facts.
fn facts_match(spec: &MatchSpec, facts: &NodeFacts) -> bool {
    if !roles_match(&spec.roles, facts) {
        return false;
    }

    if let Some(matcher) = &spec.name {
        if !string_match(matcher, facts.name.as_deref()) {
            return false;
        }
    }

    if let Some(matcher) = &spec.value {
        if !string_match(matcher, facts.value.as_deref()) {
            return false;
        }
    }

    if let Some(enabled) = spec.enabled {
        if facts.enabled != enabled {
            return false;
        }
    }

    if let Some(sensitive) = spec.sensitive {
        if facts.sensitive != sensitive {
            return false;
        }
    }

    true
}

/// Match a role against either the title-case control type or the raw role.
fn roles_match(roles: &[String], facts: &NodeFacts) -> bool {
    if roles.is_empty() {
        return true;
    }

    roles.iter().any(|role| {
        let role = role.trim();
        role.eq_ignore_ascii_case(&facts.control_type)
            || facts
                .class_name
                .as_deref()
                .is_some_and(|class| class.eq_ignore_ascii_case(role))
    })
}

/// Case-insensitive `eq`, `contains`, `prefix`, or `suffix` test.
fn string_match(matcher: &StringMatch, candidate: Option<&str>) -> bool {
    let Some(candidate) = candidate else {
        return false;
    };

    let expected = matcher.value.to_lowercase();
    let candidate = candidate.to_lowercase();

    match matcher.op.trim().to_ascii_lowercase().as_str() {
        "contains" => candidate.contains(&expected),
        "prefix" => candidate.starts_with(&expected),
        "suffix" => candidate.ends_with(&expected),
        _ => candidate == expected,
    }
}

fn role_excluded(role: Option<&str>, excluded: &[String]) -> bool {
    let Some(role) = role else {
        return false;
    };

    excluded.iter().any(|name| role.eq_ignore_ascii_case(name))
}

fn non_empty(value: &str) -> Option<String> {
    (!value.is_empty()).then(|| value.to_string())
}

fn is_password_role(role_name: &str) -> bool {
    role_name.to_ascii_lowercase().contains("password")
}

fn role_to_control_type(role_name: &str) -> String {
    if role_name.is_empty() {
        return "Unknown".to_string();
    }

    role_name
        .split_ascii_whitespace()
        .map(|word| {
            let mut characters = word.chars();
            match characters.next() {
                Some(first) => first.to_ascii_uppercase().to_string() + characters.as_str(),
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn should_read_text_value(role_name: &str, interfaces: &InterfaceSet) -> bool {
    if interfaces.contains(Interface::EditableText) {
        return true;
    }

    matches!(
        role_name.to_ascii_lowercase().as_str(),
        "entry" | "text" | "password text" | "terminal" | "document text" | "paragraph"
    )
}

fn format_number(value: f64) -> String {
    if value.is_finite() && value.fract() == 0.0 {
        return format!("{}", value as i64);
    }

    format!("{value}")
}

fn window_matches(query: &str, window: &WindowInfo) -> bool {
    let query = query.trim().to_ascii_lowercase();

    if query.is_empty() {
        return true;
    }

    window.handle.to_ascii_lowercase().contains(&query)
        || window.title.to_ascii_lowercase().contains(&query)
        || window
            .process_name
            .as_deref()
            .map(|name| name.to_ascii_lowercase().contains(&query))
            .unwrap_or(false)
}

fn select_window_index(windows: &[WindowInfo], query: &str) -> Option<usize> {
    let query = query.trim();

    if query.is_empty() {
        return (!windows.is_empty()).then_some(0);
    }

    let lowered = query.to_ascii_lowercase();

    windows
        .iter()
        .position(|window| window.handle == query)
        .or_else(|| {
            windows
                .iter()
                .position(|window| window.title.eq_ignore_ascii_case(query))
        })
        .or_else(|| {
            windows.iter().position(|window| {
                window
                    .process_name
                    .as_deref()
                    .map(|name| name.eq_ignore_ascii_case(query))
                    .unwrap_or(false)
            })
        })
        .or_else(|| {
            windows
                .iter()
                .position(|window| window.title.to_ascii_lowercase().contains(&lowered))
        })
        .or_else(|| {
            windows
                .iter()
                .position(|window| window_matches(query, window))
        })
}

fn snapshot_truncated(kept: u32, budget: u32, depth_limited: bool, pending: bool) -> bool {
    depth_limited || (kept >= budget && pending)
}

/// Truncate a child list to `cap`, returning the kept prefix and the number
/// dropped. The cap keeps one huge table from dominating the walk.
fn cap_children<T>(mut children: Vec<T>, cap: usize) -> (Vec<T>, u32) {
    if children.len() <= cap {
        return (children, 0);
    }

    let dropped = children.len() - cap;
    children.truncate(cap);

    (children, dropped as u32)
}

/// Pick the dominant reason a snapshot is incomplete. A deadline stops the walk
/// first, then the element budget, then the per-node child cap, then depth.
fn truncation_cause(
    timed_out: bool,
    budget_exhausted: bool,
    children_cut: u32,
    depth_limited: bool,
) -> Option<&'static str> {
    if timed_out {
        return Some("time");
    }

    if budget_exhausted {
        return Some("max_elements");
    }

    if children_cut > 0 {
        return Some("max_children");
    }

    if depth_limited {
        return Some("max_depth");
    }

    None
}

/// True once the ambient walk deadline has passed.
fn deadline_reached(deadline: Instant) -> bool {
    Instant::now() >= deadline
}

/// Per-request snapshot budget; `CECLI_ATSPI_SNAPSHOT_MS` overrides the call
/// timeout so one request can opt into more or less time.
fn snapshot_budget() -> Duration {
    static BUDGET: OnceLock<Duration> = OnceLock::new();

    *BUDGET.get_or_init(|| {
        std::env::var("CECLI_ATSPI_SNAPSHOT_MS")
            .ok()
            .and_then(|value| value.trim().parse::<u64>().ok())
            .filter(|value| *value > 0)
            .map(Duration::from_millis)
            .unwrap_or_else(call_timeout)
    })
}

/// Timeout for one application during enumeration. It stays below the outer
/// call budget so a single wedged peer cannot consume all of it.
fn peer_timeout() -> Duration {
    (call_timeout() / 2).min(PEER_TIMEOUT)
}

/// Drop the cached connection and health answer so the next request reconnects
/// lazily instead of reusing a killed or wedged peer.
fn reset_connection(state: &Mutex<ConnectionState>) {
    let mut state = lock(state);
    state.connection = None;
    state.health = None;
}

/// Match ``target`` against a record set in descending selector strength.
///
/// Tried one selector class at a time so a broad `role` hint can never beat an
/// `id` or `path` that the caller actually supplied.
fn find_element_index(elements: &[ElementRecord], target: &ElementRef) -> Option<usize> {
    if let Some(id) = target.id {
        if let Some(index) = elements.iter().position(|element| element.id == id) {
            return Some(index);
        }
    }

    if let Some(runtime_id) = target.runtime_id.as_deref() {
        if let Some(index) = elements
            .iter()
            .position(|element| element.runtime_id == runtime_id)
        {
            return Some(index);
        }
    }

    if let Some(automation_id) = target.automation_id.as_deref() {
        if let Some(index) = elements
            .iter()
            .position(|element| element.automation_id.as_deref() == Some(automation_id))
        {
            return Some(index);
        }
    }

    if let Some(path) = target.path.as_deref() {
        if let Some(index) = elements
            .iter()
            .position(|element| element.path.as_deref() == Some(path))
        {
            return Some(index);
        }
    }

    if let Some(name) = target.name.as_deref() {
        let role = target.role.as_deref();
        let matches = |element: &ElementRecord| {
            element.name.as_deref() == Some(name)
                && role
                    .map(|role| element.control_type.eq_ignore_ascii_case(role))
                    .unwrap_or(true)
        };

        if let Some(index) = elements
            .iter()
            .position(|element| matches(element) && element.sensitive)
        {
            return Some(index);
        }

        if let Some(index) = elements.iter().position(matches) {
            return Some(index);
        }

        return None;
    }

    // A role-only selector is the weakest form and is allowed only when nothing
    // stronger was supplied; otherwise a stale id would silently degrade to the
    // first element of that role.
    let role = target.role.as_deref()?;

    elements
        .iter()
        .position(|element| element.control_type.eq_ignore_ascii_case(role))
}

fn resolve_node<'a>(
    cache: &'a SnapshotCache,
    target: Option<&ElementRef>,
) -> Result<(&'a ElementRecord, &'a NodeRef), ErrorInfo> {
    let target = target
        .filter(|reference| !reference.is_empty())
        .ok_or_else(|| {
            ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                "action requires a target element from the latest snapshot",
            )
        })?;

    let index = find_element_index(&cache.snapshot.elements, target).ok_or_else(|| {
        ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            "no element in the latest snapshot matches the target reference",
        )
        .with_details(crate::observe::failure_details(&cache.snapshot, target))
    })?;

    let node = cache.nodes.get(index).ok_or_else(|| {
        ErrorInfo::new(
            error_kind::STALE_TARGET,
            "the snapshot no longer carries a bus reference for this element; take a fresh snapshot",
        )
    })?;

    Ok((&cache.snapshot.elements[index], node))
}

fn accessibility_setting() -> String {
    let output = std::process::Command::new("gsettings")
        .args([
            "get",
            "org.gnome.desktop.interface",
            "toolkit-accessibility",
        ])
        .output();

    match output {
        Ok(output) if output.status.success() => {
            let value = String::from_utf8_lossy(&output.stdout).trim().to_string();

            if value == "true" || value == "false" {
                value
            } else {
                "unknown".to_string()
            }
        }
        _ => "unknown".to_string(),
    }
}

/// Resolve a spreadsheet cell by row and column.
///
/// The sheet is the first node whose role contains `table`. Address lookup uses
/// the AT-SPI `Collection` interface when the sheet exposes it; otherwise a
/// bounded enumeration of up to [`MAX_CELLS`] children is indexed by
/// `row * n_columns + column`. The resolved cell is always checked through
/// `TableCell` so a success is never reported without a matching position.
///
/// A scoped `root` starts the table search at that node instead of the window.
async fn cell_at(
    connection: &AccessibilityConnection,
    state: &Mutex<ConnectionState>,
    query: &str,
    root: Option<(ElementRecord, NodeRef)>,
    row: u32,
    column: u32,
) -> Result<ActionResult, ErrorInfo> {
    let deadline = Instant::now() + call_timeout();
    let table = match root {
        Some((record, node)) => find_table_node(connection, &node, deadline)
            .await
            .map_err(|error| scoped_table_error(error, &record))?,
        None => {
            let window = window_node(connection, state, query).await?;

            find_table_node(connection, &window.node, deadline).await?
        }
    };
    let interfaces = interfaces_of(connection, &table).await?;

    if interfaces.contains(Interface::Collection) {
        if let Some(cell) = collection_cell(connection, &table, row, column).await {
            return verify_cell(connection, &cell, row, column).await;
        }
    }

    let cell = enumerate_cell(connection, &table, &interfaces, row, column).await?;

    verify_cell(connection, &cell, row, column).await
}

/// Rewrite the generic "no table" failure to name the scoped target.
fn scoped_table_error(error: ErrorInfo, record: &ElementRecord) -> ErrorInfo {
    if error.kind != error_kind::TARGET_NOT_FOUND {
        return error;
    }

    ErrorInfo::new(
        error_kind::TARGET_NOT_FOUND,
        format!(
            "the grid target {} exposes no role containing 'table' at or under it",
            describe_element(record)
        ),
    )
}

/// Human-readable identity for diagnostics.
fn describe_element(record: &ElementRecord) -> String {
    match record.name.as_deref().filter(|name| !name.is_empty()) {
        Some(name) => format!(
            "{name:?} (id {}, runtime_id {:?})",
            record.id, record.runtime_id
        ),
        None => format!("id {} (runtime_id {:?})", record.id, record.runtime_id),
    }
}

/// Breadth-first search for the first role containing `table`.
async fn find_table_node(
    connection: &AccessibilityConnection,
    root: &NodeRef,
    deadline: Instant,
) -> Result<NodeRef, ErrorInfo> {
    let mut visited: HashSet<String> = HashSet::new();
    let mut stack = WalkStack::new(root.clone());

    while let Some((node, _parent, depth)) = stack.pop() {
        if deadline_reached(deadline) {
            return Err(ErrorInfo::new(
                error_kind::TIMEOUT,
                "cell_at timed out while searching for a table",
            ));
        }

        if !visited.insert(node.key()) {
            continue;
        }

        let accessible = match accessible_for(connection, &node).await {
            Ok(accessible) => accessible,
            Err(_) => continue,
        };
        let role = role_name_of(&accessible).await;

        if role.to_ascii_lowercase().contains("table") {
            return Ok(node);
        }

        if depth >= DEFAULT_MAX_DEPTH {
            continue;
        }

        if let Ok(children) = children_of(connection, &node).await {
            let (children, _dropped) = cap_children(children, MAX_CHILDREN_PER_NODE);
            stack.push_children(0, depth + 1, children);
        }
    }

    Err(ErrorInfo::new(
        error_kind::TARGET_NOT_FOUND,
        format!(
            "no role containing 'table' was found within depth {DEFAULT_MAX_DEPTH} and the {MAX_CHILDREN_PER_NODE}-child cap"
        ),
    ))
}

/// Ask the sheet's Collection interface for the cell at `row`/`column`.
async fn collection_cell(
    connection: &AccessibilityConnection,
    table: &NodeRef,
    row: u32,
    column: u32,
) -> Option<NodeRef> {
    let collection = collection_for(connection, table).await.ok()?;
    let mut attributes = HashMap::new();
    attributes.insert("row".to_string(), row.to_string());
    attributes.insert("column".to_string(), column.to_string());
    let rule = ObjectMatchRule::builder()
        .attributes(attributes, MatchType::All)
        .interfaces([Interface::TableCell], MatchType::All)
        .build();
    let matches = collection
        .get_matches(rule, SortOrder::Canonical, 1, false)
        .await
        .ok()?;

    matches.first().and_then(node_from_reference)
}

/// Fallback address lookup by enumerating bounded table children.
async fn enumerate_cell(
    connection: &AccessibilityConnection,
    table: &NodeRef,
    interfaces: &InterfaceSet,
    row: u32,
    column: u32,
) -> Result<NodeRef, ErrorInfo> {
    if !interfaces.contains(Interface::Table) {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!(
                "the sheet exposes neither the AT-SPI Collection nor Table interface; cannot address row {row} column {column}"
            ),
        ));
    }

    let proxy = table_for(connection, table).await?;
    let rows = proxy.n_rows().await.map_err(|error| {
        ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!("the sheet Table NRows property is unavailable: {error}"),
        )
    })?;
    let columns = proxy.n_columns().await.map_err(|error| {
        ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!("the sheet Table NColumns property is unavailable: {error}"),
        )
    })?;

    if rows <= 0 || columns <= 0 {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!("the sheet reports an empty {rows}x{columns} grid"),
        ));
    }

    let cell_count = (rows as usize).saturating_mul(columns as usize);

    if cell_count > MAX_CELLS {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!(
                "the sheet has {rows}x{columns} = {cell_count} cells, beyond the {MAX_CELLS}-cell enumeration cap; the AT-SPI Collection interface is required"
            ),
        ));
    }

    if row as i32 >= rows || column as i32 >= columns {
        return Err(ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            format!("row {row} column {column} is outside the {rows}x{columns} sheet"),
        ));
    }

    let index = (row as usize).saturating_mul(columns as usize) + column as usize;
    let children = children_of(connection, table).await?;
    let Some(cell) = children.get(index) else {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!(
                "the sheet enumerated only {} children; row {row} column {column} is not addressable by index",
                children.len()
            ),
        ));
    };

    Ok(cell.clone())
}

/// Confirm the resolved cell reports the requested row and column.
async fn verify_cell(
    connection: &AccessibilityConnection,
    cell: &NodeRef,
    row: u32,
    column: u32,
) -> Result<ActionResult, ErrorInfo> {
    let interfaces = interfaces_of(connection, cell).await?;

    if !interfaces.contains(Interface::TableCell) {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!(
                "resolved cell for row {row} column {column} does not expose the AT-SPI TableCell interface; its position cannot be verified"
            ),
        ));
    }

    let proxy = table_cell_for(connection, cell).await?;
    let (_, actual_row, actual_column, _, _) = proxy.get_row_column_span().await.map_err(|error| {
        ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!("TableCell GetRowColumnSpan is unavailable; position cannot be verified: {error}"),
        )
    })?;

    if actual_row != row as i32 || actual_column != column as i32 {
        return Err(ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!(
                "resolved cell reports row {actual_row} column {actual_column}, expected row {row} column {column}"
            ),
        ));
    }

    Ok(ActionResult {
        action: "cell_at".to_string(),
        delivered: true,
        verified: true,
        uncertain: false,
        value: Some(cell.path.clone()),
        message: Some(format!("row {actual_row}, column {actual_column}")),
        outcome: Some(outcome::ACCESSIBILITY.to_string()),
    })
}

/// One step returned by a [`walk_tree`] visitor.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WalkStep {
    Continue,
    Stop,
}

/// Outcome and budget accounting for one [`walk_tree`] run.
#[derive(Debug, Default)]
struct WalkStats {
    kept: u32,
    children_cut: u32,
    depth_limited: bool,
    budget_exhausted: bool,
    timed_out: bool,
    pending: bool,
    stopped: bool,
}

/// Accumulates matches while enforcing an optional store limit.
struct FindCollector {
    limit: Option<u32>,
    matches: Vec<ElementRecord>,
    match_count: u32,
}

impl FindCollector {
    fn new(limit: Option<u32>) -> Self {
        Self {
            limit: limit.filter(|value| *value > 0),
            matches: Vec::new(),
            match_count: 0,
        }
    }

    /// Store a match and report whether the walk should stop.
    ///
    /// Every call increments `match_count`, even past the store limit, so the
    /// counter stays honest if a visitor is invoked after the vector is full.
    fn record(&mut self, mut record: ElementRecord) -> bool {
        record.id = self.match_count;
        self.match_count = self.match_count.saturating_add(1);

        let within_limit = self
            .limit
            .map_or(true, |limit| (self.matches.len() as u32) < limit);
        if within_limit {
            self.matches.push(record);
        }

        self.limit.is_some_and(|limit| self.match_count >= limit)
    }

    fn into_result(self, truncated_by: Option<String>) -> FindResult {
        let truncated = truncated_by.is_some();

        FindResult {
            matches: self.matches,
            match_count: self.match_count,
            truncated,
            truncated_by,
        }
    }
}

/// Depth-first work list that keeps pre-order numbering stable.
#[derive(Debug)]
struct WalkStack<T> {
    pending: Vec<(T, Option<u32>, u32)>,
}

impl<T> WalkStack<T> {
    fn new(root: T) -> Self {
        Self {
            pending: vec![(root, None, 0)],
        }
    }

    fn pop(&mut self) -> Option<(T, Option<u32>, u32)> {
        self.pending.pop()
    }

    fn put_back(&mut self, item: (T, Option<u32>, u32)) {
        self.pending.push(item);
    }

    fn push_children(&mut self, parent: u32, depth: u32, children: Vec<T>) {
        for child in children.into_iter().rev() {
            self.pending.push((child, Some(parent), depth));
        }
    }

    fn is_empty(&self) -> bool {
        self.pending.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::ElementRecord;

    fn window(handle: &str, title: &str, process: &str) -> WindowInfo {
        WindowInfo {
            handle: handle.to_string(),
            title: title.to_string(),
            process_name: Some(process.to_string()),
            ..Default::default()
        }
    }

    fn record(id: u32, name: &str, control_type: &str) -> ElementRecord {
        ElementRecord {
            id,
            runtime_id: format!("/path/{id}"),
            name: Some(name.to_string()),
            control_type: control_type.to_string(),
            ..Default::default()
        }
    }

    fn cache(elements: Vec<ElementRecord>) -> SnapshotCache {
        let nodes = elements
            .iter()
            .map(|element| NodeRef {
                destination: ":1.1".to_string(),
                path: element.runtime_id.clone(),
            })
            .collect();

        SnapshotCache {
            snapshot: Snapshot {
                elements,
                ..Default::default()
            },
            nodes,
        }
    }

    #[test]
    fn preorder_walk_assigns_parents_and_depths() {
        let mut stack = WalkStack::new("root");
        let mut order = Vec::new();

        while let Some((name, parent, depth)) = stack.pop() {
            let id = order.len() as u32;
            order.push((name, id, parent, depth));

            match name {
                "root" => stack.push_children(id, depth + 1, vec!["b", "c"]),
                "b" => stack.push_children(id, depth + 1, vec!["d"]),
                _ => {}
            }
        }

        let names: Vec<&str> = order.iter().map(|(name, _, _, _)| *name).collect();
        let parents: Vec<Option<u32>> = order.iter().map(|(_, _, parent, _)| *parent).collect();
        let depths: Vec<u32> = order.iter().map(|(_, _, _, depth)| *depth).collect();

        assert_eq!(names, vec!["root", "b", "d", "c"]);
        assert_eq!(parents, vec![None, Some(0), Some(1), Some(0)]);
        assert_eq!(depths, vec![0, 1, 2, 1]);
        assert_eq!(
            order.iter().map(|(_, id, _, _)| *id).collect::<Vec<_>>(),
            vec![0, 1, 2, 3]
        );
    }

    #[test]
    fn excluded_roles_match_case_insensitively() {
        let excluded = vec!["menu".to_string(), "separator".to_string()];

        assert!(role_excluded(Some("Menu"), &excluded));
        assert!(role_excluded(Some("SEPARATOR"), &excluded));
        assert!(!role_excluded(Some("Push Button"), &excluded));
        assert!(!role_excluded(None, &excluded));
    }

    #[test]
    fn truncation_reports_budget_and_depth_hits() {
        assert!(!snapshot_truncated(3, 10, false, false));
        assert!(snapshot_truncated(10, 10, false, true));
        assert!(!snapshot_truncated(10, 10, false, false));
        assert!(snapshot_truncated(1, 10, true, false));
    }

    #[test]
    fn password_roles_are_detected_by_role_name() {
        assert!(is_password_role("password text"));
        assert!(is_password_role("Password Text"));
        assert!(!is_password_role("entry"));
        assert!(!is_password_role("text"));
    }

    #[test]
    fn role_names_map_to_title_case_control_types() {
        assert_eq!(role_to_control_type("push button"), "Push Button");
        assert_eq!(role_to_control_type("password text"), "Password Text");
        assert_eq!(role_to_control_type("frame"), "Frame");
        assert_eq!(role_to_control_type(""), "Unknown");
    }

    #[test]
    fn window_selection_prefers_exact_handle_then_title_then_process() {
        let windows = vec![
            window(
                "/org/a11y/atspi/accessible/root/1",
                "Notes",
                "gnome-text-editor",
            ),
            window(
                "/org/a11y/atspi/accessible/root/2",
                "Calculator",
                "gnome-calculator",
            ),
        ];

        assert_eq!(
            select_window_index(&windows, "/org/a11y/atspi/accessible/root/2"),
            Some(1)
        );
        assert_eq!(select_window_index(&windows, "calculator"), Some(1));
        assert_eq!(select_window_index(&windows, "gnome-text-editor"), Some(0));
        assert_eq!(select_window_index(&windows, "missing"), None);
        assert_eq!(select_window_index(&[], ""), None);
        assert_eq!(select_window_index(&windows, ""), Some(0));
    }

    #[test]
    fn window_matching_is_case_insensitive_and_substring() {
        let candidate = window("/path/1", "Text Editor", "gedit");

        assert!(window_matches("text", &candidate));
        assert!(window_matches("GEDIT", &candidate));
        assert!(window_matches("/path", &candidate));
        assert!(window_matches("", &candidate));
        assert!(!window_matches("calculator", &candidate));
    }

    #[test]
    fn target_resolution_uses_id_runtime_name_and_role() {
        let cache = cache(vec![
            record(0, "Save", "Push Button"),
            record(1, "Name", "Entry"),
        ]);

        let by_id = ElementRef {
            id: Some(1),
            ..Default::default()
        };
        let by_runtime = ElementRef {
            runtime_id: Some("/path/1".to_string()),
            ..Default::default()
        };
        let by_name = ElementRef {
            name: Some("Save".to_string()),
            ..Default::default()
        };
        let by_role = ElementRef {
            role: Some("push button".to_string()),
            ..Default::default()
        };

        assert_eq!(resolve_node(&cache, Some(&by_id)).unwrap().0.id, 1);
        assert_eq!(resolve_node(&cache, Some(&by_runtime)).unwrap().0.id, 1);
        assert_eq!(resolve_node(&cache, Some(&by_name)).unwrap().0.id, 0);
        assert_eq!(resolve_node(&cache, Some(&by_role)).unwrap().0.id, 0);
    }

    #[test]
    fn an_id_beats_a_shared_role() {
        let cache = cache(vec![
            record(0, "Save", "Push Button"),
            record(1, "Close", "Push Button"),
        ]);
        let target = ElementRef {
            id: Some(1),
            role: Some("push button".to_string()),
            ..Default::default()
        };

        assert_eq!(resolve_node(&cache, Some(&target)).unwrap().0.id, 1);
    }

    #[test]
    fn stale_and_missing_targets_are_reported() {
        let cache = cache(vec![record(0, "Save", "Push Button")]);
        let missing = ElementRef {
            id: Some(99),
            ..Default::default()
        };

        let error = resolve_node(&cache, Some(&missing)).unwrap_err();
        assert_eq!(error.kind, error_kind::TARGET_NOT_FOUND);

        let error = resolve_node(&cache, None).unwrap_err();
        assert_eq!(error.kind, error_kind::TARGET_NOT_FOUND);
    }

    fn backend_with_cache(cache: SnapshotCache) -> AtspiBackend {
        let backend = AtspiBackend::new();
        *lock(&backend.last_snapshot) = Some(cache);

        backend
    }

    fn grid_target(id: u32) -> ElementRef {
        ElementRef {
            id: Some(id),
            ..Default::default()
        }
    }

    #[test]
    fn cell_at_without_a_target_falls_back_to_the_window() {
        let backend = backend_with_cache(cache(vec![record(0, "Sheet", "Table")]));

        assert!(backend.resolve_cell_root(None).unwrap().is_none());
        assert!(backend
            .resolve_cell_root(Some(&ElementRef::default()))
            .unwrap()
            .is_none());
    }

    #[test]
    fn cell_at_target_resolves_against_the_latest_snapshot() {
        let backend = backend_with_cache(cache(vec![
            record(0, "Window", "Frame"),
            record(1, "Sheet", "Table"),
        ]));
        let target = grid_target(1);
        let (record, node) = backend
            .resolve_cell_root(Some(&target))
            .unwrap()
            .expect("resolved root");

        assert_eq!(record.id, 1);
        assert_eq!(node.path, "/path/1");
    }

    #[test]
    fn cell_at_target_without_a_snapshot_is_stale() {
        let backend = AtspiBackend::new();
        let target = grid_target(0);
        let error = backend.resolve_cell_root(Some(&target)).unwrap_err();

        assert_eq!(error.kind, error_kind::STALE_TARGET);
        assert!(error.message.contains("snapshot"));
    }

    #[test]
    fn cell_at_target_that_no_longer_resolves_is_stale() {
        let backend = backend_with_cache(cache(vec![record(0, "Sheet", "Table")]));
        let target = grid_target(99);
        let error = backend.resolve_cell_root(Some(&target)).unwrap_err();

        assert_eq!(error.kind, error_kind::STALE_TARGET);
        assert!(error.message.contains("fresh snapshot"));
    }

    #[test]
    fn cell_at_scope_failure_names_the_target() {
        let target = record(3, "Budget", "Panel");
        let error = scoped_table_error(
            ErrorInfo::new(error_kind::TARGET_NOT_FOUND, "no role containing 'table'"),
            &target,
        );

        assert_eq!(error.kind, error_kind::TARGET_NOT_FOUND);
        assert!(error.message.contains("Budget"));
        assert!(error.message.contains("table"));
    }

    #[test]
    fn cell_at_scope_preserves_non_table_failures() {
        let target = record(3, "Budget", "Panel");
        let error = scoped_table_error(ErrorInfo::new(error_kind::TIMEOUT, "timed out"), &target);

        assert_eq!(error.kind, error_kind::TIMEOUT);
        assert!(error.message.contains("timed out"));
    }

    #[test]
    fn numeric_values_render_without_a_trailing_fraction() {
        assert_eq!(format_number(42.0), "42");
        assert_eq!(format_number(0.0), "0");
        assert_eq!(format_number(1.5), "1.5");
    }

    #[test]
    fn keys_and_scroll_point_at_the_xtest_driver() {
        let backend = AtspiBackend::new();
        let mut request = ActionRequest {
            window: "anything".to_string(),
            action: "keys".to_string(),
            target: None,
            args: ActionArgs::default(),
        };

        let error = backend.action(&request).unwrap_err();
        assert_eq!(error.kind, error_kind::UNSUPPORTED);
        assert!(error.message.contains("T14"));

        request.action = "scroll".to_string();
        let error = backend.action(&request).unwrap_err();
        assert_eq!(error.kind, error_kind::UNSUPPORTED);
    }

    #[test]
    fn select_and_scroll_into_view_are_recognized_actions() {
        let backend = AtspiBackend::new();

        for action in ["select", "scroll_into_view"] {
            let request = ActionRequest {
                window: "anything".to_string(),
                action: action.to_string(),
                target: None,
                args: ActionArgs::default(),
            };

            let error = backend.action(&request).unwrap_err();
            assert_eq!(error.kind, error_kind::TARGET_NOT_FOUND);
        }
    }

    #[test]
    fn unknown_actions_are_invalid_requests() {
        let backend = AtspiBackend::new();
        let request = ActionRequest {
            window: "anything".to_string(),
            action: "levitate".to_string(),
            target: None,
            args: ActionArgs::default(),
        };

        let error = backend.action(&request).unwrap_err();
        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
    }

    #[test]
    fn screenshots_are_unsupported_without_touching_x11() {
        let backend = AtspiBackend::new();
        let error = backend
            .screenshot(&ScreenshotRequest {
                window: "anything".to_string(),
            })
            .unwrap_err();

        assert_eq!(error.kind, error_kind::UNSUPPORTED);
        assert!(error.message.contains("capture"));
    }

    #[test]
    #[ignore = "requires a live AT-SPI accessibility bus"]
    fn live_windows_and_snapshot() {
        let backend = AtspiBackend::new();
        let windows = match backend.windows() {
            Ok(windows) => windows,
            Err(error) if error.kind == error_kind::UNSUPPORTED => {
                eprintln!("skipping: {}", error.message);
                return;
            }
            Err(error) => panic!("windows failed: {error}"),
        };

        if windows.is_empty() {
            eprintln!("skipping: the AT-SPI registry reports no applications");
            return;
        }

        let snapshot = backend
            .snapshot(&SnapshotRequest {
                window: windows[0].handle.clone(),
                max_depth: Some(4),
                max_elements: Some(200),
                exclude_roles: Vec::new(),
                actionable: false,
            })
            .expect("snapshot");

        assert!(!snapshot.elements.is_empty());
        assert_eq!(snapshot.elements[0].id, 0);
        assert!(snapshot.max_elements == 200);
    }

    #[test]
    #[ignore = "requires a live AT-SPI accessibility bus"]
    fn live_doctor_reports_backend_and_registry() {
        let backend = AtspiBackend::new();
        let report = backend.doctor();

        assert_eq!(report.backend, "linux-atspi");
        assert!(report
            .checks
            .iter()
            .any(|check| check.name == "backend" && check.ok));
        assert!(report
            .checks
            .iter()
            .any(|check| check.name == "session_bus"));
        assert!(report
            .checks
            .iter()
            .any(|check| check.name == "atspi_registry"));
        assert!(report
            .checks
            .iter()
            .any(|check| check.name == "accessibility_enabled"));
    }

    #[test]
    #[ignore = "requires a live AT-SPI accessibility bus"]
    fn live_actions_on_a_snapshot_element() {
        let backend = AtspiBackend::new();
        let Ok(windows) = backend.windows() else {
            eprintln!("skipping: no accessibility bus");
            return;
        };
        let Some(window) = windows.first() else {
            eprintln!("skipping: no windows");
            return;
        };
        let Ok(snapshot) = backend.snapshot(&SnapshotRequest {
            window: window.handle.clone(),
            max_depth: Some(3),
            max_elements: Some(100),
            exclude_roles: Vec::new(),
            actionable: false,
        }) else {
            eprintln!("skipping: snapshot failed");
            return;
        };

        if let Some(element) = snapshot
            .elements
            .iter()
            .find(|element| element.name.is_some())
        {
            let request = ActionRequest {
                window: window.handle.clone(),
                action: "get_value".to_string(),
                target: Some(ElementRef {
                    id: Some(element.id),
                    ..Default::default()
                }),
                args: ActionArgs::default(),
            };

            match backend.action(&request) {
                Ok(result) => {
                    assert!(result.delivered);
                }
                Err(error) => {
                    assert!(
                        matches!(
                            error.kind.as_str(),
                            error_kind::UNSUPPORTED
                                | error_kind::INPUT_BLOCKED
                                | error_kind::TARGET_NOT_FOUND
                                | error_kind::STALE_TARGET
                        ),
                        "unexpected action error: {error}"
                    );
                }
            }
        }
    }

    #[test]
    fn child_cap_truncates_and_counts_dropped() {
        let (kept, dropped) = cap_children((0..250).collect::<Vec<_>>(), MAX_CHILDREN_PER_NODE);

        assert_eq!(kept.len(), MAX_CHILDREN_PER_NODE);
        assert_eq!(kept.first(), Some(&0));
        assert_eq!(kept.last(), Some(&199));
        assert_eq!(dropped, 50);
    }

    #[test]
    fn child_cap_is_a_no_op_at_or_below_the_limit() {
        let (kept, dropped) = cap_children((0..200).collect::<Vec<_>>(), MAX_CHILDREN_PER_NODE);

        assert_eq!(kept.len(), MAX_CHILDREN_PER_NODE);
        assert_eq!(dropped, 0);

        let (empty, dropped) = cap_children(Vec::<u32>::new(), MAX_CHILDREN_PER_NODE);

        assert!(empty.is_empty());
        assert_eq!(dropped, 0);
    }

    #[test]
    fn truncation_cause_prefers_the_hard_stop() {
        assert_eq!(truncation_cause(false, false, 0, false), None);
        assert_eq!(truncation_cause(false, false, 0, true), Some("max_depth"));
        assert_eq!(
            truncation_cause(false, false, 7, true),
            Some("max_children")
        );
        assert_eq!(truncation_cause(false, true, 7, true), Some("max_elements"));
        assert_eq!(truncation_cause(true, true, 7, true), Some("time"));
    }

    #[test]
    fn deadline_check_compares_against_now() {
        assert!(deadline_reached(Instant::now()));
        assert!(deadline_reached(Instant::now() - Duration::from_millis(1)));
        assert!(!deadline_reached(Instant::now() + Duration::from_secs(60)));
    }
    fn matcher(op: &str, value: &str) -> StringMatch {
        StringMatch {
            op: op.to_string(),
            value: value.to_string(),
        }
    }

    fn facts(name: Option<&str>, value: Option<&str>, enabled: bool, sensitive: bool) -> NodeFacts {
        NodeFacts {
            control_type: "Push Button".to_string(),
            name: name.map(str::to_string),
            class_name: Some("push button".to_string()),
            value: value.map(str::to_string),
            enabled,
            offscreen: false,
            bounds: None,
            patterns: Vec::new(),
            scroll: None,
            sensitive,
        }
    }

    #[test]
    fn string_match_supports_every_operator_case_insensitively() {
        let candidate = Some("Save As Copy");

        assert!(string_match(&matcher("eq", "save as copy"), candidate));
        assert!(string_match(&matcher("EQ", "SAVE AS COPY"), candidate));
        assert!(string_match(&matcher("contains", "as"), candidate));
        assert!(string_match(&matcher("prefix", "save"), candidate));
        assert!(string_match(&matcher("suffix", "copy"), candidate));
        assert!(!string_match(&matcher("prefix", "copy"), candidate));
        assert!(!string_match(&matcher("contains", "delete"), candidate));
        assert!(string_match(&matcher("bogus", "save as copy"), candidate));
        assert!(!string_match(&matcher("eq", "save as copy"), None));
    }

    #[test]
    fn match_spec_combines_roles_strings_and_flags() {
        let node = facts(Some("Submit"), Some("ready"), true, false);

        let mut spec = MatchSpec {
            name: Some(matcher("prefix", "sub")),
            enabled: Some(true),
            sensitive: Some(false),
            ..Default::default()
        };
        assert!(facts_match(&spec, &node));

        spec.value = Some(matcher("contains", "READ"));
        assert!(facts_match(&spec, &node));

        spec.enabled = Some(false);
        assert!(!facts_match(&spec, &node));

        spec.enabled = Some(true);
        spec.sensitive = Some(true);
        assert!(!facts_match(&spec, &node));

        spec.sensitive = Some(false);
        spec.value = Some(matcher("suffix", "dy"));
        assert!(facts_match(&spec, &node));

        spec.value = Some(matcher("eq", "missing"));
        assert!(!facts_match(&spec, &node));
    }

    #[test]
    fn match_spec_roles_match_control_type_or_platform_role() {
        let node = facts(Some("Save"), None, true, false);

        assert!(facts_match(&MatchSpec::default(), &node));
        assert!(facts_match(
            &MatchSpec {
                roles: vec!["push button".to_string()],
                ..Default::default()
            },
            &node
        ));
        assert!(facts_match(
            &MatchSpec {
                roles: vec!["PUSH BUTTON".to_string()],
                ..Default::default()
            },
            &node
        ));
        assert!(!facts_match(
            &MatchSpec {
                roles: vec!["table".to_string()],
                ..Default::default()
            },
            &node
        ));
    }

    #[test]
    fn match_spec_requires_a_value_when_a_value_matcher_is_set() {
        let node = facts(Some("Save"), None, true, false);

        assert!(!facts_match(
            &MatchSpec {
                value: Some(matcher("contains", "anything")),
                ..Default::default()
            },
            &node
        ));
    }

    #[test]
    fn find_collector_stops_at_the_limit_and_counts_every_match() {
        let mut collector = FindCollector::new(Some(2));

        assert!(!collector.record(ElementRecord::default()));
        assert!(collector.record(ElementRecord::default()));
        assert!(collector.record(ElementRecord::default()));

        let result = collector.into_result(Some("limit".to_string()));
        assert_eq!(result.matches.len(), 2);
        assert_eq!(result.match_count, 3);
        assert!(result.truncated);
        assert_eq!(result.truncated_by.as_deref(), Some("limit"));
        assert_eq!(result.matches[0].id, 0);
        assert_eq!(result.matches[1].id, 1);
    }

    #[test]
    fn find_collector_without_a_limit_keeps_every_match() {
        let mut collector = FindCollector::new(None);

        assert!(!collector.record(ElementRecord::default()));
        assert!(!collector.record(ElementRecord::default()));

        let result = collector.into_result(None);
        assert_eq!(result.matches.len(), 2);
        assert_eq!(result.match_count, 2);
        assert!(!result.truncated);
        assert!(result.truncated_by.is_none());
    }

    #[test]
    fn find_collector_treats_zero_as_unlimited() {
        let mut collector = FindCollector::new(Some(0));

        assert!(!collector.record(ElementRecord::default()));
        assert!(!collector.record(ElementRecord::default()));

        let result = collector.into_result(None);
        assert_eq!(result.match_count, 2);
        assert_eq!(result.matches.len(), 2);
    }
}
