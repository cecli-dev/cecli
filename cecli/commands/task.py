import shlex
from pathlib import Path
from typing import List

from cecli.brainfile import CecliTaskStore
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class TaskCommand(BaseCommand):
    NORM_NAME = "task"
    DESCRIPTION = (
        "Manage repository tasks in .cecli/tasks "
        "(list/add/new/show/open/update/delete/complete/drop)"
    )

    _cached_task_ids: List[str] = []
    _cached_mtime: float = 0.0

    @classmethod
    def _get_cached_task_ids(cls, coder) -> List[str]:
        """Return task IDs, using a cache invalidated by directory mtime."""
        tasks_dir = Path(coder.root) / ".cecli" / "tasks"
        board_dir = tasks_dir / "board"
        logs_dir = tasks_dir / "logs"

        # Sum mtimes of both directories for a cheap staleness check
        current_mtime = 0.0
        for d in (board_dir, logs_dir):
            try:
                current_mtime += d.stat().st_mtime
            except OSError:
                pass

        if current_mtime != cls._cached_mtime or not cls._cached_task_ids:
            try:
                store = CecliTaskStore(Path(coder.root))
                cls._cached_task_ids = [t["id"] for t in store.list_tasks("all")]
            except Exception:
                cls._cached_task_ids = []
            cls._cached_mtime = current_mtime

        return cls._cached_task_ids

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        if coder is None:
            return format_command_result(io, "task", "No coder instance", error="No coder instance")

        try:
            tokens = shlex.split(args) if args.strip() else []
        except ValueError as e:
            return format_command_result(io, "task", "Invalid arguments", error=str(e))

        store = CecliTaskStore(Path(coder.root))
        command = tokens[0].lower() if tokens else "list"

        try:
            if command == "list":
                scope = tokens[1] if len(tokens) > 1 else "board"
                tasks = store.list_tasks(scope)
                if not tasks:
                    io.tool_output(f"No tasks found in scope '{scope}'.")
                    return format_command_result(io, "task", "No tasks found")

                io.tool_output(f"Tasks ({scope}):")
                for task in tasks:
                    metadata = [task["column"]]
                    if task["subtasks_total"] > 0:
                        metadata.append(f"{task['subtasks_done']}/{task['subtasks_total']}")
                    meta = " | ".join(metadata)
                    io.tool_output(f"- {task['id']}: {task['title']} [{meta}]")
                return format_command_result(io, "task", f"Listed {len(tasks)} task(s)")

            if command == "add":
                title = " ".join(tokens[1:]).strip()
                if not title:
                    return format_command_result(
                        io, "task", "Missing title", error="Usage: /task add <title>"
                    )
                created = store.create_task(title=title, column="in-progress")
                tid, col, ttl = created["id"], created["column"], created["title"]
                io.tool_output(f"Created task {tid} in column '{col}': {ttl}")
                return format_command_result(io, "task", f"Created {created['id']}")

            if command == "show":
                if len(tokens) < 2:
                    return format_command_result(
                        io,
                        "task",
                        "Missing task id",
                        error="Usage: /task show <task-id>",
                    )
                task_ref = " ".join(tokens[1:]).strip()
                task = store.find_task(task_ref)
                if not task:
                    return format_command_result(
                        io,
                        "task",
                        "Task not found",
                        error=f"Task not found: {task_ref}",
                    )
                t = task["task"]  # brainfile Task model
                subtasks = t.subtasks or []
                done = sum(1 for s in subtasks if s.completed)
                total = len(subtasks)
                io.tool_output(f"Task: {task['id']}")
                io.tool_output(f"Title: {t.title}")
                io.tool_output(f"Location: {task['location']}")
                io.tool_output(f"Column: {t.column or 'logs'}")
                io.tool_output(f"Progress: {done}/{total}")
                io.tool_output(f"Path: {task['relpath']}")
                return format_command_result(io, "task", f"Displayed {task['id']}")

            if command == "open":
                if len(tokens) < 2:
                    return format_command_result(
                        io,
                        "task",
                        "Missing task id",
                        error="Usage: /task open <task-id> [auto|editable|view]",
                    )
                modes = {"auto", "editable", "view"}
                mode = "auto"
                task_parts = tokens[1:]
                if len(task_parts) > 1 and task_parts[-1].lower() in modes:
                    mode = task_parts[-1].lower()
                    task_parts = task_parts[:-1]
                task_ref = " ".join(task_parts).strip()
                if not task_ref:
                    return format_command_result(
                        io,
                        "task",
                        "Missing task id",
                        error="Usage: /task open <task-id> [auto|editable|view]",
                    )
                opened = store.open_task_in_context(coder, task_ref, mode=mode, explicit=False)
                io.tool_output(f"Opened {opened['id']} ({opened['mode']}, {opened['location']}).")
                io.tool_output(
                    f"Active task: {opened['title']} | {opened['column']} |"
                    f" {opened['subtasks_done']}/{opened['subtasks_total']}"
                )
                return format_command_result(io, "task", f"Opened {opened['id']}")

            if command == "update":
                if len(tokens) < 3:
                    return format_command_result(
                        io,
                        "task",
                        "Missing fields",
                        error=(
                            "Usage: /task update <task-id> <new title> OR "
                            "/task update <task-id> --title <title> --column <column>"
                        ),
                    )
                task_id = tokens[1]
                title = None
                column = None

                remainder = tokens[2:]
                index = 0
                free_text_title = []
                while index < len(remainder):
                    token = remainder[index]
                    if token == "--column":
                        if index + 1 >= len(remainder):
                            return format_command_result(
                                io,
                                "task",
                                "Invalid args",
                                error="--column requires a value",
                            )
                        column = remainder[index + 1]
                        index += 2
                        continue
                    if token == "--title":
                        if index + 1 >= len(remainder):
                            return format_command_result(
                                io,
                                "task",
                                "Invalid args",
                                error="--title requires a value",
                            )
                        title = remainder[index + 1]
                        index += 2
                        continue
                    free_text_title.append(token)
                    index += 1

                if title is None and free_text_title:
                    title = " ".join(free_text_title).strip()

                updated = store.update_task(task_id=task_id, title=title, column=column)
                if not updated["changed"]:
                    io.tool_output("No changes applied.")
                    return format_command_result(io, "task", "No changes applied")
                tid, ttl, col = updated["id"], updated["title"], updated["column"]
                io.tool_output(f"Updated {tid}: title='{ttl}', column='{col}'")
                return format_command_result(io, "task", f"Updated {updated['id']}")

            if command == "delete":
                if len(tokens) < 2:
                    return format_command_result(
                        io,
                        "task",
                        "Missing task id",
                        error="Usage: /task delete <task-id>",
                    )
                task_ref = " ".join(tokens[1:]).strip()
                deleted = store.delete_task(task_ref)
                store.drop_task_from_context(coder, deleted["id"], clear_active=True)
                io.tool_output(f"Deleted task {deleted['id']} from {deleted['location']}.")
                return format_command_result(io, "task", f"Deleted {deleted['id']}")

            if command == "complete":
                if len(tokens) < 2:
                    return format_command_result(
                        io,
                        "task",
                        "Missing task id",
                        error="Usage: /task complete <task-id>",
                    )
                task_ref = " ".join(tokens[1:]).strip()
                completed = store.complete_task(task_ref)
                store.drop_task_from_context(coder, completed["id"], clear_active=True)
                io.tool_output(f"Completed task {completed['id']} (moved to logs).")
                return format_command_result(io, "task", f"Completed {completed['id']}")

            if command == "drop":
                task_ref = " ".join(tokens[1:]).strip() if len(tokens) > 1 else None
                dropped = store.drop_task_from_context(
                    coder, task_id=(task_ref or None), clear_active=True
                )
                if dropped["cleared_active"]:
                    io.tool_output(f"Closed task {dropped['id']} and cleared active task.")
                else:
                    io.tool_output(f"Closed task {dropped['id']} from context.")
                return format_command_result(io, "task", f"Dropped {dropped['id']}")

            if command == "new":
                title = " ".join(tokens[1:]).strip() if len(tokens) > 1 else None
                if not title:
                    title = store.auto_title(None)
                created = store.create_task(title=title, column="in-progress")
                opened = store.open_task_in_context(
                    coder, created["id"], mode="auto", explicit=False
                )
                io.tool_output(f"Created {created['id']}: {created['title']}")
                io.tool_output(
                    f"Active task: {opened['title']} | {opened['column']} | "
                    f"{opened['subtasks_done']}/{opened['subtasks_total']}"
                )
                return format_command_result(io, "task", f"Created {created['id']}")

            return format_command_result(
                io,
                "task",
                "Unknown subcommand",
                error=(
                    f"Unknown subcommand '{command}'. "
                    "Try: list/add/new/show/open/update/delete/complete/drop"
                ),
            )

        except (FileNotFoundError, ValueError) as e:
            return format_command_result(io, "task", "Task command failed", error=str(e))

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        if coder is None:
            return []

        try:
            tokens = shlex.split(args) if args.strip() else []
        except ValueError:
            return []

        subcommands = [
            "list",
            "add",
            "new",
            "show",
            "open",
            "update",
            "delete",
            "complete",
            "drop",
        ]
        scopes = ["board", "logs", "all"]
        modes = ["auto", "editable", "view"]

        if not tokens:
            return subcommands

        if len(tokens) == 1 and not args.endswith(" "):
            prefix = tokens[0].lower()
            return [sc for sc in subcommands if sc.startswith(prefix)]

        action = tokens[0].lower()
        if action == "list":
            if len(tokens) <= 1:
                return scopes
            if len(tokens) == 2 and not args.endswith(" "):
                prefix = tokens[1].lower()
                return [s for s in scopes if s.startswith(prefix)]
            return []

        if action in {"show", "open", "update", "delete", "complete", "drop"}:
            task_ids = cls._get_cached_task_ids(coder)
            if len(tokens) == 1:
                return task_ids
            if len(tokens) == 2 and not args.endswith(" "):
                prefix = tokens[1].lower()
                return [task_id for task_id in task_ids if task_id.startswith(prefix)]
            if action == "open" and len(tokens) >= 2:
                if len(tokens) == 2:
                    return modes
                if len(tokens) == 3 and not args.endswith(" "):
                    prefix = tokens[2].lower()
                    return [m for m in modes if m.startswith(prefix)]
            if action == "update":
                return ["--title", "--column"]

        return []

    @classmethod
    def get_help(cls) -> str:
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /task list [board|logs|all]\n"
        help_text += "  /task add <title>\n"
        help_text += "  /task new [title]       -- create a new task and set as active\n"
        help_text += "  /task show <task-id>\n"
        help_text += "  /task open <task-id> [auto|editable|view]\n"
        help_text += "  /task update <task-id> <new title>\n"
        help_text += "  /task update <task-id> --title <title> --column <column>\n"
        help_text += "  /task delete <task-id>\n"
        help_text += "  /task complete <task-id>\n"
        help_text += "  /task drop [task-id]\n"
        return help_text
