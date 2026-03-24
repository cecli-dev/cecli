import os

from cecli.helpers.hashline import hashline, strip_hashline
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import (
    ToolError,
    handle_tool_error,
    is_provided,
    resolve_paths,
)


class Tool(BaseTool):
    NORM_NAME = "showcontext"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ShowContext",
            "description": (
                "Get hashline prefixes of context between start and end patterns in multiple files."
                " Accepts an array of show objects, each with file_path, start_pattern,"
                " end_pattern, and optional padding. Special markers '<@000>' and '<000@>' can be"
                " used for start_pattern and end_pattern to represent the first and last lines of"
                " the file respectively. Never use hashlines as the start_pattern and end_pattern"
                " values. These values must be lines from the content of the file."
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
                                "start_pattern": {
                                    "type": "string",
                                    "description": (
                                        "The content marking the beginning of the context range."
                                        " Use '<@000>' for the first line."
                                    ),
                                },
                                "end_pattern": {
                                    "type": "string",
                                    "description": (
                                        "The contentmarking the end of the context range. Use"
                                        " '<000@>' for the last line."
                                    ),
                                },
                                "padding": {
                                    "type": "integer",
                                    "default": 5,
                                    "description": (
                                        "Number of lines of padding to add before start_pattern and"
                                        " after end_pattern."
                                    ),
                                },
                            },
                            "required": ["file_path", "start_pattern", "end_pattern"],
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
        tool_name = "showcontext"
        try:
            # 1. Validate show parameter
            if not isinstance(show, list):
                raise ToolError("show parameter must be an array")

            if len(show) == 0:
                raise ToolError("show array cannot be empty")

            all_outputs = []

            for show_index, show_op in enumerate(show):
                # Extract parameters for this show operation
                file_path = show_op.get("file_path")
                start_pattern = show_op.get("start_pattern")
                end_pattern = show_op.get("end_pattern")
                padding = show_op.get("padding", 5)

                if file_path is None:
                    raise ToolError(
                        f"Show operation {show_index + 1} missing required file_path parameter"
                    )

                # Validate arguments for this operation
                if not is_provided(start_pattern) or not is_provided(end_pattern):
                    raise ToolError(
                        f"Show operation {show_index + 1}: Provide both 'start_pattern' and"
                        " 'end_pattern'."
                    )

                start_pattern = strip_hashline(start_pattern)
                end_pattern = strip_hashline(end_pattern)

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

                if start_pattern is not None and end_pattern is not None:
                    if start_pattern == "<@000>":
                        start_indices = [0]
                    else:
                        start_indices = [i for i, line in enumerate(lines) if start_pattern in line]

                    if end_pattern == "<000@>":
                        end_indices = [num_lines - 1]
                    else:
                        end_indices = [i for i, line in enumerate(lines) if end_pattern in line]

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
                            f"Start pattern '{start_pattern}' not found in {file_path}."
                        )
                    if not end_indices:
                        raise ToolError(f"End pattern '{end_pattern}' not found in {file_path}.")
                    if best_pair is None:
                        raise ToolError(
                            f"End pattern '{end_pattern}' not found after start pattern in"
                            f" {file_path}."
                        )
                    s_idx, e_idx = best_pair

                    found_by = f"range '{start_pattern}' to '{end_pattern}'"

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
                from cecli.helpers.conversation.files import ConversationFiles
                from cecli.helpers.conversation.integration import ConversationChunks

                # Update the conversation cache with the displayed range
                # Note: start_line_idx and end_line_idx are 0-based, convert to 1-based for hashline
                start_line = start_line_idx + 1  # Convert to 1-based
                end_line = end_line_idx + 1  # Convert to 1-based
                ConversationFiles.update_file_context(abs_path, start_line, end_line)
                ConversationChunks.add_file_context_messages(coder)

            # Log success and return the formatted context directly
            coder.edit_allowed = True
            coder.io.tool_output(f"Successfully retrieved context for {len(show)} file(s)")
            return f"Successfully retrieved most recent context for {len(show)} file(s)"

        except ToolError as e:
            # Handle expected errors raised by utility functions or validation
            return handle_tool_error(coder, tool_name, e, add_traceback=False)
        except Exception as e:
            # Handle unexpected errors during processing
            return handle_tool_error(coder, tool_name, e)
