#![cfg(windows)]

//! Window enumeration, selection, and integrity checks for the Windows backend.
//!
//! Every call re-enumerates the desktop; nothing is cached between requests. The
//! module also exposes the helpers later Windows tasks reuse: [`resolve_window`],
//! [`check_integrity`], [`is_same_window`], and [`ensure_mta`].

use std::ffi::c_void;
use std::mem::size_of;
use std::sync::mpsc;
use std::time::Duration;

use windows::core::{IUnknown, BOOL, PWSTR};
use windows::Win32::Foundation::{CloseHandle, HANDLE, HWND, LPARAM, RECT, RPC_E_CHANGED_MODE};
use windows::Win32::Graphics::Dwm::{
    DwmGetWindowAttribute, DWMWA_CLOAKED, DWMWA_EXTENDED_FRAME_BOUNDS,
};
use windows::Win32::Security::{
    GetSidSubAuthority, GetSidSubAuthorityCount, GetTokenInformation, TokenIntegrityLevel,
    TOKEN_MANDATORY_LABEL, TOKEN_QUERY,
};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::System::Threading::{
    OpenProcess, OpenProcessToken, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
    PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::Accessibility::{CUIAutomation, IUIAutomation};
use windows::Win32::UI::Input::KeyboardAndMouse::IsWindowEnabled;
use windows::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetClassNameW, GetForegroundWindow, GetGUIThreadInfo, GetWindow, GetWindowLongW,
    GetWindowRect, GetWindowTextLengthW, GetWindowTextW, GetWindowThreadProcessId, IsIconic,
    IsWindow, IsWindowVisible, GUITHREADINFO, GWL_STYLE, GW_OWNER, WS_POPUP,
};

use crate::protocol::{error_kind, Bounds, CheckResult, ErrorInfo, WindowInfo};

/// Visible, titled, non-cloaked top-level windows in z-order.
///
/// Invisible windows, empty titles, and DWM-cloaked windows (other virtual
/// desktops, suspended UWP apps) are skipped.
///
/// # Errors
///
/// Returns `backend_error` when `EnumWindows` itself fails.
pub fn enumerate_windows() -> Result<Vec<WindowInfo>, ErrorInfo> {
    let foreground = unsafe { GetForegroundWindow() };
    let mut context = EnumContext {
        foreground,
        windows: Vec::new(),
    };

    let result = unsafe {
        EnumWindows(
            Some(enum_window),
            LPARAM((&mut context as *mut EnumContext) as isize),
        )
    };

    match result {
        Ok(()) => Ok(context.windows),
        Err(error) => Err(ErrorInfo::new(
            error_kind::BACKEND_ERROR,
            format!("EnumWindows failed: {error}"),
        )),
    }
}

/// Cheap probe that `EnumWindows` is callable without touching any target.
pub fn probe_enumeration() -> bool {
    unsafe extern "system" fn skip(_hwnd: HWND, _lparam: LPARAM) -> BOOL {
        BOOL(1)
    }

    unsafe { EnumWindows(Some(skip), LPARAM(0)).is_ok() }
}

/// Resolve a window selector to one fresh [`WindowInfo`].
///
/// Accepted selectors, in priority order: a hexadecimal or decimal handle,
/// an exact case-insensitive title, a case-insensitive title substring, or a
/// process name with or without `.exe`. When a stage matches more than one
/// window, the foreground window wins, otherwise the first in z-order.
///
/// # Errors
///
/// `invalid_request` for an empty selector, `target_not_found` when nothing
/// matches, and any enumeration failure is passed through.
pub fn resolve_window(selector: &str) -> Result<WindowInfo, ErrorInfo> {
    let selector = selector.trim();
    if selector.is_empty() {
        return Err(ErrorInfo::new(
            error_kind::INVALID_REQUEST,
            "window selector is empty",
        ));
    }

    let windows = enumerate_windows()?;
    if windows.is_empty() {
        return Err(target_not_found(selector));
    }

    if let Some(handle) = parse_handle(selector) {
        if let Some(found) = windows
            .iter()
            .find(|window| parse_handle(&window.handle) == Some(handle))
        {
            return Ok(found.clone());
        }
    }

    let needle = selector.to_lowercase();
    if let Some(found) = pick_match(&windows, |window| window.title.to_lowercase() == needle) {
        return Ok(found.clone());
    }

    if let Some(found) = pick_match(&windows, |window| {
        window.title.to_lowercase().contains(&needle)
    }) {
        return Ok(found.clone());
    }

    if let Some(found) = pick_match(&windows, |window| {
        window
            .process_name
            .as_deref()
            .is_some_and(|name| process_name_matches(name, &needle))
    }) {
        return Ok(found.clone());
    }

    Err(target_not_found(selector))
}

/// Refuse a target whose integrity level is higher than the bridge's own.
///
/// A higher-integrity target rejects input injection through UIPI, so the bridge
/// fails before sending anything.
///
/// # Errors
///
/// `elevated_target` when the target is elevated or its token cannot be queried,
/// `backend_error` when the bridge's own token cannot be queried.
pub fn check_integrity(target: &WindowInfo) -> Result<(), ErrorInfo> {
    let target_rid = integrity_rid(target.pid).map_err(|error| {
        ErrorInfo::new(
            error_kind::ELEVATED_TARGET,
            format!(
                "cannot query integrity level for pid {}: {}",
                target.pid, error.message
            ),
        )
    })?;
    let bridge_rid = integrity_rid(std::process::id())?;

    if target_rid > bridge_rid {
        return Err(ErrorInfo::new(
            error_kind::ELEVATED_TARGET,
            format!(
                "target pid {} runs at integrity {target_rid:#x}, bridge at {bridge_rid:#x}",
                target.pid
            ),
        ));
    }

    Ok(())
}

/// True when `handle` still belongs to `pid` and names a live window.
///
/// Used before every send so a recycled `HWND` never receives input meant for a
/// closed target.
pub fn is_same_window(handle: &str, pid: u32) -> bool {
    let Some(hwnd) = parse_handle(handle) else {
        return false;
    };

    unsafe {
        if !IsWindow(Some(hwnd)).as_bool() {
            return false;
        }

        let mut current_pid = 0u32;
        GetWindowThreadProcessId(hwnd, Some(&mut current_pid));
        current_pid != 0 && current_pid == pid
    }
}

/// Initialize COM as multithreaded on the calling thread when it is not already
/// initialized with a compatible model.
///
/// `RPC_E_CHANGED_MODE` is tolerated: another component already put this thread
/// in a single-threaded apartment and UIA can still be used with marshalling.
pub fn ensure_mta() -> Result<(), ErrorInfo> {
    let result = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
    if result.is_ok() || result == RPC_E_CHANGED_MODE {
        return Ok(());
    }

    Err(ErrorInfo::new(
        error_kind::BACKEND_ERROR,
        format!(
            "CoInitializeEx(COINIT_MULTITHREADED) failed: 0x{:08X}",
            result.0
        ),
    ))
}

/// Diagnostic checks reported by `doctor`.
///
/// Covers Win32 enumeration, UI Automation creation on a dedicated MTA thread,
/// and that an input desktop is reachable.
pub fn doctor_checks() -> Vec<CheckResult> {
    vec![enumeration_check(), uia_com_check(), input_desktop_check()]
}

/// Parse a handle encoded by [`enumerate_windows`], accepting `0x` hex or
/// decimal.
pub(crate) fn parse_handle(value: &str) -> Option<HWND> {
    let value = value.trim();
    let raw = match value
        .strip_prefix("0x")
        .or_else(|| value.strip_prefix("0X"))
    {
        Some(hex) => u64::from_str_radix(hex, 16).ok()?,
        None => value.parse::<u64>().ok()?,
    };

    if raw == 0 {
        return None;
    }

    Some(HWND(raw as usize as *mut c_void))
}

fn encode_handle(hwnd: HWND) -> String {
    format!("0x{:X}", hwnd.0 as usize)
}

fn target_not_found(selector: &str) -> ErrorInfo {
    ErrorInfo::new(
        error_kind::TARGET_NOT_FOUND,
        format!("no visible window matches {selector:?}"),
    )
}

fn pick_match(
    windows: &[WindowInfo],
    predicate: impl Fn(&WindowInfo) -> bool,
) -> Option<&WindowInfo> {
    let mut first = None;
    for window in windows.iter().filter(|window| predicate(window)) {
        if window.foreground {
            return Some(window);
        }

        first.get_or_insert(window);
    }

    first
}

fn process_name_matches(process_name: &str, needle: &str) -> bool {
    let name = process_name.to_lowercase();
    strip_exe(&name) == strip_exe(needle)
}

fn strip_exe(value: &str) -> &str {
    value.strip_suffix(".exe").unwrap_or(value)
}

struct EnumContext {
    foreground: HWND,
    windows: Vec<WindowInfo>,
}

unsafe extern "system" fn enum_window(hwnd: HWND, lparam: LPARAM) -> BOOL {
    let context = unsafe { &mut *(lparam.0 as *mut EnumContext) };
    let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        if let Some(info) = unsafe { describe_window(hwnd, context.foreground) } {
            context.windows.push(info);
        }
    }));

    BOOL(1)
}

unsafe fn describe_window(hwnd: HWND, foreground: HWND) -> Option<WindowInfo> {
    if !unsafe { IsWindowVisible(hwnd).as_bool() } {
        return None;
    }

    if unsafe { is_cloaked(hwnd) } {
        return None;
    }

    let title = unsafe { window_title(hwnd) }?;

    let mut pid = 0u32;
    unsafe { GetWindowThreadProcessId(hwnd, Some(&mut pid)) };
    if pid == 0 {
        return None;
    }

    let class_name = unsafe { window_class(hwnd) };
    let dialog = class_name
        .as_deref()
        .is_some_and(crate::dialog::class_is_dialog)
        || unsafe { is_owned_popup(hwnd) };
    Some(WindowInfo {
        handle: encode_handle(hwnd),
        pid,
        process_name: process_name(pid),
        title,
        class_name,
        dialog,
        bounds: unsafe { window_bounds(hwnd) },
        foreground: hwnd == foreground,
        enabled: unsafe { IsWindowEnabled(hwnd).as_bool() },
        offscreen: unsafe { IsIconic(hwnd).as_bool() },
    })
}

unsafe fn is_cloaked(hwnd: HWND) -> bool {
    let mut cloaked = 0u32;
    let result = unsafe {
        DwmGetWindowAttribute(
            hwnd,
            DWMWA_CLOAKED,
            (&mut cloaked as *mut u32).cast(),
            size_of::<u32>() as u32,
        )
    };

    result.is_ok() && cloaked != 0
}

unsafe fn is_owned_popup(hwnd: HWND) -> bool {
    let Ok(owner) = (unsafe { GetWindow(hwnd, GW_OWNER) }) else {
        return false;
    };
    if owner.is_invalid() {
        return false;
    }

    let style = unsafe { GetWindowLongW(hwnd, GWL_STYLE) } as u32;

    style & WS_POPUP.0 != 0
}
unsafe fn window_title(hwnd: HWND) -> Option<String> {
    let length = unsafe { GetWindowTextLengthW(hwnd) };
    if length <= 0 {
        return None;
    }

    let mut buffer = vec![0u16; length as usize + 1];
    let copied = unsafe { GetWindowTextW(hwnd, &mut buffer) };
    if copied <= 0 {
        return None;
    }

    let title = String::from_utf16_lossy(&buffer[..copied as usize]);
    (!title.trim().is_empty()).then_some(title)
}

unsafe fn window_class(hwnd: HWND) -> Option<String> {
    let mut buffer = [0u16; 256];
    let copied = unsafe { GetClassNameW(hwnd, &mut buffer) };
    if copied <= 0 {
        return None;
    }

    let class_name = String::from_utf16_lossy(&buffer[..copied as usize]);
    (!class_name.is_empty()).then_some(class_name)
}

unsafe fn window_bounds(hwnd: HWND) -> Bounds {
    let mut rect = RECT::default();
    let mut has_dwm_bounds = unsafe {
        DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            (&mut rect as *mut RECT).cast(),
            size_of::<RECT>() as u32,
        )
    }
    .is_ok()
        && rect.right > rect.left
        && rect.bottom > rect.top;

    if !has_dwm_bounds {
        rect = RECT::default();
        has_dwm_bounds = unsafe { GetWindowRect(hwnd, &mut rect) }.is_ok();
    }

    if !has_dwm_bounds {
        return Bounds::default();
    }

    Bounds {
        left: rect.left,
        top: rect.top,
        width: (rect.right - rect.left).max(0),
        height: (rect.bottom - rect.top).max(0),
    }
}

fn process_name(pid: u32) -> Option<String> {
    if pid == 0 {
        return None;
    }

    let process = OwnedHandle::new(
        unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }.ok()?,
    );
    let mut buffer = [0u16; 32_768];
    let mut length = buffer.len() as u32;
    unsafe {
        QueryFullProcessImageNameW(
            process.get(),
            PROCESS_NAME_WIN32,
            PWSTR(buffer.as_mut_ptr()),
            &mut length,
        )
    }
    .ok()?;

    let path = String::from_utf16_lossy(&buffer[..length as usize]);
    path.rsplit(['\\', '/'])
        .next()
        .filter(|name| !name.is_empty())
        .map(str::to_string)
}

fn integrity_rid(pid: u32) -> Result<u32, ErrorInfo> {
    let process = OwnedHandle::new(
        unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }.map_err(|error| {
            ErrorInfo::new(
                error_kind::BACKEND_ERROR,
                format!("OpenProcess(pid {pid}) failed: {error}"),
            )
        })?,
    );

    let mut token = HANDLE::default();
    unsafe { OpenProcessToken(process.get(), TOKEN_QUERY, &mut token) }.map_err(|error| {
        ErrorInfo::new(
            error_kind::BACKEND_ERROR,
            format!("OpenProcessToken(pid {pid}) failed: {error}"),
        )
    })?;
    let token = OwnedHandle::new(token);

    let mut needed = 0u32;
    let _ = unsafe { GetTokenInformation(token.get(), TokenIntegrityLevel, None, 0, &mut needed) };
    if needed == 0 {
        return Err(ErrorInfo::new(
            error_kind::BACKEND_ERROR,
            format!("GetTokenInformation(pid {pid}) returned no buffer size"),
        ));
    }

    let words = (needed as usize).div_ceil(size_of::<u64>());
    let mut buffer = vec![0u64; words];
    let mut returned = 0u32;
    unsafe {
        GetTokenInformation(
            token.get(),
            TokenIntegrityLevel,
            Some(buffer.as_mut_ptr().cast()),
            (buffer.len() * size_of::<u64>()) as u32,
            &mut returned,
        )
    }
    .map_err(|error| {
        ErrorInfo::new(
            error_kind::BACKEND_ERROR,
            format!("GetTokenInformation(pid {pid}) failed: {error}"),
        )
    })?;

    let label = buffer.as_ptr() as *const TOKEN_MANDATORY_LABEL;
    let count = unsafe { GetSidSubAuthorityCount((*label).Label.Sid) };
    if count.is_null() {
        return Err(ErrorInfo::new(
            error_kind::BACKEND_ERROR,
            format!("integrity SID for pid {pid} has no sub-authority count"),
        ));
    }

    let last = unsafe { *count }.saturating_sub(1);
    let rid = unsafe { GetSidSubAuthority((*label).Label.Sid, u32::from(last)) };
    if rid.is_null() {
        return Err(ErrorInfo::new(
            error_kind::BACKEND_ERROR,
            format!("integrity SID for pid {pid} has no sub-authority"),
        ));
    }

    Ok(unsafe { *rid })
}

fn enumeration_check() -> CheckResult {
    match enumerate_windows() {
        Ok(windows) => CheckResult::new(
            "window_enumeration",
            true,
            format!("enumerated {} visible window(s)", windows.len()),
        ),
        Err(error) => CheckResult::new("window_enumeration", false, error.message),
    }
}

fn uia_com_check() -> CheckResult {
    let (sender, receiver) = mpsc::channel();
    let worker = std::thread::Builder::new()
        .name("ce-app-bridge-uia-doctor".to_string())
        .spawn(move || {
            let result = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
            if result.is_err() && result != RPC_E_CHANGED_MODE {
                let _ = sender.send(Err(format!(
                    "CoInitializeEx(MTA) failed: 0x{:08X}",
                    result.0
                )));
                return;
            }

            let should_uninitialize = result.is_ok();
            let outcome = create_automation().map(|_| ());
            if should_uninitialize {
                unsafe { CoUninitialize() };
            }

            let _ = sender.send(outcome);
        });

    if let Err(error) = worker {
        return CheckResult::new(
            "uia_com",
            false,
            format!("cannot start UIA probe thread: {error}"),
        );
    }

    match receiver.recv_timeout(Duration::from_secs(2)) {
        Ok(Ok(())) => CheckResult::new("uia_com", true, "CUIAutomation created on an MTA thread"),
        Ok(Err(error)) => CheckResult::new("uia_com", false, error),
        Err(_) => CheckResult::new("uia_com", false, "UIA probe timed out after 2s"),
    }
}

fn create_automation() -> Result<IUIAutomation, String> {
    let automation: IUIAutomation =
        unsafe { CoCreateInstance(&CUIAutomation, None::<&IUnknown>, CLSCTX_INPROC_SERVER) }
            .map_err(|error| format!("CoCreateInstance(CUIAutomation) failed: {error}"))?;

    let condition = unsafe { automation.CreateTrueCondition() }
        .map_err(|error| format!("CreateTrueCondition failed: {error}"))?;
    drop(condition);

    Ok(automation)
}

fn input_desktop_check() -> CheckResult {
    unsafe {
        let foreground = GetForegroundWindow();
        if foreground.is_invalid() {
            return CheckResult::new(
                "input_desktop",
                false,
                "no foreground window; the input desktop may be locked",
            );
        }

        let mut pid = 0u32;
        let thread = GetWindowThreadProcessId(foreground, Some(&mut pid));
        if thread == 0 {
            return CheckResult::new(
                "input_desktop",
                false,
                "foreground window has no owning thread",
            );
        }

        let mut info = GUITHREADINFO {
            cbSize: size_of::<GUITHREADINFO>() as u32,
            ..Default::default()
        };
        match GetGUIThreadInfo(thread, &mut info) {
            Ok(()) => CheckResult::new(
                "input_desktop",
                true,
                format!(
                    "foreground window {} on thread {thread} (pid {pid})",
                    encode_handle(foreground)
                ),
            ),
            Err(error) => CheckResult::new(
                "input_desktop",
                false,
                format!("GetGUIThreadInfo(thread {thread}) failed: {error}"),
            ),
        }
    }
}

struct OwnedHandle(HANDLE);

impl OwnedHandle {
    fn new(handle: HANDLE) -> Self {
        Self(handle)
    }

    fn get(&self) -> HANDLE {
        self.0
    }
}

impl Drop for OwnedHandle {
    fn drop(&mut self) {
        let _ = unsafe { CloseHandle(self.0) };
    }
}
