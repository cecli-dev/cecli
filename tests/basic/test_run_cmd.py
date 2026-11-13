import base64
from types import SimpleNamespace
from unittest.mock import patch

import pytest  # noqa: F401

from cecli.run_cmd import (
    _wrap_windows_powershell_command,
    get_windows_parent_process_name,
    run_cmd,
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
