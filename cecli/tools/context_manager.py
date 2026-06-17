import os
import re
import time

from cecli.helpers.background_commands import BackgroundCommandManager
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError, parse_arg_as_list
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "contextmanager"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ContextManager",
            "description": (
                "Manage multiple files in the chat context: add, read_only, create, and remove."
                " Accepts arrays of file paths for each operation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "add": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of file paths to add to context. Limit to at most 2 at a time."
                        ),
                    },
                    "read_only": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of file paths to add as read-only. Limit to at most 2 at a time."
                        ),
                    },
                    "create": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to create.",
                    },
                    "remove": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to remove from context.",
                    },
                    "stop": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of command keys to stop background commands for.",
                    },
                },
                "additionalProperties": False,
                "required": [],
            },
        },
    }

    @classmethod
    def execute(
        cls, coder, remove=None, add=None, read_only=None, create=None, stop=None, **kwargs
    ):
        """Perform batch operations on the coder's context.

        Parameters
        ----------
        coder: Coder instance
            The active coder handling file context.
        remove: list[str] | None
            Files to remove from the context.
        add: list[str] | None
            Files to promote to editable status.
        view: list[str] | None
            Files to add as read-only view.
        create: list[str] | None
            Files to create and make editable.
        """
        remove_files = sorted(parse_arg_as_list(remove), key=cls._natural_sort_key)
        editable_files = sorted(parse_arg_as_list(add), key=cls._natural_sort_key)
        view_files = sorted(parse_arg_as_list(read_only), key=cls._natural_sort_key)
        create_files = sorted(parse_arg_as_list(create), key=cls._natural_sort_key)
        stop_keys = sorted(parse_arg_as_list(stop), key=cls._natural_sort_key)

        if (
            not remove_files
            and not editable_files
            and not view_files
            and not create_files
            and not stop_keys
        ):
            raise ToolError(
                "You must specify at least one of: remove, editable, view, create, or stop"
            )

        coder.io.tool_output("⚙️ Modifying Context.")
        messages = []

        for f in create_files:
            messages.append(cls._create(coder, f))
        for f in remove_files:
            messages.append(cls._remove(coder, f))
        for f in view_files:
            messages.append(cls._view(coder, f))
        for f in editable_files:
            try:
                abs_path = coder.abs_root_path(f)
            except Exception:
                abs_path = None
            if abs_path is not None and not os.path.isfile(abs_path):
                coder.io.tool_output(f"ℹ️ `{f}` missing on disk — using **create** instead of add")
                messages.append(cls._create(coder, f))
            else:
                messages.append(cls._editable(coder, f))
        for key in stop_keys:
            messages.append(cls._stop_command(coder, key))

        if coder.tui and coder.tui():
            coder.tui().refresh()

        coder.context_blocks_cache = {}
        coder.edit_allowed = True

        return "\n".join(messages)

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for ContextManager tool."""
        color_start, color_end = color_markers(coder)

        # Output header
        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        try:
            params = ToolValidations.validate_params(
                tool_response.function.arguments, cls.VALIDATIONS, cls.SCHEMA
            )
        except ToolError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        # Define action display names
        action_names = {
            "create": "create",
            "remove": "remove",
            "view": "view",
            "editable": "editable",
            "stop": "stop",
        }

        # Output each action with comma-separated file list
        for action_key, display_name in action_names.items():
            files = sorted(parse_arg_as_list(params.get(action_key)), key=cls._natural_sort_key)
            if files:
                file_list = ", ".join(files)
                coder.io.tool_output(f"{color_start}{display_name}:{color_end} {file_list}")

        tool_footer(coder=coder, tool_response=tool_response, params=params)

    @classmethod
    def _remove(cls, coder, file_path):
        """Remove a file from the coder's context."""
        from cecli.helpers.conversation import ConversationService

        try:
            abs_path = cls._resolve_file_path(coder, file_path)
            rel_path = coder.get_rel_fname(abs_path)
            removed = False

            if abs_path in coder.abs_fnames:
                coder.abs_fnames.remove(abs_path)
                removed = True

            if abs_path in coder.abs_read_only_fnames:
                coder.abs_read_only_fnames.remove(abs_path)
                removed = True

            if not removed:
                coder.io.tool_output(f"⚠️ File '{file_path}' not in context")
                return f"File not in context: {file_path}"

            coder.recently_removed[rel_path] = {"removed_at": time.time()}

            if not file_path.startswith("command_key::"):
                ConversationService.get_chunks(coder).defer_removal(abs_path)
                ConversationService.get_chunks(coder).defer_removal(rel_path)

            coder.io.tool_output(f"🗑️ Removed '{file_path}' from context")
            return (
                f"Removed: {file_path}\n"
                "Old file contents may remain visible. This is an acceptable system behavior."
            )
        except Exception as e:
            coder.io.tool_error(f"Error removing file '{file_path}': {str(e)}")
            return f"Error removing {file_path}: {e}"

    @classmethod
    def _stop_command(cls, coder, command_key):
        """Stop a background command by its command key."""
        try:
            success, output, exit_code = BackgroundCommandManager.stop_background_command(
                command_key
            )
            if success:
                coder.io.tool_output(f"🛑 Stopped background command '{command_key}'")
                return (
                    f"Background command stopped: {command_key}\n"
                    f"Exit code: {exit_code}\n"
                    f"Final output:\n{output}"
                )
            else:
                coder.io.tool_output(
                    f"⚠️ Background command '{command_key}' not found or not running"
                )
                return f"Command not found or not running: {command_key}"
        except Exception as e:
            coder.io.tool_error(f"Error stopping command '{command_key}': {str(e)}")
            return f"Error stopping {command_key}: {e}"

    @classmethod
    def _editable(cls, coder, file_path):
        """Make a file editable in the coder's context."""
        try:
            abs_path = cls._resolve_file_path(coder, file_path)
            if abs_path in coder.abs_fnames:
                coder.io.tool_output(f"📝 File '{file_path}' is already editable")
                return f"Already editable: {file_path}"
            if not os.path.isfile(abs_path):
                coder.io.tool_output(f"⚠️ File '{file_path}' not found on disk")
                return f"File not found: {file_path}"
            was_read_only = False
            if abs_path in coder.abs_read_only_fnames:
                coder.abs_read_only_fnames.remove(abs_path)
                was_read_only = True
            coder.abs_fnames.add(abs_path)
            if was_read_only:
                coder.io.tool_output(f"📝 Moved '{file_path}' from read-only to editable")
                return f"Made editable (moved): {file_path}"
            else:
                coder.io.tool_output(f"📝 Added '{file_path}' directly to editable context")
                return f"Made editable (added): {file_path}"
        except Exception as e:
            coder.io.tool_error(f"Error making editable '{file_path}': {str(e)}")
            return f"Error making editable {file_path}: {e}"

    @classmethod
    def _view(cls, coder, file_path):
        """View a file (add as read‑only) in the coder's context."""
        try:
            resolved_path = cls._resolve_file_path(coder, file_path)
            return coder._add_file_to_context(resolved_path, explicit=True)
        except Exception as e:
            coder.io.tool_error(f"Error viewing file '{file_path}': {str(e)}")
            return f"Error viewing {file_path}: {e}"

    @classmethod
    def _create(cls, coder, file_path):
        """Create a new file on the file system and make it editable in the coder's context."""
        try:
            abs_path = coder.abs_root_path(file_path)

            # Check if file already exists
            if os.path.exists(abs_path):
                coder.io.tool_output(f"⚠️ File '{file_path}' already exists")
                return f"File already exists: {file_path}"

            # Create parent directories if they don't exist
            parent = os.path.dirname(abs_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            # Create an empty file
            with open(abs_path, "w", encoding="utf-8"):
                pass

            # Add the file to editable context
            coder.abs_fnames.add(abs_path)

            coder.io.tool_output(f"📝 Created '{file_path}' and made it editable")
            return f"Created and made editable: {file_path}"

        except Exception as e:
            coder.io.tool_error(f"Error creating file '{file_path}': {str(e)}")
            return f"Error creating {file_path}: {e}"

    @classmethod
    def _resolve_file_path(cls, coder, file_path):
        """Resolve a file path, handling command_key:: aliases.

        command_key::{command_key}/{filename} resolves to the actual
        file path under the agent's local agent folder.
        """
        if file_path.startswith("command_key::"):
            alias_path = file_path[len("command_key::") :]
            parts = alias_path.split("/", 1)
            if len(parts) == 2:
                command_key = parts[0]
                filename = parts[1]
                rel_path = coder.local_agent_folder(f"{command_key}/{filename}")
                return coder.abs_root_path(rel_path)
        return coder.abs_root_path(file_path)

    @classmethod
    def _natural_sort_key(cls, s: str) -> list:
        """Natural sort key that splits "a10b2" into ["a", 10, "b", 2]."""
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]
