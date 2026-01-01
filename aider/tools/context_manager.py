import os
import time

from aider.tools.utils.base_tool import BaseTool
from aider.tools.utils.helpers import ToolError


class Tool(BaseTool):
    NORM_NAME = "contextmanager"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ContextManager",
            "description": (
                "Manage multiple files in the chat context: remove, editable, view, and create."
                " Accepts arrays of file paths for each operation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "remove": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to remove from context.",
                    },
                    "editable": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of file paths to make editable. Limit to at most 2 at a time."
                        ),
                    },
                    "view": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of file paths to view (add as read-only). Limit to at most 2 at a"
                            " time."
                        ),
                    },
                    "create": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to create.",
                    },
                },
                "additionalProperties": False,
                "required": [],
            },
        },
    }

    @classmethod
    def execute(cls, coder, remove=None, editable=None, view=None, create=None):
        """Perform batch operations on the coder's context.

        Parameters
        ----------
        coder: Coder instance
            The active coder handling file context.
        remove: list[str] | None
            Files to remove from the context.
        editable: list[str] | None
            Files to promote to editable status.
        view: list[str] | None
            Files to add as read-only view.
        create: list[str] | None
            Files to create and make editable.
        """

        # Helper to parse string arguments that might be JSON arrays
        def parse_arg(arg):
            if arg is None:
                return []
            if isinstance(arg, list):
                return arg
            if isinstance(arg, str):
                # Handle empty or whitespace-only string as empty list
                if not arg or arg.isspace():
                    return []
                # Try to parse as JSON array
                import json

                try:
                    parsed = json.loads(arg)
                    if isinstance(parsed, list):
                        return parsed
                    else:
                        # If it's not a list, wrap it in a list
                        return [parsed]
                except json.JSONDecodeError:
                    # If not valid JSON, treat as a single file path
                    return [arg]
            # For any other type, wrap in list
            return [arg]

        remove_files = parse_arg(remove)
        editable_files = parse_arg(editable)
        view_files = parse_arg(view)
        create_files = parse_arg(create)

        if not remove_files and not editable_files and not view_files and not create_files:
            raise ToolError("You must specify at least one of: remove, editable, view, or create")

        messages = []

        for f in create_files:
            messages.append(cls._create(coder, f))
        for f in remove_files:
            messages.append(cls._remove(coder, f))
        for f in view_files:
            messages.append(cls._view(coder, f))
        for f in editable_files:
            messages.append(cls._editable(coder, f))

        return "\n".join(messages)

    @staticmethod
    def _remove(coder, file_path):
        """Remove a file from the coder's context."""
        try:
            abs_path = coder.abs_root_path(file_path)
            rel_path = coder.get_rel_fname(abs_path)
            removed = False
            if abs_path in coder.abs_fnames:
                coder.abs_fnames.remove(abs_path)
                removed = True
            elif abs_path in coder.abs_read_only_fnames:
                coder.abs_read_only_fnames.remove(abs_path)
                removed = True
            if not removed:
                coder.io.tool_output("⚠️ File '{file_path}' not in context")
                return f"File not in context: {file_path}"
            coder.recently_removed[rel_path] = {"removed_at": time.time()}
            coder.io.tool_output("🗑️ Removed '{file_path}' from context")
            return f"Removed: {file_path}"
        except Exception as e:
            coder.io.tool_error(f"Error removing file '{file_path}': {str(e)}")
            return f"Error removing {file_path}: {e}"

    @staticmethod
    def _editable(coder, file_path):
        """Make a file editable in the coder's context."""
        try:
            abs_path = coder.abs_root_path(file_path)
            if abs_path in coder.abs_fnames:
                coder.io.tool_output("📝 File '{file_path}' is already editable")
                return f"Already editable: {file_path}"
            if not os.path.isfile(abs_path):
                coder.io.tool_output("⚠️ File '{file_path}' not found on disk")
                return f"File not found: {file_path}"
            was_read_only = False
            if abs_path in coder.abs_read_only_fnames:
                coder.abs_read_only_fnames.remove(abs_path)
                was_read_only = True
            coder.abs_fnames.add(abs_path)
            if was_read_only:
                coder.io.tool_output("📝 Moved '{file_path}' from read-only to editable")
                return f"Made editable (moved): {file_path}"
            else:
                coder.io.tool_output("📝 Added '{file_path}' directly to editable context")
                return f"Made editable (added): {file_path}"
        except Exception as e:
            coder.io.tool_error(f"Error making editable '{file_path}': {str(e)}")
            return f"Error making editable {file_path}: {e}"

    @staticmethod
    def _view(coder, file_path):
        """View a file (add as read‑only) in the coder's context."""
        try:
            return coder._add_file_to_context(file_path, explicit=True)
        except Exception as e:
            coder.io.tool_error(f"Error viewing file '{file_path}': {str(e)}")
            return f"Error viewing {file_path}: {e}"

    @staticmethod
    def _create(coder, file_path):
        """Create a new file on the file system and make it editable in the coder's context."""
        try:
            abs_path = coder.abs_root_path(file_path)

            # Check if file already exists
            if os.path.exists(abs_path):
                coder.io.tool_output("⚠️ File '{file_path}' already exists")
                return f"File already exists: {file_path}"

            # Create parent directories if they don't exist
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            # Create an empty file
            with open(abs_path, "w", encoding="utf-8"):
                pass

            # Add the file to editable context
            coder.abs_fnames.add(abs_path)

            coder.io.tool_output("📝 Created '{file_path}' and made it editable")
            return f"Created and made editable: {file_path}"

        except Exception as e:
            coder.io.tool_error(f"Error creating file '{file_path}': {str(e)}")
            return f"Error creating {file_path}: {e}"
