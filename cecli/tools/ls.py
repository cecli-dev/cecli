import os

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations


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
        response = ToolResponse(cls.NORM_NAME)

        try:
            # Create an absolute path from the provided relative path
            abs_path = os.path.abspath(os.path.join(coder.root, dir_path))

            # Security check: ensure the resolved path is within the project root
            if not abs_path.startswith(os.path.abspath(coder.root)):
                coder.io.tool_error(
                    f"Error: Path '{dir_path}' attempts to access files outside the project root."
                )
                response.append_result("Error: Path is outside the project root.")
                return response

            # Check if path exists
            if not os.path.exists(abs_path):
                coder.io.tool_output(f"⚠ Path '{dir_path}' not found", type="tool-result")
                response.append_result("Directory not found")
                return response

            # Get directory contents
            contents = []
            if os.path.isdir(abs_path):
                # It's a directory, list its contents
                try:
                    with os.scandir(abs_path) as entries:
                        for entry in entries:
                            if not entry.name.startswith("."):
                                rel_path = os.path.relpath(entry.path, coder.root)
                                contents.append(rel_path)
                except OSError as e:
                    coder.io.tool_error(f"Error listing directory '{dir_path}': {e}")
                    response.append_result(f"Error: {e}")
                    return response
            elif os.path.isfile(abs_path):
                # It's a file, just return its relative path
                contents.append(os.path.relpath(abs_path, coder.root))

            if contents:
                coder.io.tool_output(
                    f"🗐 Listed {len(contents)} file(s) in '{dir_path}'", type="tool-result"
                )
                sorted_contents = sorted(contents)
                if len(sorted_contents) > 500:
                    response.append_result(
                        f"Found {len(sorted_contents)} files:"
                        f" {', '.join(sorted_contents[:500])}"
                        f"\n... and {len(sorted_contents) - 500} more"
                    )
                    return response
                else:
                    response.append_result(
                        f"Found {len(sorted_contents)} files: {', '.join(sorted_contents)}"
                    )
                    return response
            else:
                coder.io.tool_output(f"🗐 No files found in '{dir_path}'", type="tool-result")
                response.append_result("No files found in directory")
                return response
        except Exception as e:
            coder.io.tool_error(f"Error in ls: {str(e)}")
            response.append_result(f"Error: {str(e)}")
            return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for Ls tool."""
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

        # Output the directory parameter with the requested format
        directory = params.get("path", "")
        if directory:
            # Format as "ls: • directory"
            formatted_query = f"{color_start}path:{color_end} {directory}"
            coder.io.tool_output(formatted_query)
            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)
