use std::env;
use std::io;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// Owns the Python bridge child process for the lifetime of the application.
struct BridgeState(Mutex<Option<Child>>);

fn main() {
    #[cfg(target_os = "linux")]
    configure_webkit();

    let app = match tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(|app| {
            let workspace = resolve_workspace();
            eprintln!("cecli desktop workspace: {}", workspace.display());
            let port = resolve_port()?;
            let script = locate_bridge_script(app.handle())?;
            let mut child = spawn_bridge(&script, &workspace, port)?;

            if let Err(err) = wait_for_bridge(&mut child, port) {
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

/// Find server.py: env override, dev tree, then bundled resource locations.
fn locate_bridge_script(app: &AppHandle) -> io::Result<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Some(value) = env::var_os("CECLI_DESKTOP_SERVER") {
        if !value.is_empty() {
            candidates.push(PathBuf::from(value));
        }
    }

    if let Some(dev_root) = Path::new(env!("CARGO_MANIFEST_DIR")).parent() {
        candidates.push(dev_root.join("server.py"));
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("server.py"));
        candidates.push(resource_dir.join("_up_").join("server.py"));
    }

    if let Some(found) = candidates.iter().find(|path| path.is_file()) {
        return Ok(found.clone());
    }

    let tried = candidates
        .iter()
        .map(|path| path.display().to_string())
        .collect::<Vec<_>>()
        .join(", ");

    Err(io::Error::new(
        io::ErrorKind::NotFound,
        format!("cecli desktop bridge script not found; tried: {tried}"),
    ))
}

/// Launch the bridge, honoring CECLI_PYTHON and the Windows python fallback.
fn spawn_bridge(script: &Path, workspace: &Path, port: u16) -> io::Result<Child> {
    let mut last_error = None;

    for python in python_candidates(script) {
        let mut command = Command::new(&python);
        command
            .arg(script)
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg(port.to_string())
            .arg("--workspace")
            .arg(workspace)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit());

        if let Some(cecli) = cecli_override() {
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

        match command.spawn() {
            Ok(child) => return Ok(child),
            Err(err) => last_error = Some(err),
        }
    }

    Err(last_error.unwrap_or_else(|| {
        io::Error::new(io::ErrorKind::NotFound, "no Python interpreter available")
    }))
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
fn wait_for_bridge(child: &mut Child, port: u16) -> io::Result<()> {
    let deadline = Instant::now() + Duration::from_secs(30);
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
