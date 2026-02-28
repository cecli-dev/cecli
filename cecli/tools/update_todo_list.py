from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError, format_tool_result, handle_tool_error
from cecli.tools.utils.output import tool_footer, tool_header


class Tool(BaseTool):
    NORM_NAME = "updatetodolist"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "UpdateTodoList",
            "description": "Update the todo list with new items or modify existing ones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "task": {
                                    "type": "string",
                                    "description": "The task description.",
                                },
                                "done": {
                                    "type": "boolean",
                                    "description": "Whether the task is completed.",
                                },
                                "current": {
                                    "type": "boolean",
                                    "description": (
                                        "Whether this is the current task being worked on. Current"
                                        " tasks are marked with '→' in the todo list."
                                    ),
                                },
                            },
                            "required": ["task", "done"],
                        },
                        "description": "Array of task items to update the todo list with.",
                    },
                    "append": {
                        "type": "boolean",
                        "description": (
                            "Whether to append to existing content instead of replacing it."
                            " Defaults to False."
                        ),
                    },
                    "change_id": {
                        "type": "string",
                        "description": "Optional change ID for tracking.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": (
                            "Whether to perform a dry run without actually updating the file."
                            " Defaults to False."
                        ),
                    },
                },
                "required": ["tasks"],
            },
        },
    }

    @classmethod
    def execute(cls, coder, tasks, append=False, change_id=None, dry_run=False, **kwargs):
        """
        Update the todo list.

        Always writes to a board task's subtasks. If no active task exists,
        one is transparently created via ``get_or_create_session_task()``.
        """
        tool_name = "UpdateTodoList"
        try:
            from cecli.brainfile import CecliTaskStore

            store = CecliTaskStore(coder.root)

            # Ensure an active board task exists
            active_task_id = getattr(coder, "active_task_id", None)
            just_created = False
            if not active_task_id:
                opened = store.get_or_create_session_task(coder)
                active_task_id = opened["id"]
                just_created = opened.get("subtasks_total", 0) == 0

            task_path = store.get_task_file_path(active_task_id)
            if not task_path or not task_path.is_file():
                raise ToolError(f"Active task file not found: {active_task_id}")

            existing_content = coder.io.read_text(str(task_path)) or ""

            if dry_run:
                action = "append to" if append else "replace"
                dry_run_message = f"Dry run: Would {action} subtasks for task '{active_task_id}'."
                return format_tool_result(
                    coder, tool_name, "", dry_run=True, dry_run_message=dry_run_message
                )

            store.update_task_subtasks(active_task_id, tasks, append=append)

            # Auto-title: if the task was just created, derive title from first item
            if just_created:
                title = store.auto_title(tasks)
                store.update_task(active_task_id, title=title)

            new_content = coder.io.read_text(str(task_path)) or ""

            if existing_content == new_content:
                coder.io.tool_warning("No changes made: new content is identical to existing")
                return "Warning: No changes made (content identical to existing)"

            metadata = {
                "append": append,
                "existing_length": len(existing_content),
                "new_length": len(new_content),
            }
            task_rel_path = store.relpath(task_path)

            final_change_id = coder.change_tracker.track_change(
                file_path=task_rel_path,
                change_type="updatetodolist",
                original_content=existing_content,
                new_content=new_content,
                metadata=metadata,
                change_id=change_id,
            )

            coder.coder_edited_files.add(task_rel_path)

            action = "appended to" if append else "updated"
            success_message = f"Successfully {action} subtasks for {active_task_id}"
            return format_tool_result(
                coder,
                tool_name,
                success_message,
                change_id=final_change_id,
            )

        except ToolError as e:
            return handle_tool_error(coder, tool_name, e, add_traceback=False)
        except Exception as e:
            return handle_tool_error(coder, tool_name, e)

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        import json

        from cecli.tools.utils.output import color_markers

        color_start, color_end = color_markers(coder)

        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        params = json.loads(tool_response.function.arguments)
        tasks = params.get("tasks", [])

        if tasks:
            done_tasks = []
            remaining_tasks = []

            for task_item in tasks:
                if task_item.get("done", False):
                    done_tasks.append(f"✓ {task_item['task']}")
                else:
                    if task_item.get("current", False):
                        remaining_tasks.append(f"→ {task_item['task']}")
                    else:
                        remaining_tasks.append(f"○ {task_item['task']}")

            coder.io.tool_output("")
            coder.io.tool_output(f"{color_start}Todo List:{color_end}")

            if done_tasks:
                coder.io.tool_output("Done:")
                for task in done_tasks:
                    coder.io.tool_output(task)
                coder.io.tool_output("")

            if remaining_tasks:
                coder.io.tool_output("Remaining:")
                for task in remaining_tasks:
                    coder.io.tool_output(task)

            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response)
