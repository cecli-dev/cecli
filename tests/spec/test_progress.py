"""Tests for unified spec implementation progress (checklist ↔ tasks_md ↔ agent)."""

from __future__ import annotations

from pathlib import Path

from cecli.spec.agent_todos import (
    AgentTodoRow,
    import_agent_plan_store,
)
from cecli.spec.progress import (
    checklist_from_agent_rows,
    implementation_steps,
    mark_implementation_step_done,
    materialize_checklist_from_tasks_md,
    merge_agent_progress_into_tasks_md,
    next_open_implementation_step,
    try_mark_focus_step_complete,
)
from cecli.spec.todos import ChecklistItem, TodoItem, TodoStore, _now_iso


def _item(*, tasks_md: str = "", checklist: list[ChecklistItem] | None = None) -> TodoItem:
    return TodoItem(
        id="t1",
        title="Feature",
        tasks_md=tasks_md,
        checklist=checklist or [],
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )


def test_merge_agent_progress_into_tasks_md_preserves_rich_text():
    tasks_md = (
        "## Implementation tasks\n\n"
        "- [ ] 1. Wire API for REQ-001 (depends: none)\n"
        '  - verify: `python -c "import api"`\n'
        "- [ ] 2. Add tests for REQ-002 (depends: 1)\n"
    )
    rows = [
        AgentTodoRow(text="1. Wire API for REQ-001 (depends: none)", done=True, current=False),
        AgentTodoRow(text="2. Add tests for REQ-002 (depends: 1)", done=False, current=True),
    ]
    merged = merge_agent_progress_into_tasks_md(tasks_md, rows)
    assert "- [x] 1. Wire API" in merged
    assert "verify: `python" in merged
    assert "- [ ] 2. Add tests" in merged


def test_checklist_from_agent_rows_reuses_stable_ids():
    prior = [
        ChecklistItem(id="keep-me", text="1. First step", done=False),
        ChecklistItem(id="also-keep", text="2. Second step", done=False),
    ]
    rows = [
        AgentTodoRow(text="1. First step", done=True, current=False),
        AgentTodoRow(text="2. Second step", done=False, current=True),
    ]
    out = checklist_from_agent_rows(rows, prior=prior)
    assert [c.id for c in out] == ["keep-me", "also-keep"]
    assert out[0].done is True


def test_materialize_checklist_from_tasks_md():
    item = _item(
        tasks_md="- [ ] 1. Scaffold lib/ (depends: none)\n- [x] 2. Add tests\n",
    )
    checklist = materialize_checklist_from_tasks_md(item)
    assert len(checklist) == 2
    assert checklist[0].done is False
    assert checklist[1].done is True


def test_implementation_steps_prefers_checklist():
    item = _item(
        tasks_md="- [ ] 9. Ignored when checklist present\n",
        checklist=[ChecklistItem(id="a", text="1. Real step", done=False)],
    )
    steps = implementation_steps(item)
    assert len(steps) == 1
    assert steps[0].step_id == "1"


def test_next_open_implementation_step_after_completed():
    item = _item(
        tasks_md=("- [x] 1. Done\n" "- [ ] 2. Next\n" "- [ ] 3. Later\n"),
    )
    nxt = next_open_implementation_step(item, after="1")
    assert nxt is not None
    assert nxt.step_id == "2"


def test_mark_implementation_step_done_updates_both_layers():
    item = _item(
        tasks_md="- [ ] 1. Wire module\n- [ ] 2. Add tests\n",
        checklist=[
            ChecklistItem(id="a", text="1. Wire module", done=False),
            ChecklistItem(id="b", text="2. Add tests", done=False),
        ],
    )
    updated = mark_implementation_step_done(item, "1", done=True)
    assert updated.checklist[0].done is True
    assert "- [x] 1. Wire module" in updated.tasks_md
    assert "- [ ] 2. Add tests" in updated.tasks_md


def test_try_mark_focus_step_complete_on_verify_pass():
    item = _item(
        tasks_md="- [ ] 1. Run lint\n  - verify: `true`\n",
        checklist=[ChecklistItem(id="a", text="1. Run lint", done=False)],
    )
    updated, changed = try_mark_focus_step_complete(
        item,
        "1",
        flutter_test_ok=None,
        verify_ok=True,
    )
    assert changed
    assert updated.checklist[0].done is True


def test_try_mark_focus_step_complete_requires_flutter_for_test_step():
    item = _item(
        checklist=[ChecklistItem(id="a", text="1.3 Write unit tests", done=False)],
    )
    _, changed = try_mark_focus_step_complete(
        item,
        "1.3",
        flutter_test_ok=False,
        verify_ok=True,
    )
    assert changed is False


def test_import_agent_plan_merges_done_into_preserved_tasks_md():
    spec_tasks = (
        "## Implementation tasks\n\n"
        "- [ ] 1. Wire generate-spec API for REQ-001 (depends: none)\n"
        "- [ ] 2. Add tests for REQ-002 (depends: 1)\n"
    )
    store = TodoStore(
        todos=[
            TodoItem(
                id="user1",
                title="My feature",
                tasks_md=spec_tasks,
                status="in_progress",
                links=[],
                checklist=[],
                created_at=_now_iso(),
                updated_at=_now_iso(),
            )
        ],
        active_id="user1",
    )
    rows = [
        AgentTodoRow(
            text="1. Wire generate-spec API for REQ-001 (depends: none)",
            done=True,
            current=False,
        ),
        AgentTodoRow(text="2. Add tests for REQ-002 (depends: 1)", done=False, current=True),
    ]
    out = import_agent_plan_store(store, rows, target_todo_id="user1")
    item = out.todos[0]
    assert "- [x] 1. Wire generate-spec" in item.tasks_md
    assert "REQ-001" in item.tasks_md
    assert item.checklist[0].done is True
    assert len(item.checklist) == 2


def test_workspace_todos_update_materializes_checklist(tmp_path: Path):
    from cecli.spec.todos import WorkspaceTodos

    api = WorkspaceTodos(tmp_path)
    store = api.load()
    item = TodoItem(
        id="t1",
        title="Feature",
        tasks_md="",
        checklist=[],
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    store.todos.append(item)
    api.save(store)

    updated, _ = api.update(
        item.id,
        tasks_md="- [ ] 1. Scaffold lib/ (depends: none)\n- [x] 2. Add tests\n",
    )
    assert len(updated.checklist) == 2
    assert updated.checklist[0].done is False
    assert updated.checklist[1].done is True
