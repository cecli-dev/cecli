//! Loopback HTTP server, token authentication, request queue, and lifecycle.
//!
//! The server speaks a deliberately small subset of HTTP/1.1 over
//! `std::net::TcpListener`: one thread per connection, `Connection: close`
//! responses, and a 1 MiB request body cap. Every request must carry
//! `X-Cecli-Token` and every JSON response is a [`Envelope`].
//!
//! Backend calls are serialized behind one mutex and bounded by a per-call
//! timeout. A timed-out action is reported as uncertain and never retried.

use std::collections::HashMap;
use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::observe::Observation;
use crate::protocol::{
    error_kind, ActionRequest, ActionResult, Bounds, BridgeFile, ElementRef, Envelope, ErrorInfo,
    FindRequest, Health, ScreenshotRequest, Snapshot, SnapshotRequest, WindowInfo,
};
use crate::{default_backend, state_for, Backend};

const STATE_PATH: &str = "/api/app/state";
const WINDOWS_PATH: &str = "/api/app/windows";
const DIALOGS_PATH: &str = "/api/app/dialogs";
const SNAPSHOT_PATH: &str = "/api/app/snapshot";
const ACTION_PATH: &str = "/api/app/action";
const FIND_PATH: &str = "/api/app/find";
const SCREENSHOT_PATH: &str = "/api/app/screenshot";
const DOCTOR_PATH: &str = "/api/app/doctor";
const SHUTDOWN_PATH: &str = "/api/app/shutdown";
const BATCH_PATH: &str = "/api/app/batch";
const HELP_PATH: &str = "/api/app/help";

/// Maximum accepted request body.
const MAX_BODY_BYTES: usize = 1024 * 1024;
/// Maximum accepted request head.
const MAX_HEAD_BYTES: usize = 64 * 1024;
/// Maximum operations in one batch request.
const MAX_BATCH_OPS: usize = 512;
/// Maximum response we are willing to buffer when acting as a client.
const MAX_RESPONSE_BYTES: usize = 8 * 1024 * 1024;
/// Default per-call backend timeout.
const DEFAULT_TIMEOUT_MS: u64 = 30_000;
/// Timeout used when probing an existing bridge.
const PING_TIMEOUT: Duration = Duration::from_millis(500);
/// How long `ensure_bridge` waits for a freshly spawned bridge.
const ENSURE_TIMEOUT: Duration = Duration::from_secs(10);
/// How long a captured frame is reused for identical screenshot requests.
const SCREENSHOT_CACHE_TTL: Duration = Duration::from_secs(1);
/// Response header carrying non-fatal notes for a binary payload.
const NOTES_HEADER: &str = "X-Cecli-Notes";
/// How long `stop` waits for the bridge process to exit.
const STOP_TIMEOUT: Duration = Duration::from_secs(5);

/// Handle to a running server.
///
/// The accept loop keeps running until the shared shutdown flag is set, either
/// by `/api/app/shutdown` or by the owner of the flag. [`ServerHandle::join`]
/// waits for the loop and removes `bridge.json` on a clean shutdown.
pub struct ServerHandle {
    /// Port the listener is bound to on `127.0.0.1`.
    pub port: u16,
    /// Path of the `bridge.json` written by this server.
    pub bridge_file: PathBuf,
    handle: Option<JoinHandle<()>>,
}

impl ServerHandle {
    /// Borrow the accept-loop thread handle.
    pub fn join_handle(&self) -> Option<&JoinHandle<()>> {
        self.handle.as_ref()
    }

    /// Wait for the accept loop and clean up the bridge file.
    pub fn join(mut self) {
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
        remove_bridge_file_if_owned(self.port);
    }
}

/// Bind a loopback server, publish `bridge.json`, and serve until `shutdown`.
pub fn serve(backend: Arc<dyn Backend>, shutdown: Arc<AtomicBool>) -> io::Result<ServerHandle> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    listener.set_nonblocking(true)?;

    let token = generate_token()?;
    let path = bridge_file_path();
    let bridge = new_bridge_file(port, token.clone());
    write_bridge_file_at(&path, &bridge)?;

    let state = Arc::new(ServerState {
        backend,
        token,
        queue: Arc::new(Mutex::new(())),
        observation: Mutex::new(Observation::default()),
        screenshot_cache: Mutex::new(ScreenshotCache::default()),
        timeout: backend_timeout(),
        shutdown: Arc::clone(&shutdown),
    });

    let loop_state = Arc::clone(&state);
    let handle = match thread::Builder::new()
        .name("ce-app-bridge-accept".to_string())
        .spawn(move || accept_loop(listener, loop_state))
    {
        Ok(handle) => handle,
        Err(error) => {
            remove_bridge_file_at(&path);
            return Err(error);
        }
    };

    Ok(ServerHandle {
        port,
        bridge_file: path,
        handle: Some(handle),
    })
}

/// Run the bridge in the foreground. Returns a process exit code.
pub fn run_foreground(foreground: bool) -> i32 {
    let log = |message: &str| {
        if foreground {
            eprintln!("{message}");
        }
    };

    if let Some(file) = reuse_or_clear() {
        log(&format!(
            "ce-app-bridge: reusing bridge on port {}",
            file.port
        ));
        return 0;
    }

    let shutdown = Arc::new(AtomicBool::new(false));
    match serve(default_backend(), shutdown) {
        Ok(handle) => {
            log(&format!(
                "ce-app-bridge: listening on http://127.0.0.1:{}",
                handle.port
            ));
            handle.join();
            log("ce-app-bridge: stopped");
            0
        }
        Err(error) => {
            eprintln!("ce-app-bridge: failed to start server: {error}");
            4
        }
    }
}

/// Reuse a healthy bridge or start one. Returns a process exit code.
pub fn ensure_bridge() -> i32 {
    if let Some(file) = reuse_or_clear() {
        println!(
            "{}",
            json!({"started": false, "port": file.port, "pid": file.pid})
        );
        return 0;
    }

    if let Err(error) = spawn_detached() {
        eprintln!("ce-app-bridge: failed to start bridge: {error}");
        return 4;
    }

    let deadline = Instant::now() + ENSURE_TIMEOUT;
    while Instant::now() < deadline {
        if let Some(file) = read_bridge_file() {
            if ping(&file, PING_TIMEOUT) {
                println!(
                    "{}",
                    json!({"started": true, "port": file.port, "pid": file.pid})
                );
                return 0;
            }
        }
        thread::sleep(Duration::from_millis(100));
    }

    eprintln!(
        "ce-app-bridge: bridge did not become healthy within {} s",
        ENSURE_TIMEOUT.as_secs()
    );
    4
}

/// Print bridge status as JSON. Returns a process exit code.
pub fn status() -> i32 {
    let Some(file) = read_bridge_file() else {
        println!("{}", json!({"bridge": Value::Null, "healthy": false}));
        return 4;
    };

    let healthy = ping(&file, PING_TIMEOUT);
    let live = if healthy {
        fetch_state(&file).ok()
    } else {
        None
    };

    println!(
        "{}",
        json!({"bridge": file, "healthy": healthy, "state": live})
    );

    if healthy {
        0
    } else {
        4
    }
}

/// Stop the running bridge. Returns a process exit code.
pub fn stop() -> i32 {
    let Some(file) = read_bridge_file() else {
        println!(
            "{}",
            json!({"stopped": false, "reason": "bridge.json not found"})
        );
        return 4;
    };

    let requested = http_request(&file, "POST", SHUTDOWN_PATH, Some(b"{}"), PING_TIMEOUT)
        .map(|response| response.status == 200)
        .unwrap_or(false);

    let deadline = Instant::now() + STOP_TIMEOUT;
    while Instant::now() < deadline {
        if !pid_alive(file.pid) {
            break;
        }
        thread::sleep(Duration::from_millis(50));
    }

    remove_bridge_file();

    let alive = pid_alive(file.pid);
    let stopped = requested || !alive;
    println!(
        "{}",
        json!({"stopped": stopped, "pid": file.pid, "requested": requested})
    );

    if stopped {
        0
    } else {
        4
    }
}

/// Path of `bridge.json`, honouring the `CECLI_BRIDGE_FILE` override.
pub fn bridge_file_path() -> PathBuf {
    if let Some(path) = std::env::var_os("CECLI_BRIDGE_FILE") {
        if !path.is_empty() {
            return PathBuf::from(path);
        }
    }
    default_bridge_file_path()
}

/// Read and decode `bridge.json`, or `None` when it is absent or corrupt.
pub fn read_bridge_file() -> Option<BridgeFile> {
    read_bridge_file_at(&bridge_file_path())
}

/// Write `bridge.json` atomically, creating the parent directory if needed.
pub fn write_bridge_file(file: &BridgeFile) -> io::Result<()> {
    write_bridge_file_at(&bridge_file_path(), file)
}

/// Remove `bridge.json`, ignoring a missing file.
pub fn remove_bridge_file() {
    remove_bridge_file_at(&bridge_file_path());
}

/// Ping `/api/app/state` on the file's endpoint within `timeout`.
pub fn ping(file: &BridgeFile, timeout: Duration) -> bool {
    match http_request(file, "GET", STATE_PATH, None, timeout) {
        Ok(response) if response.status == 200 => {
            serde_json::from_slice::<Envelope>(&response.body)
                .map(|envelope| envelope.ok && envelope.health != Health::Unavailable)
                .unwrap_or(false)
        }
        _ => false,
    }
}

struct ServerState {
    backend: Arc<dyn Backend>,
    token: String,
    queue: Arc<Mutex<()>>,
    observation: Mutex<Observation>,
    screenshot_cache: Mutex<ScreenshotCache>,
    timeout: Duration,
    shutdown: Arc<AtomicBool>,
}

enum CallResult<T> {
    Done(T),
    TimedOut,
    Failed(ErrorInfo),
}

impl ServerState {
    /// Run several requests in order against one connection.
    ///
    /// Each result is the same envelope a dedicated endpoint would return, so a
    /// client can submit a data-entry or analysis sequence in one round trip.
    fn batch_response(&self, body: &[u8]) -> Response {
        let request: BatchRequest = match decode_json(body) {
            Ok(request) => request,
            Err(message) => return bad_request("batch", message),
        };

        if request.operations.is_empty() {
            return bad_request("batch", "operations is empty".to_string());
        }

        if request.operations.len() > MAX_BATCH_OPS {
            return bad_request(
                "batch",
                format!("at most {MAX_BATCH_OPS} operations per batch"),
            );
        }

        let results: Vec<Value> = request
            .operations
            .into_iter()
            .map(|operation| {
                let op = operation
                    .get("op")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string();
                let mut payload = operation;
                if let Some(object) = payload.as_object_mut() {
                    object.remove("op");
                }
                let bytes = serde_json::to_vec(&payload).unwrap_or_default();

                let response = match op.as_str() {
                    "state" => self.state_response(),
                    "windows" => self.windows_response(),
                    "dialogs" => self.dialogs_response(),
                    "doctor" => self.doctor_response(),
                    "snapshot" => self.snapshot_response(&bytes),
                    "action" => self.action_response(&bytes),
                    "find" => self.find_response(&bytes),
                    "screenshot" => self.screenshot_response(&bytes),
                    other => Response::json(
                        200,
                        Envelope::fail(
                            "batch",
                            ErrorInfo::invalid(format!("unknown batch op '{other}'")),
                            Health::Degraded,
                        ),
                    ),
                };

                response.into_value()
            })
            .collect();

        Response::json(
            200,
            Envelope::ok("batch", json!({"results": results}), self.live_health()),
        )
    }

    fn state_response(&self) -> Response {
        let backend = Arc::clone(&self.backend);
        let call = self.call_serialized(move || Ok(state_for(backend.as_ref())));

        match call {
            CallResult::Done(state) => {
                let health = state.health;
                Response::json(200, Envelope::ok("state", json!(state), health))
            }
            CallResult::TimedOut => Response::json(
                200,
                Envelope::fail(
                    "state",
                    ErrorInfo::new(error_kind::TIMEOUT, "state probe timed out"),
                    Health::Degraded,
                ),
            ),
            CallResult::Failed(error) => {
                Response::json(200, Envelope::fail("state", error, Health::Degraded))
            }
        }
    }

    fn windows_response(&self) -> Response {
        let backend = Arc::clone(&self.backend);
        match self.call_serialized(move || backend.windows()) {
            CallResult::Done(windows) => Response::json(
                200,
                Envelope::ok("windows", json!(windows), self.live_health()),
            ),
            CallResult::TimedOut => Response::json(
                200,
                Envelope::fail(
                    "windows",
                    ErrorInfo::new(error_kind::TIMEOUT, "window enumeration timed out"),
                    Health::Degraded,
                ),
            ),
            CallResult::Failed(error) => {
                Response::json(200, Envelope::fail("windows", error, Health::Degraded))
            }
        }
    }

    fn dialogs_response(&self) -> Response {
        let backend = Arc::clone(&self.backend);
        match self.call_serialized(move || backend.windows()) {
            CallResult::Done(windows) => {
                let dialogs: Vec<WindowInfo> =
                    windows.into_iter().filter(|window| window.dialog).collect();
                Response::json(
                    200,
                    Envelope::ok("dialogs", json!({"dialogs": dialogs}), self.live_health()),
                )
            }
            CallResult::TimedOut => Response::json(
                200,
                Envelope::fail(
                    "dialogs",
                    ErrorInfo::new(error_kind::TIMEOUT, "dialog enumeration timed out"),
                    Health::Degraded,
                ),
            ),
            CallResult::Failed(error) => {
                Response::json(200, Envelope::fail("dialogs", error, Health::Degraded))
            }
        }
    }

    fn snapshot_response(&self, body: &[u8]) -> Response {
        let request: SnapshotRequest = match decode_json(body) {
            Ok(request) => request,
            Err(message) => return bad_request("snapshot", message),
        };

        let backend = Arc::clone(&self.backend);
        let call = self.call_serialized(move || backend.snapshot(&request));

        match call {
            CallResult::Done(mut snapshot) => {
                let notes = snapshot_notes(&snapshot);
                crate::observe::annotate_paths(&mut snapshot);
                lock_unpoisoned(&self.observation).record(snapshot.clone());
                Response::json(
                    200,
                    Envelope::ok_with_notes("snapshot", json!(snapshot), self.live_health(), notes),
                )
            }
            CallResult::TimedOut => Response::json(
                200,
                Envelope::fail(
                    "snapshot",
                    ErrorInfo::new(error_kind::TIMEOUT, "snapshot timed out"),
                    Health::Degraded,
                ),
            ),
            CallResult::Failed(error) => {
                Response::json(200, Envelope::fail("snapshot", error, Health::Degraded))
            }
        }
    }

    /// Evaluate a structured query while walking the accessibility tree.
    ///
    /// The backend stops at `limit`, so a large table is never materialized in
    /// full. Backends without streaming search return an `unsupported` error.
    fn find_response(&self, body: &[u8]) -> Response {
        let request: FindRequest = match decode_json(body) {
            Ok(request) => request,
            Err(message) => return bad_request("find", message),
        };

        let backend = Arc::clone(&self.backend);

        match self.call_serialized(move || backend.find(&request)) {
            CallResult::Done(result) => {
                Response::json(200, Envelope::ok("find", json!(result), self.live_health()))
            }
            CallResult::TimedOut => Response::json(
                200,
                Envelope::fail(
                    "find",
                    ErrorInfo::new(error_kind::TIMEOUT, "find timed out"),
                    Health::Degraded,
                ),
            ),
            CallResult::Failed(error) => {
                Response::json(200, Envelope::fail("find", error, Health::Degraded))
            }
        }
    }

    fn action_response(&self, body: &[u8]) -> Response {
        let mut request: ActionRequest = match decode_json(body) {
            Ok(request) => request,
            Err(message) => return bad_request("action", message),
        };
        let action = request.action.clone();

        if let Some(target) = request.target.clone() {
            if !target.is_empty() {
                match self.resolve_target(&target) {
                    Ok(Some(resolved)) => request.target = Some(resolved),
                    Ok(None) => {
                        if let Some(resolved) = self.refresh_and_resolve(&request.window, &target) {
                            request.target = Some(resolved);
                        }
                    }
                    Err(error) => {
                        // The cached snapshot may be truncated or older than the
                        // tree. Re-enumerate once so a miss does not poison later
                        // actions on unrelated elements.
                        if let Some(resolved) = self.refresh_and_resolve(&request.window, &target) {
                            request.target = Some(resolved);
                        } else {
                            return Response::json(
                                200,
                                Envelope::fail("action", error, self.live_health()),
                            );
                        }
                    }
                }
            }
        }

        let backend = Arc::clone(&self.backend);
        let call = self.call_serialized(move || backend.action(&request));

        match call {
            CallResult::Done(result) => Response::json(
                200,
                Envelope::ok("action", json!(result), self.live_health()),
            ),
            CallResult::TimedOut => {
                let result = ActionResult::uncertain(
                    action.clone(),
                    format!(
                        "no response within {} ms; observe before retrying",
                        self.timeout.as_millis()
                    ),
                );
                Response::json(
                    200,
                    Envelope::ok("action", json!(result), self.live_health()),
                )
            }
            CallResult::Failed(error) => {
                Response::json(200, Envelope::fail("action", error, Health::Degraded))
            }
        }
    }

    fn screenshot_response(&self, body: &[u8]) -> Response {
        let request: ScreenshotRequest = match decode_json(body) {
            Ok(request) => request,
            Err(message) => return bad_request("screenshot", message),
        };
        let key = self.screenshot_key(&request.window);

        if let Some((window, bounds)) = key.as_ref() {
            if let Some((bytes, burst)) =
                lock_unpoisoned(&self.screenshot_cache).cached(window, *bounds)
            {
                let note = format!("screenshot served from cache for '{window}' (burst {burst})");

                return Response::png_with_note(bytes, note);
            }
        }

        let backend = Arc::clone(&self.backend);
        match self.call_serialized(move || backend.screenshot(&request)) {
            CallResult::Done(bytes) => {
                if let Some((window, bounds)) = key {
                    lock_unpoisoned(&self.screenshot_cache).store(&window, bounds, bytes.clone());
                }

                Response::png(bytes)
            }
            CallResult::TimedOut => Response::json(
                200,
                Envelope::fail(
                    "screenshot",
                    ErrorInfo::new(error_kind::TIMEOUT, "screenshot timed out"),
                    Health::Degraded,
                ),
            ),
            CallResult::Failed(error) => {
                Response::json(200, Envelope::fail("screenshot", error, Health::Degraded))
            }
        }
    }

    /// Resolve the `(window, bounds)` key used by the screenshot cache.
    ///
    /// The key comes from the last observation so a request never pays for a
    /// fresh window enumeration; when no snapshot matches, the requested name
    /// pairs with default bounds.
    fn screenshot_key(&self, window: &str) -> Option<(String, Bounds)> {
        let requested = window.to_string();
        let observed = lock_unpoisoned(&self.observation)
            .snapshot
            .as_ref()
            .filter(|snapshot| window_matches_query(&snapshot.window, window))
            .map(|snapshot| (snapshot.window.handle.clone(), snapshot.window.bounds));

        Some(observed.unwrap_or_else(|| (requested, Bounds::default())))
    }
    fn help_response(&self) -> Response {
        let health = self.live_health();
        let backend = Arc::clone(&self.backend);
        let capabilities = backend.capabilities();
        let matrix = capability_matrix(backend.name(), backend.platform(), &capabilities);
        let doc = json!({
            "protocol_version": crate::protocol::BRIDGE_VERSION,
            "backend": backend.name(),
            "platform": backend.platform(),
            "capabilities": capabilities,
            "capabilities_matrix": matrix,
            "endpoints": {
                "state": "GET; backend identity, capabilities, health",
                "windows": "GET; handle, pid, process_name, title, bounds, foreground",
                "dialogs": "GET; top-level windows whose dialog flag is true",
                "snapshot": "POST {window, max_depth, max_elements, exclude_roles, actionable}; accessibility tree",
                "action": "POST {window, action, target, args}; target uses a selector below",
                "find": "POST {window, match, max_depth, max_elements, exclude_roles, limit}; stops at limit",
                "screenshot": "POST {window}; PNG bytes",
                "doctor": "GET; backend checks and permission notes",
                "batch": "POST {operations: [{op, ...}]}; runs them in order and keeps going",
                "help": "GET; this document",
            },
            "actions": {
                "invoke": "run an element's default action",
                "set_value": "write text (args.value); refused for sensitive elements",
                "get_value": "read text or number; refused for sensitive elements",
                "click": "element-relative click, or args.point {x, y} for a raw point",
                "double_click": "args.point plus args.button; args.count defaults to 2",
                "right_click": "args.point; args.button defaults to right",
                "hover": "move the pointer to args.point without pressing a button",
                "drag": "args.point to args.to_point with args.button and args.duration_ms",
                "select": "UIA SelectionItem.Select or the platform selection action",
                "scroll_into_view": "make the target element visible in its container",
                "focus": "give the element keyboard focus",
                "keys": "args.keys, e.g. ^s, {ENTER}, hello world",
                "scroll": "args.direction up|down|left|right, args.amount",
                "scroll_to": "args.horizontal_percent and/or args.vertical_percent, 0-100",
                "cell_at": "args.row and args.column; verified when the TableCell position matches",
                "activate": "raise and focus the window itself",
                "outcome": "result field: accessibility | pointer | keystroke | none; which delivery path actually fired",
            },
            "selectors": {
                "id": "index from the latest snapshot; stale after a new snapshot",
                "runtime_id": "platform id: HWND, AX identifier, AT-SPI path",
                "automation_id": "developer-assigned id; most repeatable",
                "name": "accessible name, optionally narrowed by role",
                "path": "role/name chain from the window root; survives runs",
            },
            "snapshot_fields": [
                "id", "parent", "depth", "runtime_id", "control_type", "name",
                "automation_id", "class_name", "value", "enabled", "offscreen",
                "bounds", "patterns", "sensitive", "path"
            ],
            "error_kinds": [
                "unauthorized", "invalid_request", "target_not_found", "stale_target",
                "input_blocked", "unsupported", "timeout", "backend_error", "not_found",
                "elevated_target", "capture_excluded", "no_permission",
                "bridge_unavailable", "version_mismatch"
            ],
            "notes": [
                "actions resolve against the latest snapshot; re-snapshot after the tree changes",
                "exclude_roles prunes whole subtrees, e.g. [\"Menu\", \"Menu Item\", \"Separator\"]",
                "sensitive elements never return or accept a value",
                "delivered means input was sent; verified means a read-back confirmed it",
                "outcome names the delivery path that actually fired; snapshot and screenshot notes report non-fatal degradation",
                "dialogs lists top-level windows with dialog == true; act on a dialog button by selector or point"
            ]
        });

        Response::json(200, Envelope::ok("help", doc, health))
    }

    fn doctor_response(&self) -> Response {
        let backend = Arc::clone(&self.backend);
        match self.call_serialized(move || Ok(backend.doctor())) {
            CallResult::Done(report) => Response::json(
                200,
                Envelope::ok("doctor", json!(report), self.live_health()),
            ),
            CallResult::TimedOut => Response::json(
                200,
                Envelope::fail(
                    "doctor",
                    ErrorInfo::new(error_kind::TIMEOUT, "doctor diagnostics timed out"),
                    Health::Degraded,
                ),
            ),
            CallResult::Failed(error) => {
                Response::json(200, Envelope::fail("doctor", error, Health::Degraded))
            }
        }
    }

    fn shutdown_response(&self) -> Response {
        let health = self.live_health();
        lock_unpoisoned(&self.observation).clear();
        self.shutdown.store(true, Ordering::SeqCst);

        Response::json(
            200,
            Envelope::ok("shutdown", json!({"stopping": true}), health),
        )
    }

    fn call_serialized<T, F>(&self, work: F) -> CallResult<T>
    where
        T: Send + 'static,
        F: FnOnce() -> Result<T, ErrorInfo> + Send + 'static,
    {
        let queue = Arc::clone(&self.queue);
        let (sender, receiver) = mpsc::channel();

        let spawned = thread::Builder::new()
            .name("ce-app-bridge-call".to_string())
            .spawn(move || {
                let _guard = lock_unpoisoned(&queue);
                let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(work));
                let result = match outcome {
                    Ok(result) => result,
                    Err(payload) => Err(ErrorInfo::backend(format!(
                        "backend panicked: {}",
                        panic_message(payload.as_ref())
                    ))),
                };
                let _ = sender.send(result);
            });

        if spawned.is_err() {
            return CallResult::Failed(ErrorInfo::backend("failed to spawn backend worker"));
        }

        match receiver.recv_timeout(self.timeout) {
            Ok(Ok(value)) => CallResult::Done(value),
            Ok(Err(error)) => CallResult::Failed(error),
            Err(RecvTimeoutError::Timeout) => CallResult::TimedOut,
            Err(RecvTimeoutError::Disconnected) => {
                CallResult::Failed(ErrorInfo::backend("backend worker vanished"))
            }
        }
    }

    fn live_health(&self) -> Health {
        let backend = Arc::clone(&self.backend);
        match self.call_serialized(move || Ok(backend.health())) {
            CallResult::Done(health) => health,
            _ => Health::Unavailable,
        }
    }

    /// Re-snapshot the window and resolve the target again.
    fn refresh_and_resolve(&self, window: &str, target: &ElementRef) -> Option<ElementRef> {
        let backend = Arc::clone(&self.backend);
        let request = SnapshotRequest {
            window: window.to_string(),
            max_depth: None,
            max_elements: None,
            exclude_roles: Vec::new(),
            actionable: false,
        };
        let call = self.call_serialized(move || backend.snapshot(&request));

        match call {
            CallResult::Done(snapshot) => {
                lock_unpoisoned(&self.observation).record(snapshot);
                self.resolve_target(target).ok().flatten()
            }
            _ => None,
        }
    }

    fn resolve_target(&self, target: &ElementRef) -> Result<Option<ElementRef>, ErrorInfo> {
        let observation = lock_unpoisoned(&self.observation);
        if observation.is_empty() {
            return Ok(None);
        }

        observation.resolve(target).map(Some)
    }
}

enum Response {
    Json {
        status: u16,
        envelope: Envelope,
        headers: Vec<(String, String)>,
    },
    Png {
        bytes: Vec<u8>,
        headers: Vec<(String, String)>,
    },
}

impl Response {
    fn json(status: u16, envelope: Envelope) -> Self {
        Self::Json {
            status,
            envelope,
            headers: Vec::new(),
        }
    }

    fn png(bytes: Vec<u8>) -> Self {
        Self::Png {
            bytes,
            headers: Vec::new(),
        }
    }

    fn png_with_note(bytes: Vec<u8>, note: String) -> Self {
        Self::Png {
            bytes,
            headers: vec![(NOTES_HEADER.to_string(), note)],
        }
    }

    /// Collapse the response into a JSON value for batch results.
    fn into_value(self) -> Value {
        match self {
            Self::Json {
                status, envelope, ..
            } => {
                let mut value =
                    serde_json::to_value(envelope).unwrap_or_else(|_| json!({"ok": false}));

                if let Some(object) = value.as_object_mut() {
                    object.insert("status".to_string(), json!(status));
                }

                value
            }
            Self::Png { bytes, headers } => {
                let notes: Vec<String> = headers
                    .iter()
                    .filter(|(name, _)| name == NOTES_HEADER)
                    .flat_map(|(_, value)| value.split('\n'))
                    .map(|note| note.trim().to_string())
                    .filter(|note| !note.is_empty())
                    .collect();

                json!({
                    "ok": true,
                    "action": "screenshot",
                    "data": {"format": "png", "bytes": bytes.len()},
                    "error": null,
                    "notes": notes,
                })
            }
        }
    }

    fn json_with_header(status: u16, envelope: Envelope, name: &str, value: &str) -> Self {
        Self::Json {
            status,
            envelope,
            headers: vec![(name.to_string(), value.to_string())],
        }
    }
}

#[derive(serde::Deserialize)]
struct BatchRequest {
    operations: Vec<Value>,
}

struct Request {
    method: String,
    path: String,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
}

impl Request {
    fn header(&self, name: &str) -> Option<&str> {
        self.headers
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value.as_str())
    }
}

struct RequestError {
    status: u16,
    message: String,
}

impl RequestError {
    fn bad(message: String) -> Self {
        Self {
            status: 400,
            message,
        }
    }

    fn too_large(message: String) -> Self {
        Self {
            status: 413,
            message,
        }
    }
}

fn accept_loop(listener: TcpListener, state: Arc<ServerState>) {
    while !state.shutdown.load(Ordering::SeqCst) {
        match listener.accept() {
            Ok((stream, _peer)) => {
                // Windows inherits the listener's non-blocking mode on accept, which
                // turns body reads into `WouldBlock`; request threads must block.
                let _ = stream.set_nonblocking(false);
                let connection_state = Arc::clone(&state);
                let _ = thread::Builder::new()
                    .name("ce-app-bridge-conn".to_string())
                    .spawn(move || handle_connection(stream, connection_state));
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(10));
            }
            Err(_) => thread::sleep(Duration::from_millis(25)),
        }
    }
}

fn handle_connection(mut stream: TcpStream, state: Arc<ServerState>) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(30)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(30)));

    let request = match read_request(&mut stream) {
        Ok(request) => request,
        Err(error) => {
            let envelope = Envelope::fail(
                "request",
                ErrorInfo::invalid(error.message),
                Health::Degraded,
            );
            let _ = write_json(&mut stream, error.status, &envelope, &[]);
            return;
        }
    };

    let action = action_for_path(&request.path);
    let provided = request.header("x-cecli-token").unwrap_or("");
    if !constant_time_eq(&state.token, provided) {
        let envelope = Envelope::fail(
            action,
            ErrorInfo::new(error_kind::UNAUTHORIZED, "missing or invalid X-Cecli-Token"),
            Health::Degraded,
        );
        let _ = write_json(&mut stream, 401, &envelope, &[]);
        return;
    }
    let response = match (request.method.as_str(), request.path.as_str()) {
        ("GET", STATE_PATH) => state.state_response(),
        ("GET", WINDOWS_PATH) => state.windows_response(),
        ("GET", DIALOGS_PATH) => state.dialogs_response(),
        ("POST", SNAPSHOT_PATH) => state.snapshot_response(&request.body),
        ("POST", ACTION_PATH) => state.action_response(&request.body),
        ("POST", FIND_PATH) => state.find_response(&request.body),
        ("POST", SCREENSHOT_PATH) => state.screenshot_response(&request.body),
        ("GET", DOCTOR_PATH) => state.doctor_response(),
        ("GET", HELP_PATH) => state.help_response(),
        ("POST", SHUTDOWN_PATH) => state.shutdown_response(),
        ("POST", BATCH_PATH) => state.batch_response(&request.body),
        (method, path) => match allowed_method(path) {
            Some(allow) => {
                let envelope = Envelope::fail(
                    action,
                    ErrorInfo::invalid(format!("method {method} not allowed; use {allow}")),
                    Health::Degraded,
                );
                Response::json_with_header(405, envelope, "Allow", allow)
            }
            None => {
                let envelope = Envelope::fail(
                    action,
                    ErrorInfo::new(error_kind::NOT_FOUND, format!("no route for {path}")),
                    Health::Degraded,
                );
                Response::json(404, envelope)
            }
        },
    };

    match response {
        Response::Json {
            status,
            envelope,
            headers,
        } => {
            let _ = write_json(&mut stream, status, &envelope, &headers);
        }
        Response::Png { bytes, headers } => {
            let _ = write_response(&mut stream, 200, "image/png", &bytes, &headers);
        }
    }
}

fn read_request(stream: &mut TcpStream) -> Result<Request, RequestError> {
    let mut buffer = Vec::with_capacity(4096);
    let mut chunk = [0u8; 4096];
    let head_end = loop {
        let read = stream
            .read(&mut chunk)
            .map_err(|error| RequestError::bad(format!("read failed: {error}")))?;
        if read == 0 {
            return Err(RequestError::bad(
                "connection closed before request head".to_string(),
            ));
        }
        buffer.extend_from_slice(&chunk[..read]);
        if let Some(position) = find_head_end(&buffer) {
            break position;
        }
        if buffer.len() > MAX_HEAD_BYTES {
            return Err(RequestError::bad("request head exceeds 64 KiB".to_string()));
        }
    };

    let head = std::str::from_utf8(&buffer[..head_end - 4])
        .map_err(|_| RequestError::bad("request head is not valid UTF-8".to_string()))?;
    let mut lines = head.split("\r\n");
    let request_line = lines.next().unwrap_or("");
    let mut parts = request_line.split_whitespace();
    let method = parts
        .next()
        .ok_or_else(|| RequestError::bad("missing method".to_string()))?
        .to_string();
    let target = parts
        .next()
        .ok_or_else(|| RequestError::bad("missing request path".to_string()))?;
    let path = target
        .split(['?', '#'])
        .next()
        .unwrap_or(target)
        .to_string();
    let mut headers = Vec::new();
    let mut content_length = 0usize;
    for line in lines {
        if line.is_empty() {
            continue;
        }
        let (name, value) = line
            .split_once(':')
            .ok_or_else(|| RequestError::bad(format!("malformed header: {line}")))?;
        let name = name.trim().to_ascii_lowercase();
        let value = value.trim().to_string();
        if name == "content-length" {
            content_length = value
                .parse::<usize>()
                .map_err(|_| RequestError::bad("invalid Content-Length".to_string()))?;
        }
        headers.push((name, value));
    }

    if content_length > MAX_BODY_BYTES {
        return Err(RequestError::too_large(format!(
            "request body exceeds {MAX_BODY_BYTES} bytes"
        )));
    }

    let mut body = buffer[head_end..].to_vec();
    while body.len() < content_length {
        let read = stream
            .read(&mut chunk)
            .map_err(|error| RequestError::bad(format!("read failed: {error}")))?;
        if read == 0 {
            break;
        }
        body.extend_from_slice(&chunk[..read]);
    }

    if body.len() < content_length {
        return Err(RequestError::bad(
            "request body shorter than Content-Length".to_string(),
        ));
    }
    body.truncate(content_length);

    Ok(Request {
        method,
        path,
        headers,
        body,
    })
}

fn find_head_end(buffer: &[u8]) -> Option<usize> {
    buffer
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|position| position + 4)
}

fn write_json(
    stream: &mut TcpStream,
    status: u16,
    envelope: &Envelope,
    headers: &[(String, String)],
) -> io::Result<()> {
    let body = envelope.to_json();
    write_response(
        stream,
        status,
        "application/json; charset=utf-8",
        body.as_bytes(),
        headers,
    )
}

fn write_response(
    stream: &mut TcpStream,
    status: u16,
    content_type: &str,
    body: &[u8],
    headers: &[(String, String)],
) -> io::Result<()> {
    let mut head = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\nCache-Control: no-store\r\n",
        status,
        reason_phrase(status),
        content_type,
        body.len()
    );

    for (name, value) in headers {
        head.push_str(name);
        head.push_str(": ");
        head.push_str(value);
        head.push_str("\r\n");
    }
    head.push_str("\r\n");

    stream.write_all(head.as_bytes())?;
    stream.write_all(body)?;
    stream.flush()?;
    let _ = stream.shutdown(std::net::Shutdown::Write);

    Ok(())
}

fn reason_phrase(status: u16) -> &'static str {
    match status {
        200 => "OK",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        405 => "Method Not Allowed",
        413 => "Payload Too Large",
        _ => "Internal Server Error",
    }
}

fn action_for_path(path: &str) -> &'static str {
    match path {
        STATE_PATH => "state",
        WINDOWS_PATH => "windows",
        DIALOGS_PATH => "dialogs",
        SNAPSHOT_PATH => "snapshot",
        ACTION_PATH => "action",
        FIND_PATH => "find",
        SCREENSHOT_PATH => "screenshot",
        DOCTOR_PATH => "doctor",
        SHUTDOWN_PATH => "shutdown",
        HELP_PATH => "help",
        _ => "unknown",
    }
}

fn allowed_method(path: &str) -> Option<&'static str> {
    match path {
        STATE_PATH | WINDOWS_PATH | DIALOGS_PATH | DOCTOR_PATH | HELP_PATH => Some("GET"),
        SNAPSHOT_PATH | ACTION_PATH | SCREENSHOT_PATH | SHUTDOWN_PATH => Some("POST"),
        FIND_PATH => Some("POST"),
        _ => None,
    }
}

fn bad_request(action: &str, message: String) -> Response {
    Response::json(
        400,
        Envelope::fail(action, ErrorInfo::invalid(message), Health::Degraded),
    )
}

fn decode_json<T>(body: &[u8]) -> Result<T, String>
where
    T: serde::de::DeserializeOwned,
{
    if body.is_empty() {
        return Err("request body is empty".to_string());
    }
    serde_json::from_slice(body).map_err(|error| format!("invalid JSON body: {error}"))
}

fn lock_unpoisoned<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn panic_message(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(message) = payload.downcast_ref::<&str>() {
        (*message).to_string()
    } else if let Some(message) = payload.downcast_ref::<String>() {
        message.clone()
    } else {
        "unknown panic".to_string()
    }
}

fn backend_timeout() -> Duration {
    let millis = std::env::var("CECLI_APP_TIMEOUT_MS")
        .ok()
        .and_then(|value| value.trim().parse::<u64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(DEFAULT_TIMEOUT_MS);
    Duration::from_millis(millis)
}

fn generate_token() -> io::Result<String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes)
        .map_err(|error| io::Error::other(format!("could not generate bridge token: {error}")))?;
    Ok(hex::encode(bytes))
}

fn constant_time_eq(expected: &str, provided: &str) -> bool {
    let expected = expected.as_bytes();
    let provided = provided.as_bytes();
    if expected.len() != provided.len() {
        return false;
    }

    let mut difference = 0u8;
    for index in 0..expected.len() {
        difference |= expected[index] ^ provided[index];
    }

    difference == 0
}

fn new_bridge_file(port: u16, token: String) -> BridgeFile {
    BridgeFile {
        version: crate::protocol::BRIDGE_VERSION.to_string(),
        platform: std::env::consts::OS.to_string(),
        host: "127.0.0.1".to_string(),
        port,
        token,
        pid: std::process::id(),
        mode: "bridge".to_string(),
        started_at: rfc3339_now(),
    }
}

fn reuse_or_clear() -> Option<BridgeFile> {
    let file = read_bridge_file()?;
    if ping(&file, PING_TIMEOUT) {
        Some(file)
    } else {
        remove_bridge_file();
        None
    }
}

fn default_bridge_file_path() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        if let Some(local) = std::env::var_os("LOCALAPPDATA") {
            if !local.is_empty() {
                return PathBuf::from(local).join("cecli").join("bridge.json");
            }
        }
    }

    #[cfg(target_os = "macos")]
    {
        if let Some(home) = std::env::var_os("HOME") {
            if !home.is_empty() {
                return PathBuf::from(home)
                    .join("Library")
                    .join("Application Support")
                    .join("cecli")
                    .join("bridge.json");
            }
        }
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        if let Some(runtime) = std::env::var_os("XDG_RUNTIME_DIR") {
            if !runtime.is_empty() {
                return PathBuf::from(runtime).join("cecli").join("bridge.json");
            }
        }
        if let Some(home) = std::env::var_os("HOME") {
            if !home.is_empty() {
                return PathBuf::from(home)
                    .join(".cache")
                    .join("cecli")
                    .join("bridge.json");
            }
        }
    }

    std::env::temp_dir().join("cecli").join("bridge.json")
}

fn read_bridge_file_at(path: &Path) -> Option<BridgeFile> {
    let raw = std::fs::read(path).ok()?;
    serde_json::from_slice(&raw).ok()
}

fn write_bridge_file_at(path: &Path, file: &BridgeFile) -> io::Result<()> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    #[cfg(unix)]
    let existed = parent.exists();
    std::fs::create_dir_all(parent)?;

    #[cfg(unix)]
    if !existed {
        set_permissions(parent, 0o700)?;
    }

    let mut encoded = serde_json::to_vec(file)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    encoded.push(b'\n');

    let temp = temp_sibling(path);
    {
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create(true).truncate(true);

        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }

        let mut handle = options.open(&temp)?;
        handle.write_all(&encoded)?;
        handle.sync_all()?;
    }

    #[cfg(unix)]
    set_permissions(&temp, 0o600)?;

    match std::fs::rename(&temp, path) {
        Ok(()) => Ok(()),
        Err(error) => {
            let _ = std::fs::remove_file(&temp);
            Err(error)
        }
    }
}

fn remove_bridge_file_at(path: &Path) {
    let _ = std::fs::remove_file(path);
}

fn remove_bridge_file_if_owned(port: u16) {
    if let Some(file) = read_bridge_file() {
        if file.port == port {
            remove_bridge_file();
        }
    }
}

fn temp_sibling(path: &Path) -> PathBuf {
    static COUNTER: AtomicU64 = AtomicU64::new(0);

    let sequence = COUNTER.fetch_add(1, Ordering::Relaxed);
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("bridge.json");

    path.with_file_name(format!(".{name}.{}.{}.tmp", std::process::id(), sequence))
}

#[cfg(unix)]
fn set_permissions(path: &Path, mode: u32) -> io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))
}

fn rfc3339_now() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    format_rfc3339(seconds)
}

fn format_rfc3339(seconds: u64) -> String {
    let days = (seconds / 86_400) as i64;
    let remainder = seconds % 86_400;
    let (hour, minute, second) = (remainder / 3_600, (remainder % 3_600) / 60, remainder % 60);
    let (year, month, day) = civil_from_days(days);

    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let shifted = days + 719_468;
    let era = if shifted >= 0 {
        shifted
    } else {
        shifted - 146_096
    } / 146_097;
    let day_of_era = shifted - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_position = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * month_position + 2) / 5 + 1) as u32;
    let month = if month_position < 10 {
        month_position + 3
    } else {
        month_position - 9
    } as u32;

    (if month <= 2 { year + 1 } else { year }, month, day)
}

struct HttpResponse {
    status: u16,
    body: Vec<u8>,
}

fn fetch_state(file: &BridgeFile) -> io::Result<Value> {
    let response = http_request(file, "GET", STATE_PATH, None, PING_TIMEOUT)?;

    if response.status != 200 {
        return Err(io::Error::other(format!(
            "state endpoint returned {}",
            response.status
        )));
    }

    let envelope: Envelope = serde_json::from_slice(&response.body)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;

    serde_json::to_value(envelope)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
}

fn http_request(
    file: &BridgeFile,
    method: &str,
    path: &str,
    body: Option<&[u8]>,
    timeout: Duration,
) -> io::Result<HttpResponse> {
    let address: SocketAddr = format!("{}:{}", file.host, file.port)
        .parse()
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, format!("{error}")))?;
    let mut stream = TcpStream::connect_timeout(&address, timeout)?;
    stream.set_read_timeout(Some(timeout))?;
    stream.set_write_timeout(Some(timeout))?;

    let mut request = format!(
        "{method} {path} HTTP/1.1\r\nHost: {}\r\nX-Cecli-Token: {}\r\nConnection: close\r\n",
        file.host, file.token
    );
    if let Some(body) = body {
        request.push_str(&format!(
            "Content-Type: application/json\r\nContent-Length: {}\r\n",
            body.len()
        ));
    }
    request.push_str("\r\n");

    stream.write_all(request.as_bytes())?;
    if let Some(body) = body {
        stream.write_all(body)?;
    }
    stream.flush()?;

    let mut raw = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(read) => {
                raw.extend_from_slice(&chunk[..read]);
                if raw.len() > MAX_RESPONSE_BYTES {
                    break;
                }
            }
            Err(error)
                if error.kind() == io::ErrorKind::WouldBlock
                    || error.kind() == io::ErrorKind::TimedOut =>
            {
                break;
            }
            Err(error) => return Err(error),
        }
    }

    parse_response(&raw)
}

fn parse_response(raw: &[u8]) -> io::Result<HttpResponse> {
    let head_end = find_head_end(raw)
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "malformed HTTP response"))?;
    let head = std::str::from_utf8(&raw[..head_end - 4])
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    let mut lines = head.split("\r\n");
    let status = lines
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|value| value.parse::<u16>().ok())
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "missing HTTP status"))?;

    Ok(HttpResponse {
        status,
        body: raw[head_end..].to_vec(),
    })
}

fn pid_alive(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }

    #[cfg(target_os = "linux")]
    {
        Path::new("/proc").join(pid.to_string()).exists()
    }

    #[cfg(target_os = "windows")]
    {
        use windows::Win32::Foundation::CloseHandle;
        use windows::Win32::System::Threading::{
            GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
        };

        const STILL_ACTIVE: u32 = 259;

        unsafe {
            let handle = match OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
                Ok(handle) => handle,
                Err(_) => return false,
            };
            let mut code = 0u32;
            let queried = GetExitCodeProcess(handle, &mut code).is_ok();
            let _ = CloseHandle(handle);

            queried && code == STILL_ACTIVE
        }
    }

    #[cfg(all(unix, not(target_os = "linux")))]
    {
        std::process::Command::new("kill")
            .arg("-0")
            .arg(pid.to_string())
            .status()
            .map(|status| status.success())
            .unwrap_or(false)
    }

    #[cfg(not(any(unix, target_os = "windows")))]
    {
        false
    }
}

fn spawn_detached() -> io::Result<()> {
    let exe = std::env::current_exe()?;

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;

        const DETACHED_PROCESS: u32 = 0x0000_0008;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;

        std::process::Command::new(exe)
            .arg("--app-harness")
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .creation_flags(DETACHED_PROCESS | CREATE_NO_WINDOW)
            .spawn()?;

        Ok(())
    }

    #[cfg(unix)]
    {
        match std::process::Command::new("setsid")
            .arg(&exe)
            .arg("--app-harness")
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
        {
            Ok(_) => Ok(()),
            Err(_) => {
                std::process::Command::new(&exe)
                    .arg("--app-harness")
                    .stdin(std::process::Stdio::null())
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .spawn()?;
                Ok(())
            }
        }
    }

    #[cfg(not(any(unix, target_os = "windows")))]
    {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "detached spawn is not supported on this platform",
        ))
    }
}

/// Feature support matrix reported by `/api/app/help`.
///
/// Statuses are derived from the declared backend capabilities plus platform
/// specifics, so clients can branch without parsing help prose.
fn capability_matrix(backend_name: &str, platform: &str, capabilities: &[String]) -> Value {
    let has = |feature: &str| capabilities.iter().any(|value| value == feature);
    let action = has("action");
    let linux = backend_name == "linux-atspi" || platform == "linux";
    let xtest = has("xtest");

    let cell_at = if has("cell_at") {
        matrix_entry("supported", "native grid row and column lookup")
    } else if backend_name == "linux-atspi" {
        matrix_entry(
            "partial",
            "AT-SPI Collection lookup with a bounded table enumeration fallback",
        )
    } else {
        matrix_entry(
            "unsupported",
            "the backend has no grid addressing; target a cell by name, e.g. 'B2'",
        )
    };

    let screenshot = if has("screenshot") {
        matrix_entry("supported", "the backend returns PNG bytes")
    } else if linux {
        matrix_entry("partial", "X11 capture plane when a display is available")
    } else {
        matrix_entry("unsupported", "the backend has no pixel capture path")
    };

    let keys = if xtest {
        matrix_entry(
            "supported",
            "XTEST synthetic keystrokes reach the focused window",
        )
    } else if linux {
        matrix_entry(
            "unsupported",
            "raw input needs an X11 display for the XTEST driver",
        )
    } else if action {
        matrix_entry("supported", "synthetic keystrokes reach the target window")
    } else {
        matrix_entry("unsupported", "the backend cannot inject input")
    };

    let scroll = if xtest {
        matrix_entry(
            "supported",
            "XTEST wheel events scroll at the pointer position",
        )
    } else if linux {
        matrix_entry(
            "unsupported",
            "raw input needs an X11 display for the XTEST driver",
        )
    } else if action {
        matrix_entry(
            "supported",
            "wheel or scroll commands reach the target window",
        )
    } else {
        matrix_entry("unsupported", "the backend cannot inject input")
    };

    let scroll_to = if backend_name == "linux-atspi" {
        matrix_entry(
            "partial",
            "AT-SPI scrollbar Value where the toolkit exposes one",
        )
    } else if action {
        matrix_entry(
            "supported",
            "platform scroll pattern or scrollbar value with a read-back check",
        )
    } else {
        matrix_entry("unsupported", "the backend has no absolute scroll path")
    };

    let activate = if xtest {
        matrix_entry(
            "supported",
            "raises the X11 window and asks the window manager to focus it",
        )
    } else if linux {
        matrix_entry("unsupported", "raising a window needs an X11 display")
    } else if action {
        matrix_entry("supported", "raise and focus the target window")
    } else {
        matrix_entry("unsupported", "the backend cannot run window actions")
    };

    json!({
        "windows": matrix_entry(
            if has("windows") { "supported" } else { "unsupported" },
            "top-level window enumeration",
        ),
        "dialogs": matrix_entry(
            if has("dialogs") {
                "supported"
            } else {
                "unsupported"
            },
            "top-level windows flagged as dialogs or owned popups",
        ),
        "snapshot": matrix_entry(
            if has("snapshot") { "supported" } else { "unsupported" },
            "accessibility tree walk with budgets and optional actionable pruning",
        ),
        "find": matrix_entry(
            if has("find") { "supported" } else { "unsupported" },
            "streaming structured search during the tree walk",
        ),
        "cell_at": cell_at,
        "screenshot": screenshot,
        "keys": keys,
        "scroll": scroll,
        "scroll_to": scroll_to,
        "set_value": matrix_entry(
            if action { "supported" } else { "unsupported" },
            "write text or numbers with a read-back check",
        ),
        "activate": activate,
    })
}

fn matrix_entry(status: &str, note: &str) -> Value {
    json!({"status": status, "note": note})
}

/// Non-fatal notes describing why a snapshot is incomplete.
fn snapshot_notes(snapshot: &Snapshot) -> Vec<String> {
    let mut notes = Vec::new();

    if let Some(reason) = snapshot.truncated_by.as_deref() {
        notes.push(format!(
            "snapshot cut by {reason} (kept {})",
            snapshot.elements.len()
        ));
    }

    if snapshot.children_cut > 0 && snapshot.truncated_by.as_deref() != Some("max_children") {
        notes.push(format!(
            "snapshot cut by max_children ({} children dropped)",
            snapshot.children_cut
        ));
    }

    notes
}

/// One screen frame kept for a short burst of identical screenshot requests.
struct CachedScreenshot {
    window: String,
    bounds: Bounds,
    bytes: Vec<u8>,
    captured: Instant,
}

/// Last frame plus the per-window request burst counters.
#[derive(Default)]
struct ScreenshotCache {
    entry: Option<CachedScreenshot>,
    bursts: HashMap<String, u32>,
}

impl ScreenshotCache {
    fn cached(&mut self, window: &str, bounds: Bounds) -> Option<(Vec<u8>, u32)> {
        let entry = self.entry.as_ref()?;
        let fresh = entry.captured.elapsed() <= SCREENSHOT_CACHE_TTL;

        if entry.window != window || entry.bounds != bounds || !fresh {
            return None;
        }

        Some((entry.bytes.clone(), self.bump(window)))
    }

    fn store(&mut self, window: &str, bounds: Bounds, bytes: Vec<u8>) {
        self.bursts.insert(window.to_string(), 1);
        self.entry = Some(CachedScreenshot {
            window: window.to_string(),
            bounds,
            bytes,
            captured: Instant::now(),
        });
    }

    fn bump(&mut self, window: &str) -> u32 {
        let burst = self.bursts.entry(window.to_string()).or_insert(0);
        *burst = burst.saturating_add(1);

        *burst
    }
}

/// True when `query` names the observed window under the same rules
/// backends use.
fn window_matches_query(window: &WindowInfo, query: &str) -> bool {
    let query = query.trim();

    if query.is_empty() {
        return true;
    }

    let lowered = query.to_lowercase();

    window.handle == query
        || window.title.eq_ignore_ascii_case(query)
        || window.title.to_lowercase().contains(&lowered)
        || window
            .process_name
            .as_deref()
            .is_some_and(|name| name.eq_ignore_ascii_case(query))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::ElementRecord;
    use std::ffi::OsString;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    struct BridgeEnv {
        path: PathBuf,
        previous: Option<OsString>,
        _lock: MutexGuard<'static, ()>,
    }

    impl BridgeEnv {
        fn new(tag: &str) -> Self {
            let lock = ENV_LOCK.lock().unwrap_or_else(|error| error.into_inner());
            let path = temp_path(tag);
            let previous = std::env::var_os("CECLI_BRIDGE_FILE");
            std::env::set_var("CECLI_BRIDGE_FILE", &path);

            Self {
                path,
                previous,
                _lock: lock,
            }
        }
    }

    impl Drop for BridgeEnv {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.path);
            match self.previous.take() {
                Some(value) => std::env::set_var("CECLI_BRIDGE_FILE", value),
                None => std::env::remove_var("CECLI_BRIDGE_FILE"),
            }
        }
    }

    struct EnvVar {
        key: &'static str,
        previous: Option<OsString>,
    }

    impl EnvVar {
        fn set(key: &'static str, value: &str) -> Self {
            let previous = std::env::var_os(key);
            std::env::set_var(key, value);
            Self { key, previous }
        }
    }

    impl Drop for EnvVar {
        fn drop(&mut self) {
            match self.previous.take() {
                Some(value) => std::env::set_var(self.key, value),
                None => std::env::remove_var(self.key),
            }
        }
    }

    struct TestServer {
        handle: Option<ServerHandle>,
        port: u16,
        file: BridgeFile,
        shutdown: Arc<AtomicBool>,
    }

    impl TestServer {
        fn start(backend: Arc<dyn Backend>) -> Self {
            let shutdown = Arc::new(AtomicBool::new(false));
            let handle = serve(backend, Arc::clone(&shutdown)).expect("serve");
            let file = read_bridge_file().expect("bridge file");
            let port = handle.port;

            Self {
                handle: Some(handle),
                port,
                file,
                shutdown,
            }
        }

        fn token(&self) -> &str {
            &self.file.token
        }

        fn send(
            &self,
            method: &str,
            path: &str,
            token: Option<&str>,
            body: Option<&str>,
        ) -> (u16, String, Vec<u8>) {
            send_request(self.port, method, path, token, body)
        }
    }

    impl Drop for TestServer {
        fn drop(&mut self) {
            self.shutdown.store(true, Ordering::SeqCst);
            if let Some(handle) = self.handle.take() {
                handle.join();
            }
        }
    }

    fn temp_path(tag: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0);

        std::env::temp_dir().join(format!(
            "cecli-bridge-test-{}-{}-{}.json",
            std::process::id(),
            tag,
            nanos
        ))
    }

    fn send_request(
        port: u16,
        method: &str,
        path: &str,
        token: Option<&str>,
        body: Option<&str>,
    ) -> (u16, String, Vec<u8>) {
        let mut stream = TcpStream::connect(("127.0.0.1", port)).expect("connect");
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .expect("read timeout");

        let mut request =
            format!("{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n");
        if let Some(token) = token {
            request.push_str(&format!("X-Cecli-Token: {token}\r\n"));
        }

        let payload = body.map(|value| value.as_bytes()).unwrap_or(&[]);
        if body.is_some() {
            request.push_str(&format!(
                "Content-Type: application/json\r\nContent-Length: {}\r\n",
                payload.len()
            ));
        }
        request.push_str("\r\n");

        stream.write_all(request.as_bytes()).expect("write head");
        if !payload.is_empty() {
            stream.write_all(payload).expect("write body");
        }

        let mut raw = Vec::new();
        stream.read_to_end(&mut raw).expect("read response");

        let head_end = find_head_end(&raw).expect("response head");
        let head = std::str::from_utf8(&raw[..head_end - 4])
            .expect("utf8 head")
            .to_string();
        let status = head
            .split_whitespace()
            .nth(1)
            .expect("status")
            .parse::<u16>()
            .expect("status number");

        (status, head, raw[head_end..].to_vec())
    }

    fn decode(body: &[u8]) -> Envelope {
        serde_json::from_slice(body).expect("envelope")
    }

    #[test]
    fn http_round_trip_covers_every_endpoint() {
        let env = BridgeEnv::new("roundtrip");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));
        let token = server.token().to_string();
        assert_eq!(server.handle.as_ref().unwrap().bridge_file, env.path);

        let (status, head, body) = server.send("GET", STATE_PATH, Some(&token), None);
        assert_eq!(status, 200);
        assert!(head.contains("Connection: close"));
        let state = decode(&body);
        assert!(state.ok);
        assert_eq!(state.action, "state");
        assert_eq!(state.health, Health::Ready);
        assert_eq!(state.data["platform"], "fake");

        let (status, _, body) = server.send("GET", WINDOWS_PATH, Some(&token), None);
        assert_eq!(status, 200);
        let windows = decode(&body);
        assert!(windows.ok);
        assert_eq!(windows.action, "windows");
        assert_eq!(windows.data[0]["title"], "Fake Window");

        let (status, _, body) = server.send(
            "POST",
            SNAPSHOT_PATH,
            Some(&token),
            Some("{\"window\":\"Fake Window\"}"),
        );
        assert_eq!(status, 200);
        let snapshot = decode(&body);
        assert!(snapshot.ok);
        assert_eq!(snapshot.action, "snapshot");
        assert!(snapshot.data["elements"][0]["runtime_id"]
            .as_str()
            .unwrap_or_default()
            .starts_with("fake:"));

        let (status, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some(
                "{\"window\":\"Fake Window\",\"action\":\"invoke\",\"target\":{\"name\":\"Save\"}}",
            ),
        );
        assert_eq!(status, 200);
        let action = decode(&body);
        assert!(action.ok);
        assert_eq!(action.action, "action");
        assert_eq!(action.data["delivered"], true);

        let (status, head, body) = server.send(
            "POST",
            SCREENSHOT_PATH,
            Some(&token),
            Some("{\"window\":\"Fake Window\"}"),
        );
        assert_eq!(status, 200);
        assert!(head.contains("Content-Type: image/png"));
        assert!(body.starts_with(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]));
        assert_eq!(&body[12..16], b"IHDR");

        let (status, _, body) = server.send("GET", DOCTOR_PATH, Some(&token), None);
        assert_eq!(status, 200);
        let doctor = decode(&body);
        assert!(doctor.ok);
        assert_eq!(doctor.action, "doctor");
        assert_eq!(doctor.data["backend"], "fake");

        let (status, _, body) = server.send("POST", SHUTDOWN_PATH, Some(&token), Some("{}"));
        assert_eq!(status, 200);
        let shutdown = decode(&body);
        assert!(shutdown.ok);
        assert_eq!(shutdown.action, "shutdown");
        assert_eq!(shutdown.data["stopping"], true);
    }

    #[test]
    fn a_repeated_screenshot_is_served_from_cache_with_a_note() {
        let _env = BridgeEnv::new("screenshot-cache");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));
        let token = server.token().to_string();
        let request = Some("{\"window\":\"Fake Window\"}");

        let (status, head, first) = server.send("POST", SCREENSHOT_PATH, Some(&token), request);
        assert_eq!(status, 200);
        assert!(first.starts_with(&[0x89, b'P', b'N', b'G']));
        assert!(!head.contains(NOTES_HEADER));

        let (status, head, second) = server.send("POST", SCREENSHOT_PATH, Some(&token), request);
        assert_eq!(status, 200);
        assert_eq!(first, second);
        assert!(head.contains(NOTES_HEADER), "expected a cache note: {head}");
        assert!(head.to_lowercase().contains("cache"));
    }

    #[test]
    fn accepts_a_body_sent_after_the_headers() {
        let _env = BridgeEnv::new("split-body");
        let server = TestServer::start(Arc::new(RefBackend));
        let token = server.token().to_string();
        let body = "{\"window\":\"Ref\"}";

        let mut stream = TcpStream::connect(("127.0.0.1", server.port)).expect("connect");
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .expect("read timeout");

        let head = format!(
            "POST {SNAPSHOT_PATH} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\nX-Cecli-Token: {token}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
            body.len()
        );
        stream.write_all(head.as_bytes()).expect("write head");
        stream.flush().expect("flush head");
        std::thread::sleep(Duration::from_millis(120));
        stream.write_all(body.as_bytes()).expect("write body");

        let mut raw = Vec::new();
        stream.read_to_end(&mut raw).expect("read response");
        let text = String::from_utf8_lossy(&raw).to_string();

        assert!(text.starts_with("HTTP/1.1 200"), "{text}");
        assert!(
            text.contains("\"ok\":true") || text.contains("\"ok\": true"),
            "{text}"
        );
    }

    #[test]
    fn rejects_missing_and_wrong_tokens() {
        let _env = BridgeEnv::new("auth");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));

        let (status, _, body) = server.send("GET", STATE_PATH, None, None);
        assert_eq!(status, 401);
        assert_eq!(
            decode(&body).error.expect("error").kind,
            error_kind::UNAUTHORIZED
        );

        let (status, _, body) = server.send("GET", STATE_PATH, Some("deadbeef"), None);
        assert_eq!(status, 401);
        assert_eq!(
            decode(&body).error.expect("error").kind,
            error_kind::UNAUTHORIZED
        );
    }

    #[test]
    fn unknown_route_and_wrong_method_are_reported() {
        let _env = BridgeEnv::new("routes");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));
        let token = server.token().to_string();

        let (status, _, body) = server.send("GET", "/api/app/nope", Some(&token), None);
        assert_eq!(status, 404);
        assert_eq!(
            decode(&body).error.expect("error").kind,
            error_kind::NOT_FOUND
        );

        let (status, head, body) = server.send("GET", ACTION_PATH, Some(&token), None);
        assert_eq!(status, 405);
        assert!(head.contains("Allow: POST"));
        assert_eq!(
            decode(&body).error.expect("error").kind,
            error_kind::INVALID_REQUEST
        );
    }

    #[test]
    fn malformed_json_is_a_bad_request() {
        let _env = BridgeEnv::new("json");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));
        let token = server.token().to_string();

        let (status, _, body) = server.send("POST", SNAPSHOT_PATH, Some(&token), Some("{oops"));
        assert_eq!(status, 400);
        assert_eq!(
            decode(&body).error.expect("error").kind,
            error_kind::INVALID_REQUEST
        );
    }

    #[test]
    fn bridge_file_is_atomic_private_and_stale_files_are_cleared() {
        let env = BridgeEnv::new("file");
        let file = BridgeFile {
            version: "0.1.0".to_string(),
            platform: "test".to_string(),
            host: "127.0.0.1".to_string(),
            port: 1,
            token: "a".repeat(64),
            pid: std::process::id(),
            mode: "bridge".to_string(),
            started_at: "2026-11-19T00:00:00Z".to_string(),
        };

        write_bridge_file(&file).expect("write");
        let loaded = read_bridge_file().expect("read");
        assert_eq!(loaded.port, 1);
        assert_eq!(loaded.token, file.token);
        assert_eq!(loaded.started_at, file.started_at);

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&env.path)
                .expect("metadata")
                .permissions()
                .mode()
                & 0o777;
            assert_eq!(mode, 0o600);
        }

        assert!(reuse_or_clear().is_none(), "port 1 is unreachable");
        assert!(read_bridge_file().is_none(), "stale file must be removed");
    }

    #[test]
    fn action_timeout_returns_uncertain_not_an_error() {
        let _env = BridgeEnv::new("action-timeout");
        let _timeout = EnvVar::set("CECLI_APP_TIMEOUT_MS", "100");
        let server = TestServer::start(Arc::new(SlowBackend::new(Duration::from_millis(400))));
        let token = server.token().to_string();

        let (status, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some("{\"window\":\"Slow\",\"action\":\"invoke\"}"),
        );

        assert_eq!(status, 200);
        let envelope = decode(&body);
        assert!(envelope.ok);
        assert_eq!(envelope.data["delivered"], true);
        assert_eq!(envelope.data["verified"], false);
        assert_eq!(envelope.data["uncertain"], true);
    }

    #[test]
    fn snapshot_timeout_returns_a_timeout_error() {
        let _env = BridgeEnv::new("snapshot-timeout");
        let _timeout = EnvVar::set("CECLI_APP_TIMEOUT_MS", "100");
        let server = TestServer::start(Arc::new(SlowBackend::new(Duration::from_millis(400))));
        let token = server.token().to_string();

        let (status, _, body) = server.send(
            "POST",
            SNAPSHOT_PATH,
            Some(&token),
            Some("{\"window\":\"Slow\"}"),
        );

        assert_eq!(status, 200);
        let envelope = decode(&body);
        assert!(!envelope.ok);
        assert_eq!(envelope.error.expect("error").kind, error_kind::TIMEOUT);
    }

    #[test]
    fn actions_resolve_targets_against_the_latest_snapshot() {
        let _env = BridgeEnv::new("resolve");
        let server = TestServer::start(Arc::new(RefBackend));
        let token = server.token().to_string();

        let (status, _, body) = server.send(
            "POST",
            SNAPSHOT_PATH,
            Some(&token),
            Some("{\"window\":\"Ref\"}"),
        );
        assert_eq!(status, 200);
        assert!(decode(&body).ok);

        let (_, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some(
                "{\"window\":\"Ref\",\"action\":\"invoke\",\"target\":{\"name\":\"Text Editor\"}}",
            ),
        );
        let resolved = decode(&body);
        assert!(resolved.ok, "resolved by name: {:?}", resolved.error);
        assert_eq!(resolved.data["delivered"], true);

        let (_, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some("{\"window\":\"Ref\",\"action\":\"invoke\",\"target\":{\"name\":\"Missing\"}}"),
        );
        let absent = decode(&body);
        assert!(!absent.ok);
        assert_eq!(
            absent.error.expect("error").kind,
            error_kind::TARGET_NOT_FOUND
        );

        let (_, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some("{\"window\":\"Ref\",\"action\":\"invoke\",\"target\":{\"id\":9999}}"),
        );
        let stale = decode(&body);
        assert!(!stale.ok);
        assert_eq!(stale.error.expect("error").kind, error_kind::STALE_TARGET);
    }

    #[test]
    fn mismatched_path_is_stale_while_a_matching_path_succeeds() {
        let _env = BridgeEnv::new("identity");
        let server = TestServer::start(Arc::new(RefBackend));
        let token = server.token().to_string();

        let (status, _, body) = server.send(
            "POST",
            SNAPSHOT_PATH,
            Some(&token),
            Some("{\"window\":\"Ref\"}"),
        );
        assert_eq!(status, 200);
        assert!(decode(&body).ok);

        let (_, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some(
                "{\"window\":\"Ref\",\"action\":\"invoke\",\"target\":{\"name\":\"Text Editor\",\"path\":\"Edit[Text Editor]\"}}",
            ),
        );
        let matching = decode(&body);
        assert!(matching.ok, "matching path: {:?}", matching.error);
        assert_eq!(matching.data["delivered"], true);

        let (_, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some(
                "{\"window\":\"Ref\",\"action\":\"invoke\",\"target\":{\"name\":\"Text Editor\",\"path\":\"Edit[Gone]\"}}",
            ),
        );
        let mismatched = decode(&body);
        assert!(!mismatched.ok, "a stale path must not re-match by name");
        let error = mismatched.error.expect("error");
        assert_eq!(error.kind, error_kind::STALE_TARGET);
        let details = error.details.expect("identity details");
        assert!(details
            .last_observed
            .as_deref()
            .is_some_and(|value| value.contains("Text Editor")));

        let (_, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some(
                "{\"window\":\"Ref\",\"action\":\"invoke\",\"target\":{\"name\":\"Text Editor\",\"runtime_id\":\"fake:9\"}}",
            ),
        );
        let stale_runtime = decode(&body);
        assert!(!stale_runtime.ok);
        assert_eq!(
            stale_runtime.error.expect("error").kind,
            error_kind::STALE_TARGET
        );
    }

    /// Returns a truncated tree on the first snapshot and the full tree after.
    #[derive(Default)]
    struct TruncatingBackend {
        snapshots: std::sync::atomic::AtomicUsize,
    }

    impl Backend for TruncatingBackend {
        fn name(&self) -> &'static str {
            "truncating"
        }

        fn platform(&self) -> &'static str {
            "test"
        }

        fn capabilities(&self) -> Vec<String> {
            vec!["snapshot".to_string(), "action".to_string()]
        }

        fn health(&self) -> Health {
            Health::Ready
        }

        fn doctor(&self) -> crate::protocol::DoctorReport {
            crate::protocol::DoctorReport {
                platform: self.platform().to_string(),
                backend: self.name().to_string(),
                health: Health::Ready,
                ..Default::default()
            }
        }

        fn windows(&self) -> Result<Vec<crate::protocol::WindowInfo>, ErrorInfo> {
            Ok(Vec::new())
        }

        fn snapshot(
            &self,
            _request: &SnapshotRequest,
        ) -> Result<crate::protocol::Snapshot, ErrorInfo> {
            let root = ElementRecord {
                id: 0,
                control_type: "Window".to_string(),
                name: Some("Ref".to_string()),
                runtime_id: "root:0".to_string(),
                ..Default::default()
            };
            let deep = ElementRecord {
                id: 1,
                parent: Some(0),
                depth: 1,
                control_type: "Button".to_string(),
                name: Some("Deep".to_string()),
                runtime_id: "deep:1".to_string(),
                ..Default::default()
            };
            let truncated = self.snapshots.fetch_add(1, Ordering::SeqCst) == 0;
            let elements = if truncated {
                vec![root]
            } else {
                vec![root, deep]
            };

            Ok(crate::protocol::Snapshot {
                total_elements: elements.len() as u32,
                elements,
                ..Default::default()
            })
        }

        fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
            match request
                .target
                .as_ref()
                .and_then(|target| target.runtime_id.as_deref())
            {
                Some("deep:1") => Ok(ActionResult::delivered(request.action.clone())),
                _ => Err(ErrorInfo::new(
                    error_kind::TARGET_NOT_FOUND,
                    "target lacks a resolved runtime id",
                )),
            }
        }

        fn screenshot(&self, _request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
            Err(ErrorInfo::new(error_kind::UNSUPPORTED, "no screenshots"))
        }
    }

    #[test]
    fn batch_runs_operations_in_order_and_keeps_going() {
        let _env = BridgeEnv::new("batch");
        let server = TestServer::start(Arc::new(RefBackend));
        let token = server.token().to_string();
        let body = r#"{"operations":[
            {"op":"snapshot","window":"Ref"},
            {"op":"action","window":"Ref","action":"invoke","target":{"name":"Text Editor"}},
            {"op":"action","window":"Ref","action":"invoke","target":{"name":"Missing"}},
            {"op":"bogus"}
        ]}"#;

        let (status, _, bytes) = server.send("POST", BATCH_PATH, Some(&token), Some(body));
        assert_eq!(status, 200);

        let envelope = decode(&bytes);
        assert!(envelope.ok, "{:?}", envelope.error);
        let results = envelope.data["results"].as_array().expect("results");

        assert_eq!(results.len(), 4);
        assert_eq!(results[0]["ok"], true);
        assert_eq!(results[0]["action"], "snapshot");
        assert_eq!(results[1]["ok"], true);
        assert_eq!(results[1]["data"]["delivered"], true);
        assert_eq!(results[2]["ok"], false);
        assert_eq!(results[2]["error"]["type"], error_kind::TARGET_NOT_FOUND);
        assert_eq!(results[3]["ok"], false);
        assert_eq!(results[3]["error"]["type"], error_kind::INVALID_REQUEST);
    }

    #[test]
    fn action_refreshes_after_a_truncated_snapshot() {
        let _env = BridgeEnv::new("refresh");
        let server = TestServer::start(Arc::new(TruncatingBackend::default()));
        let token = server.token().to_string();

        let (status, _, body) = server.send(
            "POST",
            SNAPSHOT_PATH,
            Some(&token),
            Some("{\"window\":\"Ref\"}"),
        );
        assert_eq!(status, 200);
        assert!(decode(&body).ok);

        let (status, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some("{\"window\":\"Ref\",\"action\":\"invoke\",\"target\":{\"name\":\"Deep\"}}"),
        );
        assert_eq!(status, 200);
        let envelope = decode(&body);
        assert!(envelope.ok, "retried after refresh: {:?}", envelope.error);
        assert_eq!(envelope.data["delivered"], true);
        assert_eq!(envelope.data["verified"], true);
    }

    #[test]
    fn dialogs_endpoint_returns_only_dialog_windows() {
        let _env = BridgeEnv::new("dialogs");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));
        let token = server.token().to_string();

        let (status, _, body) = server.send("GET", DIALOGS_PATH, Some(&token), None);
        assert_eq!(status, 200);

        let envelope = decode(&body);
        assert!(envelope.ok);
        assert_eq!(envelope.action, "dialogs");
        let dialogs = envelope.data["dialogs"].as_array().expect("dialogs array");
        assert_eq!(dialogs.len(), 1);
        assert_eq!(
            dialogs[0]["title"],
            crate::backend::fake::HIDDEN_WINDOW_TITLE
        );
        assert_eq!(dialogs[0]["dialog"], true);

        let (status, _, body) = server.send("GET", WINDOWS_PATH, Some(&token), None);
        assert_eq!(status, 200);
        assert_eq!(
            decode(&body).data.as_array().expect("window array").len(),
            3
        );
    }

    #[test]
    fn help_lists_endpoints_actions_and_selectors() {
        let _env = BridgeEnv::new("help");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));
        let token = server.token().to_string();

        let (status, _, body) = server.send("GET", HELP_PATH, Some(&token), None);

        assert_eq!(status, 200);

        let envelope = decode(&body);

        assert!(envelope.ok);
        assert_eq!(envelope.action, "help");
        assert_eq!(envelope.data["backend"], "fake");
        assert!(envelope.data["endpoints"].get("snapshot").is_some());
        assert!(envelope.data["actions"].get("invoke").is_some());
        assert!(envelope.data["selectors"].get("path").is_some());
        assert!(envelope.data["endpoints"].get("find").is_some());
        assert!(envelope.data["endpoints"].get("dialogs").is_some());
        assert!(envelope.data["actions"].get("drag").is_some());
        assert!(envelope.data["actions"].get("select").is_some());
        assert!(envelope.data["actions"].get("scroll_into_view").is_some());
        assert!(envelope.data["actions"].get("cell_at").is_some());
        let matrix = envelope.data["capabilities_matrix"]
            .as_object()
            .expect("capability matrix");
        for feature in [
            "windows",
            "snapshot",
            "find",
            "cell_at",
            "screenshot",
            "keys",
            "scroll",
            "set_value",
            "activate",
        ] {
            let entry = matrix
                .get(feature)
                .unwrap_or_else(|| panic!("missing matrix entry '{feature}'"));
            assert!(matches!(
                entry["status"].as_str(),
                Some("supported" | "partial" | "unsupported" | "unknown")
            ));
            assert!(entry["note"].as_str().is_some_and(|note| !note.is_empty()));
        }
        assert_eq!(matrix["screenshot"]["status"], "supported");
    }

    #[test]
    fn find_endpoint_requires_post_and_reports_unsupported_for_fake() {
        let _env = BridgeEnv::new("find");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));
        let token = server.token().to_string();

        let (status, head, _body) = server.send("GET", FIND_PATH, Some(&token), None);
        assert_eq!(status, 405);
        assert!(head.contains("Allow: POST"));

        let (status, _, body) = server.send(
            "POST",
            FIND_PATH,
            Some(&token),
            Some(r#"{"window":"Fake Window","match":{"roles":["Push Button"]}}"#),
        );
        assert_eq!(status, 200);

        let envelope = decode(&body);
        assert!(!envelope.ok);
        assert_eq!(envelope.action, "find");
        assert_eq!(envelope.error.expect("error").kind, error_kind::UNSUPPORTED);
        assert!(envelope
            .data
            .as_object()
            .map(|object| object.is_empty())
            .unwrap_or(false));
    }

    #[test]
    fn find_is_available_in_batch_requests() {
        let _env = BridgeEnv::new("find-batch");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));
        let token = server.token().to_string();
        let body = r#"{"operations":[{"op":"find","window":"Fake Window","match":{}}]}"#;

        let (status, _, bytes) = server.send("POST", BATCH_PATH, Some(&token), Some(body));
        assert_eq!(status, 200);

        let envelope = decode(&bytes);
        assert!(envelope.ok, "{:?}", envelope.error);
        let results = envelope.data["results"].as_array().expect("results");
        assert_eq!(results.len(), 1);
        assert_eq!(results[0]["action"], "find");
        assert_eq!(results[0]["error"]["type"], error_kind::UNSUPPORTED);
    }

    #[test]
    fn started_at_is_rfc3339_utc() {
        assert_eq!(format_rfc3339(1_795_046_400), "2026-11-19T00:00:00Z");
        assert_eq!(format_rfc3339(1_709_210_096), "2024-02-29T12:34:56Z");
    }

    struct SlowBackend {
        delay: Duration,
    }

    impl SlowBackend {
        fn new(delay: Duration) -> Self {
            Self { delay }
        }
    }

    impl Backend for SlowBackend {
        fn name(&self) -> &'static str {
            "slow"
        }

        fn platform(&self) -> &'static str {
            "test"
        }

        fn capabilities(&self) -> Vec<String> {
            vec!["snapshot".to_string(), "action".to_string()]
        }

        fn health(&self) -> Health {
            Health::Ready
        }

        fn doctor(&self) -> crate::protocol::DoctorReport {
            crate::protocol::DoctorReport {
                platform: self.platform().to_string(),
                backend: self.name().to_string(),
                health: Health::Ready,
                ..Default::default()
            }
        }

        fn windows(&self) -> Result<Vec<crate::protocol::WindowInfo>, ErrorInfo> {
            Ok(Vec::new())
        }

        fn snapshot(
            &self,
            _request: &SnapshotRequest,
        ) -> Result<crate::protocol::Snapshot, ErrorInfo> {
            thread::sleep(self.delay);
            Ok(crate::protocol::Snapshot::default())
        }

        fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
            thread::sleep(self.delay);
            Ok(ActionResult::delivered(request.action.clone()))
        }

        fn screenshot(&self, _request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
            Ok(vec![0x89, b'P', b'N', b'G'])
        }
    }

    struct RefBackend;

    impl Backend for RefBackend {
        fn name(&self) -> &'static str {
            "ref"
        }

        fn platform(&self) -> &'static str {
            "test"
        }

        fn capabilities(&self) -> Vec<String> {
            vec!["snapshot".to_string(), "action".to_string()]
        }

        fn health(&self) -> Health {
            Health::Ready
        }

        fn doctor(&self) -> crate::protocol::DoctorReport {
            crate::protocol::DoctorReport {
                platform: self.platform().to_string(),
                backend: self.name().to_string(),
                health: Health::Ready,
                ..Default::default()
            }
        }

        fn windows(&self) -> Result<Vec<crate::protocol::WindowInfo>, ErrorInfo> {
            Ok(Vec::new())
        }

        fn snapshot(
            &self,
            _request: &SnapshotRequest,
        ) -> Result<crate::protocol::Snapshot, ErrorInfo> {
            Ok(crate::protocol::Snapshot {
                elements: vec![ElementRecord {
                    id: 0,
                    parent: None,
                    depth: 0,
                    runtime_id: "fake:0".to_string(),
                    control_type: "Edit".to_string(),
                    name: Some("Text Editor".to_string()),
                    automation_id: Some("edit".to_string()),
                    enabled: true,
                    ..Default::default()
                }],
                total_elements: 1,
                ..Default::default()
            })
        }

        fn action(&self, request: &ActionRequest) -> Result<ActionResult, ErrorInfo> {
            match request
                .target
                .as_ref()
                .and_then(|target| target.runtime_id.as_deref())
            {
                Some("fake:0") => Ok(ActionResult::delivered(request.action.clone())),
                _ => Err(ErrorInfo::new(
                    error_kind::TARGET_NOT_FOUND,
                    "target lacks a resolved runtime id",
                )),
            }
        }

        fn screenshot(&self, _request: &ScreenshotRequest) -> Result<Vec<u8>, ErrorInfo> {
            Err(ErrorInfo::new(error_kind::UNSUPPORTED, "no screenshots"))
        }
    }
    #[test]
    fn snapshot_notes_name_each_truncation_cause() {
        let by_elements = Snapshot {
            truncated: true,
            truncated_by: Some("max_elements".to_string()),
            elements: vec![ElementRecord::default(); 3],
            ..Default::default()
        };
        assert_eq!(
            snapshot_notes(&by_elements),
            vec!["snapshot cut by max_elements (kept 3)".to_string()]
        );

        let by_children = Snapshot {
            truncated: true,
            children_cut: 7,
            ..Default::default()
        };
        assert_eq!(
            snapshot_notes(&by_children),
            vec!["snapshot cut by max_children (7 children dropped)".to_string()]
        );

        let both = Snapshot {
            truncated: true,
            truncated_by: Some("max_children".to_string()),
            children_cut: 7,
            ..Default::default()
        };
        assert_eq!(snapshot_notes(&both).len(), 1);
        assert!(snapshot_notes(&Snapshot::default()).is_empty());
    }

    #[test]
    fn capability_matrix_reports_platform_specific_support() {
        let linux = capability_matrix(
            "linux-atspi",
            "linux",
            &["windows", "snapshot", "action", "find"]
                .iter()
                .map(|value| (*value).to_string())
                .collect::<Vec<String>>(),
        );

        assert_eq!(linux["windows"]["status"], "supported");
        assert_eq!(linux["snapshot"]["status"], "supported");
        assert_eq!(linux["find"]["status"], "supported");
        assert_eq!(linux["cell_at"]["status"], "partial");
        assert_eq!(linux["screenshot"]["status"], "partial");
        assert_eq!(linux["keys"]["status"], "unsupported");
        assert_eq!(linux["scroll"]["status"], "unsupported");
        assert_eq!(linux["set_value"]["status"], "supported");
        assert_eq!(linux["activate"]["status"], "unsupported");

        let linux_display = capability_matrix(
            "linux-atspi",
            "linux",
            &[
                "windows",
                "snapshot",
                "action",
                "find",
                "xtest",
                "screenshot",
            ]
            .iter()
            .map(|value| (*value).to_string())
            .collect::<Vec<String>>(),
        );

        assert_eq!(linux_display["keys"]["status"], "supported");
        assert_eq!(linux_display["scroll"]["status"], "supported");
        assert_eq!(linux_display["activate"]["status"], "supported");
        assert_eq!(linux_display["screenshot"]["status"], "supported");

        let fake = capability_matrix(
            "fake",
            "fake",
            &["windows", "snapshot", "action", "screenshot"]
                .iter()
                .map(|value| (*value).to_string())
                .collect::<Vec<String>>(),
        );

        assert_eq!(fake["screenshot"]["status"], "supported");
        assert_eq!(fake["cell_at"]["status"], "unsupported");
        assert_eq!(fake["keys"]["status"], "supported");
        assert_eq!(fake["scroll"]["status"], "supported");
        assert_eq!(fake["set_value"]["status"], "supported");
        assert_eq!(fake["activate"]["status"], "supported");
    }
    #[test]
    fn unresolved_selector_reports_near_miss_details() {
        let _env = BridgeEnv::new("diagnosis");
        let server = TestServer::start(Arc::new(crate::backend::fake::FakeBackend::ready()));
        let token = server.token().to_string();

        let (status, _, body) = server.send(
            "POST",
            SNAPSHOT_PATH,
            Some(&token),
            Some("{\"window\":\"Fake Window\"}"),
        );
        assert_eq!(status, 200);
        assert!(decode(&body).ok);

        let (status, _, body) = server.send(
            "POST",
            ACTION_PATH,
            Some(&token),
            Some(
                "{\"window\":\"Fake Window\",\"action\":\"invoke\",\"target\":{\"name\":\"Text\"}}",
            ),
        );
        assert_eq!(status, 200);

        let envelope = decode(&body);
        assert!(!envelope.ok);
        let details = envelope
            .error
            .expect("error")
            .details
            .expect("diagnosis details");
        assert!(details
            .candidates
            .iter()
            .any(|candidate| candidate.contains("Text Editor")));
        assert!(details
            .scope
            .as_deref()
            .is_some_and(|scope| scope.contains("elements")));
        assert!(details.last_observed.is_some());
    }
}
