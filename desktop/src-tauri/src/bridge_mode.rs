//! Command-line modes for the `ce-underscore` binary.
//!
//! Tauri, GTK, and WebKit must not initialize unless the desktop window is
//! actually requested. `main` parses the arguments through [`parse_mode`]
//! before it touches `tauri::Builder`, then dispatches every non-desktop mode
//! through [`run`].
//!
//! The bridge implementation lives in `ce-app-bridge`; this module only maps
//! arguments onto the crate's process entry points and makes their output
//! visible from a Windows GUI build.

use std::ffi::OsString;
use std::path::PathBuf;

use ce_app_bridge::server;

#[cfg(windows)]
use std::sync::atomic::{AtomicBool, Ordering};

/// Which entry point the current process should run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Mode {
    /// Open the desktop window; the default for anything unrecognized.
    Desktop,
    /// Serve the app-harness bridge in the foreground.
    Bridge { foreground: bool },
    /// Start a detached bridge if no healthy one exists, then exit.
    EnsureBridge,
    /// Print bridge status as JSON.
    Status,
    /// Ask the running bridge to shut down.
    Stop,
    /// Forward the remaining arguments to the app-harness CLI.
    HarnessCli(Vec<String>),
    /// Print the mode list.
    Help,
    /// Print the package version.
    Version,
}

/// Parse arguments that follow the program name.
///
/// Unknown arguments resolve to [`Mode::Desktop`] so a positional workspace
/// path keeps its historical meaning. `-psn_*` tokens are ignored: macOS adds
/// them when the app is launched from Finder.
pub fn parse_mode<I: IntoIterator<Item = OsString>>(args: I) -> Mode {
    let mut bridge = false;
    let mut ensure = false;
    let mut status = false;
    let mut stop = false;
    let mut help = false;
    let mut version = false;
    let mut foreground = false;

    let mut harness: Option<Vec<String>> = None;
    let mut forwarding = false;

    for arg in args {
        let Some(arg) = arg.to_str() else {
            continue;
        };

        if forwarding {
            if let Some(list) = harness.as_mut() {
                list.push(arg.to_string());
            }

            continue;
        }

        if arg == "app-harness" {
            harness = Some(Vec::new());
            forwarding = true;
            continue;
        }

        if arg.starts_with("-psn_") {
            continue;
        }

        match arg {
            "--app-harness" => bridge = true,
            "--foreground" => foreground = true,
            "--ensure-bridge" => ensure = true,
            "--bridge-status" => status = true,
            "--stop-bridge" => stop = true,
            "--help" | "-h" => help = true,
            "--version" | "-V" => version = true,
            _ => {}
        }
    }

    // Run modes win over help/version so `--app-harness --help` still starts
    // a bridge; a positional workspace path leaves the desktop path alone.
    if bridge {
        return Mode::Bridge { foreground };
    }

    if ensure {
        return Mode::EnsureBridge;
    }

    if status {
        return Mode::Status;
    }

    if stop {
        return Mode::Stop;
    }

    // `ce-underscore app-harness <args>` forwards to the CLI so the bundled
    // binary can stand in for an unavailable `app-harness` command.
    if let Some(args) = harness {
        return Mode::HarnessCli(args);
    }

    if help {
        return Mode::Help;
    }

    if version {
        return Mode::Version;
    }

    Mode::Desktop
}

/// Execute a mode and return the process exit code.
///
/// `Mode::Desktop` is dispatched directly by `main`; returning 0 here keeps the
/// enum exhaustive without linking Tauri window code into this module.
pub fn run(mode: Mode) -> i32 {
    if !matches!(mode, Mode::Desktop) {
        attach_console();
    }

    match mode {
        Mode::Desktop => 0,
        Mode::Bridge { foreground } => report(server::run_foreground(foreground)),
        Mode::EnsureBridge => report(server::ensure_bridge()),
        Mode::Status => report(server::status()),
        Mode::Stop => report(server::stop()),
        Mode::HarnessCli(args) => run_harness_cli(&args),
        Mode::Help => print_help(),
        Mode::Version => print_version(),
    }
}

#[cfg(windows)]
static CONSOLE_READY: AtomicBool = AtomicBool::new(false);

/// Point stdout/stderr at the parent console for a Windows GUI build.
///
/// `AttachConsole` only joins the console; Rust caches the standard handle on
/// first use, so the handles must be replaced before any status line is print.
/// When no console is reachable, the exit code stays authoritative and
/// [`fallback_log`] keeps the diagnostic discoverable.
#[cfg(windows)]
fn attach_console() {
    use std::os::windows::io::IntoRawHandle;

    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::System::Console::{
        AttachConsole, GetStdHandle, SetStdHandle, ATTACH_PARENT_PROCESS, STD_ERROR_HANDLE,
        STD_OUTPUT_HANDLE,
    };

    unsafe {
        // A debug shell already owns a console; keep its handles untouched.
        if GetStdHandle(STD_OUTPUT_HANDLE).is_ok_and(|handle| !handle.is_invalid()) {
            CONSOLE_READY.store(true, Ordering::SeqCst);
            return;
        }

        let _ = AttachConsole(ATTACH_PARENT_PROCESS);

        let Ok(file) = std::fs::OpenOptions::new().write(true).open("CONOUT$") else {
            return;
        };

        // The handle must outlive the process; leaking the File is deliberate.
        let handle = HANDLE(file.into_raw_handle());

        if SetStdHandle(STD_OUTPUT_HANDLE, handle).is_ok()
            && SetStdHandle(STD_ERROR_HANDLE, handle).is_ok()
        {
            CONSOLE_READY.store(true, Ordering::SeqCst);
        }
    }
}

#[cfg(not(windows))]
fn attach_console() {}

/// Print one user-facing line, mirroring it to the app-data log on Windows
/// when no console could be attached.
fn write_line(line: &str) {
    println!("{line}");

    #[cfg(windows)]
    if !CONSOLE_READY.load(Ordering::SeqCst) {
        fallback_log(line);
    }
}

/// Append a line to `%LOCALAPPDATA%\cecli\bridge-mode.log`.
#[cfg(windows)]
fn fallback_log(line: &str) {
    use std::io::Write;

    let Some(base) = std::env::var_os("LOCALAPPDATA") else {
        return;
    };

    let dir = std::path::PathBuf::from(base).join("cecli");
    let _ = std::fs::create_dir_all(&dir);

    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("bridge-mode.log"))
    {
        let _ = writeln!(file, "{line}");
    }
}

/// Forward arguments to the app-harness CLI.
///
/// Release bundles run the CLI from the uv-managed runtime. Development builds
/// fall back to a Python on `PATH`, overridable with `CECLI_HARNESS_PYTHON`.
fn run_harness_cli(args: &[String]) -> i32 {
    let mut command = match harness_command() {
        Ok(command) => command,
        Err(message) => {
            write_line(&format!("ce-underscore: {message}"));
            return 4;
        }
    };

    match command.args(args).status() {
        Ok(status) => status.code().unwrap_or(1),
        Err(error) => {
            write_line(&format!("ce-underscore: cannot run app-harness: {error}"));
            4
        }
    }
}

fn harness_command() -> Result<std::process::Command, String> {
    if let Some(uv) = crate::bundled_uv() {
        let runtime = crate::ensure_runtime(&uv)
            .map_err(|error| format!("cannot provision the app-harness runtime: {error}"))?;

        let mut command = python_command(runtime.python.clone());
        if let Some(bin_dir) = runtime.python.parent() {
            crate::prepend_to_path(&mut command, bin_dir);
        }

        return Ok(command);
    }

    if let Some(python) = std::env::var_os("CECLI_HARNESS_PYTHON").filter(|value| !value.is_empty())
    {
        return Ok(python_command(PathBuf::from(python)));
    }

    let names: &[&str] = if cfg!(windows) {
        &["python.exe", "python3.exe"]
    } else {
        &["python3", "python"]
    };

    for name in names {
        if let Some(path) = on_path(name) {
            return Ok(python_command(path));
        }
    }

    Err("no bundled runtime and no Python on PATH; set CECLI_HARNESS_PYTHON".to_string())
}

fn python_command(python: PathBuf) -> std::process::Command {
    let mut command = std::process::Command::new(python);
    command
        .arg("-m")
        .arg("cecli.helpers.app_harness.cli")
        .env_remove("PYTHONHOME")
        .env_remove("PYTHONPATH");
    command
}

fn on_path(name: &str) -> Option<PathBuf> {
    std::env::split_paths(&std::env::var_os("PATH")?)
        .map(|directory| directory.join(name))
        .find(|candidate| candidate.is_file())
}
/// Prefix a failing bridge command so mixed CLI output stays attributable.
fn report(code: i32) -> i32 {
    if code != 0 {
        write_line(&format!(
            "ce-underscore: bridge command failed (exit {code})"
        ));
    }

    code
}

fn print_help() -> i32 {
    for line in [
        "Usage: ce-underscore [WORKSPACE]",
        "",
        "Without a mode the desktop window opens; a positional argument selects the workspace.",
        "",
        "Modes:",
        "  --app-harness               Run the app-harness bridge in the foreground.",
        "  --app-harness --foreground  Same, with log lines on stderr.",
        "  --ensure-bridge             Start the bridge if absent, then exit.",
        "  --bridge-status             Print bridge status as JSON.",
        "  --stop-bridge               Stop the running bridge.",
        "  app-harness <args...>       Forward to the app-harness CLI.",
        "  --version, -V               Print the version.",
        "  --help, -h                  Print this help.",
    ] {
        write_line(line);
    }

    0
}

fn print_version() -> i32 {
    write_line(&format!("ce-underscore {}", env!("CARGO_PKG_VERSION")));
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mode(args: &[&str]) -> Mode {
        parse_mode(args.iter().map(OsString::from))
    }

    #[test]
    fn cli_forwards_flags_verbatim() {
        assert_eq!(
            mode(&["app-harness", "--json", "state"]),
            Mode::HarnessCli(vec!["--json".to_string(), "state".to_string()])
        )
    }

    #[test]
    fn no_arguments_open_desktop() {
        assert_eq!(mode(&[]), Mode::Desktop);
    }

    #[test]
    fn workspace_argument_keeps_desktop() {
        assert_eq!(mode(&["/tmp/workspace"]), Mode::Desktop);
    }

    #[test]
    fn unknown_flags_keep_desktop() {
        assert_eq!(mode(&["--not-a-mode"]), Mode::Desktop);
    }

    #[test]
    fn macos_process_serial_number_is_ignored() {
        assert_eq!(mode(&["-psn_0_123456"]), Mode::Desktop);
        assert_eq!(
            mode(&["-psn_0_123456", "--app-harness"]),
            Mode::Bridge { foreground: false }
        );
    }

    #[test]
    fn app_harness_runs_foreground_bridge() {
        assert_eq!(mode(&["--app-harness"]), Mode::Bridge { foreground: false });
        assert_eq!(
            mode(&["--app-harness", "--foreground"]),
            Mode::Bridge { foreground: true }
        );
        assert_eq!(
            mode(&["--foreground", "--app-harness"]),
            Mode::Bridge { foreground: true }
        );
    }

    #[test]
    fn foreground_without_app_harness_keeps_desktop() {
        assert_eq!(mode(&["--foreground"]), Mode::Desktop);
    }

    #[test]
    fn management_modes_parse() {
        assert_eq!(mode(&["--ensure-bridge"]), Mode::EnsureBridge);
        assert_eq!(mode(&["--bridge-status"]), Mode::Status);
        assert_eq!(mode(&["--stop-bridge"]), Mode::Stop);
    }

    #[test]
    fn help_and_version_parse() {
        assert_eq!(mode(&["--help"]), Mode::Help);
        assert_eq!(mode(&["-h"]), Mode::Help);
        assert_eq!(mode(&["--version"]), Mode::Version);
        assert_eq!(mode(&["-V"]), Mode::Version);
    }

    #[test]
    fn run_mode_wins_over_help() {
        assert_eq!(
            mode(&["--help", "--app-harness"]),
            Mode::Bridge { foreground: false }
        );
    }
    #[test]
    fn positional_app_harness_forwards_to_cli() {
        assert_eq!(
            mode(&["app-harness", "state", "--json"]),
            Mode::HarnessCli(vec!["state".to_string(), "--json".to_string()])
        );
    }

    #[test]
    fn app_harness_flag_still_serves_the_bridge() {
        assert_eq!(
            mode(&["--app-harness", "app-harness", "state"]),
            Mode::Bridge { foreground: false }
        );
    }
}
