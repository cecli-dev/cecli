from cecli.helpers.hashline import (
    HashlineError,
    apply_hashline_operation,
    extract_hashline_range,
)
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import (
    ToolError,
    apply_change,
    format_tool_result,
    handle_tool_error,
    validate_file_for_edit,
)


class Tool(BaseTool):
    NORM_NAME = "indenttext"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "IndentText",
            "description": "Indent lines in a file.",
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
                    "indent_levels": {"type": "integer", "default": 1},
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
        indent_levels=1,
        change_id=None,
        dry_run=False,
        **kwargs,
    ):
        """
        Indent or unindent a block of lines in a file using hashline markers.

        Parameters:
        - coder: The Coder instance
        - file_path: Path to the file to modify
        - start_line: Hashline format for start line: "{4 char hash}" (without the braces)
        - end_line: Hashline format for end line: "{4 char hash}" (without the braces)
        - indent_levels: Number of levels to indent (positive) or unindent (negative)
        - change_id: Optional ID for tracking the change
        - dry_run: If True, simulate the change without modifying the file

        Returns a result message.
        """
        tool_name = "IndentText"
        try:
            # 1. Validate file and get content
            abs_path, rel_path, original_content = validate_file_for_edit(coder, file_path)

            # 2. Validate indent_levels parameter
            try:
                indent_levels = int(indent_levels)
            except ValueError:
                raise ToolError(
                    f"Invalid indent_levels value: '{indent_levels}'. Must be an integer."
                )

            # 3. Extract the range content using hashline
            try:
                range_content = extract_hashline_range(
                    original_content=original_content,
                    start_line_hash=start_line,
                    end_line_hash=end_line,
                )
            except HashlineError as e:
                raise ToolError(f"Hashline range extraction failed: {str(e)}")

            # 4. Apply indentation to the extracted range
            # Strip hashline prefixes to get original content
            from cecli.helpers.hashline import strip_hashline

            original_range_content = strip_hashline(range_content)

            # Split into lines and apply indentation
            range_lines = original_range_content.splitlines(keepends=True)
            indent_str = " " * 4  # Assume 4 spaces per level
            modified_range_lines = []

            for line in range_lines:
                if indent_levels > 0:
                    # Indent: add spaces
                    modified_line = (indent_str * indent_levels) + line
                elif indent_levels < 0:
                    # Unindent: remove spaces
                    spaces_to_remove = abs(indent_levels) * len(indent_str)
                    current_leading_spaces = len(line) - len(line.lstrip(" "))
                    actual_remove = min(spaces_to_remove, current_leading_spaces)
                    if actual_remove > 0:
                        modified_line = line[actual_remove:]
                    else:
                        modified_line = line
                else:
                    # indent_levels == 0, no change
                    modified_line = line
                modified_range_lines.append(modified_line)

            # Join back into text
            indented_range_content = "".join(modified_range_lines)

            # 5. Check if any changes were made
            if original_range_content == indented_range_content:
                coder.io.tool_warning("No changes made: indentation would not change file")
                return "Warning: No changes made (indentation would not change file)"

            # 6. Handle dry run
            if dry_run:
                # Parse line numbers for display
                try:
                    start_line_num_str, _ = start_line.split(":", 1)
                    end_line_num_str, _ = end_line.split(":", 1)
                    start_line_num = int(start_line_num_str)
                    end_line_num = int(end_line_num_str)
                    num_lines = end_line_num - start_line_num + 1
                except (ValueError, IndexError):
                    num_lines = "unknown"

                action = "indent" if indent_levels > 0 else "unindent"
                levels = abs(indent_levels)
                level_text = "level" if levels == 1 else "levels"

                dry_run_message = (
                    f"Dry run: Would {action} {num_lines} lines ({start_line} to {end_line})"
                    f" by {levels} {level_text} in {file_path}."
                )
                return format_tool_result(
                    coder,
                    tool_name,
                    "",
                    dry_run=True,
                    dry_run_message=dry_run_message,
                )

            # 7. Apply Change (Not dry run) using replace operation
            try:
                new_content = apply_hashline_operation(
                    original_content=original_content,
                    start_line_hash=start_line,
                    end_line_hash=end_line,
                    operation="replace",
                    text=indented_range_content,
                )
            except (ToolError, HashlineError) as e:
                raise ToolError(f"Hashline replacement failed: {str(e)}")

            # 8. Apply the change
            metadata = {
                "start_line": start_line,
                "end_line": end_line,
                "indent_levels": indent_levels,
            }
            final_change_id = apply_change(
                coder,
                abs_path,
                rel_path,
                original_content,
                new_content,
                "indenttext",
                metadata,
                change_id,
            )

            coder.files_edited_by_tools.add(rel_path)

            # 9. Format and return result
            # Parse line numbers for display
            try:
                start_line_num_str, _ = start_line.split(":", 1)
                end_line_num_str, _ = end_line.split(":", 1)
                start_line_num = int(start_line_num_str)
                end_line_num = int(end_line_num_str)
                num_lines = end_line_num - start_line_num + 1
            except (ValueError, IndexError):
                num_lines = "unknown"

            action_past = "Indented" if indent_levels > 0 else "Unindented"
            levels = abs(indent_levels)
            level_text = "level" if levels == 1 else "levels"

            success_message = (
                f"{action_past} {num_lines} lines ({start_line} to {end_line})"
                f" by {levels} {level_text} in {file_path}"
            )
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
