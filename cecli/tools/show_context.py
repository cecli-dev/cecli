import json
import os

from cecli.helpers.hashline import hashline, strip_hashline
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import (
    ToolError,
    handle_tool_error,
    is_provided,
    resolve_paths,
)
from cecli.tools.utils.output import color_markers, tool_footer, tool_header


class Tool(BaseTool):
    NORM_NAME = "showcontext"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ShowContext",
            "description": (
                "Get hashline prefixes of context between start and end patterns in multiple files."
                " Accepts an array of show objects, each with file_path, start_text,"
                " end_text, and optional padding. Special markers '@000' and '000@' can be"
                " used for start_text and end_text to represent the first and last lines of"
                " the file respectively. Never use hashlines as the start_text and end_text"
                " values. These values must be lines from the content of the file."
                " They can contain up to 3 lines but newlines should generally be avoided."
                " Avoid using generic keywords."
                " Do not use the same pattern for the start_text and end_text."
                " It is usually best to use function names and other block identifiers as "
                " start_texts and end_texts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "show": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_path": {
                                    "type": "string",
                                    "description": "File path to search in.",
                                },
                                "start_text": {
                                    "type": "string",
                                    "description": (
                                        "The content marking the beginning of the context range."
                                        " Use '@000' for the first line."
                                    ),
                                },
                                "end_text": {
                                    "type": "string",
                                    "description": (
                                        "The content marking the end of the context range. Use"
                                        " '000@' for the last line."
                                    ),
                                },
                                "padding": {
                                    "type": "integer",
                                    "default": 5,
                                    "description": (
                                        "Number of lines of padding to add before start_text and"
                                        " after end_text."
                                    ),
                                },
                            },
                            "required": ["file_path", "start_text", "end_text"],
                        },
                        "description": "Array of show operations to perform.",
                    },
                },
                "required": ["show"],
            },
        },
    }

    @classmethod
    def execute(cls, coder, show, **kwargs):
        """
        Displays numbered lines from multiple files centered around target locations
        (patterns or line_numbers), without adding files to context.
        Accepts an array of show operations to perform.
        Uses utility functions for path resolution and error handling.
        """
        tool_name = "ShowContext"
        already_up_to_date = False

        try:
            # 1. Validate show parameter
            if not isinstance(show, list):
                show = [show] if isinstance(show, dict) else show

            if len(show) == 0:
                raise ToolError("show array cannot be empty")

            all_outputs = []

            for show_index, show_op in enumerate(show):
                # Extract parameters for this show operation
                file_path = show_op.get("file_path")
                start_text = show_op.get("start_text")
                end_text = show_op.get("end_text")
                padding = max(int(show_op.get("padding", 5)), 5)

                if file_path is None:
                    raise ToolError(
                        f"Show operation {show_index + 1} missing required file_path parameter"
                    )

                # Validate arguments for this operation
                if not is_provided(start_text) or not is_provided(end_text):
                    raise ToolError(
                        f"Show operation {show_index + 1}: Provide both 'start_text' and"
                        " 'end_text'."
                    )

                if start_text.count("\n") > 4 or end_text.count("\n") > 4:
                    raise ToolError("Patterns must not contain more than 5 lines.")
                start_text = strip_hashline(start_text).strip()
                end_text = strip_hashline(end_text).strip()

                # 2. Resolve path
                abs_path, rel_path = resolve_paths(coder, file_path)
                if not os.path.exists(abs_path):
                    # Check existence after resolving, as resolve_paths doesn't guarantee existence
                    raise ToolError(f"File not found: {file_path}")

                # 3. Read file content
                content = coder.io.read_text(abs_path)
                if content is None:
                    raise ToolError(f"Could not read file: {file_path}")
                lines = content.splitlines()
                num_lines = len(lines)

                if num_lines == 0:
                    # Handle empty file case
                    output_lines = [f"File {rel_path} is empty."]
                    if show_index > 0:
                        all_outputs.append("")
                    all_outputs.extend(output_lines)
                    continue
                # 4. Determine line range
                start_line_idx = -1
                end_line_idx = -1
                found_by = ""

                if start_text is not None and end_text is not None:
                    if start_text == "@000":
                        start_indices = [0]
                    else:
                        start_pattern_lines = start_text.split("\n")
                        start_indices = []
                        for i in range(len(lines) - len(start_pattern_lines) + 1):
                            if all(
                                p_line in lines[i + j]
                                for j, p_line in enumerate(start_pattern_lines)
                            ):
                                start_indices.append(i)

                    if end_text == "000@":
                        end_indices = [num_lines - 1]
                    else:
                        end_pattern_lines = end_text.split("\n")
                        end_indices = []
                        for i in range(len(lines) - len(end_pattern_lines) + 1):
                            if all(
                                p_line in lines[i + j] for j, p_line in enumerate(end_pattern_lines)
                            ):
                                # For multiline end patterns, we want the index of the LAST line of the match
                                end_indices.append(i + len(end_pattern_lines) - 1)

                    if len(start_indices) > 5:
                        raise ToolError(
                            f"Start pattern '{start_text}' too broad. Do not search for"
                            " it again. Be more specific."
                        )

                    # if len(end_indices) > 5:
                    #     raise ToolError(
                    #         f"End pattern '{end_text}' too broad. Do not search for it"
                    #         " again. Be more specific."
                    #     )

                    best_pair = None
                    min_dist = float("inf")

                    for s in start_indices:
                        for e in [idx for idx in end_indices if idx >= s]:
                            dist = e - s
                            if dist < min_dist:
                                min_dist = dist
                                best_pair = (s, e)

                    if not start_indices:
                        raise ToolError(
                            f"Start pattern '{start_text}' not found in {file_path}. Do not search"
                            " for it again."
                        )

                    if not end_indices:
                        raise ToolError(
                            f"End pattern '{end_text}' not found in {file_path}. Do not search for"
                            " it again."
                        )

                    if best_pair is None:
                        raise ToolError(
                            f"End pattern '{end_text}' not found after start pattern in"
                            f" {file_path}."
                        )
                    s_idx, e_idx = best_pair

                    found_by = f"range '{start_text}' to '{end_text}'"

                    try:
                        padding_int = int(padding)
                        if padding_int < 0:
                            raise ValueError()
                    except ValueError:
                        coder.io.tool_warning(f"Invalid padding '{padding}', using default 5.")
                        padding_int = 5

                    start_line_idx = max(0, s_idx - padding_int)
                    end_line_idx = min(num_lines - 1, e_idx + padding_int)

                if start_line_idx == -1 or end_line_idx == -1:
                    raise ToolError("Internal error: Could not determine line range.")
                # 6. Format output for this operation
                # Use rel_path for user-facing messages
                output_lines = [f"Displaying context around {found_by} in {rel_path}:"]

                # Generate hashline for the entire file
                hashed_content = hashline(content)
                hashed_lines = hashed_content.splitlines()

                # Extract the context window from hashed lines
                context_hashed_lines = hashed_lines[start_line_idx : end_line_idx + 1]

                for i in range(start_line_idx, end_line_idx + 1):
                    hashed_line = context_hashed_lines[i - start_line_idx]
                    output_lines.append(hashed_line)

                # Add separator between multiple show operations
                if show_index > 0:
                    all_outputs.append("")
                all_outputs.extend(output_lines)

                # Update the conversation cache with the displayed range
                from cecli.helpers.conversation import ConversationService

                # Update the conversation cache with the displayed range
                # Note: start_line_idx and end_line_idx are 0-based, convert to 1-based for hashline
                start_line = start_line_idx + 1  # Convert to 1-based
                end_line = end_line_idx + 1  # Convert to 1-based

                original_context_content = ConversationService.get_files(coder).get_file_context(
                    abs_path
                )
                ConversationService.get_files(coder).update_file_context(
                    abs_path, start_line, end_line, auto_remove=False
                )
                new_context_content = ConversationService.get_files(coder).get_file_context(
                    abs_path
                )

                if original_context_content and original_context_content == new_context_content:
                    already_up_to_date = True
                else:
                    ConversationService.get_files(coder).remove_file_messages(abs_path)
                ConversationService.get_chunks(coder).add_file_context_messages()

            # Log success and return the formatted context directly
            coder.edit_allowed = True

            if already_up_to_date:
                coder.io.tool_output("File contents already up to date")
                return (
                    "File contents already up to date. Please proceed with your task. "
                    "Do not call ShowContext again until you edit the file."
                )
            else:
                coder.io.tool_output(f"✅ Successfully retrieved context for {len(show)} file(s)")
                return f"Successfully retrieved most recent contents for {len(show)} file(s)"

        except ToolError as e:
            # Handle expected errors raised by utility functions or validation
            return handle_tool_error(coder, tool_name, e, add_traceback=False)
        except Exception as e:
            # Handle unexpected errors during processing
            return handle_tool_error(coder, tool_name, e)

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for ShowContext tool."""
        color_start, color_end = color_markers(coder)

        try:
            params = json.loads(tool_response.function.arguments)
        except json.JSONDecodeError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        show_ops = params.get("show", [])
        if show_ops:
            coder.io.tool_output("")
            for i, show_op in enumerate(show_ops):
                file_path = show_op.get("file_path", "")
                start_text = strip_hashline(show_op.get("start_text", "")).strip()
                end_text = strip_hashline(show_op.get("end_text", "")).strip()
                padding = show_op.get("padding", 5)

                # Format as "show: • file_path • start_text • end_text • padding"
                formatted_query = (
                    f"{color_start}range_{i + 1}:{color_end} {file_path} • {start_text} •"
                    f" {end_text} • {padding}"
                )
                coder.io.tool_output(formatted_query)
            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response)

    @classmethod
    def on_duplicate_request(cls, coder, **kwargs):
        coder.edit_allowed = True
