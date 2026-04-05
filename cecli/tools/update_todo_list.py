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
                                "task": {"type": "string", "description": "The task description."},
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
        Update the todo list file (todo.txt) with formatted task items.
        Can either replace the entire content or append to it.
        """
        tool_name = "UpdateTodoList"
        try:
            # Define the todo file path
            todo_file_path = coder.local_agent_folder("todo.txt")
            abs_path = coder.abs_root_path(todo_file_path)

            # Format tasks into string
            done_tasks = []
            remaining_tasks = []

            for task_item in tasks:
                if not isinstance(task_item, dict):
                    task_item = {
                        "task": str(task_item),
                        "done": False,
                        "current": False,
                    }

                if task_item.get("done", False):
                    done_tasks.append(f"✓ {task_item['task']}")
                else:
                    # Check if this is the current task
                    if task_item.get("current", False):
                        remaining_tasks.append(f"→ {task_item['task']}")
                    else:
                        remaining_tasks.append(f"○ {task_item['task']}")

            # Build formatted content
            content_lines = []
            if done_tasks:
                content_lines.append("Done:")
                content_lines.extend(done_tasks)
                content_lines.append("")

            if remaining_tasks:
                content_lines.append("Remaining:")
                content_lines.extend(remaining_tasks)

            # Remove trailing empty line if present
            if content_lines and content_lines[-1] == "":
                content_lines.pop()

            content = "\n".join(content_lines)

            # Get existing content if appending
            existing_content = ""
            import os

            if os.path.isfile(abs_path):
                existing_content = coder.io.read_text(abs_path) or ""

            # Prepare new content
            if append:
                if existing_content and not existing_content.endswith("\n"):
                    existing_content += "\n"
                new_content = existing_content + content
            else:
                new_content = content

            # Check if content exceeds 4096 characters and warn
            if len(new_content) > 4096:
                coder.io.tool_warning(
                    "⚠️ Todo list content exceeds 4096 characters. Consider summarizing the plan"
                    " before proceeding."
                )

            # Check if content actually changed
            if existing_content == new_content:
                coder.io.tool_warning("No changes made: new content is identical to existing")
                return (
                    "Error: No changes made (content identical to existing)."
                    "Please make progress implementing the plan instead of updating it."
                )

            # Handle dry run
            if dry_run:
                action = "append to" if append else "replace"
                dry_run_message = f"Dry run: Would {action} todo list in {todo_file_path}."
                return format_tool_result(
                    coder, tool_name, "", dry_run=True, dry_run_message=dry_run_message
                )

            # Apply change
            metadata = {
                "append": append,
                "existing_length": len(existing_content),
                "new_length": len(new_content),
            }

            # Write the file directly since it's a special file
            coder.io.write_text(abs_path, new_content)

            # Track the change
            final_change_id = coder.change_tracker.track_change(
                file_path=todo_file_path,
                change_type="updatetodolist",
                original_content=existing_content,
                new_content=new_content,
                metadata=metadata,
                change_id=change_id,
            )

            coder.coder_edited_files.add(todo_file_path)

            # Format and return result
            action = "appended to" if append else "updated"
            success_message = f"Successfully {action} todo list"
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

        # Parse the parameters to display formatted todo list
        params = json.loads(tool_response.function.arguments)
        tasks = params.get("tasks", [])

        if tasks:
            # Format tasks for display
            done_tasks = []
            remaining_tasks = []

            for task_item in tasks:
                if not isinstance(task_item, dict):
                    task_item = {
                        "task": str(task_item),
                        "done": False,
                        "current": False,
                    }

                if task_item.get("done", False):
                    done_tasks.append(f"✓ {task_item['task']}")
                else:
                    # Check if this is the current task
                    if task_item.get("current", False):
                        remaining_tasks.append(f"→ {task_item['task']}")
                    else:
                        remaining_tasks.append(f"○ {task_item['task']}")

            # Display formatted todo list
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
