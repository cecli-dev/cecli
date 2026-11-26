"""Windows UIA acceptance checks against the PowerShell fixture app.

These tests need a logged-in interactive desktop, ``CECLI_INTEGRATION=1``, and
a reachable ``bridge.json`` written by ``ce-underscore --app-harness``. They are
skipped everywhere else so the hermetic suite stays runnable on any host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from .conftest import PNG_SIGNATURE, BridgeHandle, CliRunner

pytestmark = [pytest.mark.windows, pytest.mark.integration]

FIXTURE_TITLE = "cecli Harness Fixture"
FIXTURE_SCRIPT = Path(__file__).with_name("fixtures") / "fixture_app.ps1"
EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_UNVERIFIED = 3


@pytest.fixture(scope="session")
def windows_platform() -> None:
    """Skip unless this host can run the interactive Windows fixture."""

    if sys.platform != "win32":
        pytest.skip(f"Windows acceptance tests need win32, found {sys.platform}")

    if os.environ.get("CECLI_INTEGRATION") != "1":
        pytest.skip("set CECLI_INTEGRATION=1 to run the Windows acceptance suite")

    if _powershell() is None:
        pytest.skip("powershell.exe is not on PATH")


@pytest.fixture()
def fixture_app(
    windows_platform: None,
    real_bridge: BridgeHandle,
    cli: CliRunner,
    tmp_path: Path,
) -> Any:
    """Start the WinForms fixture, wait for its window, and stop it afterwards."""

    log_path = tmp_path / "fixture.log"
    log_path.write_text("", encoding="utf-8")
    process = start_fixture_app(log_path=log_path)

    try:
        title = wait_for_window(cli, FIXTURE_TITLE, timeout=30.0)
        yield FixtureApp(process=process, title=title, log_path=log_path)
    finally:
        stop_process(process)


def test_windows_finds_fixture_window(
    cli: CliRunner, real_bridge: BridgeHandle, fixture_app: "FixtureApp"
) -> None:
    """``windows`` lists the fixture window with a usable handle."""

    windows = list_windows(cli)
    matches = [
        window
        for window in windows
        if FIXTURE_TITLE.lower() in str(window.get("title", "")).lower()
    ]

    assert matches, f"fixture window missing from {windows!r}"

    window = matches[0]

    assert window.get("handle")
    assert int(window.get("pid") or 0) > 0


def test_snapshot_finds_edit_and_button(
    cli: CliRunner, real_bridge: BridgeHandle, fixture_app: "FixtureApp"
) -> None:
    """The UIA tree exposes the named edit and the enabled Save button."""

    snapshot = snapshot_window(cli, fixture_app.title)
    edit = find_element(snapshot, name="Text Editor", role="Edit")
    save = find_element(snapshot, name="Save", role="Button")

    assert edit is not None, summarize(snapshot)
    assert save is not None, summarize(snapshot)
    assert edit.get("enabled") is True
    assert save.get("enabled") is True


def test_set_value_reads_back(
    cli: CliRunner, real_bridge: BridgeHandle, fixture_app: "FixtureApp"
) -> None:
    """``set_value`` on the edit is confirmed by a subsequent ``get_value``."""

    snapshot_window(cli, fixture_app.title)
    value = "acceptance round trip"
    write = cli.run(
        "set-value",
        "--window",
        fixture_app.title,
        "--name",
        "Text Editor",
        "--value",
        value,
        "--json",
    )

    assert write.returncode == EXIT_OK, write.stderr
    assert write.json().get("verified") is True

    read = cli.run("get-value", "--window", fixture_app.title, "--name", "Text Editor", "--json")

    assert read.returncode == EXIT_OK, read.stderr
    assert read.json().get("value") == value


def test_keys_types_into_edit(
    cli: CliRunner, real_bridge: BridgeHandle, fixture_app: "FixtureApp"
) -> None:
    """``keys`` reaches the focused edit control."""

    snapshot_window(cli, fixture_app.title)
    cli.run(
        "set-value",
        "--window",
        fixture_app.title,
        "--name",
        "Text Editor",
        "--value",
        "",
        "--json",
    )
    focus = cli.run("focus", "--window", fixture_app.title, "--name", "Text Editor", "--json")

    assert focus.returncode == EXIT_OK, focus.stderr

    typed = "abc123"
    result = cli.run(
        "keys", "--window", fixture_app.title, "--name", "Text Editor", "--keys", typed, "--json"
    )

    assert result.returncode in {EXIT_OK, EXIT_UNVERIFIED}, result.stderr
    assert wait_for_value(cli, fixture_app.title, "Text Editor", typed, timeout=5.0)


def test_invoke_save_button(
    cli: CliRunner, real_bridge: BridgeHandle, fixture_app: "FixtureApp"
) -> None:
    """Invoking Save runs the handler and updates fixture state."""

    snapshot_window(cli, fixture_app.title)
    fixture_app.log_path.write_text("", encoding="utf-8")
    result = cli.run("invoke", "--window", fixture_app.title, "--name", "Save", "--json")

    assert result.returncode in {EXIT_OK, EXIT_UNVERIFIED}, result.stderr
    assert result.json().get("delivered") is True
    assert wait_for_log(fixture_app.log_path, "save=", timeout=5.0)


def test_password_value_is_never_returned(
    cli: CliRunner, real_bridge: BridgeHandle, fixture_app: "FixtureApp"
) -> None:
    """Password controls are sensitive and refuse ``get_value``."""

    snapshot = snapshot_window(cli, fixture_app.title)
    password = find_element(snapshot, name="Password", role="Edit") or first_sensitive(snapshot)

    assert password is not None, summarize(snapshot)
    assert password.get("sensitive") is True
    assert password.get("value") is None

    result = cli.run("get-value", "--window", fixture_app.title, "--name", "Password", "--json")
    combined = (result.stdout + result.stderr).lower()

    assert result.returncode == EXIT_REFUSED
    assert "password" not in result.stdout.lower() or "blocked" in combined
    assert any(word in combined for word in ("sensitive", "password", "blocked", "refus"))


def test_disabled_control_is_refused(
    cli: CliRunner, real_bridge: BridgeHandle, fixture_app: "FixtureApp"
) -> None:
    """The disabled Delete button is refused before any input is sent."""

    snapshot = snapshot_window(cli, fixture_app.title)
    delete = find_element(snapshot, name="Delete", role="Button")

    assert delete is not None, summarize(snapshot)
    assert delete.get("enabled") is False

    result = cli.run("invoke", "--window", fixture_app.title, "--name", "Delete", "--json")
    combined = (result.stderr + result.stdout).lower()

    assert result.returncode == EXIT_REFUSED
    assert any(word in combined for word in ("disabled", "blocked", "refus"))


def test_stale_element_ref_is_refused(
    cli: CliRunner, real_bridge: BridgeHandle, fixture_app: "FixtureApp"
) -> None:
    """An id from an older snapshot is not silently reused."""

    snapshot = snapshot_window(cli, fixture_app.title)
    edit = find_element(snapshot, name="Text Editor", role="Edit")

    assert edit is not None, summarize(snapshot)

    stale_id = int(edit["id"])
    refreshed = cli.run("snapshot", "--window", fixture_app.title, "--max-elements", "1", "--json")

    assert refreshed.returncode == EXIT_OK, refreshed.stderr

    result = cli.run("invoke", "--window", fixture_app.title, "--id", str(stale_id), "--json")
    combined = (result.stderr + result.stdout).lower()

    assert result.returncode == EXIT_REFUSED
    assert any(
        word in combined for word in ("stale", "fresh snapshot", "not found", "blocked", "refus")
    )


def test_screenshot_is_nonempty_png(
    cli: CliRunner, real_bridge: BridgeHandle, fixture_app: "FixtureApp", tmp_path: Path
) -> None:
    """``screenshot`` captures the fixture window as PNG bytes."""

    snapshot_window(cli, fixture_app.title)
    output = tmp_path / "fixture.png"
    result = cli.run("screenshot", "--window", fixture_app.title, "--out", str(output), "--json")

    assert result.returncode == EXIT_OK, result.stderr

    data = output.read_bytes()

    assert data.startswith(PNG_SIGNATURE)
    assert len(data) > len(PNG_SIGNATURE)


@dataclass
class FixtureApp:
    """Running PowerShell fixture and the window title it published."""

    process: subprocess.Popen[Any]
    title: str
    log_path: Path


def _powershell() -> str | None:
    """Return the PowerShell executable path, or ``None`` when unavailable."""

    for name in ("powershell", "powershell.exe") if sys.platform == "win32" else ("powershell",):
        found = shutil.which(name)

        if found:
            return found

    return None


def start_fixture_app(log_path: Path) -> subprocess.Popen[Any]:
    """Launch the WinForms fixture in a separate PowerShell process."""

    powershell = _powershell()

    assert powershell is not None
    assert FIXTURE_SCRIPT.exists(), f"missing fixture script at {FIXTURE_SCRIPT}"

    environment = os.environ.copy()
    environment["CECLI_FIXTURE_LOG"] = str(log_path)

    return subprocess.Popen(
        [
            powershell,
            "-STA",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(FIXTURE_SCRIPT),
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_process(process: subprocess.Popen[Any]) -> None:
    """Terminate the fixture process and reap it."""

    if process.poll() is not None:
        return

    process.terminate()

    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for_window(cli: CliRunner, title: str, timeout: float = 30.0) -> str:
    """Poll ``windows`` until a window matching ``title`` appears."""

    deadline = time.monotonic() + timeout
    last: list[dict[str, Any]] = []

    while time.monotonic() < deadline:
        last = list_windows(cli)

        for window in last:
            candidate = str(window.get("title", ""))

            if title.lower() in candidate.lower():
                return candidate

        time.sleep(0.5)

    raise AssertionError(f"window {title!r} did not appear; saw {last!r}")


def list_windows(cli: CliRunner) -> list[dict[str, Any]]:
    """Return windows or an empty list while the bridge is still starting."""

    result = cli.run("windows", "--json", timeout=30.0)

    if result.returncode != EXIT_OK:
        return []

    payload = result.json()
    return payload if isinstance(payload, list) else []


def snapshot_window(cli: CliRunner, title: str) -> dict[str, Any]:
    """Snapshot the fixture and return the parsed payload."""

    result = cli.run("snapshot", "--window", title, "--json", timeout=60.0)

    assert result.returncode == EXIT_OK, result.stderr
    return result.json()


def find_element(
    snapshot: dict[str, Any], name: str | None = None, role: str | None = None
) -> dict[str, Any] | None:
    """Return the first element matching an accessibility name and role."""

    for element in snapshot.get("elements", []):
        if name is not None and str(element.get("name") or "").lower() != name.lower():
            continue

        if role is not None and str(element.get("control_type") or "").lower() != role.lower():
            continue

        return element

    return None


def first_sensitive(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first control marked sensitive."""

    for element in snapshot.get("elements", []):
        if element.get("sensitive"):
            return element

    return None


def wait_for_value(
    cli: CliRunner, title: str, name: str, expected: str, timeout: float = 5.0
) -> bool:
    """Poll ``get-value`` until it contains ``expected``."""

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        result = cli.run("get-value", "--window", title, "--name", name, "--json", timeout=30.0)

        if result.returncode == EXIT_OK:
            value = str(result.json().get("value") or "")

            if expected in value:
                return True

        time.sleep(0.3)

    return False


def wait_for_log(path: Path, needle: str, timeout: float = 5.0) -> bool:
    """Poll a fixture log file for ``needle``."""

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            if needle in path.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            pass

        time.sleep(0.2)

    return False


def summarize(snapshot: dict[str, Any], limit: int = 40) -> str:
    """Render a compact element list for assertion messages."""

    rows = [
        f"[{element.get('id')}] {element.get('control_type')} {element.get('name')!r}"
        f" value={element.get('value')!r} enabled={element.get('enabled')}"
        for element in snapshot.get("elements", [])[:limit]
    ]
    return "snapshot elements:\n" + "\n".join(rows)
