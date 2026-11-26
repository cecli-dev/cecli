"""Tests for WSL detection and Windows forwarding with mocked subprocesses."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cecli.helpers.app_harness import interop  # noqa: E402


def _completed(command, returncode=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def _clear_wsl_env(monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    monkeypatch.delenv(interop.CHILD_ENV, raising=False)
    monkeypatch.delenv(interop.PYTHON_ENV, raising=False)
    monkeypatch.delenv(interop.TEMP_ENV, raising=False)


# WSL detection


def test_is_wsl_from_kernel_release(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(
        interop,
        "_osrelease_text",
        lambda: "6.18.58.1-microsoft-standard-WSL2",
    )

    assert interop.is_wsl() is True

    monkeypatch.setattr(interop, "_osrelease_text", lambda: "6.1.0-generic")

    assert interop.is_wsl() is False


def test_is_wsl_from_environment(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(interop, "_osrelease_text", lambda: "")

    assert interop.is_wsl() is True


# Entry conditions


def test_maybe_forward_without_flags_returns_none(monkeypatch):
    monkeypatch.setattr(interop, "_wants_forward", lambda tokens: False)
    monkeypatch.setattr(
        interop, "_discover_with_errors", lambda: pytest.fail("should not discover")
    )

    assert interop.maybe_forward(["state"]) is None


def test_maybe_forward_outside_wsl_returns_none(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(interop, "is_wsl", lambda: False)
    monkeypatch.setattr(
        interop, "_discover_with_errors", lambda: pytest.fail("should not discover")
    )

    assert interop.maybe_forward(["--host", "windows", "state"]) is None


def test_maybe_forward_child_does_not_recurse(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setenv(interop.CHILD_ENV, "1")
    monkeypatch.setattr(interop, "is_wsl", lambda: True)
    monkeypatch.setattr(
        interop, "_discover_with_errors", lambda: pytest.fail("should not discover")
    )

    assert interop.maybe_forward(["--interop", "state"]) is None


def test_maybe_forward_without_python_raises(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(interop, "is_wsl", lambda: True)
    monkeypatch.setattr(
        interop,
        "_discover_with_errors",
        lambda: (None, ["C:\\Python: ImportError"]),
    )

    with pytest.raises(interop.InteropError) as excinfo:
        interop.maybe_forward(["--interop", "state"])

    assert excinfo.value.kind == "interop_failed"
    assert "cannot find a Windows Python" in str(excinfo.value)
    assert "ImportError" in str(excinfo.value)


# Forwarding


def test_maybe_forward_runs_child_and_strips_flags(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(interop, "is_wsl", lambda: True)
    monkeypatch.setattr(
        interop,
        "_discover_with_errors",
        lambda: ("/mnt/c/Python/python.exe", []),
    )
    monkeypatch.setattr(interop, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(interop, "_reads_stdin", lambda args: False)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))

        return _completed(command, returncode=7)

    monkeypatch.setattr(interop.subprocess, "run", fake_run)

    code = interop.maybe_forward(["--host", "windows", "--window", "Book1", "state"])

    assert code == 7
    assert calls[0][0] == [
        "/mnt/c/Python/python.exe",
        "-m",
        "cecli.helpers.app_harness.cli",
        "--window",
        "Book1",
        "state",
    ]
    assert calls[0][1]["env"][interop.CHILD_ENV] == "1"
    assert calls[0][1]["input"] is None


def test_maybe_forward_accepts_host_equals_and_interop(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(interop, "is_wsl", lambda: True)
    monkeypatch.setattr(interop, "_discover_with_errors", lambda: ("/mnt/c/python.exe", []))
    monkeypatch.setattr(interop, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(interop, "_reads_stdin", lambda args: False)
    commands = []

    def fake_run(command, **kwargs):
        commands.append(list(command))

        return _completed(command)

    monkeypatch.setattr(interop.subprocess, "run", fake_run)

    assert interop.maybe_forward(["--host=windows", "state"]) == 0
    assert interop.maybe_forward(["--interop", "state"]) == 0

    for command in commands:
        assert "--host=windows" not in command
        assert "--interop" not in command


def test_forwarded_script_reads_from_a_windows_temp_file(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(interop, "is_wsl", lambda: True)
    monkeypatch.setattr(interop, "_discover_with_errors", lambda: ("/mnt/c/python.exe", []))
    monkeypatch.setattr(interop, "_reads_stdin", lambda args: True)
    monkeypatch.setattr(interop, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr(interop, "_read_stdin_bytes", lambda: b"print('hello')")
    monkeypatch.setattr(
        interop,
        "_windows_temp_script",
        lambda data: (r"C:\Temp\cecli-script.py", "/mnt/c/Temp/cecli-script.py"),
    )
    removed = []
    monkeypatch.setattr(interop, "_remove_temp", lambda path: removed.append(path))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))

        return _completed(command)

    monkeypatch.setattr(interop.subprocess, "run", fake_run)

    interop.maybe_forward(["--interop"])

    assert calls[0][0][-1] == r"C:\Temp\cecli-script.py"
    assert calls[0][1]["input"] is None
    assert removed == ["/mnt/c/Temp/cecli-script.py"]


def test_forwarded_script_falls_back_to_piped_stdin(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(interop, "is_wsl", lambda: True)
    monkeypatch.setattr(interop, "_discover_with_errors", lambda: ("/mnt/c/python.exe", []))
    monkeypatch.setattr(interop, "_reads_stdin", lambda args: True)
    monkeypatch.setattr(interop, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr(interop, "_read_stdin_bytes", lambda: b"print('hello')")
    monkeypatch.setattr(interop, "_windows_temp_script", lambda data: None)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))

        return _completed(command)

    monkeypatch.setattr(interop.subprocess, "run", fake_run)

    interop.maybe_forward(["--interop"])

    assert calls[0][1]["input"] == b"print('hello')"


def test_forwarded_command_forwards_piped_stdin(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(interop, "is_wsl", lambda: True)
    monkeypatch.setattr(interop, "_discover_with_errors", lambda: ("/mnt/c/python.exe", []))
    monkeypatch.setattr(interop, "_reads_stdin", lambda args: False)
    monkeypatch.setattr(interop, "_stdin_is_tty", lambda: False)
    monkeypatch.setattr(interop, "_read_stdin_bytes", lambda: b"payload")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))

        return _completed(command)

    monkeypatch.setattr(interop.subprocess, "run", fake_run)

    interop.maybe_forward(["--interop", "state"])

    assert calls[0][1]["input"] == b"payload"


def test_run_windows_wraps_os_error(monkeypatch):
    monkeypatch.setattr(interop, "_reads_stdin", lambda args: False)
    monkeypatch.setattr(interop, "_stdin_is_tty", lambda: True)

    def fail(command, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(interop.subprocess, "run", fail)

    with pytest.raises(interop.InteropError) as excinfo:
        interop._run_windows("/mnt/c/python.exe", ["state"])

    assert "no such file" in str(excinfo.value)


# Discovery


def test_discover_uses_env_override(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setenv(interop.PYTHON_ENV, r"C:\Python311\python.exe")
    monkeypatch.setattr(interop, "_wslpath", lambda flag, path: None)
    calls = []

    def fake_capture(argv, timeout):
        calls.append(list(argv))

        return b"", None

    monkeypatch.setattr(interop, "_capture", fake_capture)

    assert interop.discover_windows_python() == "/mnt/c/Python311/python.exe"
    assert calls == [["/mnt/c/Python311/python.exe", "-c", "import cecli.helpers.app_harness.cli"]]


def test_discover_falls_back_to_venv(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(
        interop, "_venv_candidates", lambda: ["/mnt/c/project/.venv/Scripts/python.exe"]
    )
    monkeypatch.setattr(interop, "_queried_python_paths", lambda: [])
    monkeypatch.setattr(interop, "_capture", lambda argv, timeout: (b"", None))

    assert interop.discover_windows_python() == ("/mnt/c/project/.venv/Scripts/python.exe")


def test_discover_falls_back_to_powershell(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(interop, "_venv_candidates", lambda: [])
    monkeypatch.setattr(interop, "_wslpath", lambda flag, path: None)
    monkeypatch.setattr(
        interop.shutil,
        "which",
        lambda name: "/usr/bin/powershell.exe" if name == "powershell.exe" else None,
    )
    monkeypatch.setattr(interop, "_queried_python_paths", lambda: ["/mnt/c/Python/python.exe"])
    monkeypatch.setattr(interop, "_capture", lambda argv, timeout: (b"", None))

    assert interop.discover_windows_python() == "/mnt/c/Python/python.exe"


def test_discover_rejects_interpreters_that_cannot_import(monkeypatch):
    _clear_wsl_env(monkeypatch)
    monkeypatch.setattr(interop, "_venv_candidates", lambda: ["/mnt/c/bad/python.exe"])
    monkeypatch.setattr(interop, "_queried_python_paths", lambda: [])

    def fake_capture(argv, timeout):
        return None, "ModuleNotFoundError: cecli"

    monkeypatch.setattr(interop, "_capture", fake_capture)

    assert interop.discover_windows_python() is None


def test_venv_candidates_find_scripts_python(monkeypatch, tmp_path):
    _clear_wsl_env(monkeypatch)
    python = tmp_path / "venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(interop.shutil, "which", lambda name: None)

    assert str(python) in interop._venv_candidates()


def test_venv_candidates_scan_windows_user_directories(monkeypatch, tmp_path):
    _clear_wsl_env(monkeypatch)
    python = tmp_path / "repo" / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    monkeypatch.setattr(interop, "_windows_user_roots", lambda: [tmp_path])
    monkeypatch.setattr(interop.shutil, "which", lambda name: None)

    assert str(python) in interop._venv_candidates()


def test_windows_temp_script_writes_to_a_windows_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(interop, "_windows_temp_dir", lambda: str(tmp_path))
    monkeypatch.setattr(interop, "_to_windows_path", lambda path: "C:\\Temp\\script.py")

    prepared = interop._windows_temp_script(b"print(1)")

    assert prepared is not None
    windows_path, local_path = prepared

    assert windows_path == "C:\\Temp\\script.py"
    assert Path(local_path).read_bytes() == b"print(1)"

    Path(local_path).unlink()


def test_windows_temp_script_requires_a_windows_path(monkeypatch, tmp_path):
    monkeypatch.setattr(interop, "_windows_temp_dir", lambda: str(tmp_path))
    # Simulate a temp path that cannot be converted to a Windows path,
    # regardless of whether the test host is Windows or WSL.
    monkeypatch.setattr(interop, "_to_windows_path", lambda path: "/tmp/cecli-interop.py")

    assert interop._windows_temp_script(b"print(1)") is None


def test_to_wsl_path_converts_drive_letters(monkeypatch):
    monkeypatch.setattr(interop, "_wslpath", lambda flag, path: None)

    assert interop._to_wsl_path(r"D:\work\cecli") == "/mnt/d/work/cecli"
    assert interop._to_wsl_path("/mnt/c/keep") == "/mnt/c/keep"
    assert interop._to_wsl_path("") is None


# Pure helpers


def test_strip_forward_flags_removes_only_forwarding_flags():
    assert interop._strip_forward_flags(
        ["--host", "windows", "--window", "Book1", "--interop", "state"]
    ) == ["--window", "Book1", "state"]

    assert interop._strip_forward_flags(["--host=windows", "state"]) == ["state"]


def test_with_script_path_handles_stdin_forms():
    path = r"C:\Temp\script.py"

    assert interop._with_script_path(["-"], path) == [path]
    assert interop._with_script_path(["script", "-"], path) == ["script", path]
    assert interop._with_script_path(["script"], path) == ["script", path]
    assert interop._with_script_path(["--window", "Book1"], path) == [
        "--window",
        "Book1",
        path,
    ]


def test_reads_stdin_classifies_script_forms():
    assert interop._reads_stdin([]) is True
    assert interop._reads_stdin(["-"]) is True
    assert interop._reads_stdin(["script"]) is True
    assert interop._reads_stdin(["script", "-"]) is True
    assert interop._reads_stdin(["--window", "Book1"]) is True
    assert interop._reads_stdin(["state"]) is False
    assert interop._reads_stdin(["script", "run.py"]) is False
