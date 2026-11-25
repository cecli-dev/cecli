"""Cross-platform text clipboard helpers.

Spreadsheet workflows rely on the clipboard for bulk pastes, so this module
keeps command selection in one place and reports a single, actionable error
when no supported tool is installed. Every subprocess call is bounded by a
timeout because clipboard daemons can stall when a display server is missing.
"""

from __future__ import annotations

import codecs
import shutil
import subprocess
import sys
from dataclasses import dataclass

DEFAULT_TIMEOUT_SECONDS = 5.0


class ClipboardError(RuntimeError):
    """Raised when no clipboard tool exists or every candidate tool fails."""


@dataclass(frozen=True)
class _ClipboardTool:
    """One executable that reads or writes the system clipboard."""

    name: str
    args: tuple[str, ...] = ()
    encoding: str = "utf-8"


def set_text(text: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
    """Copy ``text`` to the system clipboard.

    Raises :class:`ClipboardError` when the platform has no usable tool or all
    candidates exit non-zero. Tools are tried in preference order so a broken
    Wayland clipboard still falls back to X11 tools.
    """

    if not isinstance(text, str):
        raise TypeError("clipboard text must be a str")

    platform = _platform()
    tools = _installed(_set_tools(platform))

    if not tools:
        raise ClipboardError(_missing_tool_message(_platform()))

    failures: list[str] = []

    for tool in tools:
        output, error = _invoke(tool, text.encode(tool.encoding), timeout)

        if error is None:
            return

        failures.append(error)

    raise ClipboardError(_failure_message("write", failures))


def get_text(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
    """Return the system clipboard as text.

    Raises :class:`ClipboardError` when the platform has no usable tool or all
    candidates exit non-zero.
    """

    platform = _platform()
    tools = _installed(_get_tools(platform))

    if not tools:
        raise ClipboardError(_missing_tool_message(_platform()))

    failures: list[str] = []

    for tool in tools:
        output, error = _invoke(tool, None, timeout)

        if error is None:
            return _decode(output or b"", tool.encoding)

        failures.append(error)

    raise ClipboardError(_failure_message("read", failures))


def available_tools() -> list[str]:
    """Return the clipboard tool names that exist on this machine."""

    platform = _platform()
    tools = [*_set_tools(platform), *_get_tools(platform)]
    names: list[str] = []

    for tool in tools:
        if tool.name not in names and _find_tool(tool.name):
            names.append(tool.name)

    return names


def _platform() -> str:
    """Return ``windows``, ``macos`` or ``linux`` for the current interpreter."""

    if sys.platform.startswith("win"):
        return "windows"

    if sys.platform == "darwin":
        return "macos"

    return "linux"


def _set_tools(platform: str) -> list[_ClipboardTool]:
    """Return clipboard writers in preference order."""

    if platform == "windows":
        return [
            _ClipboardTool("clip.exe", encoding="utf-16-le"),
            _ClipboardTool(
                "powershell.exe",
                (
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "[Console]::InputEncoding=[Text.Encoding]::UTF8; "
                    "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
                ),
            ),
            _ClipboardTool(
                "pwsh",
                (
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "[Console]::InputEncoding=[Text.Encoding]::UTF8; "
                    "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
                ),
            ),
        ]

    if platform == "macos":
        return [_ClipboardTool("pbcopy")]

    return [
        _ClipboardTool("wl-copy"),
        _ClipboardTool("xclip", ("-selection", "clipboard", "-i")),
        _ClipboardTool("xsel", ("--clipboard", "--input")),
    ]


def _get_tools(platform: str) -> list[_ClipboardTool]:
    """Return clipboard readers in preference order."""

    if platform == "windows":
        command = (
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw",
        )
        return [
            _ClipboardTool("powershell.exe", command),
            _ClipboardTool("pwsh", command),
        ]

    if platform == "macos":
        return [_ClipboardTool("pbpaste")]

    return [
        _ClipboardTool("wl-paste", ("--no-newline",)),
        _ClipboardTool("xclip", ("-selection", "clipboard", "-o")),
        _ClipboardTool("xsel", ("--clipboard", "--output")),
    ]


def _invoke(
    tool: _ClipboardTool, data: bytes | None, timeout: float
) -> tuple[bytes | None, str | None]:
    """Run one clipboard tool and return its stdout or a failure description."""

    path = _find_tool(tool.name)

    if not path:
        return None, f"{tool.name} not found on PATH"

    argv = [path, *tool.args]

    try:
        completed = subprocess.run(
            argv,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"{tool.name} timed out after {timeout:g}s"
    except OSError as exc:
        return None, f"{tool.name} could not run: {exc}"

    if completed.returncode != 0:
        detail = _decode(completed.stderr or b"", tool.encoding).strip()
        suffix = f": {detail}" if detail else ""
        return None, f"{tool.name} exited {completed.returncode}{suffix}"

    return completed.stdout or b"", None


def _installed(tools: list[_ClipboardTool]) -> list[_ClipboardTool]:
    """Return only the tools that resolve to an executable."""

    return [tool for tool in tools if _find_tool(tool.name)]


def _find_tool(name: str) -> str | None:
    """Return the executable path for ``name`` or ``None`` when absent."""

    return shutil.which(name)


def _decode(data: bytes, encoding: str) -> str:
    """Decode clipboard output, honoring a UTF-16 or UTF-8 byte-order mark."""

    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16", errors="replace")

    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig", errors="replace")

    return data.decode(encoding, errors="replace")


def _missing_tool_message(platform: str) -> str:
    """Explain which clipboard tools the current platform expected."""

    if platform == "windows":
        return "no Windows clipboard tool found; expected clip.exe or powershell.exe"

    if platform == "macos":
        return "no macOS clipboard tool found; expected pbcopy and pbpaste"

    return (
        "no Linux clipboard tool found; install wl-clipboard (wl-copy/wl-paste), " "xclip, or xsel"
    )


def _failure_message(direction: str, failures: list[str]) -> str:
    """Build one error message from the per-tool failures."""

    detail = "; ".join(failures) or "no candidates were tried"

    return f"could not {direction} the clipboard: {detail}"
