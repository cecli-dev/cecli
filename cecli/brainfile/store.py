"""Thin adapter between cecli and the brainfile library.

The brainfile library handles all protocol-level operations (task CRUD,
file I/O, ID generation, complete-to-logs).  This adapter adds only
cecli-specific concerns:

* Loading/dropping task files from the coder context
* Active-task state and TUI bar updates
* Rendering context blocks for the LLM prompt
* The `.cecli/tasks/` path convention (vs `.brainfile/`)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from brainfile import (
    Subtask,
    addTaskFile,
    completeTaskFile,
    deleteTaskFile,
    ensureV2Dirs,
    findV2Task,
    getV2Dirs,
    readTasksDir,
    writeTaskFile,
)
from brainfile.workspace import V2Dirs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BRAINFILE_NAME = "brainfile.md"
_DEFAULT_BOARD_YAML = """\
---
title: cecli tasks
type: board
schema: https://brainfile.md/v2/board.json
protocolVersion: 2.0.0
strict: false
columns:
  - id: in-progress
    title: In Progress
---
# cecli tasks

Shared task board for this repository.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_task_id(raw: str) -> str:
    """Accept flexible task references: '11', 'task 11', 'task-11', 'task-11.md'."""
    normalized = raw.strip()
    if not normalized:
        return normalized

    normalized = Path(normalized).name
    if normalized.endswith(".md"):
        normalized = normalized[:-3]

    if normalized.isdigit():
        return f"task-{normalized}"

    m = re.fullmatch(r"([A-Za-z]+)[\s\-_]?(\d+)", normalized)
    if m:
        return f"{m.group(1).lower()}-{m.group(2)}"

    return normalized


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class CecliTaskStore:
    """Manages `.cecli/tasks/` using the brainfile library for all mutations."""

    def __init__(self, repo_root: str | Path):
        self.repo_root = Path(repo_root)
        self._brainfile_path = self.repo_root / ".cecli" / "tasks" / _BRAINFILE_NAME

    # -- paths --------------------------------------------------------------

    @property
    def dirs(self) -> V2Dirs:
        return getV2Dirs(str(self._brainfile_path))

    def relpath(self, path: Path | str) -> str:
        return str(Path(path).relative_to(self.repo_root))

    def board_exists(self) -> bool:
        return self._brainfile_path.is_file()

    # -- initialisation (only on explicit /task usage) ----------------------

    def ensure_initialized(self) -> V2Dirs:
        dirs = ensureV2Dirs(str(self._brainfile_path))
        if not self._brainfile_path.is_file():
            self._brainfile_path.write_text(_DEFAULT_BOARD_YAML, encoding="utf-8")
        return dirs

    # -- task CRUD (delegates to brainfile) ---------------------------------

    def list_tasks(self, scope: str = "board") -> List[Dict[str, Any]]:
        if not self.board_exists():
            return []
        dirs = self.dirs
        scope = (scope or "board").strip().lower()

        entries: list[tuple[str, Any]] = []
        if scope in ("board", "all"):
            for doc in readTasksDir(dirs.boardDir):
                entries.append(("board", doc))
        if scope in ("logs", "all"):
            for doc in readTasksDir(dirs.logsDir):
                entries.append(("logs", doc))

        tasks = []
        for location, doc in entries:
            t = doc.task
            subtasks = t.subtasks or []
            total = len(subtasks)
            done = sum(1 for s in subtasks if s.completed)
            tasks.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "column": t.column or ("logs" if location == "logs" else "in-progress"),
                    "location": location,
                    "subtasks_total": total,
                    "subtasks_done": done,
                    "relpath": self.relpath(
                        os.path.join(
                            dirs.boardDir if location == "board" else dirs.logsDir,
                            f"{t.id}.md",
                        )
                    ),
                }
            )
        return tasks

    def find_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        if not self.board_exists():
            return None
        dirs = self.dirs
        normalized = _normalize_task_id(task_id)
        result = findV2Task(dirs, normalized, searchLogs=True)
        if not result:
            return None
        doc = result["doc"]
        is_log = result["isLog"]
        location = "logs" if is_log else "board"
        return {
            "id": doc.task.id,
            "title": doc.task.title,
            "location": location,
            "path": Path(result["filePath"]),
            "relpath": self.relpath(result["filePath"]),
            "task": doc.task,
            "body": doc.body,
        }

    def create_task(
        self,
        title: str,
        column: str = "in-progress",
        description: Optional[str] = None,
        subtasks: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        dirs = self.ensure_initialized()
        result = addTaskFile(
            dirs.boardDir,
            {
                "title": title,
                "column": column,
                "type": "task",
                "description": description or "",
                "subtasks": subtasks or [],
            },
            body=f"## Description\n\n{description or ''}\n",
            logsDir=dirs.logsDir,
        )
        if not result.get("success"):
            raise ValueError(result.get("error", "Failed to create task"))
        task = result["task"]
        return {
            "id": task.id,
            "title": task.title,
            "column": task.column,
            "location": "board",
            "path": Path(result["filePath"]),
            "relpath": self.relpath(result["filePath"]),
            "task": task,
        }

    def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        column: Optional[str] = None,
    ) -> Dict[str, Any]:
        found = self.find_task(task_id)
        if not found:
            raise FileNotFoundError(f"Task not found: {task_id}")
        if found["location"] != "board":
            raise ValueError("Only active board tasks can be updated")

        task = found["task"]
        changed = False
        updates: dict[str, Any] = {}

        if title is not None and title.strip() and task.title != title.strip():
            updates["title"] = title.strip()
            changed = True
        if column is not None and column.strip() and task.column != column.strip():
            updates["column"] = column.strip()
            changed = True

        if changed:
            from datetime import datetime

            updates["updated_at"] = datetime.now().isoformat()
            updated_task = task.model_copy(update=updates)
            writeTaskFile(str(found["path"]), updated_task, found["body"])

        final_task = task.model_copy(update=updates) if changed else task
        return {
            "id": final_task.id,
            "title": final_task.title,
            "column": final_task.column or "in-progress",
            "changed": changed,
            "location": "board",
            "relpath": found["relpath"],
        }

    def complete_task(self, task_id: str) -> Dict[str, Any]:
        found = self.find_task(task_id)
        if not found:
            raise FileNotFoundError(f"Task not found: {task_id}")
        if found["location"] != "board":
            raise ValueError("Only active board tasks can be completed")

        dirs = self.dirs
        result = completeTaskFile(str(found["path"]), dirs.logsDir)
        if not result.get("success"):
            raise ValueError(result.get("error", "Failed to complete task"))
        return {
            "id": found["id"],
            "title": found["title"],
            "location": "logs",
            "relpath": self.relpath(result["filePath"]),
        }

    def delete_task(self, task_id: str) -> Dict[str, Any]:
        found = self.find_task(task_id)
        if not found:
            raise FileNotFoundError(f"Task not found: {task_id}")
        result = deleteTaskFile(str(found["path"]))
        if not result.get("success"):
            raise ValueError(result.get("error", "Failed to delete task"))
        return {
            "id": found["id"],
            "location": found["location"],
            "relpath": found["relpath"],
        }

    def next_task_id(self, current_task_id: str, scope: str = "board") -> Optional[str]:
        """Get the next same-prefix ID by numeric order."""
        current = _normalize_task_id(current_task_id)
        m = re.fullmatch(r"([a-zA-Z][a-zA-Z0-9\-]*)-(\d+)", current)
        if not m:
            return None
        prefix = m.group(1).lower()
        current_num = int(m.group(2))

        entries = self.list_tasks(scope=scope)
        candidates = []
        for entry in entries:
            em = re.fullmatch(r"([a-zA-Z][a-zA-Z0-9\-]*)-(\d+)", entry["id"])
            if not em or em.group(1).lower() != prefix:
                continue
            num = int(em.group(2))
            if num > current_num:
                candidates.append((num, entry["id"]))

        if not candidates:
            return None
        candidates.sort()
        return candidates[0][1]

    # -- session task (invisible auto-create) --------------------------------

    def get_or_create_session_task(self, coder) -> dict:
        """Return an incomplete board task or create a new one.

        Called transparently by UpdateTodoList and get_todo_list() so the
        agent never needs to know about brainfile / boards.

        1. Ensures the board directory exists.
        2. Scans ``board/`` for the most recently updated incomplete task.
        3. If found → sets ``coder.active_task_id``, returns it.
        4. Otherwise → creates a new ``in-progress`` task, sets active, returns it.

        Does **not** add the task file to coder context — the agent sees
        only the ``<context name="todo_list">`` block rendered by
        ``render_task_todo_block()``.
        """
        dirs = self.ensure_initialized()

        # Scan board for most recently updated task with incomplete subtasks
        best: dict | None = None
        best_mtime: float = 0.0

        for doc in readTasksDir(dirs.boardDir):
            t = doc.task
            subtasks = t.subtasks or []
            has_incomplete = not subtasks or any(not s.completed for s in subtasks)
            if not has_incomplete:
                continue
            file_path = os.path.join(dirs.boardDir, f"{t.id}.md")
            try:
                mtime = os.path.getmtime(file_path)
            except OSError:
                mtime = 0.0
            if mtime >= best_mtime:
                best_mtime = mtime
                best = {
                    "id": t.id,
                    "title": t.title,
                    "task": t,
                    "path": Path(file_path),
                    "relpath": self.relpath(file_path),
                }

        if best:
            task = best["task"]
            task_id = best["id"]
        else:
            # Create a new task
            title = self.auto_title(None)
            created = self.create_task(title=title, column="in-progress")
            task_id = created["id"]
            task = created["task"]

        # Set active_task_id + update TUI — but do NOT add the file to
        # coder context so the agent never sees raw YAML.
        subtasks = task.subtasks or []
        done = sum(1 for s in subtasks if s.completed)
        total = len(subtasks)

        setattr(coder, "active_task_id", task_id)

        io = getattr(coder, "io", None)
        set_active_task = getattr(io, "set_active_task", None)
        if callable(set_active_task):
            set_active_task(
                task_id=task_id,
                title=task.title,
                column=task.column or "in-progress",
                subtasks_done=done,
                subtasks_total=total,
                mode="invisible",
                location="board",
            )

        return {
            "id": task_id,
            "title": task.title,
            "column": task.column or "in-progress",
            "location": "board",
            "mode": "invisible",
            "subtasks_done": done,
            "subtasks_total": total,
        }

    @staticmethod
    def auto_title(items: list[dict] | None) -> str:
        """Derive a short title from the first non-done item, or a date fallback."""
        if items:
            for item in items:
                if not item.get("done", False):
                    text = str(item.get("task", "")).strip()
                    if text:
                        return text[:80]
        from datetime import date

        return f"Session {date.today().isoformat()}"

    # -- subtask helpers (for UpdateTodoList bridge) ------------------------

    def get_task_file_path(self, task_id: str) -> Optional[Path]:
        found = self.find_task(task_id)
        if not found:
            return None
        return found["path"]

    def update_task_subtasks(
        self,
        task_id: str,
        items: List[Dict[str, Any]],
        append: bool = False,
    ) -> Path:
        """Update a board task's subtasks from UpdateTodoList-style items."""
        found = self.find_task(task_id)
        if not found:
            raise FileNotFoundError(f"Task not found: {task_id}")
        if found["location"] != "board":
            raise ValueError("Only active board tasks can be updated")

        task = found["task"]
        existing = list(task.subtasks or [])

        # Parse incoming items
        parsed = []
        for item in items:
            title = str(item.get("task", "")).strip()
            if not title:
                continue
            parsed.append(
                {
                    "title": title,
                    "completed": bool(item.get("done", False)),
                    "current": bool(item.get("current", False)),
                }
            )

        if not append:
            # Reorder: current first, then remaining, then done
            remaining = [t for t in parsed if not t["completed"]]
            done = [t for t in parsed if t["completed"]]
            current = [t for t in remaining if t["current"]]
            not_current = [t for t in remaining if not t["current"]]
            ordered = current + not_current + done
        else:
            ordered = parsed

        # Build new subtask list
        new_subtasks = list(existing) if append else []
        max_idx = 0
        for s in existing:
            parts = s.id.split("-")
            if parts:
                try:
                    max_idx = max(max_idx, int(parts[-1]))
                except ValueError:
                    pass

        for sub in ordered:
            max_idx += 1
            new_subtasks.append(
                Subtask(
                    id=f"{task.id}-{max_idx}",
                    title=sub["title"],
                    completed=sub["completed"],
                )
            )

        new_column = "in-progress"

        from datetime import datetime

        updated_task = task.model_copy(
            update={
                "subtasks": new_subtasks,
                "column": new_column,
                "updated_at": datetime.now().isoformat(),
            }
        )

        path = found["path"]
        writeTaskFile(str(path), updated_task, found["body"])
        return path

    # -- context loading (cecli-specific) -----------------------------------

    def open_task_in_context(
        self, coder, task_id: str, mode: str = "auto", explicit: bool = True
    ) -> Dict[str, Any]:
        found = self.find_task(task_id)
        if not found:
            raise FileNotFoundError(f"Task not found: {task_id}")

        selected_mode = (mode or "auto").strip().lower()
        if selected_mode not in {"auto", "editable", "view"}:
            raise ValueError("mode must be one of: auto, editable, view")

        relpath = found["relpath"]
        abs_path = coder.abs_root_path(relpath)

        if selected_mode == "auto":
            selected_mode = "editable" if found["location"] == "board" else "view"
        if found["location"] == "logs":
            selected_mode = "view"

        if selected_mode == "editable":
            if abs_path in coder.abs_read_only_fnames:
                coder.abs_read_only_fnames.remove(abs_path)
            if abs_path in coder.abs_read_only_stubs_fnames:
                coder.abs_read_only_stubs_fnames.remove(abs_path)
            if abs_path not in coder.abs_fnames:
                content = coder.io.read_text(abs_path)
                if content is None:
                    raise ValueError(f"Unable to read task file: {relpath}")
                coder.abs_fnames.add(abs_path)
                coder.check_added_files()
            if explicit:
                coder.io.tool_output(f"Opened task '{found['id']}' as editable: {relpath}")
        else:
            if abs_path in coder.abs_fnames:
                coder.abs_fnames.remove(abs_path)
            if abs_path not in coder.abs_read_only_fnames:
                content = coder.io.read_text(abs_path)
                if content is None:
                    raise ValueError(f"Unable to read task file: {relpath}")
                coder.abs_read_only_fnames.add(abs_path)
            if explicit:
                coder.io.tool_output(f"Opened task '{found['id']}' as read-only: {relpath}")

        if hasattr(coder, "use_enhanced_context") and coder.use_enhanced_context:
            if hasattr(coder, "_calculate_context_block_tokens"):
                coder._calculate_context_block_tokens()

        task = found["task"]
        subtasks = task.subtasks or []
        done = sum(1 for s in subtasks if s.completed)
        total = len(subtasks)

        opened = {
            "id": found["id"],
            "title": task.title,
            "column": task.column or "in-progress",
            "location": found["location"],
            "mode": selected_mode,
            "relpath": relpath,
            "subtasks_done": done,
            "subtasks_total": total,
        }

        setattr(coder, "active_task_id", opened["id"])

        io = getattr(coder, "io", None)
        set_active_task = getattr(io, "set_active_task", None)
        if callable(set_active_task):
            set_active_task(
                task_id=opened["id"],
                title=opened["title"],
                column=opened["column"],
                subtasks_done=opened["subtasks_done"],
                subtasks_total=opened["subtasks_total"],
                mode=opened["mode"],
                location=opened["location"],
            )

        return opened

    def clear_active_task(self, coder) -> None:
        setattr(coder, "active_task_id", None)
        io = getattr(coder, "io", None)
        set_active_task = getattr(io, "set_active_task", None)
        if callable(set_active_task):
            set_active_task(
                task_id="",
                title="",
                column="",
                subtasks_done=0,
                subtasks_total=0,
                mode="",
                location="",
            )

    def drop_task_from_context(
        self,
        coder,
        task_id: Optional[str] = None,
        clear_active: bool = True,
    ) -> Dict[str, Any]:
        target = _normalize_task_id(task_id or getattr(coder, "active_task_id", "") or "")
        if not target:
            raise ValueError("No active task to drop. Use /task drop <task-id>.")

        dirs = self.dirs
        rel_candidates = [
            self.relpath(os.path.join(dirs.boardDir, f"{target}.md")),
            self.relpath(os.path.join(dirs.logsDir, f"{target}.md")),
        ]
        abs_candidates = [coder.abs_root_path(rel) for rel in rel_candidates]

        removed_editable = 0
        removed_read_only = 0
        for abs_path in abs_candidates:
            if abs_path in coder.abs_fnames:
                coder.abs_fnames.remove(abs_path)
                removed_editable += 1
            if abs_path in coder.abs_read_only_fnames:
                coder.abs_read_only_fnames.remove(abs_path)
                removed_read_only += 1
            if hasattr(coder, "abs_read_only_stubs_fnames"):
                if abs_path in coder.abs_read_only_stubs_fnames:
                    coder.abs_read_only_stubs_fnames.remove(abs_path)

        active_id = _normalize_task_id(getattr(coder, "active_task_id", "") or "")
        cleared_active = False
        if clear_active and active_id == target:
            self.clear_active_task(coder)
            cleared_active = True

        if hasattr(coder, "use_enhanced_context") and coder.use_enhanced_context:
            if hasattr(coder, "_calculate_context_block_tokens"):
                coder._calculate_context_block_tokens()

        return {
            "id": target,
            "removed_editable": removed_editable,
            "removed_read_only": removed_read_only,
            "cleared_active": cleared_active,
        }

    # -- LLM context blocks -------------------------------------------------

    def render_task_todo_block(self, task_id: str) -> Optional[str]:
        found = self.find_task(task_id)
        if not found or found["location"] != "board":
            return None

        task = found["task"]
        subtasks = task.subtasks or []
        if not subtasks:
            return None

        done_tasks = []
        remaining_tasks = []
        for s in subtasks:
            if s.completed:
                done_tasks.append(s.title)
            else:
                remaining_tasks.append(s.title)

        if not done_tasks and not remaining_tasks:
            return None

        result = '<context name="todo_list" from="agent">\n'
        result += "## Active Task Checklist\n\n"
        result += f"Checklist for `{task.id}`.\n\n"

        if done_tasks:
            result += "Done:\n"
            for item in done_tasks:
                result += f"[x] {item}\n"
            result += "\n"

        if remaining_tasks:
            result += "Remaining:\n"
            for i, item in enumerate(remaining_tasks):
                marker = "->" if i == 0 else "-"
                result += f"{marker} {item}\n"

        total = len(done_tasks) + len(remaining_tasks)
        done = len(done_tasks)
        result += f"\nActive: {task.title} | {task.column or 'in-progress'} | {done}/{total}\n"
        result += "</context>"
        return result
