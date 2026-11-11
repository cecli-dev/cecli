use std::env;
use std::io;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// Owns the Python bridge child process for the lifetime of the application.
struct BridgeState(Mutex<Option<Child>>);

static RESOURCE_DIR: OnceLock<Option<PathBuf>> = OnceLock::new();

static APP_DATA_DIR: OnceLock<Option<PathBuf>> = OnceLock::new();

fn main() {
    #[cfg(target_os = "linux")]
    configure_webkit();

    let app = match tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(|app| {
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
        }
    });
}

/// Force WebKitGTK's software rendering paths, which avoid blank or flickering
/// windows under some Linux and WSL GPU stacks.
#[cfg(target_os = "linux")]
fn configure_webkit() {
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

    if let Some(dir) = current_exe_dir() {
        candidates.push(dir.join(uv_binary_name()));
    }

    if let Some(dir) = resource_dir() {
        candidates.push(dir.join(uv_binary_name()));
        candidates.push(dir.join("_up_").join(uv_binary_name()));
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
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .arg("--workspace")
        .arg(workspace)
        // The AppImage AppRun exports PYTHONHOME/PYTHONPATH for its own layout.
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH")
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
        .find(|path| path.is_file())
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

    let mut builder = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        // A blank-looking title avoids WM fallback to the app identifier.
        .title(" ")
        .inner_size(1180.0, 840.0)
        .min_inner_size(720.0, 520.0)
        .theme(Some(tauri::Theme::Light))
        .background_color(tauri::webview::Color(242, 240, 255, 255));

    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone())?;
    }

    #[cfg(target_os = "macos")]
    {
        builder = builder.title_bar_style(tauri::TitleBarStyle::Transparent);
    }

    let window = builder.build()?;
    set_native_titlebar(&window);

    Ok(())
}

/// Tint the Windows 11 caption and border to match the app backdrop.
#[cfg(windows)]
fn set_native_titlebar<R: tauri::Runtime>(window: &tauri::WebviewWindow<R>) {
    use windows::Win32::Graphics::Dwm::{
        DwmSetWindowAttribute, DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR,
    };

    let Ok(hwnd) = window.hwnd() else {
        return;
    };
    // COLORREF is 0x00BBGGRR, not RGB.
    let caption: u32 = 0x00fff0f2;
    let text: u32 = 0x0033231f;
    let border: u32 = 0x00eae6e6;
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
fn set_native_titlebar<R: tauri::Runtime>(_window: &tauri::WebviewWindow<R>) {}

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
