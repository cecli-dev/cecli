import json
import os

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.output import color_markers, tool_footer, tool_header


class Tool(BaseTool):
    NORM_NAME = "ls"
    TRACK_INVOCATIONS = False
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ls",
            "description": "List files in a directory. Paths are relative to the project root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "The path of the directory to list, relative to the project root. "
                            "Defaults to the project root."
                        ),
                        "default": ".",
                    }
                },
                "required": [],
            },
        },
    }

    @classmethod
    def execute(cls, coder, path=None, **kwargs):
        """
        List files in directory and optionally add some to context.

        This provides information about the structure of the codebase,
        similar to how a developer would explore directories.
        """
        # Handle both positional and keyword arguments for backward compatibility
        dir_path = path or "."

        try:
            # Create an absolute path from the provided relative path
            abs_path = os.path.abspath(os.path.join(coder.root, dir_path))

            # Security check: ensure the resolved path is within the project root
            if not abs_path.startswith(os.path.abspath(coder.root)):
                coder.io.tool_error(
                    f"Error: Path '{dir_path}' attempts to access files outside the project root."
                )
                return "Error: Path is outside the project root."

            # Check if path exists
            if not os.path.exists(abs_path):
                coder.io.tool_output(f"⚠️ Path '{dir_path}' not found")
                return "Directory not found"

            # Get directory contents
            contents = []
            if os.path.isdir(abs_path):
                # It's a directory, list its contents
                try:
                    with os.scandir(abs_path) as entries:
                        for entry in entries:
                            if entry.is_file() and not entry.name.startswith("."):
                                rel_path = os.path.relpath(entry.path, coder.root)
                                contents.append(rel_path)
                except OSError as e:
                    coder.io.tool_error(f"Error listing directory '{dir_path}': {e}")
                    return f"Error: {e}"
            elif os.path.isfile(abs_path):
                # It's a file, just return its relative path
                contents.append(os.path.relpath(abs_path, coder.root))

            if contents:
                coder.io.tool_output(f"📋 Listed {len(contents)} file(s) in '{dir_path}'")
                sorted_contents = sorted(contents)
                if len(sorted_contents) > 10:
                    return (
                        f"Found {len(sorted_contents)} files: {', '.join(sorted_contents[:10])}..."
                    )
                else:
                    return f"Found {len(sorted_contents)} files: {', '.join(sorted_contents)}"
            else:
                coder.io.tool_output(f"📋 No files found in '{dir_path}'")
                return "No files found in directory"
        except Exception as e:
            coder.io.tool_error(f"Error in ls: {str(e)}")
            return f"Error: {str(e)}"

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for Ls tool."""
        color_start, color_end = color_markers(coder)

        try:
            params = json.loads(tool_response.function.arguments)
        except json.JSONDecodeError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        # Output the directory parameter with the requested format
        directory = params.get("path", "")
        if directory:
            # Format as "ls: • directory"
            formatted_query = f"{color_start}path:{color_end} {directory}"
            coder.io.tool_output(formatted_query)
            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response)
