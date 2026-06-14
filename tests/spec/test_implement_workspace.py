"""Tests for implement workspace snapshot injection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cecli.spec.agent_todos import AgentTodoRow
from cecli.spec.implement import (
    build_implement_workspace_block,
    checklist_step_prefix,
    dart_test_paths_for_focus,
    deliverable_paths_exist,
    focus_checklist_item,
    is_step_after,
    paths_from_checklist_text,
    resolve_flutter_executable,
    resolve_implement_focus,
)
from cecli.spec.todos import ChecklistItem


class TestImplementWorkspace(unittest.TestCase):
    def test_paths_from_checklist_text(self):
        text = "1.2 Implement NetworkInterceptor in lib/core/network/"
        assert paths_from_checklist_text(text) == ["lib/core/network"]

    def test_deliverable_paths_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            net = root / "lib" / "core" / "network"
            net.mkdir(parents=True)
            (net / "interceptor.dart").write_text("// x", encoding="utf-8")
            self.assertTrue(deliverable_paths_exist(root, ["lib/core/network"]))

    def test_focus_prefers_active_task_title_over_first_open(self):
        checklist = [
            ChecklistItem(
                id="c1", text="1.2 Implement NetworkInterceptor in lib/core/network/", done=False
            ),
            ChecklistItem(id="c2", text="1.3 Write unit tests for NetworkInterceptor", done=False),
        ]
        focus = focus_checklist_item(
            checklist,
            message="Implement the active task per the injected requirements.",
            active_task_title="1.3 Write unit tests for NetworkInterceptor",
        )
        self.assertEqual(focus.text, checklist[1].text)

    def test_focus_from_implement_step_message(self):
        checklist = [
            ChecklistItem(id="c1", text="1.1 Scaffold lib/", done=True),
            ChecklistItem(id="c2", text="1.3 Write unit tests for NetworkInterceptor", done=False),
        ]
        focus = focus_checklist_item(
            checklist,
            message="/agent Implement only implementation task 1.3: Write unit tests for NetworkInterceptor.",
        )
        self.assertEqual(focus.text, checklist[1].text)

    def test_step_ordering(self):
        self.assertTrue(is_step_after("2.1", "1.3"))
        self.assertFalse(is_step_after("1.2", "1.3"))

    def test_focus_prefers_active_task_title_even_when_done(self):
        checklist = [
            ChecklistItem(id="c1", text="1.3 Write unit tests for NetworkInterceptor", done=True),
            ChecklistItem(id="c2", text="2.2 Define abstract repository interfaces", done=False),
        ]
        focus = focus_checklist_item(
            checklist,
            message="/agent Continue the active task from where you stopped.",
            active_task_title="1.3 Write unit tests for NetworkInterceptor",
        )
        self.assertEqual(focus.text, checklist[0].text)

    def test_test_paths_for_focus_matches_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_dir = root / "test" / "core" / "network"
            test_dir.mkdir(parents=True)
            (test_dir / "network_interceptor_test.dart").write_text("", encoding="utf-8")
            (test_dir / "other_test.dart").write_text("", encoding="utf-8")
            focus = ChecklistItem(
                id="c1", text="1.3 Write unit tests for NetworkInterceptor", done=False
            )
            paths = dart_test_paths_for_focus(root, focus)
            self.assertIn("test/core/network/network_interceptor_test.dart", paths)

    def test_snapshot_lists_lib_and_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pubspec.yaml").write_text("name: x\n", encoding="utf-8")
            lib = root / "lib" / "core" / "network"
            lib.mkdir(parents=True)
            (lib / "a.dart").write_text("", encoding="utf-8")
            test = root / "test" / "core" / "network"
            test.mkdir(parents=True)
            (test / "a_test.dart").write_text("", encoding="utf-8")
            checklist = [
                ChecklistItem(
                    id="c1", text="1.3 Write unit tests for NetworkInterceptor", done=False
                ),
            ]
            block = build_implement_workspace_block(
                root,
                checklist,
                resume=True,
                active_task_title="1.3 Write unit tests for NetworkInterceptor",
            )
            self.assertIn("Workspace snapshot", block)
            self.assertIn("lib/core/network/a.dart", block)
            self.assertIn("test/core/network/a_test.dart", block)
            self.assertIn("1.3 Write unit tests", block)
            self.assertIn("Do not batch UpdateTodoList", block)
            self.assertIn("flutter test", block)
            self.assertNotIn("1.2 Implement NetworkInterceptor", block)

    def test_continuation_block_is_trimmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pubspec.yaml").write_text("name: x\n", encoding="utf-8")
            block = build_implement_workspace_block(
                root,
                [],
                resume=True,
                agent_continuation=True,
            )
            self.assertIn("Continue (trimmed", block)

    def test_resolve_focus_from_agent_todo_when_checklist_all_done(self):
        checklist = [
            ChecklistItem(id="c1", text="2.2 Define abstract repository interfaces", done=True),
            ChecklistItem(id="c2", text="2.3 Write unit tests mocking repositories", done=True),
        ]
        agent_rows = [
            AgentTodoRow(
                text="3.1 Develop EncryptedStorageRepository for local encrypted data",
                done=False,
                current=True,
            ),
        ]
        focus, from_agent = resolve_implement_focus(
            checklist,
            message="/agent Continue the active task.",
            active_task_title="Agent session plan",
            agent_todo_rows=agent_rows,
        )
        self.assertTrue(from_agent)
        self.assertIn("3.1 Develop EncryptedStorageRepository", focus.text)

    def test_build_block_uses_agent_todo_when_checklist_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pubspec.yaml").write_text("name: x\n", encoding="utf-8")
            agents = root / ".cecli" / "agents" / "2026-06-07" / "abc"
            agents.mkdir(parents=True)
            (agents / "todo.txt").write_text(
                "Remaining:\n→ 3.1 Develop EncryptedStorageRepository for local encrypted data\n",
                encoding="utf-8",
            )
            checklist = [
                ChecklistItem(id="c1", text="2.2 Define abstract repository interfaces", done=True),
            ]
            block = build_implement_workspace_block(
                root,
                checklist,
                resume=True,
                active_task_title="Agent session plan",
            )
            self.assertIn("Agent todo", block)
            self.assertIn("3.1 Develop EncryptedStorageRepository", block)
            self.assertNotIn("All checklist items are marked done", block)

    def test_checklist_step_prefix(self):
        self.assertEqual(checklist_step_prefix("1.3 Write unit tests"), "1.3")

    @patch("cecli.spec.implement.shutil.which", return_value="/opt/flutter/bin/flutter")
    def test_resolve_flutter_executable(self, _which):
        self.assertEqual(resolve_flutter_executable(), "/opt/flutter/bin/flutter")


if __name__ == "__main__":
    unittest.main()
