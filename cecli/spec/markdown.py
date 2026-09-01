"""
Import/export workspace tasks as markdown.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from cecli.spec.todos import ChecklistItem, TodoItem, TodoStore, migrate_todo_layers

_TASK_HEADER = re.compile(r"^#\s+(.+)$")
_META_ID = re.compile(r"^id:\s*(\S+)\s*$", re.I)
_META_STATUS = re.compile(r"^status:\s*(\S+)\s*$", re.I)
_META_DEPENDS = re.compile(r"^depends_on:\s*(.+)$", re.I)
_META_BRANCH = re.compile(r"^branch:\s*(.+)$", re.I)
_META_PR = re.compile(r"^pr:\s*(.+)$", re.I)
_CHECKLIST_ITEM = re.compile(r"^-\s*\[([ xX])\]\s*(.*)$")

_LAYER_SECTIONS = {
    "requirements": "requirements",
    "design": "design",
    "implementation tasks": "tasks_md",
    "specification": "spec",
}


def export_markdown(store: TodoStore) -> str:
    blocks: list[str] = []
    for item in store.todos:
        item = migrate_todo_layers(item)
        lines = [
            f"# {item.title}",
            f"id: {item.id}",
            f"status: {item.status}",
        ]
        if item.depends_on:
            lines.append(f"depends_on: {', '.join(item.depends_on)}")
        if item.branch.strip():
            lines.append(f"branch: {item.branch.strip()}")
        if item.pr_url.strip():
            lines.append(f"pr: {item.pr_url.strip()}")
        lines.append("")
        if item.requirements.strip() or item.design.strip() or item.tasks_md.strip():
            lines += ["## Requirements", item.requirements.strip() or "", ""]
            lines += ["## Design", item.design.strip() or "", ""]
            lines += ["## Implementation tasks", item.tasks_md.strip() or ""]
        else:
            lines += ["## Specification", item.spec.strip() or ""]
        if item.checklist:
            lines += ["", "## Checklist"]
            for c in item.checklist:
                mark = "x" if c.done else " "
                lines.append(f"- [{mark}] {c.text}")
        if item.links:
            lines += ["", "## Links"]
            for link in item.links:
                lines.append(f"- {link}")
        blocks.append("\n".join(lines))
    active = f"activeId: {store.active_id}\n\n" if store.active_id else ""
    body = "\n---\n\n".join(blocks)
    return f"# BrightVision Tasks\n\n{active}{body}\n" if body else "# BrightVision Tasks\n\n"


def _parse_checklist_line(line: str) -> ChecklistItem | None:
    m = _CHECKLIST_ITEM.match(line.strip())
    if not m:
        return None
    return ChecklistItem(
        id=uuid.uuid4().hex[:8],
        text=m.group(2).strip(),
        done=m.group(1).lower() == "x",
    )


def import_markdown(
    text: str, existing: TodoStore | None = None, *, merge: bool = False
) -> TodoStore:
    store = existing if merge and existing else TodoStore()
    if not merge:
        store = TodoStore()

    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    active_from_header: str | None = None
    if lines and lines[0].strip().lower() == "# brightvision tasks":
        i = 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines) and lines[i].strip().lower().startswith("activeid:"):
            active_from_header = lines[i].split(":", 1)[1].strip() or None
            i += 1

    current: dict[str, Any] | None = None
    section: str | None = None
    section_lines: list[str] = []

    def flush_task() -> None:
        nonlocal current, section_lines, section
        if not current or not current.get("title"):
            current = None
            section_lines = []
            section = None
            return
        item = TodoItem(
            id=str(current.get("id") or uuid.uuid4().hex),
            title=str(current["title"]),
            spec=str(current.get("spec") or ""),
            requirements=str(current.get("requirements") or ""),
            design=str(current.get("design") or ""),
            tasks_md=str(current.get("tasks_md") or ""),
            depends_on=list(current.get("depends_on") or []),
            branch=str(current.get("branch") or ""),
            pr_url=str(current.get("pr_url") or ""),
            status=current.get("status") or "open",
            links=list(current.get("links") or []),
            checklist=list(current.get("checklist") or []),
        )
        store.todos.append(migrate_todo_layers(item))
        current = None
        section_lines = []
        section = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == "---":
            flush_task()
            i += 1
            continue

        hm = _TASK_HEADER.match(stripped)
        if hm and not stripped.lower().startswith("# brightvision"):
            flush_task()
            current = {
                "title": hm.group(1).strip(),
                "checklist": [],
                "links": [],
                "depends_on": [],
                "branch": "",
                "pr_url": "",
            }
            section = None
            section_lines = []
            i += 1
            continue

        if current is None:
            i += 1
            continue

        mid = _META_ID.match(stripped)
        if mid:
            current["id"] = mid.group(1)
            i += 1
            continue
        ms = _META_STATUS.match(stripped)
        if ms:
            st = ms.group(1).lower()
            if st in ("open", "in_progress", "done", "cancelled"):
                current["status"] = st
            i += 1
            continue
        md = _META_DEPENDS.match(stripped)
        if md:
            current["depends_on"] = [p.strip() for p in md.group(1).split(",") if p.strip()]
            i += 1
            continue
        mb = _META_BRANCH.match(stripped)
        if mb:
            current["branch"] = mb.group(1).strip()
            i += 1
            continue
        mp = _META_PR.match(stripped)
        if mp:
            current["pr_url"] = mp.group(1).strip()
            i += 1
            continue

        if stripped.lower().startswith("## "):
            if section and section_lines:
                key = _LAYER_SECTIONS.get(section, section)
                current[key] = "\n".join(section_lines).strip()
            section_key = stripped[3:].strip().lower()
            section = _LAYER_SECTIONS.get(section_key, section_key)
            section_lines = []
            if section in ("checklist", "links"):
                pass
            i += 1
            continue

        if section == "checklist":
            entry = _parse_checklist_line(stripped)
            if entry:
                current["checklist"].append(entry)
        elif section == "links":
            if stripped.startswith("- "):
                current["links"].append(stripped[2:].strip())
        elif section in ("requirements", "design", "tasks_md", "spec"):
            section_lines.append(line)

        i += 1

    if section and section_lines and current:
        current[section] = "\n".join(section_lines).strip()
    flush_task()

    if active_from_header and any(t.id == active_from_header for t in store.todos):
        store.active_id = active_from_header

    return store
