"""Spec-focus gating: preamble only with active task + spec layers."""

from __future__ import annotations

import tempfile
import unittest

from cecli.spec.focus import (
    build_user_message_with_spec_context,
    should_inject_task_context,
    spec_focus_preamble_applies,
    spec_focus_requested,
    todo_has_spec_content,
)
from cecli.spec.todos import ChecklistItem, TodoItem, TodoStore, migrate_todo_layers


def _item(
    *,
    requirements: str = "",
    design: str = "",
    tasks_md: str = "",
) -> TodoItem:
    now = "2026-01-01T00:00:00Z"
    return migrate_todo_layers(
        TodoItem(
            id="task-1",
            title="Git tab",
            spec="",
            requirements=requirements,
            design=design,
            tasks_md=tasks_md,
            depends_on=[],
            branch="",
            pr_url="",
            status="open",
            links=[],
            checklist=[],
            created_at=now,
            updated_at=now,
        )
    )


class TestSpecFocusGating(unittest.TestCase):
    def test_spec_focus_requested_flags(self):
        self.assertTrue(
            spec_focus_requested(
                message_spec_focus=True,
                session_spec_focus=False,
                session_mode="vibe",
            )
        )
        self.assertTrue(
            spec_focus_requested(
                message_spec_focus=False,
                session_spec_focus=False,
                session_mode="spec",
            )
        )

    def test_empty_layers_not_spec_content(self):
        item = _item()
        self.assertFalse(todo_has_spec_content(item))
        self.assertFalse(spec_focus_preamble_applies(focus_requested=True, item=item))

    def test_tasks_md_alone_not_spec_content(self):
        item = _item(tasks_md="- [ ] Explore project structure\n- [ ] Ship feature")
        self.assertFalse(todo_has_spec_content(item))
        self.assertFalse(spec_focus_preamble_applies(focus_requested=True, item=item))

    def test_layers_with_requirements_is_spec_content(self):
        item = _item(requirements="### REQ-001\n**WHEN** x **THE** system **SHALL** y")
        self.assertTrue(todo_has_spec_content(item))
        self.assertTrue(spec_focus_preamble_applies(focus_requested=True, item=item))

    def test_no_preamble_without_active_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, active, tid = build_user_message_with_spec_context(
                tmp,
                "Add revert in Git tab",
                item=None,
                store=None,
                focus_requested=True,
                inject_todo_spec=False,
            )
            self.assertFalse(active)
            self.assertIsNone(tid)
            self.assertEqual(text, "Add revert in Git tab")
            self.assertNotIn("Spec-focus mode", text)

    def test_preamble_without_full_reinject_on_followup_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = _item(requirements="### REQ-001\n**WHEN** open **THE** UI **SHALL** show revert")
            store = TodoStore(version=1, active_id=item.id, todos=[item])
            text, active, tid = build_user_message_with_spec_context(
                tmp,
                "continue scaffolding",
                item=item,
                store=store,
                focus_requested=True,
                inject_todo_spec=False,
            )
            self.assertTrue(active)
            self.assertIsNone(tid)
            self.assertIn("Spec-focus mode", text)
            self.assertNotIn("REQ-001", text)
            self.assertTrue(text.endswith("continue scaffolding"))

    def test_full_inject_when_inject_todo_spec_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = _item(requirements="### REQ-001\n**WHEN** open **THE** UI **SHALL** show revert")
            store = TodoStore(version=1, active_id=item.id, todos=[item])
            text, active, tid = build_user_message_with_spec_context(
                tmp,
                "Implement REQ-001",
                item=item,
                store=store,
                focus_requested=True,
                inject_todo_spec=True,
            )
            self.assertTrue(active)
            self.assertIn("REQ-001", text)

    def test_implement_inject_uses_lean_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = "### REQ-001: Auth\n**WHEN** x **THE** system **SHALL** y\n" + ("detail " * 400)
            design = "Overview\n" + ("architecture " * 500)
            tasks = "- [ ] 1. Scaffold lib/ (depends: none)"
            item = _item(requirements=req, design=design, tasks_md=tasks)
            store = TodoStore(version=1, active_id=item.id, todos=[item])
            text, _, _ = build_user_message_with_spec_context(
                tmp,
                "Implement the active task per the injected requirements, design, and implementation tasks.",
                item=item,
                store=store,
                focus_requested=True,
                inject_todo_spec=True,
            )
            self.assertIn("Requirements (summary)", text)
            self.assertIn("### REQ-001", text)
            self.assertNotIn("detail detail detail", text)
            self.assertIn("Implementation tasks", text)
            self.assertIn("Scaffold lib/", text)
            self.assertIn("Implementation turn (tools)", text)
            self.assertIn("EditText", text)
            self.assertIn("Workspace snapshot", text)

    def test_tasks_tab_implement_injects_workspace_without_spec_focus_toggle(self):
        """Production path: inject_todo_spec=True, focus_requested=False (Tasks → Implement)."""
        with tempfile.TemporaryDirectory() as tmp:
            item = _item(
                requirements="### REQ-001\n**WHEN** x **THE** system **SHALL** y",
                design="Overview",
                tasks_md="- [ ] 2. Implement auth token helper in `src/auth/token.ts` (depends: 1)",
            )
            item = migrate_todo_layers(item)
            item.checklist = [
                ChecklistItem(id="c1", text="1. Review layout (depends: none)", done=False),
                ChecklistItem(
                    id="c2",
                    text="2. Implement auth token helper in `src/auth/token.ts` (depends: 1)",
                    done=False,
                ),
            ]
            store = TodoStore(version=1, active_id=item.id, todos=[item])
            agent_msg = (
                "/agent Implement only implementation task 2: "
                "Implement auth token helper in `src/auth/token.ts` (depends: 1)."
            )
            text, preamble, tid = build_user_message_with_spec_context(
                tmp,
                agent_msg,
                item=item,
                store=store,
                focus_requested=False,
                inject_todo_spec=True,
            )
            self.assertFalse(preamble)
            self.assertEqual(tid, item.id)
            self.assertIn("Workspace snapshot", text)
            self.assertIn("Implementation turn (tools)", text)
            self.assertNotIn("Spec-focus mode (BrightVision)", text)
            self.assertIn("ContextManager create", text)

    def test_resume_injects_workspace_without_reinject_or_spec_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = _item(
                requirements="### REQ-001\n**WHEN** x **THE** system **SHALL** y",
                tasks_md="- [x] 1. Create handler\n- [ ] 2. Add tests",
            )
            item = migrate_todo_layers(item)
            item.checklist = [
                ChecklistItem(id="c1", text="1. Create handler", done=True),
                ChecklistItem(id="c2", text="2. Add tests", done=False),
            ]
            store = TodoStore(version=1, active_id=item.id, todos=[item])
            text, preamble, tid = build_user_message_with_spec_context(
                tmp,
                "/agent Continue the active task from where you stopped.",
                item=item,
                store=store,
                focus_requested=False,
                inject_todo_spec=False,
            )
            self.assertFalse(preamble)
            self.assertIsNone(tid)
            self.assertIn("Workspace snapshot", text)
            self.assertNotIn("[Active task:", text)

    def test_implement_turn_detects_agent_prefix(self):
        from cecli.spec.focus import is_implement_turn_message

        self.assertTrue(
            is_implement_turn_message("/agent Implement only implementation task 1: Scaffold lib/.")
        )
        self.assertTrue(
            is_implement_turn_message("/agent Continue the active task from where you stopped.")
        )

    def test_agent_continuation_skips_full_spec_preamble(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = "### REQ-001: Auth\n**WHEN** x **THE** system **SHALL** y\n"
            item = _item(requirements=req, design="Overview", tasks_md="- [ ] 1. Scaffold")
            store = TodoStore(version=1, active_id=item.id, todos=[item])
            text, _, _ = build_user_message_with_spec_context(
                tmp,
                "/agent Continue the active task from where you stopped.",
                item=item,
                store=store,
                focus_requested=True,
                inject_todo_spec=False,
                agent_continuation=True,
            )
            self.assertIn("Workspace snapshot", text)
            self.assertIn("Continue (trimmed", text)
            self.assertNotIn("Spec-focus mode (BrightVision)", text)
            self.assertNotIn("Implementation turn (tools)", text)

    def test_agent_continuation_skips_full_task_inject(self):
        item = _item(requirements="### REQ-001\n**WHEN** open **THE** UI **SHALL** show revert")
        self.assertFalse(
            should_inject_task_context(
                focus_requested=True,
                item=item,
                inject_todo_spec=True,
                agent_continuation=True,
            )
        )

    def test_resume_implement_skips_full_task_inject(self):
        item = _item(requirements="### REQ-001\n**WHEN** x **THE** y **SHALL** z")
        self.assertFalse(
            should_inject_task_context(
                focus_requested=True,
                item=item,
                inject_todo_spec=True,
                message="/agent Continue the active task from where you stopped.",
            )
        )

    def test_resume_implement_injects_open_tasks_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = (
                "- [ ] 1. Scaffold workspace (`package.json`)\n"
                "- [ ] 2. Add domain (`packages/domain/src/index.ts`)\n"
            )
            item = _item(
                requirements="### REQ-001\n**WHEN** x **THE** y **SHALL** z", tasks_md=tasks
            )
            store = TodoStore(version=1, active_id=item.id, todos=[item])
            text, _, _ = build_user_message_with_spec_context(
                tmp,
                "/agent Continue the active task from where you stopped.",
                item=item,
                store=store,
                focus_requested=True,
                inject_todo_spec=False,
            )
            self.assertIn("Open implementation tasks (resume)", text)
            self.assertIn("package.json", text)
            self.assertNotIn("Requirements (summary)", text)

    def test_inject_without_preamble_when_layers_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = _item()
            store = TodoStore(version=1, active_id=item.id, todos=[item])
            text, active, tid = build_user_message_with_spec_context(
                tmp,
                "Seed requirements",
                item=item,
                store=store,
                focus_requested=True,
                inject_todo_spec=True,
            )
            self.assertFalse(active)
            self.assertEqual(tid, item.id)
            self.assertIn("[Active task:", text)
            self.assertNotIn("Spec-focus mode", text)
            self.assertNotIn("(No requirements yet.)", text)

    def test_light_inject_for_checklist_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = "2026-01-01T00:00:00Z"
            item = migrate_todo_layers(
                TodoItem(
                    id="task-2",
                    title="Explore repo",
                    spec="",
                    requirements="",
                    design="",
                    tasks_md="",
                    depends_on=[],
                    branch="",
                    pr_url="",
                    status="open",
                    links=[],
                    checklist=[
                        ChecklistItem(id="c1", text="List crates", done=False),
                    ],
                    created_at=now,
                    updated_at=now,
                )
            )
            store = TodoStore(version=1, active_id=item.id, todos=[item])
            text, active, tid = build_user_message_with_spec_context(
                tmp,
                "/agent go",
                item=item,
                store=store,
                focus_requested=False,
                inject_todo_spec=True,
            )
            self.assertEqual(tid, item.id)
            self.assertIn("## Checklist", text)
            self.assertIn("```markdown", text)
            self.assertIn("List crates", text)
            self.assertNotIn("Requirements", text)


if __name__ == "__main__":
    unittest.main()
