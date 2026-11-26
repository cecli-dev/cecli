//! Windows UI Automation snapshots and element handles.
//!
//! A [`UiaSession`] owns the `IUIAutomation` client on one dedicated
//! multithreaded apartment (MTA) thread. Every COM call is funneled through that
//! thread so a hung provider cannot block the bridge's HTTP threads beyond the
//! per-call timeout. Identity is never assumed: a handle re-reads the element's
//! runtime id and a fresh `IsEnabled` before any action uses it.
//!
//! ## API for action tasks (T7/T8)
//!
//! `WindowsBackend` keeps the last [`UiaSnapshotCache`] in a mutex. Resolve an
//! [`ElementRef`] with `cache.resolve_target(&target)` or a snapshot runtime id
//! with `cache.element_for(&runtime_id)`. Both return an [`ElementHandle`]:
//!
//! - `record()` / `runtime_id()` / `is_password()`
//! - `is_enabled_fresh()` reads `IsEnabled` right now; refuse actions when false.
//! - `invoke_pattern()`, `value_pattern()`, `toggle_pattern()`,
//!   `selection_item_pattern()`, `expand_collapse_pattern()`,
//!   `range_value_pattern()`, `scroll_pattern()`, `selection_pattern()`,
//!   `select_pattern()` (LegacyIAccessible, for `Select`/`DoDefaultAction`).
//!
//! `value_pattern()` returns `input_blocked` for password elements so no caller
//! can read or write a secret. Identity failures surface as `stale_target`;
//! elements that vanished return `target_not_found`.

use std::collections::{HashMap, HashSet};
use std::ffi::c_void;
use std::ptr;
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use windows::core::{IUnknown, Interface, BSTR};
use windows::Win32::Foundation::{HWND, RECT};
use windows::Win32::System::Com::{CoCreateInstance, CLSCTX_INPROC_SERVER};
use windows::Win32::System::Ole::{
    SafeArrayAccessData, SafeArrayDestroy, SafeArrayGetLBound, SafeArrayGetUBound,
    SafeArrayUnaccessData,
};
use windows::Win32::UI::Accessibility::{
    AutomationElementMode_Full, CUIAutomation, IUIAutomation, IUIAutomationCacheRequest,
    IUIAutomationCondition, IUIAutomationElement, IUIAutomationExpandCollapsePattern,
    IUIAutomationGridPattern, IUIAutomationInvokePattern, IUIAutomationLegacyIAccessiblePattern,
    IUIAutomationRangeValuePattern, IUIAutomationScrollItemPattern, IUIAutomationScrollPattern,
    IUIAutomationSelectionItemPattern, IUIAutomationSelectionPattern, IUIAutomationTextPattern,
    IUIAutomationTogglePattern, IUIAutomationTreeWalker, IUIAutomationValuePattern,
    TreeScope_Descendants, TreeScope_Element, UIA_AutomationIdPropertyId,
    UIA_BoundingRectanglePropertyId, UIA_ClassNamePropertyId, UIA_ControlTypePropertyId,
    UIA_GridPatternId, UIA_IsEnabledPropertyId, UIA_IsOffscreenPropertyId,
    UIA_IsPasswordPropertyId, UIA_NamePropertyId, UIA_RuntimeIdPropertyId, UIA_ScrollPatternId,
    UIA_TextPatternId, UIA_ValuePatternId, UIA_PATTERN_ID,
};
use windows::Win32::UI::WindowsAndMessaging::IsWindow;

use super::element::{self, ElementBounds, ElementSeed};
use super::enumerate;
use crate::protocol::{
    error_kind, Bounds, CheckResult, ElementRecord, ElementRef, ErrorInfo, ScrollState, Snapshot,
    SnapshotRequest, WindowInfo,
};

/// Default depth budget when the request omits one. Matches the fake backend.
pub const DEFAULT_MAX_DEPTH: u32 = 10;
/// Default element budget when the request omits one.
pub const DEFAULT_MAX_ELEMENTS: u32 = 1000;

const SESSION_READY_TIMEOUT: Duration = Duration::from_secs(5);
const UIA_CALL_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_WALK_DEPTH: u32 = 256;
const TEXT_VALUE_LIMIT: i32 = 4096;

/// A snapshot plus the cache needed to act on its elements.
#[derive(Debug, Clone)]
pub struct SnapshotOutcome {
    pub snapshot: Snapshot,
    pub cache: UiaSnapshotCache,
}

/// Snapshot an entire window through UI Automation.
pub fn snapshot(window: &WindowInfo, request: &SnapshotRequest) -> Result<Snapshot, ErrorInfo> {
    Ok(snapshot_with_cache(window, request)?.snapshot)
}

/// Snapshot a window and return the connection-scoped element cache.
pub fn snapshot_with_cache(
    window: &WindowInfo,
    request: &SnapshotRequest,
) -> Result<SnapshotOutcome, ErrorInfo> {
    let max_depth = request.max_depth.unwrap_or(DEFAULT_MAX_DEPTH);
    let max_elements = request.max_elements.unwrap_or(DEFAULT_MAX_ELEMENTS);
    let session = Arc::new(UiaSession::new()?);

    let target = window.clone();
    let snapshot =
        session.run(move |worker| worker.take_snapshot(&target, max_depth, max_elements))?;
    let cache = UiaSnapshotCache::new(Arc::clone(&session), window.clone(), &snapshot.elements);

    Ok(SnapshotOutcome { snapshot, cache })
}

/// Doctor check that a UIA client can be created on an MTA thread.
pub fn doctor_check() -> CheckResult {
    match UiaSession::new() {
        Ok(session) => {
            drop(session);
            CheckResult::new(
                "uia_session",
                true,
                "UIA client created on a dedicated MTA thread",
            )
        }
        Err(error) => CheckResult::new("uia_session", false, error.message),
    }
}

/// Connection-scoped session owning the UIA client on its own MTA thread.
#[derive(Debug)]
pub struct UiaSession {
    sender: Option<mpsc::Sender<Job>>,
    worker: Mutex<Option<JoinHandle<()>>>,
}

impl UiaSession {
    /// Start the MTA worker and create the `CUIAutomation` client.
    pub fn new() -> Result<Self, ErrorInfo> {
        let (job_sender, job_receiver) = mpsc::channel::<Job>();
        let (ready_sender, ready_receiver) = mpsc::channel::<Result<(), ErrorInfo>>();

        let worker = thread::Builder::new()
            .name("ce-app-bridge-uia".to_string())
            .spawn(move || {
                let setup = enumerate::ensure_mta().and_then(|()| create_automation());
                match setup {
                    Ok(automation) => {
                        let mut worker = UiaWorker {
                            automation,
                            windows: HashMap::new(),
                        };
                        let _ = ready_sender.send(Ok(()));
                        while let Ok(job) = job_receiver.recv() {
                            job(&mut worker);
                        }
                    }
                    Err(error) => {
                        let _ = ready_sender.send(Err(error));
                    }
                }
            })
            .map_err(|error| {
                ErrorInfo::backend(format!("cannot start the UIA worker thread: {error}"))
            })?;

        let session = Self {
            sender: Some(job_sender),
            worker: Mutex::new(Some(worker)),
        };

        match ready_receiver.recv_timeout(SESSION_READY_TIMEOUT) {
            Ok(Ok(())) => Ok(session),
            Ok(Err(error)) => Err(error),
            Err(_) => Err(ErrorInfo::new(
                error_kind::TIMEOUT,
                "UIA session did not become ready within 5s",
            )),
        }
    }

    fn run<T, F>(&self, work: F) -> Result<T, ErrorInfo>
    where
        T: Send + 'static,
        F: FnOnce(&mut UiaWorker) -> Result<T, ErrorInfo> + Send + 'static,
    {
        let sender = self
            .sender
            .as_ref()
            .ok_or_else(|| ErrorInfo::backend("UIA session is closed"))?;
        let (result_sender, result_receiver) = mpsc::channel();

        let job: Job = Box::new(move |worker| {
            let _ = result_sender.send(work(worker));
        });
        sender
            .send(job)
            .map_err(|_| ErrorInfo::backend("UIA worker thread stopped"))?;

        match result_receiver.recv_timeout(UIA_CALL_TIMEOUT) {
            Ok(result) => result,
            Err(RecvTimeoutError::Timeout) => Err(ErrorInfo::new(
                error_kind::TIMEOUT,
                "UIA call timed out; the outcome is unknown and it will not be retried",
            )),
            Err(RecvTimeoutError::Disconnected) => {
                Err(ErrorInfo::backend("UIA worker thread stopped"))
            }
        }
    }
}

impl Drop for UiaSession {
    fn drop(&mut self) {
        self.sender.take();

        if let Ok(mut guard) = self.worker.lock() {
            if let Some(worker) = guard.take() {
                if worker.is_finished() {
                    let _ = worker.join();
                }
            }
        }
    }
}

/// Last snapshot for one window, used to resolve element references.
#[derive(Debug, Clone)]
pub struct UiaSnapshotCache {
    session: Arc<UiaSession>,
    window: WindowInfo,
    elements: Vec<ElementRecord>,
    by_id: HashMap<u32, ElementRecord>,
    by_runtime_id: HashMap<String, ElementRecord>,
}

impl UiaSnapshotCache {
    /// Element records in visit order.
    pub fn elements(&self) -> &[ElementRecord] {
        &self.elements
    }

    /// Window this cache belongs to.
    pub fn window(&self) -> &WindowInfo {
        &self.window
    }

    /// Resolve a client reference by id, runtime id, or selectors.
    pub fn resolve_target(&self, target: &ElementRef) -> Result<ElementHandle, ErrorInfo> {
        if target.is_empty() {
            return Err(ErrorInfo::invalid("action requires a target element"));
        }

        if let Some(record) = target.id.and_then(|id| self.by_id.get(&id)) {
            return self.handle_for_record(record);
        }

        if let Some(record) = target
            .runtime_id
            .as_ref()
            .and_then(|runtime_id| self.by_runtime_id.get(runtime_id))
        {
            return self.handle_for_record(record);
        }

        if let Some(record) = self.match_selectors(target) {
            return self.handle_for_record(record);
        }

        Err(ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            "no element in the current snapshot matches the target reference",
        ))
    }

    /// Fetch an element by its snapshot runtime id and re-check its identity.
    pub fn element_for(&self, runtime_id: &str) -> Result<ElementHandle, ErrorInfo> {
        let record = self.by_runtime_id.get(runtime_id).cloned().ok_or_else(|| {
            ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                format!("no element with runtime id {runtime_id:?} in this snapshot"),
            )
        })?;

        self.handle_for_record(&record)
    }

    fn handle_for_record(&self, record: &ElementRecord) -> Result<ElementHandle, ErrorInfo> {
        if !enumerate::is_same_window(&self.window.handle, self.window.pid) {
            return Err(ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                "target window closed or its handle was reused",
            ));
        }

        let window_handle = self.window.handle.clone();
        let runtime_id = record.runtime_id.clone();
        let (RawElement(element), enabled) = self
            .session
            .run(move |worker| worker.fetch_element(&window_handle, &runtime_id))?;

        let mut record = record.clone();
        record.enabled = enabled;
        Ok(ElementHandle { element, record })
    }

    fn match_selectors(&self, target: &ElementRef) -> Option<&ElementRecord> {
        if target.automation_id.is_none() && target.name.is_none() {
            return None;
        }

        self.elements.iter().find(|record| {
            let automation_matches = target
                .automation_id
                .as_deref()
                .map_or(true, |automation_id| {
                    record.automation_id.as_deref() == Some(automation_id)
                });
            let name_matches = target
                .name
                .as_deref()
                .map_or(true, |name| record.name.as_deref() == Some(name));
            let role_matches = target
                .role
                .as_deref()
                .map_or(true, |role| record.control_type.eq_ignore_ascii_case(role));

            automation_matches && name_matches && role_matches
        })
    }

    fn new(session: Arc<UiaSession>, window: WindowInfo, elements: &[ElementRecord]) -> Self {
        let mut by_id = HashMap::with_capacity(elements.len());
        let mut by_runtime_id = HashMap::with_capacity(elements.len());
        for record in elements {
            by_id.insert(record.id, record.clone());
            by_runtime_id.insert(record.runtime_id.clone(), record.clone());
        }

        Self {
            session,
            window,
            elements: elements.to_vec(),
            by_id,
            by_runtime_id,
        }
    }
}

/// Verified element handle exposed to the action tasks.
#[derive(Debug)]
pub struct ElementHandle {
    element: IUIAutomationElement,
    record: ElementRecord,
}

impl ElementHandle {
    /// Record captured for this element, with `enabled` refreshed.
    pub fn record(&self) -> &ElementRecord {
        &self.record
    }

    /// Borrow the underlying element for subtree queries a pattern cannot answer.
    pub fn raw_element(&self) -> &IUIAutomationElement {
        &self.element
    }

    /// Stable runtime id inside the snapshot's window lifetime.
    pub fn runtime_id(&self) -> &str {
        &self.record.runtime_id
    }

    /// True when the element holds secret text; its value is never readable.
    pub fn is_password(&self) -> bool {
        self.record.sensitive
    }

    /// Read `IsEnabled` now. Actions must refuse when this returns false.
    pub fn is_enabled_fresh(&self) -> Result<bool, ErrorInfo> {
        enumerate::ensure_mta()?;
        match unsafe { self.element.CurrentIsEnabled() } {
            Ok(value) => Ok(value.as_bool()),
            Err(error) => Err(ErrorInfo::new(
                error_kind::STALE_TARGET,
                format!("IsEnabled read failed; the element is stale: {error}"),
            )),
        }
    }

    /// Invoke the element (buttons, menu items).
    pub fn invoke_pattern(&self) -> Result<IUIAutomationInvokePattern, ErrorInfo> {
        self.pattern("Invoke", element::PATTERN_PROBES[1].1)
    }

    /// Value pattern. Password elements are refused so their value never leaks.
    pub fn value_pattern(&self) -> Result<IUIAutomationValuePattern, ErrorInfo> {
        if self.record.sensitive {
            return Err(ErrorInfo::new(
                error_kind::INPUT_BLOCKED,
                "value access is blocked for password and otherwise sensitive elements",
            ));
        }

        self.pattern("Value", element::PATTERN_PROBES[0].1)
    }

    /// Toggle pattern for checkboxes and toggle buttons.
    pub fn toggle_pattern(&self) -> Result<IUIAutomationTogglePattern, ErrorInfo> {
        self.pattern("Toggle", element::PATTERN_PROBES[2].1)
    }

    /// Selection item pattern (`Select`, `AddToSelection`).
    pub fn selection_item_pattern(&self) -> Result<IUIAutomationSelectionItemPattern, ErrorInfo> {
        self.pattern("SelectionItem", element::PATTERN_PROBES[3].1)
    }

    /// Expand/collapse pattern.
    pub fn expand_collapse_pattern(&self) -> Result<IUIAutomationExpandCollapsePattern, ErrorInfo> {
        self.pattern("ExpandCollapse", element::PATTERN_PROBES[4].1)
    }

    /// Range value pattern for sliders and spinners.
    pub fn range_value_pattern(&self) -> Result<IUIAutomationRangeValuePattern, ErrorInfo> {
        self.pattern("RangeValue", element::PATTERN_PROBES[5].1)
    }

    /// Scroll pattern for scrollable containers.
    pub fn scroll_pattern(&self) -> Result<IUIAutomationScrollPattern, ErrorInfo> {
        self.pattern("Scroll", element::PATTERN_PROBES[6].1)
    }

    /// Scroll item pattern (`ScrollIntoView`) for virtualized lists and grids.
    pub fn scroll_item_pattern(&self) -> Result<IUIAutomationScrollItemPattern, ErrorInfo> {
        self.pattern("ScrollItem", element::PATTERN_PROBES[9].1)
    }

    /// Selection pattern for multi-select containers.
    pub fn selection_pattern(&self) -> Result<IUIAutomationSelectionPattern, ErrorInfo> {
        self.pattern("Selection", 10001)
    }

    /// Grid pattern for tabular data such as spreadsheets and data grids.
    pub fn grid_pattern(&self) -> Result<IUIAutomationGridPattern, ErrorInfo> {
        self.pattern("Grid", UIA_GridPatternId.0)
    }

    /// LegacyIAccessible pattern (`Select`, `DoDefaultAction`) as a fallback.
    pub fn select_pattern(&self) -> Result<IUIAutomationLegacyIAccessiblePattern, ErrorInfo> {
        self.pattern("LegacyIAccessible", element::PATTERN_PROBES[8].1)
    }

    fn pattern<T: Interface>(&self, name: &str, pattern_id: i32) -> Result<T, ErrorInfo> {
        enumerate::ensure_mta()?;
        match unsafe {
            self.element
                .GetCurrentPatternAs::<T>(UIA_PATTERN_ID(pattern_id))
        } {
            Ok(pattern) => Ok(pattern),
            Err(error) => Err(ErrorInfo::new(
                error_kind::UNSUPPORTED,
                format!("element does not support the {name} pattern: {error}"),
            )),
        }
    }
}

type Job = Box<dyn FnOnce(&mut UiaWorker) + Send>;

/// Raw element moved across threads after the worker verified its identity.
struct RawElement(IUIAutomationElement);

// UIA client objects are free-threaded proxies used from an MTA. Every caller
// initializes COM with `ensure_mta`, and the handle's first job re-checks the
// runtime id, so sharing the pointer is safe.
unsafe impl Send for RawElement {}

struct UiaWorker {
    automation: IUIAutomation,
    windows: HashMap<String, WindowCache>,
}

struct WindowCache {
    elements: HashMap<String, IUIAutomationElement>,
}

impl UiaWorker {
    fn take_snapshot(
        &mut self,
        window: &WindowInfo,
        max_depth: u32,
        max_elements: u32,
    ) -> Result<Snapshot, ErrorInfo> {
        let hwnd = parse_window_handle(window)?;
        let condition = unsafe { self.automation.CreateTrueCondition() }
            .map_err(|error| ErrorInfo::backend(format!("CreateTrueCondition failed: {error}")))?;
        let cache = create_cache_request(&self.automation, &condition)?;

        let root = unsafe { self.automation.ElementFromHandleBuildCache(hwnd, &cache) }.map_err(
            |error| {
                ErrorInfo::new(
                    error_kind::TARGET_NOT_FOUND,
                    format!(
                        "UI Automation could not attach to {:?}: {error}",
                        window.handle
                    ),
                )
            },
        )?;

        let walker = unsafe { self.automation.CreateTreeWalker(&condition) }.ok();
        let root_seed = seed_from_element(&root, Some(element::unstable_runtime_id(0)));
        let mut elements: HashMap<String, IUIAutomationElement> = HashMap::new();
        elements.insert(root_seed.runtime_id.clone(), root.clone());
        let mut known: HashSet<String> = HashSet::new();
        known.insert(root_seed.runtime_id.clone());

        let mut seeds = Vec::new();
        let found = unsafe { root.FindAllBuildCache(TreeScope_Descendants, &condition, &cache) };

        match found {
            Ok(array) => {
                let length = unsafe { array.Length() }.unwrap_or(0);
                for index in 0..length {
                    let Ok(element) = (unsafe { array.GetElement(index) }) else {
                        continue;
                    };
                    let fallback = Some(element::unstable_runtime_id((index + 1) as u32));
                    let mut seed = seed_from_element(&element, fallback);

                    if known.contains(&seed.runtime_id) {
                        continue;
                    }

                    seed.parent_runtime_id = resolve_parent(&walker, &element, &known);
                    known.insert(seed.runtime_id.clone());
                    elements.insert(seed.runtime_id.clone(), element);
                    seeds.push(seed);
                }
            }
            Err(_) => {
                if let Some(walker) = &walker {
                    collect_by_walker(
                        walker,
                        &cache,
                        &root,
                        &root_seed.runtime_id,
                        &mut seeds,
                        &mut elements,
                        0,
                    );
                }
            }
        }

        self.windows
            .insert(window.handle.clone(), WindowCache { elements });

        let built = element::build_snapshot(root_seed, seeds, max_depth, max_elements);
        let elements = built.nodes.into_iter().map(to_record).collect();

        Ok(Snapshot {
            window: window.clone(),
            elements,
            truncated: built.truncated,
            truncated_by: None,
            children_cut: 0,
            max_depth,
            max_elements,
            total_elements: built.total_elements,
        })
    }

    fn fetch_element(
        &mut self,
        window_handle: &str,
        runtime_id: &str,
    ) -> Result<(RawElement, bool), ErrorInfo> {
        let element = match self
            .windows
            .get(window_handle)
            .and_then(|window| window.elements.get(runtime_id))
        {
            Some(element) => element.clone(),
            None => {
                return Err(ErrorInfo::new(
                    error_kind::TARGET_NOT_FOUND,
                    format!("element {runtime_id:?} is not cached for this window"),
                ));
            }
        };

        if !element::is_unstable_runtime_id(runtime_id) {
            let current = runtime_id_of(&element).ok_or_else(|| {
                ErrorInfo::new(
                    error_kind::STALE_TARGET,
                    "element no longer reports a runtime id",
                )
            })?;

            if current != runtime_id {
                if let Some(window) = self.windows.get_mut(window_handle) {
                    window.elements.remove(runtime_id);
                }
                return Err(ErrorInfo::new(
                    error_kind::STALE_TARGET,
                    format!(
                        "element runtime id changed from {runtime_id:?} to {current:?}; target is stale"
                    ),
                ));
            }
        }

        let enabled = unsafe { element.CurrentIsEnabled() }
            .map(|value| value.as_bool())
            .map_err(|error| {
                ErrorInfo::new(
                    error_kind::STALE_TARGET,
                    format!("fresh IsEnabled read failed; target is stale: {error}"),
                )
            })?;

        Ok((RawElement(element), enabled))
    }
}

fn create_automation() -> Result<IUIAutomation, ErrorInfo> {
    let automation: IUIAutomation =
        unsafe { CoCreateInstance(&CUIAutomation, None::<&IUnknown>, CLSCTX_INPROC_SERVER) }
            .map_err(|error| {
                ErrorInfo::new(
                    error_kind::UNSUPPORTED,
                    format!("CoCreateInstance(CUIAutomation) failed: {error}"),
                )
            })?;

    let condition = unsafe { automation.CreateTrueCondition() }.map_err(|error| {
        ErrorInfo::new(
            error_kind::UNSUPPORTED,
            format!("CreateTrueCondition failed: {error}"),
        )
    })?;
    drop(condition);

    Ok(automation)
}

fn create_cache_request(
    automation: &IUIAutomation,
    condition: &IUIAutomationCondition,
) -> Result<IUIAutomationCacheRequest, ErrorInfo> {
    let cache = unsafe { automation.CreateCacheRequest() }
        .map_err(|error| ErrorInfo::backend(format!("CreateCacheRequest failed: {error}")))?;

    unsafe { cache.SetTreeFilter(condition) }
        .map_err(|error| ErrorInfo::backend(format!("cache SetTreeFilter failed: {error}")))?;
    unsafe { cache.SetTreeScope(TreeScope_Element) }
        .map_err(|error| ErrorInfo::backend(format!("cache SetTreeScope failed: {error}")))?;
    unsafe { cache.SetAutomationElementMode(AutomationElementMode_Full) }
        .map_err(|error| ErrorInfo::backend(format!("cache SetMode failed: {error}")))?;

    for property in [
        UIA_NamePropertyId,
        UIA_ControlTypePropertyId,
        UIA_AutomationIdPropertyId,
        UIA_ClassNamePropertyId,
        UIA_IsEnabledPropertyId,
        UIA_IsOffscreenPropertyId,
        UIA_BoundingRectanglePropertyId,
        UIA_IsPasswordPropertyId,
        UIA_RuntimeIdPropertyId,
    ] {
        unsafe { cache.AddProperty(property) }
            .map_err(|error| ErrorInfo::backend(format!("cache AddProperty failed: {error}")))?;
    }

    for (_, pattern_id) in element::PATTERN_PROBES {
        // Providers may decline to cache a pattern they do not support; probing
        // the cached pattern later reports the truth for each element.
        let _ = unsafe { cache.AddPattern(UIA_PATTERN_ID(pattern_id)) };
    }

    Ok(cache)
}

fn seed_from_element(
    element: &IUIAutomationElement,
    fallback_runtime_id: Option<String>,
) -> ElementSeed {
    let runtime_id = runtime_id_of(element)
        .or(fallback_runtime_id)
        .unwrap_or_else(|| element::unstable_runtime_id(0));
    let control_type_id = unsafe { element.CachedControlType() }
        .map(|value| value.0)
        .unwrap_or(0);
    let control_type = element::control_type_name(control_type_id).to_string();
    let is_password = unsafe { element.CachedIsPassword() }
        .map(|value| value.as_bool())
        .unwrap_or(false);
    let sensitive = is_password || control_type == element::PASSWORD_CONTROL_TYPE;

    let mut seed = ElementSeed::new(runtime_id, control_type.clone());
    seed.parent_runtime_id = None;
    seed.name = cached_text(element, |element| unsafe { element.CachedName() });
    seed.automation_id = cached_text(element, |element| unsafe { element.CachedAutomationId() });
    seed.class_name = cached_text(element, |element| unsafe { element.CachedClassName() });
    seed.enabled = unsafe { element.CachedIsEnabled() }
        .map(|value| value.as_bool())
        .unwrap_or(true);
    seed.offscreen = unsafe { element.CachedIsOffscreen() }
        .map(|value| value.as_bool())
        .unwrap_or(false);
    seed.bounds = unsafe { element.CachedBoundingRectangle() }
        .ok()
        .and_then(bounds_from_rect);
    seed.patterns = pattern_names(element);
    seed.scroll = read_scroll(element);
    seed.sensitive = sensitive;

    if sensitive {
        seed.value = None;
    } else {
        seed.value = read_value(element, &control_type);
    }

    seed
}

fn read_scroll(element: &IUIAutomationElement) -> Option<element::ElementScroll> {
    let pattern: IUIAutomationScrollPattern =
        unsafe { element.GetCachedPatternAs(UIA_ScrollPatternId) }
            .or_else(|_| unsafe { element.GetCurrentPatternAs(UIA_ScrollPatternId) })
            .ok()?;

    let horizontal = unsafe { pattern.CachedHorizontallyScrollable() }
        .or_else(|_| unsafe { pattern.CurrentHorizontallyScrollable() })
        .map(|value| value.as_bool())
        .unwrap_or(false);
    let vertical = unsafe { pattern.CachedVerticallyScrollable() }
        .or_else(|_| unsafe { pattern.CurrentVerticallyScrollable() })
        .map(|value| value.as_bool())
        .unwrap_or(false);

    if !horizontal && !vertical {
        return None;
    }

    Some(element::ElementScroll {
        horizontal_percent: unsafe { pattern.CachedHorizontalScrollPercent() }
            .or_else(|_| unsafe { pattern.CurrentHorizontalScrollPercent() })
            .ok()
            .and_then(scroll_percent),
        vertical_percent: unsafe { pattern.CachedVerticalScrollPercent() }
            .or_else(|_| unsafe { pattern.CurrentVerticalScrollPercent() })
            .ok()
            .and_then(scroll_percent),
        horizontal_view_percent: unsafe { pattern.CachedHorizontalViewSize() }
            .or_else(|_| unsafe { pattern.CurrentHorizontalViewSize() })
            .ok()
            .and_then(scroll_percent),
        vertical_view_percent: unsafe { pattern.CachedVerticalViewSize() }
            .or_else(|_| unsafe { pattern.CurrentVerticalViewSize() })
            .ok()
            .and_then(scroll_percent),
        horizontal,
        vertical,
    })
}

fn scroll_percent(value: f64) -> Option<f64> {
    (0.0..=100.0).contains(&value).then_some(value)
}

fn cached_text(
    element: &IUIAutomationElement,
    getter: impl FnOnce(&IUIAutomationElement) -> windows::core::Result<BSTR>,
) -> Option<String> {
    let value = getter(element).ok()?;
    let text = value.to_string();

    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

fn read_value(element: &IUIAutomationElement, control_type: &str) -> Option<String> {
    let direct = value_pattern_value(element);

    if direct.as_deref().map_or(true, str::is_empty) && matches!(control_type, "Edit" | "Text") {
        return text_pattern_text(element).or(direct);
    }

    direct
}

fn value_pattern_value(element: &IUIAutomationElement) -> Option<String> {
    let pattern: IUIAutomationValuePattern =
        unsafe { element.GetCachedPatternAs(UIA_ValuePatternId) }
            .or_else(|_| unsafe { element.GetCurrentPatternAs(UIA_ValuePatternId) })
            .ok()?;
    let value = unsafe { pattern.CachedValue() }
        .or_else(|_| unsafe { pattern.CurrentValue() })
        .ok()?;
    let text = value.to_string();

    Some(text)
}

fn text_pattern_text(element: &IUIAutomationElement) -> Option<String> {
    let pattern: IUIAutomationTextPattern =
        unsafe { element.GetCachedPatternAs(UIA_TextPatternId) }
            .or_else(|_| unsafe { element.GetCurrentPatternAs(UIA_TextPatternId) })
            .ok()?;
    let range = unsafe { pattern.DocumentRange() }.ok()?;
    let text = unsafe { range.GetText(TEXT_VALUE_LIMIT) }.ok()?.to_string();

    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

fn pattern_names(element: &IUIAutomationElement) -> Vec<String> {
    element::PATTERN_PROBES
        .iter()
        .filter(|(_, pattern_id)| {
            unsafe { element.GetCachedPattern(UIA_PATTERN_ID(*pattern_id)) }.is_ok()
        })
        .map(|(name, _)| (*name).to_string())
        .collect()
}

fn bounds_from_rect(rect: RECT) -> Option<ElementBounds> {
    let width = rect.right - rect.left;
    let height = rect.bottom - rect.top;

    if width <= 0 || height <= 0 {
        return None;
    }

    Some(ElementBounds {
        left: rect.left,
        top: rect.top,
        width,
        height,
    })
}

fn runtime_id_of(element: &IUIAutomationElement) -> Option<String> {
    let array = unsafe { element.GetRuntimeId() }.ok()?;

    if array.is_null() {
        return None;
    }

    let parts = unsafe { safe_array_i32(array) }.unwrap_or_default();
    let _ = unsafe { SafeArrayDestroy(array as *const _) };

    if parts.is_empty() {
        None
    } else {
        Some(element::format_runtime_id(&parts))
    }
}

unsafe fn safe_array_i32(array: *const windows::Win32::System::Com::SAFEARRAY) -> Option<Vec<i32>> {
    let lower = unsafe { SafeArrayGetLBound(array, 1) }.ok()?;
    let upper = unsafe { SafeArrayGetUBound(array, 1) }.ok()?;
    let count = upper - lower + 1;

    if count <= 0 {
        return Some(Vec::new());
    }

    let mut data: *mut c_void = ptr::null_mut();
    unsafe { SafeArrayAccessData(array, &mut data) }.ok()?;

    let values = unsafe { std::slice::from_raw_parts(data as *const i32, count as usize) }.to_vec();
    let _ = unsafe { SafeArrayUnaccessData(array) };

    Some(values)
}

fn resolve_parent(
    walker: &Option<IUIAutomationTreeWalker>,
    element: &IUIAutomationElement,
    known: &HashSet<String>,
) -> Option<String> {
    let walker = walker.as_ref()?;
    let mut current = unsafe { element.GetCachedParent() }
        .ok()
        .or_else(|| unsafe { walker.GetParentElement(element) }.ok());

    for _ in 0..8 {
        let parent = current?;

        if let Some(runtime_id) = runtime_id_of(&parent) {
            if known.contains(&runtime_id) {
                return Some(runtime_id);
            }
        }

        current = unsafe { walker.GetParentElement(&parent) }.ok();
    }

    None
}

fn collect_by_walker(
    walker: &IUIAutomationTreeWalker,
    cache: &IUIAutomationCacheRequest,
    parent: &IUIAutomationElement,
    parent_runtime_id: &str,
    seeds: &mut Vec<ElementSeed>,
    elements: &mut HashMap<String, IUIAutomationElement>,
    depth: u32,
) {
    if depth > MAX_WALK_DEPTH {
        return;
    }

    let mut child = unsafe { walker.GetFirstChildElementBuildCache(parent, cache) }.ok();
    while let Some(element) = child {
        child = unsafe { walker.GetNextSiblingElementBuildCache(&element, cache) }.ok();

        let fallback = Some(element::unstable_runtime_id(seeds.len() as u32 + 1));
        let mut seed = seed_from_element(&element, fallback);

        if elements.contains_key(&seed.runtime_id) {
            continue;
        }

        let runtime_id = seed.runtime_id.clone();
        seed.parent_runtime_id = Some(parent_runtime_id.to_string());
        elements.insert(runtime_id.clone(), element.clone());
        seeds.push(seed);

        collect_by_walker(
            walker,
            cache,
            &element,
            &runtime_id,
            seeds,
            elements,
            depth + 1,
        );
    }
}

fn parse_window_handle(window: &WindowInfo) -> Result<HWND, ErrorInfo> {
    let hwnd = enumerate::parse_handle(&window.handle).ok_or_else(|| {
        ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            format!("invalid window handle {:?}", window.handle),
        )
    })?;

    if !unsafe { IsWindow(Some(hwnd)) }.as_bool() {
        return Err(ErrorInfo::new(
            error_kind::TARGET_NOT_FOUND,
            "target window closed before the snapshot started",
        ));
    }

    Ok(hwnd)
}

fn to_record(node: element::ElementNode) -> ElementRecord {
    ElementRecord {
        id: node.id,
        parent: node.parent,
        depth: node.depth,
        runtime_id: node.runtime_id,
        control_type: node.control_type,
        name: node.name,
        automation_id: node.automation_id,
        class_name: node.class_name,
        value: node.value,
        enabled: node.enabled,
        offscreen: node.offscreen,
        bounds: node.bounds.map(|bounds| Bounds {
            left: bounds.left,
            top: bounds.top,
            width: bounds.width,
            height: bounds.height,
        }),
        patterns: node.patterns,
        sensitive: node.sensitive,
        path: None,
        scroll: node.scroll.map(|scroll| ScrollState {
            horizontal_percent: scroll.horizontal_percent,
            vertical_percent: scroll.vertical_percent,
            horizontal_view_percent: scroll.horizontal_view_percent,
            vertical_view_percent: scroll.vertical_view_percent,
            horizontal: scroll.horizontal,
            vertical: scroll.vertical,
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sensitive_element_records_never_carry_a_value() {
        let root = ElementSeed::new("1", "Window");
        let mut password = ElementSeed::new("2", "Edit");
        password.sensitive = true;
        password.value = Some("correct horse battery staple".to_string());

        let built = element::build_snapshot(root, vec![password], 10, 100);
        let records: Vec<ElementRecord> = built.nodes.into_iter().map(to_record).collect();

        assert!(records[1].sensitive);
        assert_eq!(records[1].value, None);
    }

    #[test]
    fn sensitive_seeds_clear_the_value_before_the_record() {
        let mut seed = ElementSeed::new("1", "Window");
        seed.sensitive = true;
        seed.value = Some("secret".to_string());

        let built = element::build_snapshot(seed, Vec::new(), 10, 100);
        let record = to_record(built.nodes.into_iter().next().unwrap());

        assert!(record.sensitive);
        assert_eq!(record.value, None);
    }
}
