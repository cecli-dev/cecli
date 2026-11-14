"""Tests for workspace config persistence and GUI onboarding discovery."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import conf_store  # noqa: E402
import onboarding_api  # noqa: E402

SERVER = ROOT / "server.py"
FAKE_AGENT = Path(__file__).resolve().parent / "fake_acp_agent.py"


class ConfStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.global_path = self.root / "global.yml"
        self.project_path = self.workspace / ".cecli" / "conf.yml"
        self.desktop_path = self.root / "desktop.yml"
        self.global_path.write_text("model: openai/gpt-5\nunrelated: 7\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def store(self) -> conf_store.ConfStore:
        return conf_store.ConfStore(
            self.workspace,
            global_path=self.global_path,
            project_path=self.project_path,
            desktop_path=self.desktop_path,
        )

    def test_absent_folders_means_zero_workspaces(self) -> None:
        store = self.store()

        self.assertEqual(store.workspaces(), [])
        self.assertEqual(store.model(), "openai/gpt-5")

    def test_add_and_remove_workspace_preserves_other_keys(self) -> None:
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        self.desktop_path.write_text("theme: dark\ndesktop:\n  extra: true\n", encoding="utf-8")
        second = self.root / "second"
        second.mkdir()
        store = self.store()

        entry = store.add_workspace(str(second), "Second")

        self.assertEqual(entry["path"], str(second))
        self.assertEqual(entry["name"], "Second")
        data = yaml.safe_load(self.desktop_path.read_text(encoding="utf-8"))
        self.assertEqual(data["theme"], "dark")
        self.assertTrue(data["desktop"]["extra"])
        self.assertEqual(data["folders"][0]["path"], str(second))

        self.assertTrue(store.remove_workspace(str(second)))
        data = yaml.safe_load(self.desktop_path.read_text(encoding="utf-8"))
        self.assertEqual(data["folders"], [])
        self.assertEqual(data["desktop"]["extra"], True)

    def test_enable_on_startup_defaults_and_updates(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir()
        second.mkdir()
        store = self.store()

        first_entry = store.add_workspace(str(first), "First")
        second_entry = store.add_workspace(str(second), "Second")

        self.assertTrue(first_entry["enable_on_startup"])
        self.assertFalse(second_entry["enable_on_startup"])
        updated = store.update_workspace(str(second), enable_on_startup=True, name="Renamed")
        self.assertTrue(updated["enable_on_startup"])
        self.assertEqual(updated["name"], "Renamed")

        data = yaml.safe_load(self.desktop_path.read_text(encoding="utf-8"))
        self.assertTrue(data["folders"][0]["enable_on_startup"])
        self.assertTrue(data["folders"][1]["enable_on_startup"])
        self.assertEqual(data["folders"][1]["name"], "Renamed")

    def test_desktop_file_wins_over_legacy_configs(self) -> None:
        desktop_folder = self.root / "desktop-ws"
        desktop_folder.mkdir()
        legacy_global = self.root / "global-ws"
        legacy_global.mkdir()
        self.desktop_path.write_text(
            yaml.safe_dump({"folders": [{"path": str(desktop_folder)}]}),
            encoding="utf-8",
        )
        self.global_path.write_text(
            yaml.safe_dump({"desktop": {"folders": [{"path": str(legacy_global)}]}}),
            encoding="utf-8",
        )
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        self.project_path.write_text(
            yaml.safe_dump({"desktop": {"folders": [{"path": str(self.workspace)}]}}),
            encoding="utf-8",
        )

        self.assertEqual(self.store().workspaces()[0]["path"], str(desktop_folder))

    def test_global_conf_is_legacy_fallback(self) -> None:
        legacy = self.root / "legacy-ws"
        legacy.mkdir()
        self.global_path.write_text(
            yaml.safe_dump({"desktop": {"folders": [{"path": str(legacy)}]}}),
            encoding="utf-8",
        )

        self.assertEqual(self.store().workspaces()[0]["path"], str(legacy))

    def test_project_folders_are_legacy_fallback(self) -> None:
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        self.project_path.write_text(
            yaml.safe_dump({"desktop": {"folders": [{"path": str(self.workspace)}]}}),
            encoding="utf-8",
        )

        self.assertEqual(self.store().workspaces()[0]["path"], str(self.workspace))

    def test_key_bindings_copy_tui_config_into_desktop_yml(self) -> None:
        self.global_path.write_text(
            yaml.safe_dump(
                {
                    "tui-config": {
                        "key_bindings": {
                            "submit": "ctrl+j",
                            "newline": "enter",
                            "panel_cycle": "alt+o",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        bindings = self.store().key_bindings()

        self.assertEqual(
            bindings,
            {"submit": "ctrl+j", "newline": "enter", "panel_cycle": "alt+o"},
        )
        data = yaml.safe_load(self.desktop_path.read_text(encoding="utf-8"))
        self.assertEqual(data["key-bindings"], bindings)

    def test_desktop_key_bindings_are_never_overwritten(self) -> None:
        self.global_path.write_text(
            yaml.safe_dump({"tui-config": {"key_bindings": {"submit": "ctrl+j"}}}),
            encoding="utf-8",
        )
        self.desktop_path.write_text(
            yaml.safe_dump({"key-bindings": {"submit": "enter"}}),
            encoding="utf-8",
        )

        bindings = self.store().key_bindings()

        self.assertEqual(bindings, {"submit": "enter"})
        data = yaml.safe_load(self.desktop_path.read_text(encoding="utf-8"))
        self.assertEqual(data["key-bindings"], {"submit": "enter"})

    def test_invalid_folder_is_reported_not_raised(self) -> None:
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        self.desktop_path.write_text(
            yaml.safe_dump({"folders": [{"path": str(self.root / "missing")}]}),
            encoding="utf-8",
        )

        states = self.store().workspace_states()

        self.assertEqual(len(states), 1)
        self.assertFalse(states[0]["valid"])
        self.assertIn("does not exist", states[0]["error"])


class OnboardingServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.global_path = self.root / "global.yml"
        self.project_path = self.root / "conf.yml"
        self.desktop_path = self.root / "desktop.yml"
        self.global_path.write_text("", encoding="utf-8")
        self.store = conf_store.ConfStore(
            self.workspace,
            global_path=self.global_path,
            project_path=self.project_path,
            desktop_path=self.desktop_path,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_provider_listing_exposes_copilot_without_a_key(self) -> None:
        service = onboarding_api.OnboardingService(mock.Mock(sessions={}), self.store)

        with mock.patch.object(onboarding_api, "provider_has_key", return_value=True):
            payload = service.providers("github_copilot")

        copilot = next(item for item in payload["providers"] if item["slug"] == "github_copilot")
        self.assertFalse(copilot["requires_key"])
        self.assertTrue(copilot["configured"])
        self.assertTrue(payload["models"])

    def test_status_requires_onboarding_without_a_model(self) -> None:
        service = onboarding_api.OnboardingService(mock.Mock(sessions={}), self.store)

        with mock.patch.object(onboarding_api, "_env_values", return_value={}):
            status = service.status()

        self.assertFalse(status["configured"])
        self.assertTrue(status["requires_onboarding"])

    def test_configure_persists_keys_and_model(self) -> None:
        service = onboarding_api.OnboardingService(mock.Mock(sessions={}), self.store)
        home = self.root / "home"
        home.mkdir()

        with (
            mock.patch.object(onboarding_api.Path, "home", return_value=home),
            mock.patch.object(
                onboarding_api.OnboardingService, "_restart_sessions", mock.AsyncMock()
            ),
        ):
            import asyncio

            result = asyncio.run(
                service.configure(
                    {
                        "provider": "openai",
                        "model": "openai/gpt-5",
                        "api_keys": {"OPENAI_API_KEY": "sk-test"},
                    }
                )
            )

        self.assertTrue(result["configured"])
        env_file = home / ".cecli" / ".env"
        conf_file = home / ".cecli" / "conf.yml"
        self.assertIn("OPENAI_API_KEY", env_file.read_text(encoding="utf-8"))
        self.assertEqual(
            yaml.safe_load(conf_file.read_text(encoding="utf-8"))["model"],
            "openai/gpt-5",
        )


class EmptyWorkspaceServerTest(unittest.TestCase):
    """A server started without `desktop.folders` must expose zero sessions."""

    def setUp(self) -> None:
        import socket

        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            probe.close()
        except OSError as err:
            raise unittest.SkipTest(f"sockets are unavailable: {err}") from err

        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.port = self._free_port()
        conf = self.root / "conf.yml"
        conf.write_text("", encoding="utf-8")
        wrapper = self.root / "fake-cecli"
        wrapper.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_AGENT}" "$@"\n', encoding="utf-8"
        )
        wrapper.chmod(0o755)
        global_conf = self.root / "global.yml"
        global_conf.write_text("", encoding="utf-8")
        desktop_conf = self.root / "desktop.yml"
        desktop_conf.write_text("", encoding="utf-8")
        env = dict(
            os.environ,
            CECLI_DESKTOP_CONF_FILE=str(conf),
            CECLI_DESKTOP_GLOBAL_CONF=str(global_conf),
            CECLI_DESKTOP_FOLDERS_FILE=str(desktop_conf),
        )
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(SERVER),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--workspace",
                str(self.root),
                "--cecli",
                str(wrapper),
            ],
            cwd=str(ROOT.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._wait()

    def tearDown(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate(timeout=5)
        self.temp_dir.cleanup()

    def test_health_and_sessions_start_empty(self) -> None:
        status, health = self._request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["sessions"], 0)
        self.assertEqual(health["status"], "idle")

        status, listing = self._request("/api/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(listing["sessions"], [])

    def test_directory_suggestions(self) -> None:
        projects = self.root / "projects"
        projects.mkdir()
        (projects / "alpha").mkdir()
        (projects / "alpine").mkdir()
        (projects / "beta").mkdir()
        (projects / "alpha.txt").write_text("", encoding="utf-8")

        status, payload = self._request(
            f"/api/fs/dirs?path={urllib.parse.quote(str(projects / 'al'))}"
        )
        self.assertEqual(status, 200)
        self.assertEqual([entry["name"] for entry in payload["entries"]], ["alpha", "alpine"])

        status, payload = self._request(
            f"/api/fs/dirs?path={urllib.parse.quote(str(projects) + os.sep)}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            [entry["name"] for entry in payload["entries"]],
            ["alpha", "alpine", "beta"],
        )

    def test_onboarding_providers_list_copilot(self) -> None:
        status, payload = self._request("/api/onboarding/providers")
        self.assertEqual(status, 200)
        slugs = [item["slug"] for item in payload["providers"]]
        self.assertIn("github_copilot", slugs)

        status, copilot = self._request("/api/onboarding/providers?slug=github_copilot")
        self.assertEqual(status, 200)
        self.assertFalse(copilot["provider"]["requires_key"])
        self.assertTrue(copilot["models"])

    def _wait(self) -> None:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stderr = self.process.stderr.read().decode("utf-8", errors="replace")
                raise AssertionError(f"server exited during startup:\n{stderr}")
            try:
                status, _ = self._request("/api/health")
                if status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.05)
        raise AssertionError("server did not start listening")

    def _request(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}", timeout=2.0
            ) as response:
                import json

                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            import json

            try:
                return err.code, json.loads(err.read().decode("utf-8"))
            finally:
                err.close()

    def _free_port(self) -> int:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


if __name__ == "__main__":
    unittest.main()
