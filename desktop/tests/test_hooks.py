#!/usr/bin/env python3
"""End-to-end tests for the desktop Hooks registry.

Each case owns a real ``server.py`` process and the scripted ACP agent, so the
HTTP routes, the ``cecli/hook`` extension round trip and the cached state all
run together. Only the standard library is used.
"""

from __future__ import annotations

import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
FAKE_AGENT = Path(__file__).resolve().parent / "fake_acp_agent.py"


def free_port() -> int:
    """Ask the kernel for an unused loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class HooksTest(unittest.TestCase):
    """One server plus fake agent per test."""

    def setUp(self) -> None:
        try:
            free_port()
        except OSError as err:
            raise unittest.SkipTest(f"sockets are unavailable: {err}") from err

        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir()
        self.host = "127.0.0.1"
        self.port = free_port()

        global_conf = Path(self.temp_dir.name) / "global.yml"
        global_conf.write_text("{}\n", encoding="utf-8")
        desktop_conf = Path(self.temp_dir.name) / "desktop.yml"
        desktop_conf.write_text(
            "folders:\n  - path: " + json.dumps(str(self.workspace)) + "\n    name: workspace\n",
            encoding="utf-8",
        )
        self.env = dict(
            os.environ,
            CECLI_DESKTOP_CONF_FILE=str(Path(self.temp_dir.name) / "conf.yml"),
            CECLI_DESKTOP_GLOBAL_CONF=str(global_conf),
            CECLI_DESKTOP_FOLDERS_FILE=str(desktop_conf),
        )
        (Path(self.temp_dir.name) / "conf.yml").write_text("{}\n", encoding="utf-8")

        wrapper = Path(self.temp_dir.name) / "fake-cecli"
        wrapper.write_text(
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(FAKE_AGENT))} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

        self.process = subprocess.Popen(
            [
                sys.executable,
                str(SERVER),
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--workspace",
                str(self.workspace),
                "--cecli",
                str(wrapper),
            ],
            cwd=str(ROOT.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
        )
        self.wait_listening()
        self.wait_ready()

    def tearDown(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate(timeout=5)
        self.temp_dir.cleanup()

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 5.0
    ) -> tuple[int, dict[str, Any]]:
        """Send one JSON request and decode either the body or the error body."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"http://{self.host}:{self.port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            try:
                return err.code, json.loads(err.read().decode("utf-8"))
            finally:
                err.close()

    def wait_listening(self, timeout: float = 15.0) -> None:
        """Block until the HTTP server answers ``/api/health``."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stderr = self.process.stderr.read().decode("utf-8", errors="replace")
                raise AssertionError(f"server exited during startup:\n{stderr}")
            try:
                status, _ = self.request("GET", "/api/health", timeout=1.0)
            except OSError:
                time.sleep(0.05)
                continue
            if status == 200:
                return
            time.sleep(0.05)
        raise AssertionError("server did not start listening")

    def wait_ready(self, timeout: float = 15.0) -> dict[str, Any]:
        """Wait until the bridge reports a ready ACP session."""
        deadline = time.monotonic() + timeout
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                status, last = self.request("GET", "/api/state", timeout=2.0)
            except OSError:
                time.sleep(0.05)
                continue
            if status == 200 and last.get("status") == "ready":
                return last
            time.sleep(0.05)
        raise AssertionError(f"state never became ready; last state: {last}")

    def hook_by_name(self, hooks: list[dict[str, Any]], name: str) -> dict[str, Any]:
        """Return one hook entry from a state payload."""
        return next(hook for hook in hooks if hook["name"] == name)

    def test_state_exposes_configured_hooks(self) -> None:
        state = self.wait_ready()

        hooks = state["hooks"]
        self.assertEqual(len(hooks), 2)
        self.assertEqual({hook["name"] for hook in hooks}, {"guard", "notify"})
        self.assertTrue(self.hook_by_name(hooks, "guard")["enabled"])
        self.assertFalse(self.hook_by_name(hooks, "notify")["enabled"])
        self.assertEqual(self.hook_by_name(hooks, "guard")["priority"], 5)
        self.assertEqual(self.hook_by_name(hooks, "guard")["description"], "Blocks unsafe commands")

    def test_load_and_remove_toggle_enabled_state(self) -> None:
        self.wait_ready()

        status, body = self.request("POST", "/api/hooks", {"action": "load", "name": "notify"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(self.hook_by_name(body["hooks"], "notify")["enabled"])

        status, state = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertTrue(self.hook_by_name(state["hooks"], "notify")["enabled"])

        status, body = self.request("POST", "/api/hooks", {"action": "remove", "name": "guard"})
        self.assertEqual(status, 200)
        self.assertFalse(self.hook_by_name(body["hooks"], "guard")["enabled"])

        status, state = self.request("GET", "/api/state")
        self.assertFalse(self.hook_by_name(state["hooks"], "guard")["enabled"])

    def test_list_action_returns_hooks(self) -> None:
        self.wait_ready()

        status, body = self.request("POST", "/api/hooks", {"action": "list"})

        self.assertEqual(status, 200)
        self.assertEqual(
            sorted(hook["name"] for hook in body["hooks"]),
            ["guard", "notify"],
        )

    def test_unknown_hook_and_action_are_rejected(self) -> None:
        self.wait_ready()

        status, body = self.request("POST", "/api/hooks", {"action": "load", "name": "nope"})
        self.assertEqual(status, 502)
        self.assertFalse(body["ok"])

        status, body = self.request("POST", "/api/hooks", {"action": "explode", "name": "guard"})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])


class HooksStateTest(unittest.TestCase):
    """Unit tests for the flat, sorted ACP payload built by ``_hooks_state``."""

    def test_hooks_are_flattened_and_sorted_by_type_then_priority(self) -> None:
        from types import SimpleNamespace

        from cecli.helpers.server.acp.agent.agent import AcpAgent
        from cecli.hooks.service import HookService
        from cecli.hooks.types import HookType

        def hook(name: str, hook_type: HookType, priority: int, enabled: bool = True):
            return SimpleNamespace(
                name=name,
                type=hook_type,
                priority=priority,
                enabled=enabled,
                description=None,
            )

        grouped = {
            "end": [hook("cleanup", HookType.END, 1)],
            "start": [hook("hello", HookType.START, 5)],
            "pre_tool": [
                hook("guard", HookType.PRE_TOOL, 9),
                hook("lint", HookType.PRE_TOOL, 1, enabled=False),
            ],
        }
        manager = SimpleNamespace(get_all_hooks=lambda: grouped)
        original = HookService.get_manager
        HookService.get_manager = staticmethod(lambda coder: manager)

        try:
            hooks = AcpAgent._hooks_state(None, object())
        finally:
            HookService.get_manager = original

        self.assertEqual(
            [item["name"] for item in hooks],
            ["hello", "lint", "guard", "cleanup"],
        )
        self.assertEqual(
            [item["type"] for item in hooks],
            ["start", "pre_tool", "pre_tool", "end"],
        )
        self.assertEqual(
            set(hooks[0]),
            {"name", "type", "enabled", "priority", "description"},
        )
        self.assertFalse(hooks[1]["enabled"])

    def test_missing_manager_yields_an_empty_list(self) -> None:
        from cecli.helpers.server.acp.agent.agent import AcpAgent
        from cecli.hooks.service import HookService

        original = HookService.get_manager
        HookService.get_manager = staticmethod(
            lambda coder: (_ for _ in ()).throw(RuntimeError("no hooks"))
        )

        try:
            self.assertEqual(AcpAgent._hooks_state(None, object()), [])
        finally:
            HookService.get_manager = original


if __name__ == "__main__":
    unittest.main()
