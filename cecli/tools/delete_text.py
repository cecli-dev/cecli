from cecli.helpers.hashline import apply_hashline_operation
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import (
    ToolError,
    apply_change,
    format_tool_result,
    handle_tool_error,
    validate_file_for_edit,
)


class Tool(BaseTool):
    NORM_NAME = "deletetext"
    TRACK_INVOCATIONS = False
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "DeleteText",
            "description": (
                "Delete a block of lines from a file using hashline markers. Uses start_line and"
                ' end_line parameters with format "{4 char hash}" (without the braces) to specify'
                " the range to delete."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "start_line": {
                        "type": "string",
                        "description": (
                            'Hashline format for start line: "{4 char hash}" (without the braces)'
                        ),
                    },
                    "end_line": {
                        "type": "string",
                        "description": (
                            'Hashline format for end line: "{4 char hash}" (without the braces)'
                        ),
                    },
                    "change_id": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": False},
                },
                "required": ["file_path", "start_line", "end_line"],
            },
        },
    }

    @classmethod
    def execute(
        cls,
        coder,
        file_path,
        start_line,
        end_line,
        change_id=None,
        dry_run=False,
        **kwargs,
    ):
        """
        Delete a block of text using hashline markers.
        """

        if not coder.edit_allowed:
            raise ToolError(
                "Please call `ShowContext` first to make sure edits are appropriately scoped"
            )
        else:
            coder.edit_allowed = False

        tool_name = "DeleteText"
        try:
            # 1. Validate file and get content
            abs_path, rel_path, original_content = validate_file_for_edit(coder, file_path)

            # 2. Apply hashline operation for deletion
            try:
                new_content = apply_hashline_operation(
                    original_content=original_content,
                    start_line_hash=start_line,
                    end_line_hash=end_line,
                    operation="delete",
                    text=None,
                )
            except Exception as e:
                coder.edit_allowed = True
                raise ToolError(f"Hashline deletion failed: {str(e)}")

            # Check if any changes were made
            if original_content == new_content:
                coder.io.tool_warning("No changes made: deletion would not change file")
                return "Warning: No changes made (deletion would not change file)"

            # 3. Handle dry run
            if dry_run:
                dry_run_message = (
                    f"Dry run: Would delete lines {start_line} to {end_line} in {file_path}."
                )
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
                "end_line": end_line,
            }
            final_change_id = apply_change(
                coder,
                abs_path,
                rel_path,
                original_content,
                new_content,
                "deletetext",
                metadata,
                change_id,
            )

            coder.files_edited_by_tools.add(rel_path)
            # 5. Format and return result
            success_message = f"Deleted lines {start_line} to {end_line} in {file_path}"
            return format_tool_result(
                coder,
                tool_name,
                success_message,
                change_id=final_change_id,
            )

        except ToolError as e:
            # Handle errors raised by utility functions (expected errors)
            return handle_tool_error(coder, tool_name, e, add_traceback=False)
        except Exception as e:
            # Handle unexpected errors
            return handle_tool_error(coder, tool_name, e)
