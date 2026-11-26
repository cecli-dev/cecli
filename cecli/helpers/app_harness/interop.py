"""Forward app-harness invocations from WSL to a Windows Python.

A bridge running on Windows is not reachable from WSL under NAT networking, so
``--host windows`` (or ``--interop``) re-runs the CLI with a Windows Python and
lets it talk to the local bridge. The child receives ``CECLI_INTEROP_CHILD=1``
so a forwarded invocation never forwards again.
"""

from __future__ import annotations

import codecs
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

from .client import AppHarnessError

CHILD_ENV = "CECLI_INTEROP_CHILD"
PYTHON_ENV = "CECLI_WINDOWS_PYTHON"
TEMP_ENV = "CECLI_WINDOWS_TEMP"
DISCOVERY_TIMEOUT_SECONDS = 20.0
IMPORT_TIMEOUT_SECONDS = 30.0

_VALUE_FLAGS = ("--window", "--timeout-ms")
_WINDOWS_PATH_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


class InteropError(AppHarnessError):
    """Raised when WSL forwarding was requested but cannot be arranged."""

    def __init__(self, message: str) -> None:
        """Record the error under a stable ``interop_failed`` kind."""

        super().__init__("interop_failed", message)


def is_wsl() -> bool:
    """Return whether this interpreter runs inside Windows Subsystem for Linux."""

    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True

    return _looks_like_wsl(_osrelease_text())


def discover_windows_python() -> str | None:
    """Return a Windows Python executable that can import this package.

    Candidates are tried in this order: ``CECLI_WINDOWS_PYTHON``, common
    ``Scripts/python.exe`` locations under the current project and home
    directory, executables already on PATH, and finally the path reported by
    ``powershell.exe (Get-Command python.exe).Source`` or ``where.exe``. Every
    candidate is validated with an import, so a Windows Python without cecli
    installed is rejected.
    """

    python, _ = _discover_with_errors()

    return python


def maybe_forward(argv: Sequence[str] | None = None) -> int | None:
    """Forward ``argv`` to Windows when requested from WSL.

    Returns ``None`` when forwarding does not apply: the flags are absent, the
    process is already the forwarded child, or this is not WSL. Raises
    :class:`InteropError` when forwarding was requested but no usable Windows
    Python exists.
    """

    tokens = list(sys.argv[1:] if argv is None else argv)

    if not _wants_forward(tokens):
        return None

    if os.environ.get(CHILD_ENV) == "1":
        return None

    if not is_wsl():
        return None

    forward_args = _strip_forward_flags(tokens)
    python, errors = _discover_with_errors()

    if not python:
        detail = "; ".join(errors[:3])
        message = "cannot find a Windows Python that can import cecli.helpers.app_harness.cli"

        if detail:
            message = f"{message}: {detail}"

        raise InteropError(message)

    return _run_windows(python, forward_args)


def _discover_with_errors() -> tuple[str | None, list[str]]:
    """Return the first usable Windows Python and the rejected candidates."""

    errors: list[str] = []
    override = os.environ.get(PYTHON_ENV)

    if override:
        candidate = _to_wsl_path(override)

        if candidate:
            ok, detail = _can_import(candidate)

            if ok:
                return candidate, errors

            errors.append(f"{PYTHON_ENV}={override!r}: {detail}")
        else:
            errors.append(f"{PYTHON_ENV}={override!r}: empty path")

    for candidate in _venv_candidates():
        ok, detail = _can_import(candidate)

        if ok:
            return candidate, errors

        errors.append(f"{candidate}: {detail}")

    for candidate in _queried_python_paths():
        ok, detail = _can_import(candidate)

        if ok:
            return candidate, errors

        errors.append(f"{candidate}: {detail}")

    return None, errors


def _can_import(python: str) -> tuple[bool, str]:
    """Return whether ``python`` can import the app-harness CLI module."""

    _, error = _capture(
        [python, "-c", "import cecli.helpers.app_harness.cli"],
        timeout=IMPORT_TIMEOUT_SECONDS,
    )

    if error:
        return False, error

    return True, ""


def _venv_candidates() -> list[str]:
    """Return Windows virtualenv interpreters near the project, home and PATH."""

    candidates: list[str] = []
    roots = [Path.cwd(), Path.home(), *_windows_user_roots()]

    for root in roots:
        for name in (".venv", "venv", ".venv-win", "env", "env-win"):
            candidate = root / name / "Scripts" / "python.exe"

            if candidate.is_file():
                _append_unique(candidates, str(candidate))

        for candidate in sorted(root.glob("*/.venv/Scripts/python.exe")):
            _append_unique(candidates, str(candidate))

        for candidate in sorted(root.glob("AppData/Local/Programs/Python/*/python.exe")):
            _append_unique(candidates, str(candidate))

    for name in ("python.exe", "python3.exe"):
        found = shutil.which(name)

        if found:
            _append_unique(candidates, found)

    return candidates


def _windows_user_roots() -> list[Path]:
    """Return Windows user directories that may hold a Python environment."""

    roots: list[Path] = []
    override = os.environ.get("USERPROFILE")

    if override:
        candidate = _to_wsl_path(override)

        if candidate and Path(candidate).is_dir():
            roots.append(Path(candidate))

    drive_home = Path("/mnt/c/Users") / Path.home().name

    if drive_home.is_dir() and drive_home not in roots:
        roots.append(drive_home)

    return roots


def _queried_python_paths() -> list[str]:
    """Ask Windows where python.exe lives and return WSL-visible paths."""

    candidates: list[str] = []
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")

    if powershell:
        output, _ = _capture(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-Command python.exe).Source",
            ],
            timeout=DISCOVERY_TIMEOUT_SECONDS,
        )

        for line in _decode(output or b"").splitlines():
            candidate = _to_wsl_path(line)

            if candidate:
                _append_unique(candidates, candidate)

    where = shutil.which("where.exe")

    if where:
        output, _ = _capture([where, "python.exe"], timeout=DISCOVERY_TIMEOUT_SECONDS)

        for line in _decode(output or b"").splitlines():
            candidate = _to_wsl_path(line)

            if candidate:
                _append_unique(candidates, candidate)

    return candidates


def _run_windows(python: str, args: Sequence[str]) -> int:
    """Run the CLI under ``python`` and return its exit code."""

    forward_args = list(args)
    stdin_data: bytes | None = None
    temp_path: str | None = None

    if _reads_stdin(forward_args) and not _stdin_is_tty():
        data = _read_stdin_bytes()

        if data:
            prepared = _windows_temp_script(data)

            if prepared:
                windows_path, temp_path = prepared
                forward_args = _with_script_path(forward_args, windows_path)
            else:
                stdin_data = data

    elif not _stdin_is_tty():
        stdin_data = _read_stdin_bytes()

    command = [python, "-m", "cecli.helpers.app_harness.cli", *forward_args]
    env = os.environ.copy()
    env[CHILD_ENV] = "1"
    timeout = _interop_timeout() if stdin_data is not None else None

    try:
        completed = subprocess.run(
            command,
            input=stdin_data,
            env=env,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise InteropError(f"the Windows CLI did not finish within {timeout:g}s") from exc
    except OSError as exc:
        raise InteropError(f"cannot run the Windows Python {python!r}: {exc}") from exc
    finally:
        if temp_path:
            _remove_temp(temp_path)

    return completed.returncode


def _windows_temp_script(data: bytes) -> tuple[str, str] | None:
    """Write a stdin script to a Windows-visible temp file.

    Returns ``(windows_path, local_path)`` so the caller can pass the Windows
    path to the child and still delete the file from WSL afterwards. ``None``
    means no Windows-visible temp directory was found and the caller should
    fall back to piping stdin.
    """

    directory = _windows_temp_dir()

    if not directory:
        return None

    try:
        descriptor, local_path = tempfile.mkstemp(
            prefix="cecli-interop-", suffix=".py", dir=directory
        )

        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except OSError:
        return None

    windows_path = _to_windows_path(local_path)

    if not _WINDOWS_PATH_PATTERN.match(windows_path):
        _remove_temp(local_path)
        return None

    return windows_path, local_path


def _windows_temp_dir() -> str | None:
    """Return a WSL path to a directory Windows can also write and read."""

    override = os.environ.get(TEMP_ENV)

    if override:
        candidate = _to_wsl_path(override)

        if candidate and Path(candidate).is_dir():
            return candidate

    powershell = shutil.which("powershell.exe")

    if powershell:
        output, _ = _capture(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[IO.Path]::GetTempPath()",
            ],
            timeout=DISCOVERY_TIMEOUT_SECONDS,
        )
        candidate = _to_wsl_path(_decode(output or b"").strip())

        if candidate and Path(candidate).is_dir():
            return candidate

    for candidate in ("/mnt/c/Windows/Temp",):
        if Path(candidate).is_dir():
            return candidate

    return None


def _reads_stdin(args: Sequence[str]) -> bool:
    """Return whether the forwarded CLI would read its script from stdin."""

    index = _first_positional(args)

    if index is None:
        return True

    token = args[index]

    if token == "-":
        return True

    if token == "script":
        return index + 1 >= len(args) or args[index + 1] == "-"

    return False


def _with_script_path(args: Sequence[str], script_path: str) -> list[str]:
    """Replace the stdin script token with ``script_path``."""

    tokens = list(args)
    index = _first_positional(tokens)

    if index is None:
        return [*tokens, script_path]

    if tokens[index] == "-":
        tokens[index] = script_path

        return tokens

    if tokens[index] == "script":
        if index + 1 < len(tokens) and tokens[index + 1] == "-":
            tokens[index + 1] = script_path
        else:
            tokens.insert(index + 1, script_path)

        return tokens

    return [*tokens, script_path]


def _first_positional(args: Sequence[str]) -> int | None:
    """Return the index of the first positional argument."""

    skip_value = False

    for index, token in enumerate(args):
        if skip_value:
            skip_value = False
            continue

        if token == "--":
            return index + 1 if index + 1 < len(args) else None

        if token == "-":
            return index

        if token.startswith("-"):
            if "=" not in token and token in _VALUE_FLAGS:
                skip_value = True

            continue

        return index

    return None


def _wants_forward(tokens: Iterable[str]) -> bool:
    """Return whether the invocation carries ``--interop`` or ``--host windows``."""

    items = list(tokens)

    for index, token in enumerate(items):
        if token == "--interop":
            return True

        if token == "--host" and index + 1 < len(items):
            if items[index + 1].casefold() == "windows":
                return True

        if token.startswith("--host="):
            if token.split("=", 1)[1].casefold() == "windows":
                return True

    return False


def _strip_forward_flags(tokens: Sequence[str]) -> list[str]:
    """Remove forwarding-only flags from the child argv."""

    result: list[str] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if token == "--interop":
            index += 1
            continue

        if token == "--host":
            index += 2
            continue

        if token.startswith("--host="):
            index += 1
            continue

        result.append(token)
        index += 1

    return result


def _capture(argv: Sequence[str], timeout: float) -> tuple[bytes | None, str | None]:
    """Run a short-lived command and return stdout or a failure description."""

    try:
        completed = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:g}s"
    except OSError as exc:
        return None, str(exc)

    if completed.returncode != 0:
        detail = _decode(completed.stderr or b"").strip()

        return None, detail or f"exited {completed.returncode}"

    return completed.stdout or b"", None


def _to_wsl_path(value: str) -> str | None:
    """Convert a Windows path to its WSL ``/mnt/<drive>`` equivalent."""

    text = value.strip().strip("\"'")

    if not text:
        return None

    if _WINDOWS_PATH_PATTERN.match(text):
        converted = _wslpath("-u", text)

        if converted:
            return converted

        drive = text[0].casefold()
        rest = text[2:].replace("\\", "/").lstrip("/")

        return f"/mnt/{drive}/{rest}"

    return text


def _to_windows_path(linux_path: str) -> str:
    """Convert a WSL path to a Windows path when possible."""

    converted = _wslpath("-w", linux_path)

    if converted:
        return converted

    match = re.match(r"^/mnt/([A-Za-z])/(.*)$", linux_path)

    if match:
        return f"{match.group(1).upper()}:\\" + match.group(2).replace("/", "\\")

    return linux_path


def _wslpath(flag: str, path: str) -> str | None:
    """Run ``wslpath`` when available and return its stripped output."""

    tool = shutil.which("wslpath")

    if not tool:
        return None

    output, error = _capture([tool, flag, path], timeout=5.0)

    if error or not output:
        return None

    return _decode(output).strip() or None


def _decode(data: bytes) -> str:
    """Decode Windows command output, which may be UTF-8 or UTF-16LE."""

    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16", errors="replace")

    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig", errors="replace")

    if b"\x00" in data[:200]:
        return data.decode("utf-16-le", errors="replace")

    return data.decode("utf-8", errors="replace")


def _read_stdin_bytes() -> bytes:
    """Read every byte currently available on stdin."""

    stream = getattr(sys.stdin, "buffer", None)

    if stream is not None:
        return stream.read()

    data = sys.stdin.read()

    return data.encode("utf-8") if isinstance(data, str) else b""


def _stdin_is_tty() -> bool:
    """Return whether stdin is an interactive terminal."""

    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):
        return True


def _osrelease_text() -> str:
    """Return kernel release text, or an empty string when unreadable."""

    try:
        return Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8")
    except OSError:
        return ""


def _looks_like_wsl(text: str) -> bool:
    """Return whether kernel release text identifies a WSL kernel."""

    lowered = text.casefold()

    return "microsoft" in lowered or "wsl" in lowered


def _append_unique(values: list[str], value: str) -> None:
    """Append ``value`` when it is not already present."""

    if value not in values:
        values.append(value)


def _remove_temp(path: str) -> None:
    """Best-effort deletion of a forwarded stdin script."""

    try:
        os.unlink(path)
    except OSError:
        pass


def _interop_timeout() -> float:
    """Return the forwarded-child timeout in seconds, overridable by env."""

    raw = os.environ.get("CECLI_INTEROP_TIMEOUT")

    if not raw:
        return 600.0

    try:
        return max(1.0, float(raw))
    except ValueError:
        return 600.0
