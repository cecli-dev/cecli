"""Cecli agent todo.txt → workspace Tasks bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from cecli.spec.agent_todos import (
    AGENT_PLAN_TITLE,
    AgentTodoRow,
    AgentTodoSanitizeContext,
    _recover_char_split_agent_rows,
    agent_todo_link_for,
    current_agent_todo_row,
    export_todo_item_to_agent,
    format_agent_todo_txt,
    import_agent_plan_for_workspace,
    load_agent_todo_rows,
    parse_agent_todo_txt,
    plan_title_from_rows,
    rows_from_todo_item,
    rows_to_tasks_md,
    sanitize_agent_todo_rows,
    sync_session_agent_todos,
)
from cecli.spec.todos import ChecklistItem, TodoItem, WorkspaceTodos, _now_iso


def test_parse_agent_todo_txt():
    raw = """Done:
✓ First done

Remaining:
→ Current task
○ Next task
"""
    rows = parse_agent_todo_txt(raw)
    assert len(rows) == 3
    assert rows[0].done and rows[0].text == "First done"
    assert rows[1].current and not rows[1].done
    assert rows[2].text == "Next task"


def test_parse_agent_todo_txt_preserves_space_only_task_lines():
    # Char-split corruption uses ``○ {ch}``; a space task is ``○  `` (prefix + space).
    rows = parse_agent_todo_txt("Remaining:\n○  \n○ x\n")
    assert len(rows) == 2
    assert rows[0].text == " "
    assert rows[1].text == "x"


def test_plan_title_skips_char_split_debris():
    broken = [AgentTodoRow(text=c, done=False, current=(c == "[")) for c in "[{"]
    assert plan_title_from_rows(broken) == AGENT_PLAN_TITLE


def test_plan_title_uses_recovered_current_task():
    rows = [
        AgentTodoRow(text="Explore the codebase", done=False, current=True),
        AgentTodoRow(text="Draft roadmap", done=False, current=False),
    ]
    assert plan_title_from_rows(rows) == "Explore the codebase"


def test_recover_char_split_agent_rows():
    json_text = (
        '[{"task": "Explore the codebase", "done": false, "current": true},'
        '{"task": "Draft roadmap", "done": false}]'
    )
    broken = [AgentTodoRow(text=c, done=False, current=False) for c in json_text]
    rows = _recover_char_split_agent_rows(broken)
    assert len(rows) == 2
    assert rows[0].text == "Explore the codebase"
    assert rows[0].current
    assert rows[1].text == "Draft roadmap"


def test_import_agent_plan_into_workspace(tmp_path: Path):
    agents = tmp_path / ".cecli" / "agents" / "2026-05-27" / "abc"
    agents.mkdir(parents=True)
    (agents / "todo.txt").write_text(
        "Remaining:\n→ Ship feature\n○ Write tests\n",
        encoding="utf-8",
    )
    store = import_agent_plan_for_workspace(tmp_path)
    assert len(store.todos) == 1
    item = store.todos[0]
    assert item.title == "Ship feature"
    assert len(item.checklist) == 2
    assert store.active_id == item.id
    assert item.status == "in_progress"

    # Second import updates same task
    (agents / "todo.txt").write_text(
        "Remaining:\n→ Ship feature\n✓ Write tests\n",
        encoding="utf-8",
    )
    store2 = import_agent_plan_for_workspace(tmp_path)
    assert len(store2.todos) == 1
    assert store2.todos[0].checklist[1].done is True


def test_import_agent_plan_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        import_agent_plan_for_workspace(tmp_path)


def test_try_import_agent_plan_returns_none_when_missing(tmp_path: Path):
    from cecli.spec.agent_todos import try_import_agent_plan_for_workspace

    assert try_import_agent_plan_for_workspace(tmp_path) is None


def test_import_merges_into_active_task(tmp_path: Path):
    api = WorkspaceTodos(tmp_path)
    now = _now_iso()
    user_task = TodoItem(
        id="user1",
        title="My feature",
        tasks_md="",
        status="in_progress",
        links=[],
        checklist=[],
        created_at=now,
        updated_at=now,
    )
    store = api.load()
    store.todos.append(user_task)
    store.active_id = user_task.id
    api.save(store)

    agents = tmp_path / ".cecli" / "agents" / "2026-05-27" / "sess"
    agents.mkdir(parents=True)
    rel = ".cecli/agents/2026-05-27/sess/todo.txt"
    (agents / "todo.txt").write_text("Remaining:\n→ Step A\n○ Step B\n", encoding="utf-8")

    store2 = import_agent_plan_for_workspace(tmp_path, agent_todo_relpath=rel)
    assert len(store2.todos) == 1
    item = store2.todos[0]
    assert item.id == "user1"
    assert item.title == "My feature"
    assert len(item.checklist) == 2
    assert agent_todo_link_for(rel) in item.links


def test_import_agent_plan_preserves_spec_tasks_md(tmp_path: Path):
    from cecli.spec.agent_todos import preserve_spec_tasks_md_on_agent_import

    spec_tasks = (
        "- [ ] 1. Wire generate-spec API for REQ-001 (depends: none)\n"
        "- [ ] 2. Add tests for REQ-002 (depends: 1)\n"
    )
    agent_tasks = rows_to_tasks_md(
        [
            AgentTodoRow(text="Step A", done=False, current=True),
            AgentTodoRow(text="Step B", done=False, current=False),
        ]
    )
    item = TodoItem(
        id="user1",
        title="My feature",
        tasks_md=spec_tasks,
        status="in_progress",
        links=[],
        checklist=[],
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    assert preserve_spec_tasks_md_on_agent_import(item, agent_tasks) is True

    api = WorkspaceTodos(tmp_path)
    store = api.load()
    store.todos.append(item)
    store.active_id = item.id
    api.save(store)

    agents = tmp_path / ".cecli" / "agents" / "2026-05-27" / "sess"
    agents.mkdir(parents=True)
    rel = ".cecli/agents/2026-05-27/sess/todo.txt"
    (agents / "todo.txt").write_text("Remaining:\n→ Step A\n○ Step B\n", encoding="utf-8")

    store2 = import_agent_plan_for_workspace(tmp_path, agent_todo_relpath=rel)
    merged = store2.todos[0]
    assert merged.tasks_md == spec_tasks
    assert len(merged.checklist) == 2


def test_export_roundtrip(tmp_path: Path):
    rows = [
        AgentTodoRow(text="Done step", done=True, current=False),
        AgentTodoRow(text="Now", done=False, current=True),
        AgentTodoRow(text="Later", done=False, current=False),
    ]
    rel = ".cecli/agents/x/todo.txt"
    item = TodoItem(
        id="t1",
        title="Plan",
        tasks_md="",
        status="in_progress",
        links=[agent_todo_link_for(rel)],
        checklist=[
            ChecklistItem(id="a", text="Done step", done=True),
            ChecklistItem(id="b", text="Now", done=False),
            ChecklistItem(id="c", text="Later", done=False),
        ],
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    assert rows_from_todo_item(item) == rows
    export_todo_item_to_agent(tmp_path, rel, item)
    path = tmp_path / rel
    assert path.is_file()
    parsed = parse_agent_todo_txt(path.read_text(encoding="utf-8"))
    assert [r.text for r in parsed] == [r.text for r in rows]
    assert format_agent_todo_txt(rows) in path.read_text(encoding="utf-8")


def test_sanitize_reverts_premature_done_beyond_focus():
    rows = [
        AgentTodoRow(text="1.3 Write unit tests", done=True, current=False),
        AgentTodoRow(text="2.1 Create entities", done=True, current=False),
    ]
    ctx = AgentTodoSanitizeContext(focus_step="1.3", flutter_test_ok=None)
    sanitized, warnings = sanitize_agent_todo_rows(
        rows,
        ctx=ctx,
        prior_done_texts=frozenset(),
    )
    assert sanitized[0].done is True
    assert sanitized[1].done is False
    assert warnings


def test_sanitize_reverts_test_done_without_flutter_pass():
    rows = [
        AgentTodoRow(text="1.3 Write unit tests for NetworkInterceptor", done=True, current=False)
    ]
    ctx = AgentTodoSanitizeContext(focus_step="1.3", flutter_test_ok=False)
    sanitized, warnings = sanitize_agent_todo_rows(
        rows,
        ctx=ctx,
        prior_done_texts=frozenset(),
    )
    assert sanitized[0].done is False
    assert warnings


def test_current_agent_todo_row_prefers_marked_current(tmp_path: Path):
    rows = [
        AgentTodoRow(text="Done step", done=True, current=False),
        AgentTodoRow(text="3.1 Encrypted storage", done=False, current=True),
        AgentTodoRow(text="3.2 Later", done=False, current=False),
    ]
    row = current_agent_todo_row(rows)
    assert row is not None
    assert row.text.startswith("3.1")


def test_load_agent_todo_rows_from_latest(tmp_path: Path):
    agents = tmp_path / ".cecli" / "agents" / "2026-06-07" / "abc"
    agents.mkdir(parents=True)
    (agents / "todo.txt").write_text(
        "Remaining:\n→ 3.1 Develop EncryptedStorageRepository\n",
        encoding="utf-8",
    )
    rows = load_agent_todo_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0].current
    assert "3.1" in rows[0].text


def test_sync_session_pull_prefers_linked_agent_todo_over_stale_session_copy(tmp_path: Path):
    """Pre-session push must not revert a later workspace import from the linked todo.txt."""
    spec_tasks = (
        "## Implementation tasks\n\n"
        "- [ ] 1. Wire generate-spec API for REQ-001 (depends: none)\n"
        "- [ ] 2. Add tests for REQ-002 (depends: 1)\n"
    )
    api = WorkspaceTodos(tmp_path)
    store = api.load()
    item = TodoItem(
        id="user1",
        title="My feature",
        tasks_md=spec_tasks,
        status="in_progress",
        links=[],
        checklist=[],
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    store.todos.append(item)
    store.active_id = item.id
    api.save(store)

    class FakeCoder:
        def __init__(self, root: Path):
            self.root = root

        def local_agent_folder(self, name: str) -> str:
            return f".cecli/agents/2026-06-03/session-a/{name}"

    class FakeSession:
        def __init__(self, root: Path):
            self.coder = FakeCoder(root)

    session_rel = ".cecli/agents/2026-06-03/session-a/todo.txt"
    export_todo_item_to_agent(tmp_path, session_rel, item)

    linked_rel = ".cecli/agents/2026-05-27/imported/todo.txt"
    linked = tmp_path / linked_rel
    linked.parent.mkdir(parents=True)
    linked.write_text(
        "Done:\n"
        "✓ 1. Wire generate-spec API for REQ-001 (depends: none)\n\n"
        "Remaining:\n"
        "→ 2. Add tests for REQ-002 (depends: 1)\n",
        encoding="utf-8",
    )
    import_agent_plan_for_workspace(tmp_path, agent_todo_relpath=linked_rel)

    store2, _ = sync_session_agent_todos(FakeSession(tmp_path), pull=True, push_active=True)
    merged = store2.todos[0]
    assert "- [x] 1. Wire generate-spec" in merged.tasks_md
    assert merged.checklist[0].done is True


def test_sync_skips_pull_when_workspace_tasks_empty(tmp_path: Path):
    class FakeCoder:
        def __init__(self, root: Path):
            self.root = root

        def local_agent_folder(self, name: str) -> str:
            return f".cecli/agents/2026-06-03/session-a/{name}"

    class FakeSession:
        def __init__(self, root: Path):
            self.coder = FakeCoder(root)

    session = FakeSession(tmp_path)
    todo_path = tmp_path / session.coder.local_agent_folder("todo.txt")
    todo_path.parent.mkdir(parents=True, exist_ok=True)
    todo_path.write_text(
        "Remaining:\n→ Resurrect me\n",
        encoding="utf-8",
    )
    api = WorkspaceTodos(tmp_path)
    api.save(api.load())

    store, warnings = sync_session_agent_todos(session, pull=True, push_active=False)
    assert store.todos == []
    assert any("Skipped agent todo sync" in w for w in warnings)


def test_clear_session_agent_todo_file(tmp_path: Path):
    from cecli.spec.agent_todos import clear_session_agent_todo_file

    class FakeCoder:
        def __init__(self, root: Path):
            self.root = root

        def local_agent_folder(self, name: str) -> str:
            return f".cecli/agents/2026-06-03/session-a/{name}"

    class FakeSession:
        def __init__(self, root: Path):
            self.coder = FakeCoder(root)

    session = FakeSession(tmp_path)
    todo_path = tmp_path / session.coder.local_agent_folder("todo.txt")
    todo_path.parent.mkdir(parents=True, exist_ok=True)
    todo_path.write_text("Remaining:\n→ stale\n", encoding="utf-8")
    assert clear_session_agent_todo_file(session) is True
    assert not todo_path.is_file()
    assert clear_session_agent_todo_file(session) is False
