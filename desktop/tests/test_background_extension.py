#!/usr/bin/env python3
"""Exercise the fake ACP agent's ``cecli/background`` extension."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

FAKE_AGENT = Path(__file__).resolve().parent / "fake_acp_agent.py"


class BackgroundExtensionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(FAKE_AGENT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def tearDown(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        self.process.wait(timeout=5)

    def call(self, request_id: int, params: dict[str, Any]) -> dict[str, Any]:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "cecli/background",
                    "params": params,
                }
            )
            + "\n"
        )
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        self.assertTrue(line, "fake agent closed stdout")
        return json.loads(line)

    def test_list_returns_camel_case_commands(self) -> None:
        response = self.call(1, {"action": "list"})

        commands = response["result"]["commands"]
        self.assertEqual([item["key"] for item in commands], ["bg_1_0001", "bg_2_0002"])
        self.assertEqual(
            set(commands[0]),
            {
                "key",
                "command",
                "running",
                "persist",
                "continuedInBackground",
                "bufferSize",
                "pages",
                "totalChars",
                "startTime",
                "endTime",
                "duration",
            },
        )
        self.assertTrue(commands[0]["running"])
        self.assertTrue(commands[0]["continuedInBackground"])

    def test_output_returns_text_and_command(self) -> None:
        response = self.call(2, {"action": "output", "key": "bg_1_0001"})

        payload = response["result"]
        self.assertEqual(payload["output"], "tick 1\ntick 2\ntick 3\n")
        self.assertEqual(payload["command"]["command"], "sleep 60")

    def test_unknown_key_is_invalid_params(self) -> None:
        response = self.call(3, {"action": "output", "key": "missing"})

        self.assertEqual(response["error"]["code"], -32602)

    def test_unknown_action_is_invalid_params(self) -> None:
        response = self.call(4, {"action": "stop"})

        self.assertEqual(response["error"]["code"], -32602)


class RealBackgroundHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        from cecli.helpers.server.acp.agent.agent import AcpAgent

        self.agent = object.__new__(AcpAgent)

    def test_list_maps_manager_entries(self) -> None:
        from unittest import mock

        from cecli.helpers.background_commands import BackgroundCommandManager

        info = {
            "command": "sleep 60",
            "running": True,
            "persist": False,
            "continued_in_background": True,
            "buffer_size": 12,
            "pages": 2,
            "total_chars": 40,
            "start_time": 5.0,
            "end_time": None,
            "duration": 1.5,
        }

        with mock.patch.object(
            BackgroundCommandManager, "list_background_commands", return_value={"bg_x": info}
        ):
            payload = self.agent._on_cecli_background({"action": "list"}, 1)

        self.assertEqual(
            payload,
            {
                "commands": [
                    {
                        "key": "bg_x",
                        "command": "sleep 60",
                        "state": "running",
                        "running": True,
                        "persist": False,
                        "continuedInBackground": True,
                        "pid": None,
                        "cols": 100,
                        "rows": 30,
                        "pty": False,
                        "seq": 0,
                        "startSeq": 0,
                        "exitCode": None,
                        "signal": None,
                        "endedAt": None,
                        "needsInput": False,
                        "lastPrompt": None,
                        "inputOwner": None,
                        "consumedAt": None,
                        "bufferSize": 12,
                        "pages": 2,
                        "totalChars": 40,
                        "startTime": 5.0,
                        "endTime": None,
                        "duration": 1.5,
                    }
                ]
            },
        )

    def test_browser_endpoint_updates_the_shared_helper(self) -> None:
        from unittest import mock

        from cecli.helpers import browser

        browser.clear_active_cdp_url()
        try:
            payload = self.agent._on_cecli_browser(
                {"cdpUrl": "http://127.0.0.1:9334", "port": 9334}, 5
            )
            assert payload["ok"] is True
            with mock.patch.object(browser, "cdp_available", return_value=True):
                assert browser.ensure_cdp_url() == "http://127.0.0.1:9334"

            browser.clear_active_cdp_url()
            assert browser.get_browser_config()["cdp_url"] is None
        finally:
            browser.clear_active_cdp_url()

    def test_output_returns_buffer_and_entry(self) -> None:
        from unittest import mock

        from cecli.helpers.background_commands import BackgroundCommandManager

        info = {"command": "echo hi", "running": False}

        with (
            mock.patch.object(
                BackgroundCommandManager, "list_background_commands", return_value={"bg_y": info}
            ),
            mock.patch.object(BackgroundCommandManager, "get_command_output", return_value="hi\n"),
        ):
            payload = self.agent._on_cecli_background({"action": "output", "key": "bg_y"}, 2)

        self.assertEqual(payload["output"], "hi\n")
        self.assertEqual(payload["command"]["key"], "bg_y")
        self.assertEqual(payload["command"]["command"], "echo hi")

    def test_unknown_key_and_action_raise_invalid_params(self) -> None:
        from unittest import mock

        from cecli.helpers.background_commands import BackgroundCommandManager
        from cecli.helpers.server.acp.agent.agent import AcpError

        with mock.patch.object(
            BackgroundCommandManager, "list_background_commands", return_value={}
        ):
            with self.assertRaises(AcpError) as unknown_key:
                self.agent._on_cecli_background({"action": "output", "key": "nope"}, 3)

            with self.assertRaises(AcpError) as unknown_action:
                self.agent._on_cecli_background({"action": "stop"}, 4)

        self.assertEqual(unknown_key.exception.code, -32602)
        self.assertEqual(unknown_action.exception.code, -32602)


if __name__ == "__main__":
    unittest.main()
