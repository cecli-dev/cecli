#!/usr/bin/env python3
"""Parent-death cleanup for the desktop bridge and its ACP child."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
FAKE_AGENT = Path(__file__).resolve().parent / "fake_acp_agent.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import parent_death  # noqa: E402

PARENT_SCRIPT = """
import os
import subprocess
import sys
import time

server, pid_file, ready_file, port, workspace, cecli = sys.argv[1:7]
child = subprocess.Popen(
    [
        sys.executable,
        server,
        "--host",
        "127.0.0.1",
        "--port",
        port,
        "--workspace",
        workspace,
        "--cecli",
        cecli,
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
with open(pid_file, "w", encoding="utf-8") as handle:
    handle.write(str(child.pid))
while not os.path.exists(ready_file):
    time.sleep(0.05)
"""


class ParentDeathTest(unittest.TestCase):
    """A bridge and its ACP child must not outlive the spawning process."""

    def setUp(self) -> None:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
            probe.close()
        except OSError as err:
            raise unittest.SkipTest(f"sockets are unavailable: {err}") from err

        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()

        conf = root / "conf.yml"
        conf.write_text("{}\n", encoding="utf-8")
        global_conf = root / "global.yml"
        global_conf.write_text("{}\n", encoding="utf-8")
        desktop_conf = root / "desktop.yml"
        desktop_conf.write_text(
            "folders:\n  - path: " + json.dumps(str(self.workspace)) + "\n    name: workspace\n",
            encoding="utf-8",
        )

        wrapper = root / "fake-cecli"
        wrapper.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_AGENT}" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

        self.cecli = wrapper
        self.env = dict(
            os.environ,
            CECLI_DESKTOP_CONF_FILE=str(conf),
            CECLI_DESKTOP_GLOBAL_CONF=str(global_conf),
            CECLI_DESKTOP_FOLDERS_FILE=str(desktop_conf),
        )
        self.pid_file = root / "server.pid"
        self.ready_file = root / "ready"
        self.parent_script = root / "parent.py"
        self.parent_script.write_text(PARENT_SCRIPT, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_bridge_and_agent_exit_when_parent_dies(self) -> None:
        if not sys.platform.startswith("linux"):
            self.skipTest("parent-death signals are Linux-specific")

        parent, server_pid, agent_pid = self._start_parent()

        self.ready_file.write_text("go", encoding="utf-8")
        parent.wait(timeout=15)

        self.assertTrue(_wait_gone(server_pid, 15.0), "bridge outlived its parent")
        self.assertTrue(_wait_gone(agent_pid, 15.0), "ACP child outlived its bridge")

    def test_agent_exits_when_bridge_is_killed(self) -> None:
        if not sys.platform.startswith("linux"):
            self.skipTest("parent-death signals are Linux-specific")

        parent, server_pid, agent_pid = self._start_parent()

        os.kill(server_pid, signal.SIGKILL)

        self.assertTrue(_wait_gone(server_pid, 10.0), "bridge survived SIGKILL")
        self.assertTrue(_wait_gone(agent_pid, 10.0), "ACP child outlived a killed bridge")

        self.ready_file.write_text("go", encoding="utf-8")
        parent.wait(timeout=15)

    def test_opt_out_keeps_bridge_alive(self) -> None:
        if not sys.platform.startswith("linux"):
            self.skipTest("parent-death signals are Linux-specific")

        env = dict(self.env, CECLI_DESKTOP_KEEP_ON_PARENT_EXIT="1")
        parent, server_pid, agent_pid = self._start_parent(env)

        self.ready_file.write_text("go", encoding="utf-8")
        parent.wait(timeout=15)
        time.sleep(2.0)

        self.assertTrue(_alive(server_pid), "opt-out bridge exited with its parent")
        self.assertTrue(_alive(agent_pid), "opt-out ACP child exited with the bridge")

        _kill_pid(server_pid)
        _kill_pid(agent_pid)
        self.assertTrue(_wait_gone(server_pid, 10.0))
        self.assertTrue(_wait_gone(agent_pid, 10.0))

    def test_child_hook_matches_platform(self) -> None:
        hook = parent_death.child_parent_death_hook()

        if sys.platform.startswith("linux"):
            self.assertTrue(callable(hook))
        else:
            self.assertIsNone(hook)

    def _start_parent(
        self, env: dict[str, str] | None = None
    ) -> tuple[subprocess.Popen[bytes], int, int]:
        parent = subprocess.Popen(
            [
                sys.executable,
                str(self.parent_script),
                str(SERVER),
                str(self.pid_file),
                str(self.ready_file),
                str(self.port),
                str(self.workspace),
                str(self.cecli),
            ],
            cwd=str(ROOT.parent),
            env=env or self.env,
        )
        self.addCleanup(_kill_process, parent)

        server_pid = self._wait_for_pid_file()
        self.addCleanup(_kill_pid, server_pid)
        agent_pid = self._wait_for_child(server_pid)
        self.addCleanup(_kill_pid, agent_pid)
        self._wait_listening()

        return parent, server_pid, agent_pid

    def _wait_for_pid_file(self, timeout: float = 10.0) -> int:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if self.pid_file.exists():
                text = self.pid_file.read_text(encoding="utf-8").strip()
                if text:
                    return int(text)

            time.sleep(0.05)

        self.fail("the bridge parent never wrote its child pid")

    def _wait_for_child(self, pid: int, timeout: float = 10.0) -> int:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            children = _children(pid)
            if children:
                return children[0]

            time.sleep(0.05)

        self.fail("the bridge did not spawn an ACP child")

    def _wait_listening(self, timeout: float = 10.0) -> None:
        url = f"http://127.0.0.1:{self.port}/api/health"
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.0) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass

            time.sleep(0.05)

        self.fail("the bridge never answered /api/health")


def _children(pid: int) -> list[int]:
    try:
        text = Path(f"/proc/{pid}/task/{pid}/children").read_text(encoding="utf-8")
    except OSError:
        return []

    return [int(value) for value in text.split() if value.isdigit()]


def _wait_gone(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if not _alive(pid):
            return True

        time.sleep(0.05)

    return not _alive(pid)


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2]
    except (OSError, IndexError):
        return False

    return state != "Z"


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    process.kill()

    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass
