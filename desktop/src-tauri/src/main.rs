use std::env;
use std::io;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

mod bridge_mode;

const DARK_THEME: &str = "dark";
const LIGHT_THEME: &str = "light";

/// Bundled logo used for the window icon.
///
/// Windows resolves `default_window_icon()` from the executable's icon resource,
/// which is only present when the binary is linked with one. Debug builds run
/// through `cargo run` have none, so the title bar falls back to the generic
/// system placeholder. Embedding the PNG keeps the real logo in that case.
const WINDOW_ICON_PNG: &[u8] = include_bytes!("../icons/128x128.png");

/// Owns the Python bridge child process for the lifetime of the application.
struct BridgeState(Mutex<Option<Child>>);

/// In-process app-harness bridge hosted by the desktop window.
struct BridgeHostState {
    shutdown: Arc<AtomicBool>,
    join: Mutex<Option<thread::JoinHandle<()>>>,
}

static RESOURCE_DIR: OnceLock<Option<PathBuf>> = OnceLock::new();

static APP_DATA_DIR: OnceLock<Option<PathBuf>> = OnceLock::new();

/// Process entry point. Mode dispatch happens before Tauri initializes.
fn main() {
    match bridge_mode::parse_mode(env::args_os().skip(1)) {
        bridge_mode::Mode::Desktop => run_desktop(),
        mode => std::process::exit(bridge_mode::run(mode)),
    }
}

/// Open the desktop window, hosting the Python UI and the app-harness bridge.
fn run_desktop() {
    #[cfg(target_os = "linux")]
    configure_webkit();

    let bridge_host = start_bridge_host();

    let app = match tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(move |app| {
            if let Some(host) = bridge_host {
                app.manage(host);
            }

            let workspace = resolve_workspace();
            eprintln!("cecli desktop workspace: {}", workspace.display());
            let port = resolve_port()?;
            let _ = RESOURCE_DIR.set(app.path().resource_dir().ok());
            let _ = APP_DATA_DIR.set(app.path().app_local_data_dir().ok());
            let bridge = locate_bridge()?;
            let mut child = spawn_bridge(&bridge, &workspace, port)?;

            if let Err(err) = wait_for_bridge(&mut child, port, bridge_timeout(&bridge)) {
                terminate(&mut child);
                return Err(err.into());
            }

            if let Err(err) = build_window(app.handle(), port) {
                terminate(&mut child);
                return Err(err);
            }

            app.manage(BridgeState(Mutex::new(Some(child))));

            Ok(())
        })
        .build(tauri::generate_context!())
    {
        Ok(app) => app,
        Err(err) => {
            eprintln!("failed to build cecli desktop: {err}");
            std::process::exit(1);
        }
    };

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit) {
            if let Some(state) = app_handle.try_state::<BridgeState>() {
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(mut child) = guard.take() {
                        terminate(&mut child);
                    }
                }
            }

            stop_bridge_host(app_handle);
        }
    });
}

/// Reuse a healthy bridge, otherwise serve one on a background thread.
///
/// Returns `None` when another process already publishes `bridge.json` or the
/// thread cannot start. A failure is logged and never aborts the GUI: the UI
/// keeps working without native app control.
fn start_bridge_host() -> Option<BridgeHostState> {
    if let Some(file) = ce_app_bridge::server::read_bridge_file() {
        if ce_app_bridge::server::ping(&file, Duration::from_millis(500)) {
            eprintln!("app-harness bridge already running on port {}", file.port);
            return None;
        }
    }

    let shutdown = Arc::new(AtomicBool::new(false));
    let flag = Arc::clone(&shutdown);
    let (port_tx, port_rx) = std::sync::mpsc::channel();

    let join = match thread::Builder::new()
        .name("ce-app-bridge".to_string())
        .spawn(
            move || match ce_app_bridge::server::serve(ce_app_bridge::default_backend(), flag) {
                Ok(handle) => {
                    let _ = port_tx.send(Ok(handle.port));
                    handle.join();
                }
                Err(error) => {
                    let _ = port_tx.send(Err(error.to_string()));
                }
            },
        ) {
        Ok(join) => join,
        Err(error) => {
            eprintln!("app-harness bridge thread failed: {error}");
            return None;
        }
    };

    match port_rx.recv_timeout(Duration::from_secs(5)) {
        Ok(Ok(port)) => eprintln!("app-harness bridge listening on http://127.0.0.1:{port}"),
        Ok(Err(error)) => eprintln!("app-harness bridge failed to start: {error}"),
        Err(error) => eprintln!("app-harness bridge did not report a port: {error}"),
    }

    Some(BridgeHostState {
        shutdown,
        join: Mutex::new(Some(join)),
    })
}

/// Signal the hosted bridge and give it a moment to remove `bridge.json`.
fn stop_bridge_host(app_handle: &AppHandle) {
    let Some(state) = app_handle.try_state::<BridgeHostState>() else {
        return;
    };

    state.shutdown.store(true, Ordering::SeqCst);

    let Ok(mut guard) = state.join.lock() else {
        return;
    };

    let Some(handle) = guard.take() else {
        return;
    };

    let deadline = Instant::now() + Duration::from_millis(1000);

    while !handle.is_finished() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(20));
    }

    // Joining a live accept loop would block exit; leave that thread behind.
    if handle.is_finished() {
        let _ = handle.join();
    }
}

/// Opt into WebKitGTK's software rendering paths for blank or flickering
/// windows caused by some Linux and WSL GPU stacks.
#[cfg(target_os = "linux")]
fn configure_webkit() {
    let enabled = env::var("CECLI_SOFTWARE_WEBKIT")
        .map(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "on"))
        .unwrap_or(false);

    if !enabled {
        return;
    }

    env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    env::set_var("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
}

/// Resolve the workspace from the env override, first non-flag argument, or cwd.
fn resolve_workspace() -> PathBuf {
    let candidate = env::var_os("CECLI_DESKTOP_WORKSPACE")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or_else(|| {
            env::args()
                .skip(1)
                .find(|arg| !arg.starts_with('-'))
                .map(PathBuf::from)
        })
        .or_else(|| {
            let cwd = env::current_dir().ok()?;
            Some(dev_workspace_root(&cwd).unwrap_or(cwd))
        })
        .unwrap_or_else(|| PathBuf::from("."));

    std::fs::canonicalize(&candidate).unwrap_or(candidate)
}

/// In development Tauri runs the binary from `src-tauri`; prefer the repo root.
fn dev_workspace_root(cwd: &Path) -> Option<PathBuf> {
    if !cfg!(debug_assertions) {
        return None;
    }

    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    if !cwd.starts_with(manifest) {
        return None;
    }

    manifest.parent()?.parent().map(Path::to_path_buf)
}

/// Use CECLI_DESKTOP_PORT when set, otherwise reserve an ephemeral loopback port.
fn resolve_port() -> io::Result<u16> {
    if let Ok(value) = env::var("CECLI_DESKTOP_PORT") {
        let value = value.trim();
        if !value.is_empty() {
            return value.parse::<u16>().map_err(|err| {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("invalid CECLI_DESKTOP_PORT {value:?}: {err}"),
                )
            });
        }
    }

    let listener = std::net::TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    drop(listener);

    Ok(port)
}

/// The bridge script runs under a uv-managed Python in release builds.
///
/// Release bundles ship only `uv`; `server.py` and the UI are resources.
/// Development keeps using the system Python and the source tree.
enum Bridge {
    Managed { uv: PathBuf, script: PathBuf },
    Script(PathBuf),
}

fn cecli_binary_name() -> &'static str {
    if cfg!(windows) {
        "cecli.exe"
    } else {
        "cecli"
    }
}

fn uv_binary_name() -> &'static str {
    if cfg!(windows) {
        "uv.exe"
    } else {
        "uv"
    }
}

/// Resolve uv only from the app bundle or an explicit override, so development
/// keeps running the source tree instead of provisioning a released cecli.
fn bundled_uv() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Some(value) = env::var_os("CECLI_DESKTOP_UV").filter(|value| !value.is_empty()) {
        candidates.push(PathBuf::from(value));
    }

    // Debug builds follow the checkout; a uv left in target/ by a bundled build
    // must not silently switch npm run dev to a released cecli.
    if !cfg!(debug_assertions) {
        if let Some(dir) = current_exe_dir() {
            candidates.push(dir.join(uv_binary_name()));
        }

        if let Some(dir) = resource_dir() {
            candidates.push(dir.join(uv_binary_name()));
            candidates.push(dir.join("_up_").join(uv_binary_name()));
        }
    }

    candidates.into_iter().find(|path| path.is_file())
}

/// The bundled server.py that a uv-managed runtime executes.
fn bundled_server() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Some(value) = env::var_os("CECLI_DESKTOP_SERVER").filter(|value| !value.is_empty()) {
        let path = PathBuf::from(value);

        if path
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("py"))
        {
            candidates.push(path);
        }
    }

    if let Some(dir) = resource_dir() {
        candidates.push(dir.join("server.py"));
        candidates.push(dir.join("_up_").join("server.py"));
    }

    candidates.into_iter().find(|path| path.is_file())
}

/// Find the bridge: a bundled uv plus server.py, then the development script.
fn locate_bridge() -> io::Result<Bridge> {
    if let (Some(uv), Some(script)) = (bundled_uv(), bundled_server()) {
        return Ok(Bridge::Managed { uv, script });
    }

    let mut scripts: Vec<PathBuf> = Vec::new();

    if let Some(value) = env::var_os("CECLI_DESKTOP_SERVER") {
        if !value.is_empty() {
            let path = PathBuf::from(value);

            if path
                .extension()
                .is_some_and(|ext| ext.eq_ignore_ascii_case("py"))
            {
                scripts.insert(0, path);
            }
        }
    }

    if let Some(dev_root) = Path::new(env!("CARGO_MANIFEST_DIR")).parent() {
        scripts.push(dev_root.join("server.py"));
    }

    if let Some(dir) = resource_dir() {
        scripts.push(dir.join("server.py"));
        scripts.push(dir.join("_up_").join("server.py"));
    }

    if let Some(found) = scripts.iter().find(|path| path.is_file()) {
        return Ok(Bridge::Script(found.clone()));
    }

    let tried = scripts
        .iter()
        .map(|path| path.display().to_string())
        .collect::<Vec<_>>()
        .join(", ");

    Err(io::Error::new(
        io::ErrorKind::NotFound,
        format!("cecli desktop bridge not found; tried: {tried}"),
    ))
}

fn current_exe_dir() -> Option<PathBuf> {
    let exe = env::current_exe().ok()?;
    exe.parent().map(Path::to_path_buf)
}

/// Launch the bridge, honoring CECLI_PYTHON only for the Python fallback.
fn spawn_bridge(bridge: &Bridge, workspace: &Path, port: u16) -> io::Result<Child> {
    match bridge {
        Bridge::Managed { uv, script } => spawn_bridge_managed(uv, script, workspace, port),
        Bridge::Script(script) => spawn_bridge_script(script, workspace, port),
    }
}

/// Run the bundled server.py against a uv-managed cecli runtime.
fn spawn_bridge_managed(
    uv: &Path,
    script: &Path,
    workspace: &Path,
    port: u16,
) -> io::Result<Child> {
    let runtime = ensure_runtime(uv)?;
    let mut command = Command::new(&runtime.python);

    if let Some(exe_dir) = current_exe_dir() {
        prepend_to_path(&mut command, &exe_dir);
    }

    if let Some(bin_dir) = runtime.python.parent() {
        prepend_to_path(&mut command, bin_dir);
    }

    command.arg(script);

    if let Some(static_root) = bundled_static_root() {
        command.arg("--static-root").arg(static_root);
    }

    configure_bridge(&mut command, workspace, port, Some(&runtime.cecli));
    command.spawn()
}

fn spawn_bridge_script(script: &Path, workspace: &Path, port: u16) -> io::Result<Child> {
    let mut last_error = None;

    for python in python_candidates(script) {
        let mut command = Command::new(&python);
        command.arg(script);

        if let Some(exe_dir) = current_exe_dir() {
            prepend_to_path(&mut command, &exe_dir);
        }

        if let Some(bin_dir) = Path::new(&python).parent() {
            prepend_to_path(&mut command, bin_dir);
        }

        configure_bridge(&mut command, workspace, port, None);

        match command.spawn() {
            Ok(child) => return Ok(child),
            Err(err) => last_error = Some(err),
        }
    }

    Err(last_error.unwrap_or_else(|| {
        io::Error::new(io::ErrorKind::NotFound, "no Python interpreter available")
    }))
}

/// Shared bridge arguments, stdio, agent path and process-group handling.
fn configure_bridge(command: &mut Command, workspace: &Path, port: u16, cecli: Option<&Path>) {
    command
        .arg("--desktop-bridge")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .arg("--workspace")
        .arg(workspace)
        // The AppImage AppRun exports PYTHONHOME/PYTHONPATH for its own layout.
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit());

    let cecli = cecli
        .map(|path| path.display().to_string())
        .or_else(cecli_override)
        .or_else(bundled_cecli);

    if let Some(cecli) = cecli {
        command.arg("--cecli").arg(cecli);
    }

    #[cfg(unix)]
    command.process_group(0);

    #[cfg(target_os = "linux")]
    {
        let parent_pid = std::process::id() as libc::pid_t;
        unsafe {
            command.pre_exec(move || {
                libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
                if libc::getppid() != parent_pid {
                    libc::_exit(1);
                }
                Ok(())
            });
        }
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW: the bridge must not flash a console window.
        command.creation_flags(0x0800_0000);
    }
}

/// Prefer the `cecli` shipped next to the app over whatever is on PATH.
fn bundled_cecli() -> Option<String> {
    let name = cecli_binary_name();
    let current_exe = env::current_exe().ok();
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Some(dir) = current_exe_dir() {
        candidates.push(dir.join(name));
    }

    if let Some(dir) = resource_dir() {
        candidates.push(dir.join(name));
        candidates.push(dir.join("_up_").join(name));
    }

    candidates
        .into_iter()
        .find(|path| path.is_file() && Some(path.as_path()) != current_exe.as_deref())
        .map(|path| path.display().to_string())
}

/// Point the bridge at the bundled UI when the binary does not embed it.
fn bundled_static_root() -> Option<PathBuf> {
    let dir = resource_dir()?;
    let candidates = [dir.clone(), dir.join("_up_")];

    candidates
        .into_iter()
        .find(|path| path.join("static").join("index.html").is_file())
}

/// Bundle directory, cached during setup so spawn helpers need no AppHandle.
fn resource_dir() -> Option<PathBuf> {
    RESOURCE_DIR.get().cloned().flatten()
}

/// First launch of the uv build downloads CPython and the cecli wheel set.
fn bridge_timeout(bridge: &Bridge) -> Duration {
    if matches!(bridge, Bridge::Managed { .. }) {
        Duration::from_secs(900)
    } else {
        Duration::from_secs(30)
    }
}

struct ManagedRuntime {
    python: PathBuf,
    cecli: PathBuf,
}

/// Provision (once per runtime spec) and return the uv-managed interpreter.
fn ensure_runtime(uv: &Path) -> io::Result<ManagedRuntime> {
    let root = runtime_root()?;
    let spec = runtime_spec();
    let env_dir = root.join(sanitize(&spec));
    let python = venv_python(&env_dir);
    let cecli = venv_cecli(&env_dir);
    let marker = env_dir.join(".cecli-ready");

    let ready = marker.is_file()
        && python.is_file()
        && cecli.is_file()
        && std::fs::read_to_string(&marker).is_ok_and(|value| value.trim() == spec);

    if !ready {
        provision_runtime(uv, &root, &env_dir, &python, &spec)?;
    }

    Ok(ManagedRuntime { python, cecli })
}

fn provision_runtime(
    uv: &Path,
    root: &Path,
    env_dir: &Path,
    python: &Path,
    spec: &str,
) -> io::Result<()> {
    eprintln!("provisioning cecli runtime {spec}; first launch needs network access");

    let _ = std::fs::remove_dir_all(env_dir);
    std::fs::create_dir_all(root)?;

    let mut venv = Command::new(uv);
    venv.arg("venv")
        .arg("--python")
        .arg("3.12")
        // Require uv's own CPython so the runtime survives a system Python change.
        .arg("--managed-python")
        .arg("--no-progress")
        .arg(env_dir);
    prepare_uv(&mut venv, root);
    run_uv(&mut venv, "create the Python environment")?;

    let mut install = Command::new(uv);
    install
        .arg("pip")
        .arg("install")
        // --native-tls: trust the OS store so corporate TLS interception does not fail.
        .arg("--native-tls")
        .arg("--python")
        .arg(python)
        .arg("--no-progress")
        .arg(spec);
    prepare_uv(&mut install, root);
    run_uv(&mut install, "install cecli")?;

    std::fs::write(env_dir.join(".cecli-ready"), spec)
}

/// Keep uv's CPython inside the runtime so deleting it is a complete uninstall.
fn prepare_uv(command: &mut Command, root: &Path) {
    command
        .env("UV_PYTHON_INSTALL_DIR", root.join("python"))
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW: do not flash a console while provisioning.
        command.creation_flags(0x0800_0000);
    }
}

fn run_uv(command: &mut Command, action: &str) -> io::Result<()> {
    let status = command.status()?;

    if !status.success() {
        return Err(io::Error::other(format!(
            "uv failed to {action} ({status})"
        )));
    }

    Ok(())
}

fn runtime_root() -> io::Result<PathBuf> {
    if let Some(value) = env::var_os("CECLI_DESKTOP_RUNTIME").filter(|value| !value.is_empty()) {
        return Ok(PathBuf::from(value));
    }

    let base = APP_DATA_DIR
        .get()
        .cloned()
        .flatten()
        .or_else(current_exe_dir)
        .ok_or_else(|| io::Error::other("could not resolve a writable runtime directory"))?;

    Ok(base.join("runtime"))
}

fn runtime_spec() -> String {
    env::var("CECLI_DESKTOP_RUNTIME_SPEC")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .or_else(|| option_env!("CECLI_RUNTIME_SPEC").map(str::to_string))
        .unwrap_or_else(|| "cecli-dev".to_string())
}

/// Expose the runtime's console scripts (`app-harness`, `browser-harness`) to child processes.
pub(crate) fn prepend_to_path(command: &mut Command, directory: &Path) {
    let mut entries = vec![directory.to_path_buf()];

    if let Some(existing) = env::var_os("PATH") {
        entries.extend(env::split_paths(&existing));
    }

    if let Ok(joined) = env::join_paths(entries) {
        command.env("PATH", joined);
    }
}

fn venv_python(env_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        env_dir.join("Scripts").join("python.exe")
    } else {
        env_dir.join("bin").join("python")
    }
}

fn venv_cecli(env_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        env_dir.join("Scripts").join("cecli.exe")
    } else {
        env_dir.join("bin").join("cecli")
    }
}

fn sanitize(value: &str) -> String {
    value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '.' | '-' | '_') {
                ch
            } else {
                '_'
            }
        })
        .collect()
}

fn python_candidates(script: &Path) -> Vec<String> {
    if let Ok(value) = env::var("CECLI_PYTHON") {
        let value = value.trim();
        if !value.is_empty() {
            return vec![value.to_string()];
        }
    }

    let mut candidates = Vec::new();
    if let Some(root) = script.parent() {
        let runtime = if cfg!(windows) {
            root.join(".runtime")
                .join("venv")
                .join("Scripts")
                .join("python.exe")
        } else {
            root.join(".runtime")
                .join("venv")
                .join("bin")
                .join("python")
        };
        if runtime.is_file() {
            candidates.push(runtime.display().to_string());
        }
    }

    if cfg!(windows) {
        candidates.extend(["python".to_string(), "python3".to_string()]);
    } else {
        candidates.push("python3".to_string());
    }

    candidates
}

fn cecli_override() -> Option<String> {
    env::var("CECLI_DESKTOP_CECLI")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

/// Poll the loopback socket until the bridge listens or the timeout expires.
fn wait_for_bridge(child: &mut Child, port: u16, timeout: Duration) -> io::Result<()> {
    let deadline = Instant::now() + timeout;
    let address = SocketAddr::from(([127, 0, 0, 1], port));

    while Instant::now() < deadline {
        if let Some(status) = child.try_wait()? {
            return Err(io::Error::other(format!(
                "cecli desktop bridge exited early with status {status}"
            )));
        }

        if TcpStream::connect_timeout(&address, Duration::from_millis(500)).is_ok() {
            return Ok(());
        }

        thread::sleep(Duration::from_millis(200));
    }

    Err(io::Error::new(
        io::ErrorKind::TimedOut,
        format!("timed out waiting for the bridge on 127.0.0.1:{port}"),
    ))
}

/// Create the main window pointing at the Python-served UI.
fn build_window(app: &AppHandle, port: u16) -> Result<(), Box<dyn std::error::Error>> {
    let url = format!("http://127.0.0.1:{port}/").parse()?;

    let theme = initial_theme();

    let mut builder = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        // A blank-looking title avoids WM fallback to the app identifier.
        .title(" ")
        .inner_size(1180.0, 840.0)
        .zoom_hotkeys_enabled(true)
        .min_inner_size(720.0, 520.0)
        .background_color(webview_background(&theme));

    let window_icon = app
        .default_window_icon()
        .cloned()
        .or_else(|| tauri::image::Image::from_bytes(WINDOW_ICON_PNG).ok());

    if let Some(icon) = window_icon {
        builder = builder.icon(icon)?;
    }

    #[cfg(target_os = "macos")]
    {
        builder = builder.title_bar_style(tauri::TitleBarStyle::Transparent);
    }

    let window = builder.build()?;
    set_window_theme(&window, &theme);
    spawn_theme_watcher(window.clone());

    Ok(())
}

/// Track the persisted theme so the chrome follows in-app toggles.
fn spawn_theme_watcher<R: tauri::Runtime>(window: tauri::WebviewWindow<R>) {
    thread::spawn(move || {
        let mut current = initial_theme();

        loop {
            thread::sleep(Duration::from_millis(750));

            let Some(next) = stored_theme() else {
                continue;
            };

            if next == current {
                continue;
            }

            current = next.clone();
            let target = window.clone();
            let _ = window.run_on_main_thread(move || set_window_theme(&target, &next));
        }
    });
}

fn set_window_theme<R: tauri::Runtime>(window: &tauri::WebviewWindow<R>, theme: &str) {
    let dark = is_dark_theme(theme);
    let native_theme = if dark {
        tauri::Theme::Dark
    } else {
        tauri::Theme::Light
    };

    let _ = window.set_theme(Some(native_theme));
    set_native_titlebar(window, dark);
}

/// Tint the Windows 11 caption and border to match the app backdrop.
#[cfg(windows)]
fn set_native_titlebar<R: tauri::Runtime>(window: &tauri::WebviewWindow<R>, dark: bool) {
    use windows::Win32::Graphics::Dwm::{
        DwmSetWindowAttribute, DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR,
    };

    let Ok(hwnd) = window.hwnd() else {
        return;
    };

    // COLORREF is 0x00BBGGRR, not RGB.
    let (caption, text, border): (u32, u32, u32) = if dark {
        (0x00463430, 0x00f5d0c6, 0x00594541)
    } else {
        (0x00f5f1ef, 0x00694f4c, 0x00dad0cc)
    };
    let size = std::mem::size_of::<u32>() as u32;

    unsafe {
        let _ = DwmSetWindowAttribute(
            hwnd,
            DWMWA_CAPTION_COLOR,
            &caption as *const u32 as *const core::ffi::c_void,
            size,
        );
        let _ = DwmSetWindowAttribute(
            hwnd,
            DWMWA_TEXT_COLOR,
            &text as *const u32 as *const core::ffi::c_void,
            size,
        );
        let _ = DwmSetWindowAttribute(
            hwnd,
            DWMWA_BORDER_COLOR,
            &border as *const u32 as *const core::ffi::c_void,
            size,
        );
    }
}

#[cfg(not(windows))]
fn set_native_titlebar<R: tauri::Runtime>(_window: &tauri::WebviewWindow<R>, _dark: bool) {}

/// Ask the bridge to stop, then force it down after a short grace period.
fn terminate(child: &mut Child) {
    if matches!(child.try_wait(), Ok(Some(_))) {
        return;
    }

    request_termination(child);
    let deadline = Instant::now() + Duration::from_secs(6);

    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => return,
            Ok(None) => thread::sleep(Duration::from_millis(100)),
            Err(_) => break,
        }
    }

    force_kill(child);
}

#[cfg(unix)]
fn request_termination(child: &mut Child) {
    let pid = child.id() as i32;
    let group_sent = unsafe { libc::kill(-pid, libc::SIGTERM) } == 0;
    let child_sent = group_sent || unsafe { libc::kill(pid, libc::SIGTERM) } == 0;

    if !child_sent {
        force_kill(child);
    }
}

#[cfg(not(unix))]
fn request_termination(child: &mut Child) {
    force_kill(child);
}

fn force_kill(child: &mut Child) {
    #[cfg(unix)]
    unsafe {
        libc::kill(-(child.id() as i32), libc::SIGKILL);
    }

    let _ = child.kill();
    let _ = child.wait();
}

/// Match the first paint to the persisted theme, then to the system scheme.
fn initial_theme() -> String {
    if let Some(stored) = stored_theme() {
        return stored;
    }

    if system_prefers_dark() {
        return DARK_THEME.to_string();
    }

    LIGHT_THEME.to_string()
}

/// Read `theme:` from the desktop config so the window opens in the right palette.
fn stored_theme() -> Option<String> {
    let home = env::var_os("HOME").or_else(|| env::var_os("USERPROFILE"))?;
    let path = env::var_os("CECLI_DESKTOP_FOLDERS_FILE")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(home).join(".cecli").join("desktop.yml"));

    let text = std::fs::read_to_string(path).ok()?;
    text.lines().find_map(|line| {
        let (key, value) = line.split_once(':')?;
        if key.trim() != "theme" {
            return None;
        }

        let value = value.trim().trim_matches(|ch| ch == '"' || ch == '\'');
        matches!(value, DARK_THEME | LIGHT_THEME).then(|| value.to_string())
    })
}

fn is_dark_theme(theme: &str) -> bool {
    theme.eq_ignore_ascii_case(DARK_THEME)
}

fn webview_background(theme: &str) -> tauri::webview::Color {
    if is_dark_theme(theme) {
        tauri::webview::Color(0x30, 0x34, 0x46, 0xff)
    } else {
        tauri::webview::Color(0xef, 0xf1, 0xf5, 0xff)
    }
}

#[cfg(target_os = "linux")]
fn system_prefers_dark() -> bool {
    use gtk::prelude::*;

    let Some(settings) = gtk::Settings::default() else {
        return false;
    };

    settings.is_gtk_application_prefer_dark_theme()
        || settings
            .gtk_theme_name()
            .is_some_and(|name| name.to_lowercase().contains("dark"))
}

#[cfg(not(target_os = "linux"))]
fn system_prefers_dark() -> bool {
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prepend_to_path_puts_runtime_bin_first() {
        let mut command = Command::new("python");
        prepend_to_path(&mut command, Path::new("/runtime/bin"));

        let path = command
            .get_envs()
            .find_map(|(key, value)| (key == "PATH").then_some(value))
            .flatten()
            .expect("PATH should be set");

        let first = std::env::split_paths(path).next().expect("PATH entry");

        assert_eq!(first, Path::new("/runtime/bin"));
    }

    #[test]
    fn configure_bridge_sets_utf8_stdio_encoding() {
        let mut command = Command::new("python");
        configure_bridge(&mut command, Path::new("/workspace"), 8000, None);

        let encoding = command
            .get_envs()
            .find_map(|(key, value)| (key == "PYTHONIOENCODING").then_some(value))
            .flatten()
            .expect("PYTHONIOENCODING should be set");

        assert_eq!(encoding, "utf-8");
    }
}
