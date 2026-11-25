//! Windows window capture owned by T9.
//!
//! `capture` is wired from [`super::WindowsBackend::screenshot`]. It renders a
//! window with `PrintWindow`/`PW_RENDERFULLCONTENT` into a top-down 32-bit DIB
//! and falls back to `BitBlt` from the window DC. Pixel conversion and PNG
//! encoding are platform-independent; only the Win32 module is gated.

use crate::protocol::{error_kind, ErrorInfo, WindowInfo};

/// Capture one visible window as PNG bytes.
///
/// # Errors
///
/// `target_not_found` when the handle is invalid, closed, or reused;
/// `capture_excluded` for cloaked or capture-protected windows, and when both
/// capture paths return an empty frame; `backend_error` for GDI failures;
/// `invalid_request` when the window has no usable size.
#[cfg(windows)]
pub fn capture(window: &WindowInfo) -> Result<Vec<u8>, ErrorInfo> {
    let (width, height, rgba) = win32::capture_rgba(window)?;
    encode_png(width, height, &rgba)
}

/// Encode tightly packed RGBA pixels as PNG bytes.
pub(crate) fn encode_png(width: u32, height: u32, rgba: &[u8]) -> Result<Vec<u8>, ErrorInfo> {
    let expected = rgba_len(width, height)?;
    if rgba.len() != expected {
        return Err(ErrorInfo::new(
            error_kind::INVALID_REQUEST,
            format!("RGBA buffer has {} bytes, expected {expected}", rgba.len()),
        ));
    }

    let mut output = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut output, width, height);
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        let mut writer = encoder.write_header().map_err(|error| {
            ErrorInfo::new(
                error_kind::BACKEND_ERROR,
                format!("PNG header encoding failed: {error}"),
            )
        })?;
        writer.write_image_data(rgba).map_err(|error| {
            ErrorInfo::new(
                error_kind::BACKEND_ERROR,
                format!("PNG image encoding failed: {error}"),
            )
        })?;
    }

    Ok(output)
}

/// Convert a 32-bit BGRA/BGRX DIB into tightly packed RGBA with opaque alpha.
pub(crate) fn dib_to_rgba(
    width: u32,
    height: u32,
    dib: &[u8],
    top_down: bool,
) -> Result<Vec<u8>, ErrorInfo> {
    let expected = rgba_len(width, height)?;
    if dib.len() != expected {
        return Err(ErrorInfo::new(
            error_kind::INVALID_REQUEST,
            format!("DIB buffer has {} bytes, expected {expected}", dib.len()),
        ));
    }

    let width = width as usize;
    let height = height as usize;
    let stride = width * 4;
    let mut rgba = vec![0u8; expected];

    for y in 0..height {
        let source_row = if top_down { y } else { height - 1 - y };
        let source = &dib[source_row * stride..(source_row + 1) * stride];
        let destination = &mut rgba[y * stride..(y + 1) * stride];

        for (pixel, target) in source.chunks_exact(4).zip(destination.chunks_exact_mut(4)) {
            target[0] = pixel[2];
            target[1] = pixel[1];
            target[2] = pixel[0];
            target[3] = 255;
        }
    }

    Ok(rgba)
}

fn rgba_len(width: u32, height: u32) -> Result<usize, ErrorInfo> {
    if width == 0 || height == 0 {
        return Err(ErrorInfo::new(
            error_kind::INVALID_REQUEST,
            "image dimensions must be non-zero",
        ));
    }

    (width as usize)
        .checked_mul(height as usize)
        .and_then(|pixels| pixels.checked_mul(4))
        .ok_or_else(|| {
            ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                "image dimensions are too large",
            )
        })
}

#[cfg(windows)]
mod win32 {
    use std::ffi::c_void;
    use std::mem::size_of;
    use std::ptr;

    use windows::Win32::Foundation::{GetLastError, HWND, RECT};
    use windows::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_CLOAKED};
    use windows::Win32::Graphics::Gdi::{
        BitBlt, CreateCompatibleDC, CreateDIBSection, DeleteDC, DeleteObject, GetWindowDC,
        ReleaseDC, SelectObject, BITMAPINFO, BITMAPINFOHEADER, BI_RGB, CAPTUREBLT, DIB_RGB_COLORS,
        HBITMAP, HDC, HGDIOBJ, ROP_CODE, SRCCOPY,
    };
    use windows::Win32::UI::WindowsAndMessaging::{
        GetWindowDisplayAffinity, GetWindowRect, IsWindow, WDA_EXCLUDEFROMCAPTURE, WDA_MONITOR,
    };

    use super::{dib_to_rgba, ErrorInfo, WindowInfo};
    use crate::protocol::error_kind;
    use crate::windows::enumerate;

    const PW_RENDERFULLCONTENT: u32 = 0x2;

    #[link(name = "user32")]
    extern "system" {
        fn PrintWindow(hwnd: HWND, hdc_blt: HDC, flags: u32) -> i32;
    }

    /// Capture the window into tightly packed RGBA plus its dimensions.
    pub(super) fn capture_rgba(window: &WindowInfo) -> Result<(u32, u32, Vec<u8>), ErrorInfo> {
        let hwnd = resolve(window)?;
        reject_excluded(hwnd)?;
        let (width, height) = capture_size(hwnd, window)?;
        let dib = MemoryDib::create(width, height)?;
        render(hwnd, &dib, width, height)?;
        let rgba = dib_to_rgba(width as u32, height as u32, dib.bytes(), true)?;
        Ok((width as u32, height as u32, rgba))
    }

    fn resolve(window: &WindowInfo) -> Result<HWND, ErrorInfo> {
        let hwnd = enumerate::parse_handle(&window.handle).ok_or_else(|| {
            ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                format!("invalid window handle {:?}", window.handle),
            )
        })?;

        if !unsafe { IsWindow(Some(hwnd)) }.as_bool() {
            return Err(ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                "target window closed before capture",
            ));
        }

        if !enumerate::is_same_window(&window.handle, window.pid) {
            return Err(ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                "target window handle was reused before capture",
            ));
        }

        Ok(hwnd)
    }

    fn reject_excluded(hwnd: HWND) -> Result<(), ErrorInfo> {
        let mut cloaked = 0u32;
        let cloaked_ok = unsafe {
            DwmGetWindowAttribute(
                hwnd,
                DWMWA_CLOAKED,
                (&mut cloaked as *mut u32).cast(),
                size_of::<u32>() as u32,
            )
        }
        .is_ok();
        if cloaked_ok && cloaked != 0 {
            return Err(ErrorInfo::new(
                error_kind::CAPTURE_EXCLUDED,
                "the window is cloaked by the desktop compositor",
            ));
        }

        let mut affinity = 0u32;
        if unsafe { GetWindowDisplayAffinity(hwnd, &mut affinity) }.is_ok()
            && affinity & (WDA_EXCLUDEFROMCAPTURE.0 | WDA_MONITOR.0) != 0
        {
            return Err(ErrorInfo::new(
                error_kind::CAPTURE_EXCLUDED,
                "the window opts out of screen capture",
            ));
        }

        Ok(())
    }

    fn capture_size(hwnd: HWND, window: &WindowInfo) -> Result<(i32, i32), ErrorInfo> {
        let mut rect = RECT::default();
        if unsafe { GetWindowRect(hwnd, &mut rect) }.is_ok() {
            let width = rect.right - rect.left;
            let height = rect.bottom - rect.top;
            if width > 0 && height > 0 {
                return Ok((width, height));
            }
        }

        let width = window.bounds.width;
        let height = window.bounds.height;
        if width <= 0 || height <= 0 {
            return Err(ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                format!("window has an empty capture area ({width}x{height})"),
            ));
        }

        Ok((width, height))
    }

    fn render(hwnd: HWND, dib: &MemoryDib, width: i32, height: i32) -> Result<(), ErrorInfo> {
        let printed = unsafe { PrintWindow(hwnd, dib.dc, PW_RENDERFULLCONTENT) } != 0;
        if printed && !is_blank(dib.bytes()) {
            return Ok(());
        }

        if !unsafe { IsWindow(Some(hwnd)) }.as_bool() {
            return Err(ErrorInfo::new(
                error_kind::TARGET_NOT_FOUND,
                "target window closed during capture",
            ));
        }

        blit(hwnd, dib, width, height)?;
        if is_blank(dib.bytes()) {
            return Err(ErrorInfo::new(
                error_kind::CAPTURE_EXCLUDED,
                "PrintWindow and BitBlt both produced an empty frame; the window may be capture-protected",
            ));
        }

        Ok(())
    }

    fn blit(hwnd: HWND, dib: &MemoryDib, width: i32, height: i32) -> Result<(), ErrorInfo> {
        let window_dc = unsafe { GetWindowDC(Some(hwnd)) };
        if window_dc.0.is_null() {
            if !unsafe { IsWindow(Some(hwnd)) }.as_bool() {
                return Err(ErrorInfo::new(
                    error_kind::TARGET_NOT_FOUND,
                    "target window closed during capture",
                ));
            }

            return Err(win32_failure("GetWindowDC"));
        }

        let rop = ROP_CODE(SRCCOPY.0 | CAPTUREBLT.0);
        let result = unsafe { BitBlt(dib.dc, 0, 0, width, height, Some(window_dc), 0, 0, rop) };
        let last_error = unsafe { GetLastError() }.0;
        unsafe { ReleaseDC(Some(hwnd), window_dc) };

        result.map_err(|error| {
            ErrorInfo::new(
                error_kind::BACKEND_ERROR,
                format!("BitBlt failed (Win32 error {last_error}): {error}"),
            )
        })
    }

    fn is_blank(bytes: &[u8]) -> bool {
        bytes
            .chunks_exact(4)
            .all(|pixel| pixel[0] == 0 && pixel[1] == 0 && pixel[2] == 0)
    }

    fn win32_failure(context: &str) -> ErrorInfo {
        let code = unsafe { GetLastError() }.0;
        ErrorInfo::new(
            error_kind::BACKEND_ERROR,
            format!("{context} failed (Win32 error {code})"),
        )
    }

    struct MemoryDib {
        dc: HDC,
        bitmap: HBITMAP,
        previous: HGDIOBJ,
        bits: *mut c_void,
        len: usize,
    }

    impl MemoryDib {
        fn create(width: i32, height: i32) -> Result<Self, ErrorInfo> {
            let len = pixel_bytes(width, height)?;
            let dc = unsafe { CreateCompatibleDC(None) };
            if dc.0.is_null() {
                return Err(win32_failure("CreateCompatibleDC"));
            }

            let info = BITMAPINFO {
                bmiHeader: BITMAPINFOHEADER {
                    biSize: size_of::<BITMAPINFOHEADER>() as u32,
                    biWidth: width,
                    biHeight: -height,
                    biPlanes: 1,
                    biBitCount: 32,
                    biCompression: BI_RGB.0,
                    biSizeImage: len as u32,
                    ..Default::default()
                },
                ..Default::default()
            };

            let mut bits: *mut c_void = ptr::null_mut();
            let bitmap = match unsafe {
                CreateDIBSection(Some(dc), &info, DIB_RGB_COLORS, &mut bits, None, 0)
            } {
                Ok(bitmap) if !bitmap.0.is_null() => bitmap,
                Ok(_) => {
                    let failure = win32_failure("CreateDIBSection");
                    unsafe {
                        let _ = DeleteDC(dc);
                    }
                    return Err(failure);
                }
                Err(error) => {
                    unsafe {
                        let _ = DeleteDC(dc);
                    }
                    return Err(ErrorInfo::new(
                        error_kind::BACKEND_ERROR,
                        format!("CreateDIBSection failed: {error}"),
                    ));
                }
            };

            let previous = unsafe { SelectObject(dc, HGDIOBJ::from(bitmap)) };
            if previous.0.is_null() || bits.is_null() {
                let failure = win32_failure("SelectObject");
                unsafe {
                    let _ = DeleteObject(HGDIOBJ::from(bitmap));
                    let _ = DeleteDC(dc);
                }
                return Err(failure);
            }

            Ok(Self {
                dc,
                bitmap,
                previous,
                bits,
                len,
            })
        }

        fn bytes(&self) -> &[u8] {
            unsafe { std::slice::from_raw_parts(self.bits.cast::<u8>(), self.len) }
        }
    }

    impl Drop for MemoryDib {
        fn drop(&mut self) {
            unsafe {
                if !self.previous.0.is_null() {
                    SelectObject(self.dc, self.previous);
                }

                let _ = DeleteObject(HGDIOBJ::from(self.bitmap));
                let _ = DeleteDC(self.dc);
            }
        }
    }

    fn pixel_bytes(width: i32, height: i32) -> Result<usize, ErrorInfo> {
        if width <= 0 || height <= 0 {
            return Err(ErrorInfo::new(
                error_kind::INVALID_REQUEST,
                format!("window has an empty capture area ({width}x{height})"),
            ));
        }

        (width as usize)
            .checked_mul(height as usize)
            .and_then(|pixels| pixels.checked_mul(4))
            .filter(|bytes| *bytes <= u32::MAX as usize)
            .ok_or_else(|| {
                ErrorInfo::new(
                    error_kind::INVALID_REQUEST,
                    "window capture area is too large",
                )
            })
    }
}

#[cfg(test)]
mod tests {
    use super::{dib_to_rgba, encode_png};
    use crate::protocol::error_kind;

    #[test]
    fn encode_png_writes_signature_and_ihdr_dimensions() {
        let rgba = [255, 0, 0, 255, 0, 255, 0, 255];
        let png = encode_png(2, 1, &rgba).expect("encode succeeds");

        assert!(png.len() > 8);
        assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
        assert_eq!(&png[12..16], b"IHDR");
        assert_eq!(u32::from_be_bytes(png[16..20].try_into().unwrap()), 2);
        assert_eq!(u32::from_be_bytes(png[20..24].try_into().unwrap()), 1);
        assert_eq!(png[24], 8);
        assert_eq!(png[25], 6);
    }

    #[test]
    fn encode_png_rejects_mismatched_buffer() {
        let error = encode_png(2, 2, &[0, 0, 0, 255]).unwrap_err();
        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
    }

    #[test]
    fn dib_to_rgba_converts_top_down_bgra() {
        let dib = [1, 2, 3, 0, 4, 5, 6, 0];
        let rgba = dib_to_rgba(2, 1, &dib, true).expect("conversion succeeds");
        assert_eq!(rgba, [3, 2, 1, 255, 6, 5, 4, 255]);
    }

    #[test]
    fn dib_to_rgba_flips_bottom_up_rows() {
        let dib = [4, 5, 6, 0, 1, 2, 3, 0];
        let rgba = dib_to_rgba(1, 2, &dib, false).expect("conversion succeeds");
        assert_eq!(rgba, [3, 2, 1, 255, 6, 5, 4, 255]);
    }

    #[test]
    fn dib_to_rgba_rejects_wrong_length() {
        let error = dib_to_rgba(2, 2, &[0, 0, 0, 0], true).unwrap_err();
        assert_eq!(error.kind, error_kind::INVALID_REQUEST);
    }
}
