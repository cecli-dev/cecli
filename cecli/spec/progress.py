"""Unified implementation progress: checklist, tasks_md, and agent todo rows."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from cecli.spec.agent_todos import AgentTodoRow, rows_from_tasks_md, rows_to_tasks_md
from cecli.spec.implement import checklist_step_prefix, step_sort_key
from cecli.spec.todos import ChecklistItem, TodoItem

_TASK_MD_CHECKBOX = re.compile(r"^(\s*)-\s*\[([ xX])\]\s*(.+)$")

_VERIFY_RE = re.compile(
    r"^\s*[-*]?\s*verify:\s*`([^`]+)`",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImplementationStep:
    step_id: str | None
    text: str
    done: bool
    current: bool
    verify_cmd: str | None = None


def extract_verify_for_step(tasks_md: str, step_prefix: str) -> str | None:
    """Find ``verify: `...` `` under a numbered step block in tasks_md."""
    if not tasks_md or not step_prefix:
        return None

    lines = tasks_md.splitlines()
    in_step = False
    step_indent: int | None = None

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if not in_step:
            m = re.match(r"-\s*\[[ xX]\]\s+(" + re.escape(step_prefix) + r")\s", stripped)
            if m:
                in_step = True
                step_indent = indent
                continue
        elif stripped and indent <= step_indent:  # type: ignore[operator]
            in_step = False
        elif in_step:
            vm = _VERIFY_RE.match(line)
            if vm:
                return vm.group(1)
    return None


def merge_agent_progress_into_tasks_md(tasks_md: str, rows: list[AgentTodoRow]) -> str:
    """Patch checkbox marks in rich spec tasks_md without replacing REQ/verify prose."""
    if not (tasks_md or "").strip():
        return tasks_md

    done_by_step: dict[str, bool] = {}
    done_by_text: dict[str, bool] = {}
    for row in rows:
        text = (row.text or "").strip()
        if not text:
            continue
        done_by_text[text] = row.done
        step = checklist_step_prefix(text)
        if step:
            done_by_step[step] = row.done

    out: list[str] = []
    for line in tasks_md.splitlines():
        m = _TASK_MD_CHECKBOX.match(line)
        if not m:
            out.append(line)
            continue
        indent, body = m.group(1), m.group(3).strip()
        step = checklist_step_prefix(body)
        new_done = None
        if step and step in done_by_step:
            new_done = done_by_step[step]
        elif body in done_by_text:
            new_done = done_by_text[body]
        if new_done is None:
            out.append(line)
            continue
        mark = "x" if new_done else " "
        out.append(f"{indent}- [{mark}] {body}")

    merged = "\n".join(out)
    if tasks_md.endswith("\n"):
        merged += "\n"
    return merged


def checklist_from_agent_rows(
    rows: list[AgentTodoRow],
    prior: list[ChecklistItem] | None = None,
) -> list[ChecklistItem]:
    """Build checklist from agent rows, reusing stable ids when step/text matches."""
    prior = prior or []
    by_step: dict[str, ChecklistItem] = {}
    by_text: dict[str, ChecklistItem] = {}
    for entry in prior:
        text = entry.text.strip()
        by_text[text] = entry
        step = checklist_step_prefix(text)
        if step:
            by_step[step] = entry

    out: list[ChecklistItem] = []
    for row in rows:
        text = row.text.strip()
        step = checklist_step_prefix(text)
        existing = by_step.get(step) if step else None
        if existing is None and text in by_text:
            existing = by_text[text]
        cid = existing.id if existing else uuid.uuid4().hex[:8]
        out.append(ChecklistItem(id=cid, text=row.text, done=row.done))
    return out


def materialize_checklist_from_tasks_md(item: TodoItem) -> list[ChecklistItem]:
    """Populate checklist from tasks_md checkbox lines when runtime checklist is missing."""
    parsed = rows_from_tasks_md(item.tasks_md or "")
    if not parsed:
        return list(item.checklist or [])
    rows = [AgentTodoRow(text=row.text, done=row.done, current=row.current) for row in parsed]
    return checklist_from_agent_rows(rows, prior=item.checklist or [])


def _rows_from_item(item: TodoItem) -> list[AgentTodoRow]:
    if item.checklist:
        marked_current = False
        rows: list[AgentTodoRow] = []
        for entry in item.checklist:
            current = not entry.done and not marked_current
            if current:
                marked_current = True
            rows.append(AgentTodoRow(text=entry.text, done=entry.done, current=current))
        return rows
    return rows_from_tasks_md(item.tasks_md or "")


def implementation_steps(item: TodoItem) -> list[ImplementationStep]:
    """Ordered implement steps from checklist (preferred) or tasks_md."""
    tasks_md = item.tasks_md or ""
    steps: list[ImplementationStep] = []
    for row in _rows_from_item(item):
        step_id = checklist_step_prefix(row.text)
        verify = extract_verify_for_step(tasks_md, step_id) if step_id else None
        steps.append(
            ImplementationStep(
                step_id=step_id,
                text=row.text.strip(),
                done=row.done,
                current=row.current,
                verify_cmd=verify,
            )
        )
    return steps


def parse_open_step_ids(item: TodoItem) -> list[str]:
    """Open numbered step ids in document order."""
    ids: list[str] = []
    for step in implementation_steps(item):
        if step.done or not step.step_id:
            continue
        ids.append(step.step_id)
    return ids


def next_open_implementation_step(
    item: TodoItem,
    after: str | None,
) -> ImplementationStep | None:
    """Next open step after ``after`` (or first open when ``after`` is None)."""
    open_steps = [s for s in implementation_steps(item) if s.step_id and not s.done]
    if not open_steps:
        return None
    if not after:
        return open_steps[0]

    completed_key = step_sort_key(after)
    for step in open_steps:
        if step_sort_key(step.step_id or "") > completed_key:
            return step
    return open_steps[0]


def extract_step_text_from_tasks_md(tasks_md: str, step: str) -> str:
    """First-line + indented body for a numbered checkbox step in tasks_md."""
    lines = tasks_md.splitlines()
    collecting = False
    step_indent: int | None = None
    collected: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if not collecting:
            m = re.match(r"-\s*\[[ xX]\]\s+" + re.escape(step) + r"\s+(.*)", stripped)
            if m:
                collecting = True
                step_indent = indent
                collected.append(m.group(1))
                continue
        elif stripped and indent <= step_indent:  # type: ignore[operator]
            break
        else:
            collected.append(stripped)
    return "\n".join(collected).strip()


def mark_implementation_step_done(
    item: TodoItem,
    step_id: str,
    *,
    done: bool = True,
) -> TodoItem:
    """Mark one numbered step done in both checklist and tasks_md."""
    step_id = (step_id or "").strip()
    if not step_id:
        return item

    if not item.checklist:
        item.checklist = materialize_checklist_from_tasks_md(item)

    rows: list[AgentTodoRow] = []
    new_checklist: list[ChecklistItem] = []
    for entry in item.checklist:
        prefix = checklist_step_prefix(entry.text)
        is_target = prefix == step_id
        new_done = done if is_target else entry.done
        new_checklist.append(ChecklistItem(id=entry.id, text=entry.text, done=new_done))
        rows.append(AgentTodoRow(text=entry.text, done=new_done, current=False))

    item.checklist = new_checklist
    if (item.tasks_md or "").strip():
        item.tasks_md = merge_agent_progress_into_tasks_md(item.tasks_md, rows)
    elif rows:
        item.tasks_md = rows_to_tasks_md(rows)
    return item


def try_mark_focus_step_complete(
    item: TodoItem,
    focus_step: str | None,
    *,
    flutter_test_ok: bool | None,
    verify_ok: bool | None,
) -> tuple[TodoItem, bool]:
    """Mark the focused step done when automation gates pass (#53)."""
    from cecli.spec.implement import is_test_related_checklist_text

    focus = (focus_step or "").strip()
    if not focus:
        return item, False
    if verify_ok is False:
        return item, False

    steps = implementation_steps(item)
    focus_step_row = next((s for s in steps if s.step_id == focus), None)
    if focus_step_row is None:
        return item, False
    if focus_step_row.done:
        return item, False

    passed_gate = False
    if is_test_related_checklist_text(focus_step_row.text):
        passed_gate = flutter_test_ok is True
    elif verify_ok is True:
        passed_gate = True

    if not passed_gate:
        return item, False

    return mark_implementation_step_done(item, focus, done=True), True
