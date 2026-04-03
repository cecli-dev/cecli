import json

from cecli.helpers.hashline import (
    HashlineError,
    apply_hashline_operations,
    get_hashline_diff,
    strip_hashline,
)
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import (
    ToolError,
    apply_change,
    format_tool_result,
    handle_tool_error,
    validate_file_for_edit,
)
from cecli.tools.utils.output import color_markers, tool_footer, tool_header


class Tool(BaseTool):
    NORM_NAME = "replacetext"
    TRACK_INVOCATIONS = False
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ReplaceText",
            "description": (
                "Replace text in one or more files. Can handle an array of up to 10 edits across"
                " multiple files. Each edit must include its own file_path. Use hashline ranges"
                " with the start_line and end_line parameters with format"
                ' "{4 char hash}" (without the braces). For empty files, use "@000" as the hashline'
                " references."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_path": {
                                    "type": "string",
                                    "description": "Required file path for this specific edit.",
                                },
                                "replace_text": {"type": "string"},
                                "start_line": {
                                    "type": "string",
                                    "description": (
                                        'Hashline format for start line: "{4 char hash}" (without'
                                        " the braces)"
                                    ),
                                },
                                "end_line": {
                                    "type": "string",
                                    "description": (
                                        'Hashline format for end line: "{4 char hash}" (without the'
                                        " braces)"
                                    ),
                                },
                            },
                            "required": ["file_path", "replace_text", "start_line", "end_line"],
                        },
                        "description": "Array of edits to apply.",
                    },
                    "change_id": {"type": "string"},
                },
                "required": ["edits"],
            },
        },
    }

    @classmethod
    def execute(
        cls,
        coder,
        edits=None,
        change_id=None,
        **kwargs,
    ):
        """
        Replace text in one or more files. Can handle single edit or array of edits across multiple files.
        Each edit object must include its own file_path.
        """

        if not coder.edit_allowed:
            raise ToolError(
                "Please call `ShowContext` first to make sure edits are appropriately scoped"
            )
        else:
            coder.edit_allowed = False

        tool_name = "ReplaceText"
        try:
            # 1. Validate edits parameter
            if not isinstance(edits, list):
                raise ToolError("edits parameter must be an array")

            if len(edits) == 0:
                raise ToolError("edits array cannot be empty")

            # 2. Group edits by file_path
            edits_by_file = {}
            for i, edit in enumerate(edits):
                edit_file_path = edit.get("file_path")
                if edit_file_path is None:
                    raise ToolError(f"Edit {i + 1} missing required file_path parameter")

                if edit_file_path not in edits_by_file:
                    edits_by_file[edit_file_path] = []
                edits_by_file[edit_file_path].append((i, edit))

            # 3. Process each file
            all_results = []
            all_failed_edits = []
            total_successful_edits = 0
            files_processed = 0

            for file_path_key, file_edits in edits_by_file.items():
                try:
                    # Validate file and get content
                    abs_path, rel_path, original_content = validate_file_for_edit(
                        coder, file_path_key
                    )

                    # Process all edits for this file using batch operations
                    operations = []
                    file_metadata = []
                    file_successful_edits = 0
                    file_failed_edits = []

                    for edit_index, edit in file_edits:
                        try:
                            edit_replace_text = edit.get("replace_text")
                            edit_start_line = edit.get("start_line")
                            edit_end_line = edit.get("end_line")

                            if edit_replace_text is None:
                                raise ToolError(
                                    f"Edit {edit_index + 1} missing required replace_text parameter"
                                )

                            # Add operation to batch
                            operations.append(
                                {
                                    "start_line_hash": edit_start_line,
                                    "end_line_hash": edit_end_line,
                                    "operation": "replace",
                                    "text": edit_replace_text,
                                }
                            )

                            # Create metadata for this edit
                            metadata = {
                                "start_line": edit_start_line,
                                "end_line": edit_end_line,
                                "replace_text": edit_replace_text,
                            }
                            file_metadata.append(metadata)

                        except Exception as e:
                            # Record failed edit but continue with others
                            file_failed_edits.append(f"Edit {edit_index + 1}: {str(e)}")
                            continue

                    # Apply all operations in batch
                    try:
                        new_content, successful_ops, failed_ops = apply_hashline_operations(
                            original_content=original_content,
                            operations=operations,
                        )

                        if new_content != original_content:
                            file_successful_edits += len(successful_ops)
                        else:
                            raise ToolError("Invalid Edit - Source Not Modified")

                        if len(failed_ops):
                            for failed_op in failed_ops:
                                op_index = failed_op["index"]
                                op_error = failed_op["error"]
                                file_failed_edits.append(f"Edit {op_index + 1}: {str(op_error)}")
                    except Exception as e:
                        # If batch operation fails, mark all operations as failed
                        for edit_index, _ in file_edits:
                            file_failed_edits.append(f"Edit {edit_index + 1}: {str(e)}")

                    all_failed_edits.extend(file_failed_edits)

                    # Check if any changes were made for this file
                    if original_content == new_content or file_successful_edits == 0:
                        continue

                    # Apply Change
                    metadata = {
                        "edits": file_metadata,
                        "total_edits": file_successful_edits,
                        "failed_edits": file_failed_edits if file_failed_edits else None,
                    }

                    # Apply the change (common path for both hashline and non-hashline cases)
                    final_change_id = apply_change(
                        coder,
                        abs_path,
                        rel_path,
                        original_content,
                        new_content,
                        "replacetext",
                        metadata,
                        change_id,
                    )

                    coder.files_edited_by_tools.add(rel_path)

                    all_results.append(
                        {
                            "file_path": file_path_key,
                            "successful_edits": file_successful_edits,
                            "failed_edits": file_failed_edits,
                            "change_id": final_change_id,
                        }
                    )
                    total_successful_edits += file_successful_edits
                    all_failed_edits.extend(file_failed_edits)
                    files_processed += 1

                except Exception as e:
                    # Record all edits for this file as failed
                    for edit_index, _ in file_edits:
                        all_failed_edits.append(f"Edit {edit_index + 1}: {str(e)}")
                    continue

            # 4. Check if any edits succeeded overall
            if total_successful_edits == 0:
                coder.edit_allowed = True
                error_msg = "No edits were successfully applied:\n" + "\n".join(all_failed_edits)
                raise ToolError(error_msg)

            # 6. Format and return result
            # Log failed edit messages to console for visibility
            if all_failed_edits:
                for failed_msg in all_failed_edits:
                    coder.io.tool_error(failed_msg)

            if files_processed == 1:
                # Single file case for backward compatibility
                result = all_results[0]
                success_message = (
                    f"Applied {result['successful_edits']} edits in {result['file_path']}"
                )
                if result["failed_edits"]:
                    success_message += f" ({len(result['failed_edits'])} failed)"
                    # Include failed edit details in message to LLM
                    success_message += "\nFailed edits:\n" + "\n".join(result["failed_edits"])
                change_id_to_return = result.get("change_id")
            else:
                # Multiple files case
                success_message = (
                    f"Applied {total_successful_edits} edits across {files_processed} files"
                )
                if all_failed_edits:
                    success_message += f" ({len(all_failed_edits)} failed)"
                    # Include failed edit details in message to LLM
                    success_message += "\nFailed edits:\n" + "\n".join(all_failed_edits)
                change_id_to_return = None  # Multiple change IDs, can't return single one

            return format_tool_result(
                coder,
                tool_name,
                success_message,
                change_id=change_id_to_return,
            )

        except ToolError as e:
            # Handle errors raised by utility functions or explicitly raised here
            return handle_tool_error(coder, tool_name, e, add_traceback=False)
        except Exception as e:
            # Handle unexpected errors
            return handle_tool_error(coder, tool_name, e)

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        color_start, color_end = color_markers(coder)

        try:
            params = json.loads(tool_response.function.arguments)
        except json.JSONDecodeError:
            coder.io.tool_error("Invalid Tool JSON")

        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        # Group edits by file_path for display
        edits_by_file = {}

        for i, edit in enumerate(params["edits"]):
            edit_file_path = edit.get("file_path")
            if edit_file_path not in edits_by_file:
                edits_by_file[edit_file_path] = []
            edits_by_file[edit_file_path].append((i, edit))

        # Display edits grouped by file
        for file_path_key, file_edits in edits_by_file.items():
            if file_path_key:
                coder.io.tool_output("")
                coder.io.tool_output(f"{color_start}file_path:{color_end}")
                coder.io.tool_output(file_path_key)
                coder.io.tool_output("")

            for edit_index, edit in file_edits:
                # Show diff for this edit using hashline diff
                replace_text = edit.get("replace_text", "")
                start_line = edit.get("start_line")
                end_line = edit.get("end_line")

                # Try to read the file to get original content for diff
                diff_output = ""

                if file_path_key and start_line and end_line:
                    try:
                        # Try to read the file
                        abs_path = coder.abs_root_path(file_path_key)
                        original_content = coder.io.read_text(abs_path)

                        if original_content is not None:
                            # Generate diff using get_hashline_diff
                            diff_output = get_hashline_diff(
                                original_content=strip_hashline(original_content),
                                start_line_hash=start_line,
                                end_line_hash=end_line,
                                operation="replace",
                                text=strip_hashline(replace_text),
                            )
                    except HashlineError as e:
                        # If hashline verification fails, show the error
                        diff_output = f"Hashline verification failed: {str(e)}"
                    except Exception:
                        # If we can't read the file or generate diff, continue without it
                        pass

                # Only show diff section if we have diff output
                if diff_output:
                    if len(params["edits"]) > 1:
                        coder.io.tool_output(f"{color_start}diff_{edit_index + 1}:{color_end}")
                    else:
                        coder.io.tool_output(f"{color_start}diff:{color_end}")

                    coder.io.tool_output(diff_output)
                    coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response)
