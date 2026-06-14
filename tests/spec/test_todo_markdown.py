"""Markdown import/export for workspace tasks."""

from __future__ import annotations

import unittest

from cecli.spec.markdown import export_markdown, import_markdown
from cecli.spec.todos import ChecklistItem, TodoItem, TodoStore


class TestTodoMarkdown(unittest.TestCase):
    def test_export_import_roundtrip(self):
        store = TodoStore(
            todos=[
                TodoItem(
                    id="task-1",
                    title="Auth flow",
                    status="in_progress",
                    requirements="### REQ-001\n**WHEN** login\n**THE** system **SHALL** auth.\n",
                    design="## Overview\nOAuth.",
                    tasks_md="- [ ] 1. Add route (depends: none)",
                    checklist=[ChecklistItem(id="c1", text="Wire UI", done=False)],
                    depends_on=["task-0"],
                    branch="feature/auth",
                )
            ],
            active_id="task-1",
        )
        md = export_markdown(store)
        self.assertIn("# Auth flow", md)
        self.assertIn("activeId: task-1", md)
        self.assertIn("## Requirements", md)
        self.assertIn("REQ-001", md)

        imported = import_markdown(md)
        self.assertEqual(len(imported.todos), 1)
        item = imported.todos[0]
        self.assertEqual(item.title, "Auth flow")
        self.assertEqual(item.id, "task-1")
        self.assertIn("REQ-001", item.requirements)
        self.assertEqual(imported.active_id, "task-1")
        self.assertEqual(len(item.checklist), 1)
        self.assertEqual(item.checklist[0].text, "Wire UI")

    def test_import_legacy_specification_section(self):
        md = """\
# Legacy task
id: legacy-1
status: todo

## Specification
Single-layer spec body.
"""
        store = import_markdown(md)
        self.assertEqual(len(store.todos), 1)
        self.assertIn("Single-layer", store.todos[0].spec)


if __name__ == "__main__":
    unittest.main()
