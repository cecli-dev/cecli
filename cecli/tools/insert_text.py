from cecli.helpers.hashline import apply_hashline_operation, strip_hashline
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import (
    ToolError,
    apply_change,
    format_tool_result,
    handle_tool_error,
    validate_file_for_edit,
)
from cecli.tools.utils.output import tool_body_unwrapped, tool_footer, tool_header


class Tool(BaseTool):
    NORM_NAME = "inserttext"
    TRACK_INVOCATIONS = False
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "InsertText",
            "description": (
                "Insert content into a file using hashline markers. "
                'Uses start_line parameter with format "{4 char hash}" (without the braces) '
                "to specify where to insert content. For empty files, "
                'use "@000" as the hashline reference. '
                "Note: Content will be inserted on the line AFTER the specified location"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                    "start_line": {
                        "type": "string",
                        "description": (
                            'Hashline format for insertion point: "{4 char hash}" (without the'
                            " braces)"
                        ),
                    },
                    "change_id": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": False},
                },
                "required": ["file_path", "content", "start_line"],
            },
        },
    }

    @classmethod
    def execute(
        cls,
        coder,
        file_path,
        content,
        start_line,
        change_id=None,
        dry_run=False,
        **kwargs,
    ):
        """
        Insert content into a file using hashline markers.

        Args:
            coder: The coder instance
            file_path: Path to the file to modify
            content: The content to insert
            start_line: Hashline format for insertion point: "{4 char hash}" (without the braces)
            change_id: Optional ID for tracking changes
            dry_run: If True, only simulate the change
        """

        if not coder.edit_allowed:
            raise ToolError(
                "Please call `ShowContext` first to make sure edits are appropriately scoped"
            )

        tool_name = "InsertText"
        try:
            # 1. Validate file and get content
            abs_path, rel_path, original_content = validate_file_for_edit(coder, file_path)

            # 2. Apply hashline operation for insertion
            try:
                new_content = apply_hashline_operation(
                    original_content=original_content,
                    start_line_hash=start_line,
                    end_line_hash=start_line,  # For insert, end_line is same as start_line
                    operation="insert",
                    text=strip_hashline(content),
                )
            except Exception as e:
                coder.edit_allowed = True
                raise ToolError(f"Hashline insertion failed: {str(e)}")

            # Check if any changes were made
            if original_content == new_content:
                coder.io.tool_warning("No changes made: insertion would not change file")
                return "Warning: No changes made (insertion would not change file)"

            # 3. Handle dry run
            if dry_run:
                dry_run_message = f"Dry run: Would insert content at {start_line} in {file_path}."
                return format_tool_result(
                    coder,
                    tool_name,
                    "",
                    dry_run=True,
                    dry_run_message=dry_run_message,
                )

            # 4. Apply Change (Not dry run)
            metadata = {
                "start_line": start_line,
                "content": content,
            }
            final_change_id = apply_change(
                coder,
                abs_path,
                rel_path,
                original_content,
                new_content,
                "inserttext",
                metadata,
                change_id,
            )

            coder.files_edited_by_tools.add(rel_path)
            cls.clear_invocation_cache()

            # 5. Format and return result
            success_message = f"Inserted content at {start_line} in {file_path}"
            return format_tool_result(
                coder,
                tool_name,
                success_message,
                change_id=final_change_id,
            )

        except ToolError as e:
            # Handle errors raised by utility functions (expected errors)
            coder.edit_allowed = False
            return handle_tool_error(coder, tool_name, e, add_traceback=False)

        except Exception as e:
            coder.edit_allowed = False
            return handle_tool_error(coder, tool_name, e)

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)
        tool_body_unwrapped(coder=coder, tool_response=tool_response)
        tool_footer(coder=coder, tool_response=tool_response)
