"""Link Cecli agent ``todo.txt`` (UpdateTodoList) with workspace Tasks (``.cecli/todos.json``)."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from cecli.spec.runtime import AgentTodoSession
from cecli.spec.todos import (
    ChecklistItem,
    TodoItem,
    TodoStore,
    WorkspaceTodos,
    _now_iso,
)

AGENT_PLAN_TITLE = "Agent session plan"
AGENT_PLAN_LINK = "cecli:agent-todo"
AGENT_TODO_LINK_PREFIX = "cecli:agent-todo:"


@dataclass(frozen=True)
class AgentTodoRow:
    text: str
    done: bool
    current: bool


@dataclass(frozen=True)
class AgentTodoSanitizeContext:
    """Optional guards applied when pulling agent todo.txt into workspace Tasks."""

    focus_step: str | None = None
    flutter_test_ok: bool | None = None


def sanitize_agent_todo_rows(
    rows: list[AgentTodoRow],
    *,
    ctx: AgentTodoSanitizeContext,
    prior_done_texts: frozenset[str],
) -> tuple[list[AgentTodoRow], list[str]]:
    """Revert premature done marks from agent UpdateTodoList during implement turns."""
    from cecli.spec.implement import (
        checklist_step_prefix,
        is_step_after,
        is_test_related_checklist_text,
    )

    warnings: list[str] = []
    sanitized: list[AgentTodoRow] = []
    for row in rows:
        keep = row
        step = checklist_step_prefix(row.text)
        newly_done = row.done and row.text not in prior_done_texts

        if newly_done and ctx.focus_step and step and is_step_after(step, ctx.focus_step):
            keep = AgentTodoRow(text=row.text, done=False, current=row.current)
            warnings.append(
                f"Reverted premature done on **{row.text[:72]}** "
                f"(beyond current focus **{ctx.focus_step}**)."
            )
        elif (
            newly_done and ctx.flutter_test_ok is False and is_test_related_checklist_text(row.text)
        ):
            keep = AgentTodoRow(text=row.text, done=False, current=row.current)
            warnings.append(
                f"Reverted done on **{row.text[:72]}** — BrightVision flutter test did not pass."
            )

        sanitized.append(keep)
    return sanitized, warnings


def agent_todo_link_for(relpath: str) -> str:
    return f"{AGENT_TODO_LINK_PREFIX}{relpath.replace(chr(92), '/')}"


def current_agent_todo_row(rows: list[AgentTodoRow]) -> AgentTodoRow | None:
    """First ``→`` (current) open row, else first remaining open row."""
    for row in rows:
        if row.current and not row.done:
            return row
    for row in rows:
        if not row.done:
            return row
    return None


def load_agent_todo_rows(workspace: str | Path, item: TodoItem | None = None) -> list[AgentTodoRow]:
    """Read Cecli agent ``todo.txt`` for implement-turn grounding."""
    root = Path(workspace).resolve()
    relpath = parse_agent_todo_link(item.links) if item else None
    if not relpath and item and AGENT_PLAN_LINK in item.links:
        latest = find_latest_agent_todo_txt(root)
        if latest:
            relpath = str(latest.relative_to(root)).replace("\\", "/")
    if not relpath:
        latest = find_latest_agent_todo_txt(root)
        if latest:
            relpath = str(latest.relative_to(root)).replace("\\", "/")
    path = resolve_agent_todo_path(root, relpath)
    if not path:
        return []
    rows = parse_agent_todo_txt(path.read_text(encoding="utf-8"))
    return _recover_char_split_agent_rows(rows)


def parse_agent_todo_link(links: list[str]) -> str | None:
    for link in links:
        if link.startswith(AGENT_TODO_LINK_PREFIX):
            return link[len(AGENT_TODO_LINK_PREFIX) :]
    return None


def is_agent_linked_task(item: TodoItem) -> bool:
    return bool(parse_agent_todo_link(item.links)) or AGENT_PLAN_LINK in item.links


def _recover_char_split_agent_rows(rows: list[AgentTodoRow]) -> list[AgentTodoRow]:
    """
    Recover when UpdateTodoList wrote one todo line per JSON character (local model quirk).

    BrightVision imports agent todo.txt into Tasks checklist + tasks_md; without this,
    a corrupted file keeps single-character rows until the user clears the task.
    """
    if len(rows) < 8 or not all(len(row.text) <= 2 for row in rows):
        return rows
    joined = "".join(row.text for row in rows).strip()
    if not joined.startswith(("[", "{")):
        return rows
    try:
        parsed = json.loads(joined)
    except json.JSONDecodeError:
        return rows
    if isinstance(parsed, dict):
        items = [parsed]
    elif isinstance(parsed, list):
        items = parsed
    else:
        return rows
    recovered: list[AgentTodoRow] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("task") or "").strip()
        if not text:
            continue
        recovered.append(
            AgentTodoRow(
                text=text,
                done=bool(item.get("done", False)),
                current=bool(item.get("current", False)),
            )
        )
    return recovered or rows


def parse_agent_todo_txt(content: str) -> list[AgentTodoRow]:
    """Parse ``todo.txt`` written by cecli ``updatetodolist``."""
    rows: list[AgentTodoRow] = []
    for raw in content.splitlines():
        line = raw.rstrip("\n\r")
        stripped = line.strip()
        if stripped in ("Done:", "Remaining:"):
            continue
        done = False
        current = False
        text = line
        if line.startswith("✓ "):
            done = True
            text = line[2:]
        elif line.startswith("→ "):
            current = True
            text = line[2:]
        elif line.startswith("○ "):
            text = line[2:]
        else:
            continue
        if text != "":
            rows.append(AgentTodoRow(text=text, done=done, current=current))
    return rows


def format_agent_todo_txt(rows: list[AgentTodoRow]) -> str:
    done_tasks: list[str] = []
    remaining: list[str] = []
    for row in rows:
        if row.done:
            done_tasks.append(f"✓ {row.text}")
        elif row.current:
            remaining.append(f"→ {row.text}")
        else:
            remaining.append(f"○ {row.text}")
    lines: list[str] = []
    if done_tasks:
        lines.append("Done:")
        lines.extend(done_tasks)
        lines.append("")
    if remaining:
        lines.append("Remaining:")
        lines.extend(remaining)
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def find_latest_agent_todo_txt(workspace: Path) -> Path | None:
    agents = workspace / ".cecli" / "agents"
    if not agents.is_dir():
        return None
    candidates = list(agents.glob("**/todo.txt"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def resolve_agent_todo_path(workspace: Path, relpath: str | None) -> Path | None:
    if relpath:
        path = workspace / relpath
        return path if path.is_file() else None
    latest = find_latest_agent_todo_txt(workspace)
    return latest


def rows_from_checklist(checklist: list[ChecklistItem]) -> list[AgentTodoRow]:
    rows: list[AgentTodoRow] = []
    marked_current = False
    for entry in checklist:
        current = not entry.done and not marked_current
        if current:
            marked_current = True
        rows.append(AgentTodoRow(text=entry.text, done=entry.done, current=current))
    return rows


_TASK_MD_LINE = re.compile(r"^-\s*\[([ xX])\]\s*(.+)$")


def rows_from_tasks_md(tasks_md: str) -> list[AgentTodoRow]:
    rows: list[AgentTodoRow] = []
    marked_current = False
    for raw in tasks_md.splitlines():
        m = _TASK_MD_LINE.match(raw.strip())
        if not m:
            continue
        done = m.group(1).lower() == "x"
        text = m.group(2).strip()
        if not text:
            continue
        current = not done and not marked_current
        if current:
            marked_current = True
        rows.append(AgentTodoRow(text=text, done=done, current=current))
    return rows


def rows_from_todo_item(item: TodoItem) -> list[AgentTodoRow]:
    if item.checklist:
        return rows_from_checklist(item.checklist)
    if item.tasks_md.strip():
        parsed = rows_from_tasks_md(item.tasks_md)
        if parsed:
            return parsed
    return []


def rows_to_tasks_md(rows: list[AgentTodoRow]) -> str:
    lines = ["## Implementation tasks", ""]
    for row in rows:
        mark = "x" if row.done else " "
        lines.append(f"- [{mark}] {row.text}")
    return "\n".join(lines).strip() + "\n"


def preserve_spec_tasks_md_on_agent_import(item: TodoItem, incoming_tasks_md: str) -> bool:
    """Keep spec-generated implementation tasks when syncing agent todo.txt.

    Agent pull updates the runtime checklist; it must not replace a rich
    ``tasks_md`` layer produced by generate-spec (numbered steps, REQ refs).
    """
    existing = (item.tasks_md or "").strip()
    if not existing:
        return False
    if re.search(r"(?m)^\s*(?:-\s*\[[ xX]\]\s*)?\d+\.", existing):
        return True
    if re.search(r"REQ-\d+", existing, re.I):
        return True
    if "depends:" in existing.lower():
        return True
    incoming = (incoming_tasks_md or "").strip()
    if incoming and len(existing) > len(incoming) + 40:
        return True
    return False


def _usable_plan_title_text(text: str) -> bool:
    """Reject char-split JSON debris (e.g. ``[``) mistaken for a task title after /agent."""
    t = text.strip()
    if not t:
        return False
    alnum = sum(1 for c in t if c.isalnum())
    if len(t) <= 2 and alnum < 2:
        return False
    return True


def plan_title_from_rows(rows: list[AgentTodoRow]) -> str:
    for row in rows:
        if row.current and not row.done:
            t = row.text.strip()
            if _usable_plan_title_text(t):
                return t[:120]
    for row in rows:
        if not row.done:
            t = row.text.strip()
            if _usable_plan_title_text(t):
                return t[:120]
    return AGENT_PLAN_TITLE


def _ensure_agent_link(item: TodoItem, agent_todo_relpath: str | None) -> None:
    if agent_todo_relpath:
        link = agent_todo_link_for(agent_todo_relpath)
        if link not in item.links:
            item.links = [*item.links, link]
    elif AGENT_PLAN_LINK not in item.links:
        item.links = [*item.links, AGENT_PLAN_LINK]


def _resolve_target_task(store: TodoStore, target_todo_id: str | None) -> TodoItem | None:
    if target_todo_id:
        return store.todos and next((t for t in store.todos if t.id == target_todo_id), None)
    if not store.active_id:
        return None
    item = next((t for t in store.todos if t.id == store.active_id), None)
    if item and item.status not in ("done", "cancelled"):
        return item
    return None


def import_agent_plan_store(
    store: TodoStore,
    rows: list[AgentTodoRow],
    *,
    target_todo_id: str | None = None,
    agent_todo_relpath: str | None = None,
) -> TodoStore:
    if not rows:
        return store

    rows = _recover_char_split_agent_rows(rows)

    incoming_tasks_md = rows_to_tasks_md(rows)
    from cecli.spec.progress import (
        checklist_from_agent_rows,
        merge_agent_progress_into_tasks_md,
    )

    target = _resolve_target_task(store, target_todo_id)

    def _apply_rows_to_item(task: TodoItem) -> None:
        task.checklist = checklist_from_agent_rows(rows, prior=task.checklist)
        if preserve_spec_tasks_md_on_agent_import(task, incoming_tasks_md):
            task.tasks_md = merge_agent_progress_into_tasks_md(task.tasks_md, rows)
        else:
            task.tasks_md = incoming_tasks_md

    any_open = any(not row.done for row in rows)
    status: str = "in_progress" if any_open else "done"
    now = _now_iso()

    if target:
        target.title = (
            plan_title_from_rows(rows)
            if target.title in (AGENT_PLAN_TITLE, "Untitled")
            else target.title
        )
        _apply_rows_to_item(target)
        if target.status not in ("done", "cancelled"):
            target.status = status  # type: ignore[assignment]
        target.updated_at = now
        _ensure_agent_link(target, agent_todo_relpath)
        store.active_id = target.id
        return store

    existing = next(
        (
            t
            for t in store.todos
            if AGENT_PLAN_LINK in t.links
            or parse_agent_todo_link(t.links)
            or t.title == AGENT_PLAN_TITLE
        ),
        None,
    )
    title = plan_title_from_rows(rows)
    if existing:
        existing.title = title
        _apply_rows_to_item(existing)
        existing.status = status  # type: ignore[assignment]
        existing.updated_at = now
        _ensure_agent_link(existing, agent_todo_relpath)
        store.active_id = existing.id
    else:
        item = TodoItem(
            id=uuid.uuid4().hex,
            title=title,
            tasks_md=incoming_tasks_md,
            status=status,  # type: ignore[arg-type]
            links=[AGENT_PLAN_LINK],
            checklist=checklist_from_agent_rows(rows),
            created_at=now,
            updated_at=now,
        )
        _apply_rows_to_item(item)
        _ensure_agent_link(item, agent_todo_relpath)
        store.todos.insert(0, item)
        store.active_id = item.id

    return store


def export_todo_item_to_agent(workspace: Path, relpath: str, item: TodoItem) -> None:
    rows = rows_from_todo_item(item)
    if not rows:
        return
    path = workspace / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_agent_todo_txt(rows) + "\n", encoding="utf-8")


def export_agent_plan_for_task(workspace_dir: str | Path, todo_id: str) -> None:
    api = WorkspaceTodos(workspace_dir)
    store = api.load()
    item = api.find(store, todo_id)
    if not item:
        raise ValueError(f"Unknown task: {todo_id}")
    relpath = parse_agent_todo_link(item.links)
    if not relpath:
        raise ValueError("Task is not linked to a Cecli agent todo.txt")
    export_todo_item_to_agent(api.root, relpath, item)


def import_agent_plan_for_workspace(
    workspace_dir: str | Path,
    *,
    agent_todo_relpath: str | None = None,
    target_todo_id: str | None = None,
) -> TodoStore:
    api = WorkspaceTodos(workspace_dir)
    root = api.root
    todo_path = resolve_agent_todo_path(root, agent_todo_relpath)
    if not todo_path:
        raise FileNotFoundError(
            "No Cecli agent todo.txt in this workspace (.cecli/agents/…/todo.txt)"
        )
    rows = parse_agent_todo_txt(todo_path.read_text(encoding="utf-8"))
    if not rows:
        raise ValueError("Agent todo.txt is empty")
    relpath = agent_todo_relpath or str(todo_path.relative_to(root)).replace("\\", "/")
    store = import_agent_plan_store(
        api.load(),
        rows,
        target_todo_id=target_todo_id,
        agent_todo_relpath=relpath,
    )
    api.save(store)
    active = next((t for t in store.todos if t.id == store.active_id), None)
    if active:
        api.sync_spec_files(active)
    return store


def session_agent_todo_relpath(session: AgentTodoSession) -> str:
    return session.coder.local_agent_folder("todo.txt")


def _resolve_agent_todo_pull_relpath(
    api: WorkspaceTodos,
    store: TodoStore,
    session: AgentTodoSession,
) -> str:
    """Prefer the active task's linked agent todo over this session's stale copy."""
    session_relpath = session_agent_todo_relpath(session)
    active = api.find(store, store.active_id) if store.active_id else None
    if active:
        linked = parse_agent_todo_link(active.links)
        if linked:
            linked_path = api.root / linked
            if linked_path.is_file():
                return linked.replace("\\", "/")
    session_path = api.root / session_relpath
    if session_path.is_file():
        return session_relpath
    latest = find_latest_agent_todo_txt(api.root)
    if latest:
        return str(latest.relative_to(api.root)).replace("\\", "/")
    return session_relpath


def try_import_agent_plan_for_workspace(
    workspace_dir: str | Path,
    *,
    agent_todo_relpath: str | None = None,
) -> TodoStore | None:
    """Import agent todo.txt when present; return None if missing or empty."""
    try:
        return import_agent_plan_for_workspace(workspace_dir, agent_todo_relpath=agent_todo_relpath)
    except (FileNotFoundError, ValueError):
        return None


def clear_session_agent_todo_file(session: AgentTodoSession) -> bool:
    """Remove this session's agent ``todo.txt`` so deleted Tasks are not resurrected on sync."""
    api = WorkspaceTodos(session.coder.root)
    path = api.root / session_agent_todo_relpath(session)
    if not path.is_file():
        return False
    path.unlink()
    return True


def sync_session_agent_todos(
    session: AgentTodoSession,
    *,
    pull: bool = True,
    push_active: bool = True,
    sanitize: AgentTodoSanitizeContext | None = None,
    prior_done_texts: frozenset[str] | None = None,
) -> tuple[TodoStore, list[str]]:
    """
    Two-way link for the current chat session:
    - pull: agent todo.txt → workspace (active task, or agent-plan task)
    - push: active workspace task → this session's todo.txt

    Returns ``(store, sanitize_warnings)``.
    """
    api = WorkspaceTodos(session.coder.root)
    session_relpath = session_agent_todo_relpath(session)
    store = api.load()
    warnings: list[str] = []

    if pull:
        pull_relpath = _resolve_agent_todo_pull_relpath(api, store, session)
        path = api.root / pull_relpath
        if path.is_file():
            rows = parse_agent_todo_txt(path.read_text(encoding="utf-8"))
            if rows and sanitize is not None:
                rows, warnings = sanitize_agent_todo_rows(
                    rows,
                    ctx=sanitize,
                    prior_done_texts=prior_done_texts or frozenset(),
                )
                if warnings:
                    path.write_text(format_agent_todo_txt(rows) + "\n", encoding="utf-8")
            if rows:
                if not store.todos and not store.active_id:
                    warnings.append(
                        "Skipped agent todo sync — workspace Tasks are empty "
                        "(clear session todo or create a task first)."
                    )
                else:
                    store = import_agent_plan_store(
                        store,
                        rows,
                        target_todo_id=store.active_id,
                        agent_todo_relpath=pull_relpath,
                    )

    if push_active and store.active_id:
        item = api.find(store, store.active_id)
        if item:
            export_todo_item_to_agent(api.root, session_relpath, item)
            _ensure_agent_link(item, session_relpath)
            item.updated_at = _now_iso()

    api.save(store)
    if store.active_id:
        active = api.find(store, store.active_id)
        if active:
            api.sync_spec_files(active)
    return store, warnings


def maybe_export_task_to_agent(workspace_dir: str | Path, item: TodoItem) -> None:
    """After a workspace task edit, push to linked agent todo.txt if bound."""
    relpath = parse_agent_todo_link(item.links)
    if not relpath:
        return
    export_todo_item_to_agent(Path(workspace_dir).resolve(), relpath, item)
