"""CLI tests for cecli.spec.tasks_cli."""

from __future__ import annotations

import json
from pathlib import Path

from cecli.spec.tasks_cli import main
from cecli.spec.todos import TodoItem, WorkspaceTodos, _now_iso


def test_cli_materialize_and_progress(tmp_path: Path):
    api = WorkspaceTodos(tmp_path)
    store = api.load()
    item = TodoItem(
        id="t1",
        title="Feature",
        tasks_md="- [ ] 1.1 Wire (depends: none)\n- [x] 1.2 Test\n",
        checklist=[],
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    store.todos.append(item)
    store.active_id = item.id
    api.save(store)

    assert main(["--workspace", str(tmp_path), "materialize", "--todo-id", "t1"]) == 0
    assert main(["--workspace", str(tmp_path), "progress", "--todo-id", "t1"]) == 0

    updated = api.load().todos[0]
    assert len(updated.checklist) == 2
