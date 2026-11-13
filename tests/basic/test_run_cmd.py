import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import patch

import pytest  # noqa: F401

from cecli.run_cmd import (
    _wrap_windows_powershell_command,
    get_windows_parent_process_name,
    run_cmd,
    run_cmd_async,
)


def test_run_cmd_echo():
    command = "echo Hello"
    exit_code, output = run_cmd(command)

    assert exit_code == 0
    assert output.strip() == "Hello"


def test_get_windows_parent_process_name_detects_pwsh():
    grandparent = SimpleNamespace(name=lambda: "pwsh.exe", parent=lambda: None)
    parent = SimpleNamespace(name=lambda: "uv.exe", parent=lambda: grandparent)
    current = SimpleNamespace(parent=lambda: parent)

    with patch("cecli.run_cmd.psutil.Process", return_value=current):
        assert get_windows_parent_process_name() == "pwsh.exe"


@pytest.mark.parametrize(
    "parent_process,expected_exe",
    [
        ("pwsh.exe", "pwsh"),
        ("powershell.exe", "powershell"),
    ],
)
def test_wrap_windows_powershell_command(parent_process, expected_exe):
    wrapped = _wrap_windows_powershell_command("Get-ChildItem", parent_process)
    assert wrapped.startswith(
        f"{expected_exe} -NoProfile -NonInteractive -OutputFormat Text -EncodedCommand "
    )
    encoded = wrapped.split("-EncodedCommand ", 1)[1]
    decoded = base64.b64decode(encoded).decode("utf-16-le")
    assert decoded == "$ProgressPreference='SilentlyContinue'; Get-ChildItem"


def test_wrap_windows_powershell_command_passthrough_for_cmd():
    assert _wrap_windows_powershell_command("dir", "cmd.exe") == "dir"
    assert _wrap_windows_powershell_command("dir", None) == "dir"


def test_wrap_windows_powershell_command_skips_already_encoded_command():
    already_wrapped = (
        r"C:\windows\System32\WindowsPowerShell\v1.0\powershell.EXE "
        "-NoProfile -NonInteractive -OutputFormat Text -EncodedCommand ZQBjAGgAbwAgADEA"
    )
    assert _wrap_windows_powershell_command(already_wrapped, "pwsh.exe") == already_wrapped
    assert _wrap_windows_powershell_command(already_wrapped, "powershell.exe") == already_wrapped


def test_get_windows_parent_process_name_defaults_to_powershell():
    parent = SimpleNamespace(name=lambda: "explorer.exe", parent=lambda: None)
    current = SimpleNamespace(parent=lambda: parent)

    with (
        patch("cecli.run_cmd.psutil.Process", return_value=current),
        patch("cecli.run_cmd.shutil.which", side_effect=lambda name: name == "pwsh"),
    ):
        assert get_windows_parent_process_name() == "pwsh.exe"

    with (
        patch("cecli.run_cmd.psutil.Process", return_value=current),
        patch("cecli.run_cmd.shutil.which", side_effect=lambda name: name == "powershell"),
    ):
        assert get_windows_parent_process_name() == "powershell.exe"


def test_run_cmd_async_windows_fallback_does_not_double_wrap():
    recorded = []

    def fake_run_cmd_subprocess(command, verbose, cwd, encoding, should_print):
        recorded.append(command)
        return 0, "ok"

    async def _run():
        return await run_cmd_async("echo hi", interrupt_event=None)

    with (
        patch("cecli.run_cmd.platform.system", return_value="Windows"),
        patch("cecli.run_cmd.get_windows_parent_process_name", return_value="pwsh.exe"),
        patch("cecli.run_cmd.run_cmd_subprocess", side_effect=fake_run_cmd_subprocess),
        patch("cecli.run_cmd.asyncio.create_subprocess_shell", side_effect=NotImplementedError),
    ):
        code, out = asyncio.run(_run())

    assert (code, out) == (0, "ok")
    assert recorded == ["echo hi"]
