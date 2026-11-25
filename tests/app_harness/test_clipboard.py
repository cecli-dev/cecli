"""Tests for clipboard tool selection and subprocess handling."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness import clipboard  # noqa: E402


def _install(monkeypatch, platform, available, handler):
    """Fake the platform, tool lookup and subprocess runner."""

    calls = []

    monkeypatch.setattr(clipboard, "_platform", lambda: platform)
    monkeypatch.setattr(
        clipboard,
        "_find_tool",
        lambda name: f"/tools/{name}" if name in available else None,
    )

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs))

        return handler(list(argv), kwargs)

    monkeypatch.setattr(clipboard.subprocess, "run", run)

    return calls


def _ok(argv, kwargs, stdout=b""):
    return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")


def test_set_text_prefers_wl_copy(monkeypatch):
    calls = _install(
        monkeypatch, "linux", {"wl-copy", "xclip", "xsel"}, lambda argv, kw: _ok(argv, kw)
    )

    clipboard.set_text("hello")

    assert len(calls) == 1
    assert calls[0][0] == ["/tools/wl-copy"]
    assert calls[0][1]["input"] == b"hello"
    assert calls[0][1]["timeout"] == clipboard.DEFAULT_TIMEOUT_SECONDS


def test_set_text_falls_back_to_xclip(monkeypatch):
    calls = _install(monkeypatch, "linux", {"xclip"}, lambda argv, kw: _ok(argv, kw))

    clipboard.set_text("hello")

    assert calls[0][0] == ["/tools/xclip", "-selection", "clipboard", "-i"]
    assert calls[0][1]["input"] == b"hello"


def test_set_text_windows_clip_uses_utf16(monkeypatch):
    calls = _install(monkeypatch, "windows", {"clip.exe"}, lambda argv, kw: _ok(argv, kw))

    clipboard.set_text("héllo")

    assert calls[0][0] == ["/tools/clip.exe"]
    assert calls[0][1]["input"] == "héllo".encode("utf-16-le")


def test_set_text_windows_falls_back_to_powershell(monkeypatch):
    calls = _install(
        monkeypatch,
        "windows",
        {"powershell.exe"},
        lambda argv, kw: _ok(argv, kw),
    )

    clipboard.set_text("hello")

    assert calls[0][0][0] == "/tools/powershell.exe"
    assert "Set-Clipboard" in calls[0][0][-1]
    assert calls[0][1]["input"] == b"hello"


def test_get_text_linux_uses_wl_paste(monkeypatch):
    calls = _install(
        monkeypatch,
        "linux",
        {"wl-paste"},
        lambda argv, kw: _ok(argv, kw, stdout=b"pasted"),
    )

    assert clipboard.get_text() == "pasted"
    assert calls[0][0] == ["/tools/wl-paste", "--no-newline"]
    assert calls[0][1]["input"] is None


def test_get_text_windows_uses_powershell(monkeypatch):
    calls = _install(
        monkeypatch,
        "windows",
        {"powershell.exe"},
        lambda argv, kw: _ok(argv, kw, stdout=b"clip text"),
    )

    assert clipboard.get_text() == "clip text"
    assert calls[0][0][0] == "/tools/powershell.exe"
    assert "Get-Clipboard -Raw" in calls[0][0][-1]


def test_get_text_macos_uses_pbpaste(monkeypatch):
    calls = _install(
        monkeypatch, "macos", {"pbpaste"}, lambda argv, kw: _ok(argv, kw, stdout=b"mac")
    )

    assert clipboard.get_text() == "mac"
    assert calls[0][0] == ["/tools/pbpaste"]


def test_get_text_decodes_utf16_with_bom(monkeypatch):
    payload = "snow ☃".encode("utf-16")
    _install(
        monkeypatch,
        "windows",
        {"powershell.exe"},
        lambda argv, kw: _ok(argv, kw, stdout=payload),
    )

    assert clipboard.get_text() == "snow ☃"


def test_missing_tool_raises_platform_hint(monkeypatch):
    _install(monkeypatch, "linux", set(), lambda argv, kw: _ok(argv, kw))

    with pytest.raises(clipboard.ClipboardError) as excinfo:
        clipboard.set_text("hello")

    assert "install wl-clipboard" in str(excinfo.value)


def test_failed_tool_falls_back_to_next(monkeypatch):
    def handler(argv, kwargs):
        if argv[0].endswith("wl-copy"):
            return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"no display")

        return _ok(argv, kwargs)

    calls = _install(monkeypatch, "linux", {"wl-copy", "xclip"}, handler)

    clipboard.set_text("hello")

    assert [call[0][0] for call in calls] == ["/tools/wl-copy", "/tools/xclip"]


def test_timeout_falls_back_to_next(monkeypatch):
    calls = []

    monkeypatch.setattr(clipboard, "_platform", lambda: "linux")
    monkeypatch.setattr(
        clipboard,
        "_find_tool",
        lambda name: f"/tools/{name}" if name in {"wl-copy", "xclip"} else None,
    )

    def run(argv, **kwargs):
        calls.append(list(argv))

        if argv[0].endswith("wl-copy"):
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 1))

        return _ok(argv, kwargs)

    monkeypatch.setattr(clipboard.subprocess, "run", run)

    clipboard.set_text("hello")

    assert [call[0] for call in calls] == ["/tools/wl-copy", "/tools/xclip"]


def test_all_tools_failing_raises_with_details(monkeypatch):
    def handler(argv, kwargs):
        return subprocess.CompletedProcess(argv, 2, stdout=b"", stderr=b"bad")

    _install(monkeypatch, "linux", {"wl-copy"}, handler)

    with pytest.raises(clipboard.ClipboardError) as excinfo:
        clipboard.set_text("hello")

    message = str(excinfo.value)

    assert "could not write the clipboard" in message
    assert "wl-copy exited 2" in message
    assert "bad" in message


def test_available_tools_reports_installed_names(monkeypatch):
    monkeypatch.setattr(clipboard, "_platform", lambda: "linux")
    monkeypatch.setattr(
        clipboard,
        "_find_tool",
        lambda name: f"/tools/{name}" if name in {"xclip", "xsel"} else None,
    )

    assert clipboard.available_tools() == ["xclip", "xsel"]


def test_set_text_rejects_non_string(monkeypatch):
    _install(monkeypatch, "linux", {"wl-copy"}, lambda argv, kw: _ok(argv, kw))

    with pytest.raises(TypeError):
        clipboard.set_text(123)  # type: ignore[arg-type]
