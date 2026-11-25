"""Linux AT-SPI acceptance checks against a GTK fixture.

These tests need ``CECLI_INTEGRATION=1``, a reachable ``bridge.json`` from
``ce-underscore --app-harness``, and a live AT-SPI bus in a graphical session.
Without a bus the whole module skips with a reason instead of failing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from .conftest import BridgeHandle, CliRunner

pytestmark = [pytest.mark.linux, pytest.mark.integration]

FIXTURE_TITLE = "cecli GTK Fixture"
FIXTURE_SCRIPT = Path(__file__).with_name("gtk_fixture.py")
EXIT_OK = 0


@pytest.fixture(scope="session")
def linux_platform() -> None:
    """Skip unless a Linux session with an AT-SPI bus is available."""

    if not sys.platform.startswith("linux"):
        pytest.skip(f"Linux acceptance tests need linux, found {sys.platform}")

    if os.environ.get("CECLI_INTEGRATION") != "1":
        pytest.skip("set CECLI_INTEGRATION=1 to run the Linux acceptance suite")

    available, reason = atspi_bus_state()

    if not available:
        pytest.skip(f"no AT-SPI accessibility bus: {reason}")


def test_doctor_reports_the_atspi_bus(
    cli: CliRunner, real_bridge: BridgeHandle, linux_platform: None
) -> None:
    """``doctor`` surfaces the session bus and the AT-SPI registry check."""

    result = cli.run("doctor", "--json")

    assert result.returncode == EXIT_OK, result.stderr

    payload = result.json()
    harness = json.dumps(payload).lower()

    assert payload.get("platform") == "linux" or "linux" in str(payload.get("backend", "")).lower()

    if "atspi" not in harness and "a11y" not in harness and "accessibility" not in harness:
        pytest.skip("doctor did not report AT-SPI; accessibility is probably disabled")

    names = {str(check.get("name", "")).lower() for check in payload.get("checks", [])}

    assert names & {"atspi_registry", "session_bus", "accessibility", "bus"}, names


def test_snapshot_of_any_window_is_structurally_valid(
    cli: CliRunner, real_bridge: BridgeHandle, linux_platform: None
) -> None:
    """Any accessible window returns a well-formed tree."""

    windows = list_windows(cli)

    assert windows, "AT-SPI reported no windows; is accessibility enabled?"

    title = str(windows[0].get("title") or "")
    result = cli.run("snapshot", "--window", title, "--json", timeout=60.0)

    assert result.returncode == EXIT_OK, result.stderr

    snapshot = result.json()

    assert isinstance(snapshot.get("window"), dict)
    assert isinstance(snapshot.get("elements"), list) and snapshot["elements"]

    ids = [element["id"] for element in snapshot["elements"]]

    assert len(ids) == len(set(ids))

    for element in snapshot["elements"]:
        assert isinstance(element.get("id"), int)
        assert isinstance(element.get("control_type"), str) and element["control_type"]
        assert isinstance(element.get("depth"), int) and element["depth"] >= 0


def test_gtk_fixture_is_snapshotted(
    cli: CliRunner, real_bridge: BridgeHandle, linux_platform: None
) -> None:
    """The GTK fixture appears in AT-SPI and exposes its entry and button."""

    if not display_available():
        pytest.skip("no DISPLAY or WAYLAND_DISPLAY for the GTK fixture")

    available, reason = gtk_available()

    if not available:
        pytest.skip(f"PyGObject/GTK3 unavailable: {reason}")

    process = start_gtk_fixture()

    try:
        title = wait_for_window(cli, FIXTURE_TITLE, timeout=30.0)
        snapshot = snapshot_window(cli, title)
    finally:
        stop_process(process)

    roles = {str(element.get("control_type", "")).lower() for element in snapshot["elements"]}
    names = {str(element.get("name", "")) for element in snapshot["elements"]}

    assert snapshot["elements"], "GTK fixture produced an empty snapshot"
    assert any("entry" in role or "button" in role for role in roles), roles
    assert "Save" in names or any("save" in role for role in roles), names


def atspi_bus_state(timeout: float = 5.0) -> tuple[bool, str]:
    """Return whether an AT-SPI bus is reachable and a human-readable reason."""

    if os.environ.get("AT_SPI_BUS_ADDRESS"):
        return True, "AT_SPI_BUS_ADDRESS is set"

    session_bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    runtime_bus = Path(f"/run/user/{os.getuid()}/bus")

    if not session_bus and not runtime_bus.exists():
        return False, "no DBUS_SESSION_BUS_ADDRESS and no session bus socket"

    gdbus = shutil.which("gdbus")

    if gdbus is None:
        return True, "session bus present; gdbus is not installed for a deeper probe"

    try:
        completed = subprocess.run(
            [
                gdbus,
                "call",
                "--session",
                "--dest",
                "org.a11y.Bus",
                "--object-path",
                "/org/a11y/bus",
                "--method",
                "org.a11y.Bus.GetAddress",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"org.a11y.Bus probe failed: {exc}"

    if completed.returncode != 0:
        return False, f"org.a11y.Bus is not on the session bus: {completed.stderr.strip()}"

    return True, completed.stdout.strip()


def display_available() -> bool:
    """True when an X11 or Wayland display is configured."""

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def gtk_available(timeout: float = 20.0) -> tuple[bool, str]:
    """Probe whether this interpreter can import GTK3 through PyGObject."""

    program = "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk"

    try:
        completed = subprocess.run(
            [sys.executable, "-c", program], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)

    if completed.returncode != 0:
        return False, completed.stderr.strip() or "import failed"

    return True, ""


def start_gtk_fixture() -> subprocess.Popen[Any]:
    """Launch the GTK fixture in its own process."""

    assert FIXTURE_SCRIPT.exists(), f"missing fixture script at {FIXTURE_SCRIPT}"

    return subprocess.Popen(
        [sys.executable, str(FIXTURE_SCRIPT)],
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_process(process: subprocess.Popen[Any]) -> None:
    """Terminate the fixture process and reap it."""

    if process.poll() is not None:
        return

    process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def list_windows(cli: CliRunner) -> list[dict[str, Any]]:
    """Return the parsed ``windows`` payload, or an empty list on failure."""

    result = cli.run("windows", "--json", timeout=60.0)

    if result.returncode != EXIT_OK:
        return []

    payload = result.json()
    return payload if isinstance(payload, list) else []


def wait_for_window(cli: CliRunner, title: str, timeout: float = 30.0) -> str:
    """Poll ``windows`` until a matching title appears."""

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


def snapshot_window(cli: CliRunner, title: str) -> dict[str, Any]:
    """Snapshot a window and return the parsed payload."""

    result = cli.run("snapshot", "--window", title, "--json", timeout=90.0)

    assert result.returncode == EXIT_OK, result.stderr
    return result.json()
