"""Subprocess contract checks for the ``app-harness`` command.

The CLI is the only public surface most callers use. These tests pin its exit
codes, JSON mode, script mode, and human output against a fake bridge.
"""

from __future__ import annotations

from typing import Any

import pytest

from .conftest import BridgeHandle, CliRunner

pytestmark = pytest.mark.integration

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_UNVERIFIED = 3
EXIT_UNAVAILABLE = 4


def test_exit_zero_for_successful_commands(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """Read-only commands exit 0 and produce output."""

    for command in ("state", "windows", "doctor"):
        result = cli.run(command, "--json")

        assert result.returncode == EXIT_OK, result.stderr
        assert result.stdout.strip(), f"{command} produced no stdout"


def test_exit_two_when_argument_is_missing(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """Missing selectors are refused before any request reaches the bridge."""

    title = first_window_title(cli)
    before = fake_bridge.request_paths()
    snapshot = cli.run("snapshot")
    invoke = cli.run("invoke", "--window", title)

    assert snapshot.returncode == EXIT_REFUSED
    assert invoke.returncode == EXIT_REFUSED
    assert "error:" in snapshot.stderr.lower()
    assert "error:" in invoke.stderr.lower()

    if fake_bridge.is_python_fake:
        assert fake_bridge.request_paths() == before


def test_exit_two_when_control_is_disabled(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """A disabled control is refused by the bridge and exits 2."""

    title = first_window_title(cli)

    if fake_bridge.is_python_fake:
        fake_bridge.set_action_mode("refuse")
        result = cli.run("invoke", "--window", title, "--name", "Save", "--json")
        fake_bridge.set_action_mode("ok")
    else:
        result = cli.run("invoke", "--window", title, "--name", "Delete", "--json")

    assert result.returncode == EXIT_REFUSED
    assert "error:" in result.stderr.lower()


def test_exit_three_when_action_is_unverified(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """A delivered but unconfirmed action exits 3."""

    title = first_window_title(cli)

    if fake_bridge.is_python_fake:
        fake_bridge.set_action_mode("unverified")
        result = cli.run("invoke", "--window", title, "--name", "Save", "--json")
        fake_bridge.set_action_mode("ok")
    else:
        result = cli.run("keys", "--window", title, "--keys", "X", "--json")

    assert result.returncode == EXIT_UNVERIFIED

    payload = result.json()

    assert payload.get("delivered") is True
    assert payload.get("verified") is False
    assert payload.get("uncertain") is False


def test_exit_three_when_action_is_uncertain(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """An uncertain action exits 3 without a retry."""

    if not fake_bridge.is_python_fake:
        pytest.skip("the native fake has no scripted uncertain action")

    fake_bridge.set_action_mode("uncertain")

    try:
        result = cli.run("invoke", "--window", first_window_title(cli), "--name", "Save", "--json")
    finally:
        fake_bridge.set_action_mode("ok")

    assert result.returncode == EXIT_UNVERIFIED
    assert result.json().get("uncertain") is True


def test_exit_four_without_a_bridge(cli: CliRunner, tmp_path: Any) -> None:
    """A missing discovery file reports bridge-unavailable with exit 4."""

    missing = tmp_path / "nowhere" / "bridge.json"
    result = cli.run("state", "--json", env={"CECLI_BRIDGE_FILE": str(missing)})

    assert result.returncode == EXIT_UNAVAILABLE
    assert result.json().get("ok") is False
    assert "ce-underscore" in result.stderr or "bridge" in result.stderr


def test_json_mode_emits_only_json(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """``--json`` stdout decodes as one JSON document and nothing else."""

    result = cli.run("state", "--json")

    assert result.returncode == EXIT_OK, result.stderr

    payload = result.json()

    assert isinstance(payload, dict)
    assert payload.get("health") in {"ready", "degraded"}


def test_script_mode_chains_requests_in_one_session(
    cli: CliRunner, fake_bridge: BridgeHandle
) -> None:
    """A stdin script holds one client and can chain state, windows, snapshot."""

    program = (
        "info = state()\n"
        "wins = windows()\n"
        "title = wins[0].title\n"
        "snap = snapshot(window=title)\n"
        "print(f'script-ok:{info.backend}:{len(snap.elements)}')\n"
    )
    before = len(fake_bridge.request_paths())
    result = cli.run(stdin=program)

    assert result.returncode == EXIT_OK, result.stderr
    assert "script-ok:" in result.stdout

    if fake_bridge.is_python_fake:
        paths = fake_bridge.request_paths()[before:]

        assert paths == ["/api/app/state", "/api/app/windows", "/api/app/snapshot"]


def test_script_mode_reports_unverified_exit(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """Any unverified action in a script makes the script exit 3."""

    title = first_window_title(cli)

    if fake_bridge.is_python_fake:
        fake_bridge.set_action_mode("unverified")

        try:
            result = cli.run("--window", title, stdin="invoke(name='Save')\n")
        finally:
            fake_bridge.set_action_mode("ok")
    else:
        result = cli.run("--window", title, stdin="keys('X')\n")

    assert result.returncode == EXIT_UNVERIFIED


def test_human_snapshot_prints_a_tree(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """``--format lines`` renders an indented tree with ids."""

    result = cli.run("snapshot", "--window", first_window_title(cli), "--format", "lines")

    assert result.returncode == EXIT_OK, result.stderr

    lines = result.stdout.splitlines()

    assert lines[0].startswith("window:")

    element_lines = [line for line in lines if line.lstrip().startswith("[")]

    assert element_lines, result.stdout
    assert any(line.startswith("  ") for line in element_lines), "tree is not indented"


def test_human_windows_prints_a_table(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """The human window list has a header row and one row per window."""

    result = cli.run("windows")

    assert result.returncode == EXIT_OK, result.stderr

    lines = result.stdout.splitlines()

    assert "HANDLE" in lines[0]
    assert "PID" in lines[0]
    assert "TITLE" in lines[0]
    assert len(lines) >= 2


def test_doctor_reports_checks_in_both_modes(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """``doctor`` exposes permissions, named checks, and notes."""

    machine = cli.run("doctor", "--json")

    assert machine.returncode == EXIT_OK, machine.stderr

    payload = machine.json()

    assert isinstance(payload.get("platform"), str)
    assert isinstance(payload.get("backend"), str)
    assert isinstance(payload.get("permissions"), dict)
    assert isinstance(payload.get("checks"), list) and payload["checks"]

    for check in payload["checks"]:
        assert isinstance(check.get("name"), str) and check["name"]
        assert isinstance(check.get("ok"), bool)
        assert isinstance(check.get("detail"), str)

    human = cli.run("doctor")

    assert human.returncode == EXIT_OK
    assert "platform:" in human.stdout
    assert "checks:" in human.stdout


def test_repeated_runs_share_no_client_state(cli: CliRunner, fake_bridge: BridgeHandle) -> None:
    """Consecutive invocations see the same zero-state bridge identity."""

    first = cli.run("state", "--json")
    second = cli.run("state", "--json")

    assert first.returncode == EXIT_OK
    assert second.returncode == EXIT_OK
    assert first.json().get("pid") == second.json().get("pid")
    assert first.json().get("version") == second.json().get("version")


def first_window_title(cli: CliRunner) -> str:
    """Return the title of the first window reported by the fake bridge."""

    result = cli.run("windows", "--json")

    assert result.returncode == EXIT_OK, result.stderr

    windows = result.json()

    assert windows, "fake backend reported no windows"
    return str(windows[0]["title"])
