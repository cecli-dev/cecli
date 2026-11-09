"""Tests for file-edit diff extraction and history payload exposure."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cecli.helpers.conversation.service import ConversationService  # noqa: E402
from cecli.helpers.conversation.tags import MessageTag  # noqa: E402
from cecli.helpers.server.acp.agent.agent import (  # noqa: E402
    MAX_DIFF_CHARS,
    _conversation_diffs,
    _parse_diff_message,
)
from cecli.helpers.server.acp.agent.updates import UpdateEmitter  # noqa: E402

PLAIN = (
    "src/a.py has been updated. Review this diff of the changes to ensure all "
    "modifications are appropriate:\n\n@@ -1 +1 @@\n-old line\n+new line"
)
HASHLINES = (
    "src/b.py has been updated. Review this content ID prefixed diff of the changes "
    "to ensure all modifications are appropriate:\n\n"
    + json.dumps({"file_name": "src/b.py", "prefixed_diff": "1|@@ -1 +1 @@\n2|-old\n3|+new"})
)


def load_server_module():
    """Import desktop/server.py by path without invoking its CLI."""
    spec = importlib.util.spec_from_file_location("desktop_server_diffs", ROOT / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeManager:
    """Minimal conversation manager surface used by _conversation_diffs."""

    def __init__(self, messages):
        self._messages = messages

    def get_messages(self):
        return list(self._messages)


def fake_message(tag, content):
    return SimpleNamespace(tag=tag, to_dict=lambda: {"role": "user", "content": content})


class ParseDiffMessageTest(unittest.TestCase):
    def test_plain_diff(self) -> None:
        parsed = _parse_diff_message(PLAIN)

        self.assertIsNotNone(parsed)
        file_name, diff = parsed
        self.assertEqual(file_name, "src/a.py")
        self.assertEqual(diff, "@@ -1 +1 @@\n-old line\n+new line")

    def test_hashlines_json(self) -> None:
        parsed = _parse_diff_message(HASHLINES)

        self.assertIsNotNone(parsed)
        file_name, diff = parsed
        self.assertEqual(file_name, "src/b.py")
        self.assertIn("1|@@ -1 +1 @@", diff)

    def test_missing_body_returns_none(self) -> None:
        self.assertIsNone(_parse_diff_message("src/a.py has been updated. Review this diff"))

    def test_empty_content_returns_none(self) -> None:
        self.assertIsNone(_parse_diff_message(""))


class ConversationDiffsTest(unittest.TestCase):
    def test_extracts_dedupes_and_ignores_other_tags(self) -> None:
        messages = [
            fake_message(MessageTag.DIFFS.value, PLAIN),
            fake_message(MessageTag.DIFFS.value, PLAIN),
            fake_message(MessageTag.CUR.value, "unrelated"),
            fake_message(MessageTag.DIFFS.value, HASHLINES),
        ]

        with mock.patch.object(
            ConversationService, "get_manager", return_value=FakeManager(messages)
        ):
            diffs = _conversation_diffs(object())

        self.assertEqual(
            diffs,
            [
                {"file": "src/a.py", "diff": "@@ -1 +1 @@\n-old line\n+new line"},
                {
                    "file": "src/b.py",
                    "diff": "1|@@ -1 +1 @@\n2|-old\n3|+new",
                },
            ],
        )

    def test_no_diffs_returns_empty(self) -> None:
        messages = [fake_message(MessageTag.CUR.value, "just chat")]

        with mock.patch.object(
            ConversationService, "get_manager", return_value=FakeManager(messages)
        ):
            self.assertEqual(_conversation_diffs(object()), [])

    def test_long_diffs_are_capped(self) -> None:
        body = "+" + "x" * (MAX_DIFF_CHARS + 100)
        content = (
            "src/big.py has been updated. Review this diff of the changes to ensure all "
            f"modifications are appropriate:\n\n{body}"
        )

        with mock.patch.object(
            ConversationService,
            "get_manager",
            return_value=FakeManager([fake_message(MessageTag.DIFFS.value, content)]),
        ):
            diffs = _conversation_diffs(object())

        self.assertEqual(len(diffs), 1)
        self.assertTrue(diffs[0]["diff"].endswith("...(truncated)"))
        self.assertLessEqual(len(diffs[0]["diff"]), MAX_DIFF_CHARS + len("\n...(truncated)"))


class BridgeHistoryTest(unittest.TestCase):
    def test_history_preserves_main_and_subagent_diffs(self) -> None:
        module = load_server_module()
        bridge = object.__new__(module.AcpBridge)
        bridge.status = "ready"
        bridge.session_id = "s1"

        async def call_extension(method, params):
            self.assertEqual(method, "cecli/history")
            return {
                "messages": [],
                "diffs": [{"file": "src/a.py", "diff": "@@ -1 +1 @@\n-a\n+b"}],
                "subagents": [
                    {
                        "sessionId": "child-1",
                        "uuid": "uuid-1",
                        "messages": [],
                        "diffs": [{"file": "src/b.py", "diff": "@@ -2 +2 @@\n-c\n+d"}],
                    }
                ],
            }

        bridge.call_extension = call_extension
        result = asyncio.run(bridge.history())

        self.assertEqual(result["diffs"], [{"file": "src/a.py", "diff": "@@ -1 +1 @@\n-a\n+b"}])
        self.assertEqual(
            result["subagents"][0]["diffs"],
            [{"file": "src/b.py", "diff": "@@ -2 +2 @@\n-c\n+d"}],
        )


class UpdateEmitterDiffTest(unittest.TestCase):
    def test_diff_emits_session_update(self) -> None:
        updates = []
        emitter = UpdateEmitter(updates.append)

        emitter.diff("src/a.py", "@@ -1 +1 @@\n-a\n+b")

        self.assertEqual(
            updates,
            [
                {
                    "sessionUpdate": "diff",
                    "filePath": "src/a.py",
                    "diff": "@@ -1 +1 @@\n-a\n+b",
                }
            ],
        )

    def test_diff_without_path_is_ignored(self) -> None:
        updates = []
        UpdateEmitter(updates.append).diff("", "body")

        self.assertEqual(updates, [])


if __name__ == "__main__":
    unittest.main()
