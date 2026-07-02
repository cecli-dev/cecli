import json
import os
from typing import Dict, List

from cecli.helpers.hashline import hashline_formatted, strip_hashline
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import (
    ToolError,
    handle_tool_error,
    is_provided,
    resolve_paths,
)
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "readrange"
    TRACK_INVOCATIONS = False
    VALIDATIONS = {
        "read": ["coerce_list"],
        "read[]": ["coerce_dict"],
        "read[].range_start": ["coerce_str"],
        "read[].range_end": ["coerce_str"],
    }
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ReadRange",
            "description": (
                "Get content ID prefixed content between start and end markers in files."
                " This is useful for files you are attempting to edit and for understanding their structure."
                " Accepts an array of `read` objects, each with file_path, range_start, range_end."
                " They can contain up to 3 lines of content. Avoid using singular generic keywords and"
                " symbols. Special markers @000 and 000@ represent the file boundaries and can be"
                " used for range_start and range_end for the first and last lines of the file"
                " respectively. Line numbers may also be used for range lookups."
                " It is best to use function names, variable declarations, entire line contents"
                " and other meaningful identifiers as range_start and range_end values."
                " Do not use the same pattern for the range_start and range_end."
                " Do not use empty strings for the range_start and range_end."
                " Do not use content IDs for the range_start and range_end values as they change between edits."
                " Always use the ReadRange tool instead of cli tools for reading file contents."
                " Line number and special marker ranges greater than 200 lines will return"
                " preview content for further, more scoped investigation."
                " Call this tool sequentially on increasingly finer grained searches "
                " to help with understanding important structural features in large files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "read": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_path": {
                                    "type": "string",
                                    "description": "File path to search in.",
                                },
                                "range_start": {
                                    "type": "string",
                                    "description": (
                                        "The text marking the beginning of the range."
                                        " Use '@000' for the first line on empty files."
                                    ),
                                },
                                "range_end": {
                                    "type": "string",
                                    "description": (
                                        "The text marking the end of the range."
                                        " Use '000@' for the last line on empty files."
                                    ),
                                },
                            },
                            "required": ["file_path", "range_start", "range_end"],
                        },
                        "description": "Array of read operations to perform.",
                    },
                },
                "required": ["read"],
            },
        },
    }

    _last_invocation = {}  # file_path -> {start_idx, end_idx}
    _last_read_turn: Dict[str, int] = {}  # abs_path -> turn_count when last read
    _special_marker_count: Dict[str, int] = {}  # abs_path -> count of both-special-marker reads

    @classmethod
    def execute(cls, coder, read, **kwargs):
        """
        Displays numbered lines from multiple files centered around target locations
        (patterns or line_numbers), without adding files to context.
        Accepts an array of read operations to perform.
        Uses utility functions for path resolution and error handling.
        """
        from cecli.helpers.conversation import ConversationService

        tool_name = "ReadRange"
        already_up_to_date = []
        new_context_retrieved = []
        error_outputs = []

        try:
            # 1. Validate read parameter
            if not isinstance(read, list):
                read = [read] if isinstance(read, dict) else read

            if len(read) == 0:
                raise ToolError("read array cannot be empty")

            all_outputs = []
            already_up_to_details = []
            new_context_details = []
            all_outputs_set = set()
            new_context_set = set()
            already_up_to_set = set()
            ranges = {}

            for read_index, read_op in enumerate(read):
                # Extract parameters for this read operation
                file_path = read_op.get("file_path")
                range_start = read_op.get("range_start")
                range_end = read_op.get("range_end")
                padding = 5

                if file_path is None:
                    error_outputs.append(
                        cls.format_error(
                            coder,
                            f"read operation {read_index + 1} missing required file_path parameter",
                            None,
                            None,
                            None,
                            read_index,
                        )
                    )
                    continue

                # Validate arguments for this operation
                if not is_provided(range_start) or not is_provided(range_end):
                    # Auto-fallback: if the file is in editable context and markers are
                    # missing/junk, show the whole file instead of erroring.
                    abs_fnames = getattr(coder, "abs_fnames", set())
                    abs_ro = getattr(coder, "abs_read_only_fnames", set())
                    try:
                        abs_path_check = coder.abs_root_path(file_path) if file_path else None
                    except Exception:
                        abs_path_check = None
                    if abs_path_check and (
                        abs_path_check in abs_fnames or abs_path_check in abs_ro
                    ):
                        range_start = "@000"
                        range_end = "000@"
                    else:
                        error_outputs.append(
                            cls.format_error(
                                coder,
                                (
                                    f"read operation {read_index + 1}: Provide both 'range_start' and"
                                    " 'range_end'."
                                ),
                                file_path,
                                range_start,
                                range_end,
                                read_index,
                            )
                        )
                        continue

                # Models sometimes pass line numbers as int; coerce before str ops.
                range_start = str(range_start)
                range_end = str(range_end)

                if range_start.count("\n") > 4 or range_end.count("\n") > 4:
                    error_outputs.append(
                        cls.format_error(
                            coder,
                            "Patterns must not contain more than 5 lines.",
                            file_path,
                            range_start,
                            range_end,
                            read_index,
                        )
                    )
                    continue

                range_start = strip_hashline(range_start).strip()
                range_end = strip_hashline(range_end).strip()

                # 2. Resolve path
                abs_path, rel_path = resolve_paths(coder, file_path)
                if not os.path.exists(abs_path):
                    # Check existence after resolving, as resolve_paths doesn't guarantee existence
                    error_outputs.append(
                        cls.format_error(
                            coder,
                            f"File not found: {file_path}",
                            file_path,
                            range_start,
                            range_end,
                            read_index,
                        )
                    )
                    continue

                # 3. Read file content
                content: str = coder.io.read_text(abs_path)

                if content is None:
                    error_outputs.append(
                        cls.format_error(
                            coder,
                            f"Could not read file: {file_path}",
                            file_path,
                            range_start,
                            range_end,
                            read_index,
                        )
                    )
                    continue

                lines = content.splitlines()
                num_lines = len(lines)

                if num_lines == 0:
                    new_context_details.append(
                        "\n".join(
                            [
                                f"File {rel_path} is empty.",
                                (
                                    "Next: use EditText with start_line @000 and end_line @000 to"
                                    " write content, or ResourceManager to scaffold — do not call"
                                    " ReadRange again on this empty file."
                                ),
                            ]
                        )
                    )
                    new_context_retrieved.append(rel_path)
                    cls._last_read_turn[abs_path] = coder.turn_count
                    continue
                # 4. Determine line range
                start_line_idx = -1
                end_line_idx = -1
                both_structured = False
                # found_by = ""

                if range_start is not None and range_end is not None:

                    def _is_valid_int(s):
                        try:
                            int(s)
                            return True
                        except ValueError:
                            return False

                    start_is_digit = _is_valid_int(range_start)
                    end_is_digit = _is_valid_int(range_end)
                    start_is_special = range_start in ("@000", "000@")
                    end_is_special = range_end in ("@000", "000@")
                    both_structured = (start_is_digit or start_is_special) and (
                        end_is_digit or end_is_special
                    )
                    start_is_text = not start_is_digit and not start_is_special
                    end_is_text = not end_is_digit and not end_is_special
                    mixed_special_search = (start_is_special and end_is_text) or (
                        end_is_special and start_is_text
                    )
                    start_indices = []
                    end_indices = []

                    if both_structured:
                        if start_is_digit:
                            start_line_num = int(range_start) - 1
                            start_line_num = max(0, min(start_line_num, num_lines - 1))
                            start_indices = [start_line_num]
                        else:
                            start_indices = [0]

                        if end_is_digit:
                            end_line_num = int(range_end) - 1
                            end_line_num = max(0, min(end_line_num, num_lines - 1))
                            end_indices = [end_line_num]
                        else:
                            end_indices = [num_lines - 1]

                    elif mixed_special_search:
                        if start_is_special:
                            # Start is special marker, end is text pattern
                            if range_start == "@000":
                                start_indices = [0]
                            else:  # 000@
                                start_indices = [num_lines - 1]
                            # Search for end pattern as text
                            end_pattern_lines = range_end.split("\n")
                            end_indices = []
                            for i in range(len(lines) - len(end_pattern_lines) + 1):
                                if all(
                                    p_line in lines[i + j]
                                    for j, p_line in enumerate(end_pattern_lines)
                                ):
                                    end_indices.append(i + len(end_pattern_lines) - 1)
                        else:
                            # Start is text pattern, end is special marker
                            start_pattern_lines = range_start.split("\n")
                            start_indices = []
                            for i in range(len(lines) - len(start_pattern_lines) + 1):
                                if all(
                                    p_line in lines[i + j]
                                    for j, p_line in enumerate(start_pattern_lines)
                                ):
                                    start_indices.append(i)
                            if range_end == "@000":
                                end_indices = [0]
                            else:  # 000@
                                end_indices = [num_lines - 1]
                    else:
                        start_pattern_lines = range_start.split("\n")
                        start_indices = []
                        for i in range(len(lines) - len(start_pattern_lines) + 1):
                            if all(
                                p_line in lines[i + j]
                                for j, p_line in enumerate(start_pattern_lines)
                            ):
                                start_indices.append(i)

                        end_pattern_lines = range_end.split("\n")
                        end_indices = []
                        for i in range(len(lines) - len(end_pattern_lines) + 1):
                            if all(
                                p_line in lines[i + j] for j, p_line in enumerate(end_pattern_lines)
                            ):
                                # For multiline end patterns, we want the index of the LAST line of the match
                                end_indices.append(i + len(end_pattern_lines) - 1)

                    if len(start_indices) > 5:
                        # Too many matches - use _last_invocation to disambiguate
                        last = cls._last_invocation.get(abs_path)
                        if last is None:
                            error_outputs.append(
                                cls.format_error(
                                    coder,
                                    (
                                        f"Start pattern '{range_start}' too broad."
                                        " Refine your search. Be more specific."
                                    ),
                                    file_path,
                                    range_start,
                                    range_end,
                                    read_index,
                                )
                            )
                            continue

                        # Find the best match: smallest sum of absolute distances to last start/end
                        # that comes after the range, with tie-breaking by smallest sum
                        last_s, last_e = last["start_idx"], last["end_idx"]
                        candidates = []
                        for s in start_indices:
                            for e in [idx for idx in end_indices if idx >= s]:
                                dist_sum = abs(s - last_s) + abs(e - last_e)
                                candidates.append((dist_sum, s, e))
                        # Sort by distance sum, then prefer ranges after the last range
                        candidates.sort(key=lambda x: (x[0], x[1] < last_s, x[1], x[2]))
                        if candidates:
                            best_pair = (candidates[0][1], candidates[0][2])
                        else:
                            best_pair = None
                    else:
                        best_pair = None
                        min_dist = float("inf")

                        for s in start_indices:
                            for e in [idx for idx in end_indices if idx >= s]:
                                dist = e - s
                                if dist < min_dist:
                                    min_dist = dist
                                    best_pair = (s, e)

                        # If no valid pair found and one side has exactly one match,
                        # try inverted matching in case LLM got the order of methods wrong
                        if best_pair is None and (len(start_indices) == 1 or len(end_indices) == 1):
                            for s in start_indices:
                                for e in end_indices:
                                    if e < s:  # end pattern match is before start pattern match
                                        dist = s - e
                                        if dist < min_dist:
                                            min_dist = dist
                                            best_pair = (e, s)

                        if not start_indices:
                            error_outputs.append(
                                cls.format_error(
                                    coder,
                                    (
                                        f"Start pattern '{range_start}' not found in {file_path}."
                                        " Refine your search."
                                    ),
                                    file_path,
                                    range_start,
                                    range_end,
                                    read_index,
                                )
                            )
                            continue

                        if not end_indices:
                            error_outputs.append(
                                cls.format_error(
                                    coder,
                                    (
                                        f"End pattern '{range_end}' not found in {file_path}."
                                        " Refine your search."
                                    ),
                                    file_path,
                                    range_start,
                                    range_end,
                                    read_index,
                                )
                            )
                            continue

                        if best_pair is None:
                            error_outputs.append(
                                cls.format_error(
                                    coder,
                                    (
                                        f"End pattern '{range_end}' not found after start pattern in"
                                        f" {file_path}."
                                    ),
                                    file_path,
                                    range_start,
                                    range_end,
                                    read_index,
                                )
                            )
                            continue

                    if best_pair is None:
                        error_outputs.append(
                            cls.format_error(
                                coder,
                                (
                                    f"End pattern '{range_end}' not found after start pattern in"
                                    f" {file_path}."
                                ),
                                file_path,
                                range_start,
                                range_end,
                                read_index,
                            )
                        )
                        continue

                    s_idx, e_idx = best_pair
                    s_idx, e_idx = cls._extend_range_with_stub(
                        coder, abs_path, s_idx, e_idx, num_lines
                    )

                # Store the found indices for future disambiguation
                cls._last_invocation[abs_path] = {"start_idx": s_idx, "end_idx": e_idx}

                # For structured searches (line numbers, special markers) or mixed searches
                # (one special marker, one text pattern), cap large ranges with preview
                # Text pattern searches are not subject to capping
                sliced_contents = "\n".join(content.splitlines()[s_idx:e_idx])
                token_count = coder.main_model.token_count(content)
                sliced_token_count = coder.main_model.token_count(sliced_contents)
                is_small_file = token_count <= min(coder.large_file_token_threshold / 4, 2048)
                is_small_range = sliced_token_count <= min(
                    coder.large_file_token_threshold / 8, 1024
                )
                if (
                    both_structured or (mixed_special_search and is_small_file)
                ) and not is_small_range:

                    preview, has_stub = cls._get_range_preview(
                        coder, abs_path, start_idx=s_idx, end_idx=e_idx, line_numbers=True
                    )

                    if abs_path not in coder.abs_fnames:
                        # Track special marker usage for auto-editable detection
                        if token_count <= coder.large_file_token_threshold:
                            cls._special_marker_count[abs_path] = (
                                cls._special_marker_count.get(abs_path, 0) + 1
                            )
                            if cls._special_marker_count[abs_path] > 1:
                                coder.abs_fnames.add(abs_path)
                                preview = f"Full contents of {rel_path} will be added to context in future message."
                                if abs_path in coder.abs_read_only_fnames:
                                    coder.abs_read_only_fnames.remove(abs_path)

                    if preview not in all_outputs_set:
                        all_outputs_set.add(preview)
                        if len(all_outputs):
                            all_outputs.append("")
                        all_outputs.append(preview)

                    continue

                # found_by = f"range '{range_start}' to '{range_end}'"

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
                    error_outputs.append(
                        cls.format_error(
                            coder,
                            "Internal error: Could not determine line range.",
                            file_path,
                            range_start,
                            range_end,
                            read_index,
                        )
                    )
                    continue

                # 6. Format output for this operation
                # Use rel_path for user-facing messages
                # output_lines = [f"Displaying context around {found_by} in {rel_path}:"]

                # Generate hashline for the entire file
                hashed_content, _ = hashline_formatted(
                    content, file_name=abs_path, partial=False, expanded=False
                )
                hashed_lines = hashed_content.splitlines()

                # Extract the context window from hashed lines
                # context_hashed_lines = hashed_lines[start_line_idx : end_line_idx + 1]

                # for i in range(start_line_idx, end_line_idx + 1):
                #    hashed_line = context_hashed_lines[i - start_line_idx]
                #    output_lines.append(hashed_line)

                # Add separator between multiple read operations
                # if read_index > 0:
                #     all_outputs.append("")
                # all_outputs.extend(output_lines)

                # Update the conversation cache with the displayed range
                # Note: start_line_idx and end_line_idx are 0-based, convert to 1-based for hashline
                start_line = start_line_idx + 1  # Convert to 1-based
                end_line = end_line_idx + 1  # Convert to 1-based

                original_context_content = ConversationService.get_files(coder).get_file_context(
                    abs_path,
                    all_ranges=True,
                    check_versions=False,
                )
                update_tuple = ConversationService.get_files(coder).update_file_context(
                    abs_path, start_line, end_line, auto_remove=False
                )
                new_context_content = ConversationService.get_files(coder).get_file_context(
                    abs_path,
                    all_ranges=True,
                    check_versions=False,
                )

                is_already_up_to_date = False
                add_to_ranges = False
                # last_turn = cls._last_read_turn.get(abs_path)

                if original_context_content and original_context_content == new_context_content:
                    already_up_to_date.append(rel_path)
                    is_already_up_to_date = True

                    # if last_turn is None or coder.turn_count - last_turn < 3 and already_up_to_date:
                    #    add_to_ranges = True
                else:
                    add_to_ranges = True

                if add_to_ranges:
                    if not ranges.get(abs_path, None):
                        ranges[abs_path] = []

                    ranges[abs_path].append(update_tuple)

                    if not is_already_up_to_date:
                        new_context_retrieved.append(rel_path)

                # Collect hashline info for response
                if (
                    s_idx >= 0
                    and s_idx < len(hashed_lines)
                    and e_idx >= 0
                    and e_idx < len(hashed_lines)
                ):
                    # hashed_slice = hashed_lines[s_idx : e_idx + 1]
                    model_response = cls.format_model_response(
                        coder, rel_path, s_idx, e_idx, hashed_lines, current=is_already_up_to_date
                    )

                    if is_already_up_to_date:
                        if model_response not in already_up_to_set:
                            already_up_to_set.add(model_response)
                            already_up_to_details.append(model_response)
                    else:
                        if model_response not in new_context_set:
                            new_context_set.add(model_response)
                            new_context_details.append(model_response)

                # Conditionally remove old file context messages
                # If the file was last read >= 3 turns ago, keep old messages (allow coexistence)
                # Otherwise, remove them to avoid duplicates

                # last_turn = cls._last_read_turn.get(abs_path)
                # if last_turn is None or coder.turn_count - last_turn < 3 and already_up_to_date:
                #    ConversationService.get_files(coder).remove_file_messages(abs_path)

                # Update the last read turn for this file
                cls._last_read_turn[abs_path] = coder.turn_count

            for abs_path, tuples in ranges.items():
                ConversationService.get_files(coder).clear_ranges(abs_path)
                ConversationService.get_files(coder).push_range(abs_path, tuples)

            ConversationService.get_chunks(coder).add_file_context_messages()

            # if (
            #    ConversationService.get_chunks(coder).last_clear_count > 20
            #    and coder.context_compaction_current_ratio > 0.8
            # ):
            #    cls.clear_old_messages(coder)

            # Log success and return the formatted context directly
            coder.edit_allowed = True

            result_parts = [f"File Context Turn {coder.turn_count}"]

            if already_up_to_details or new_context_details:
                if new_context_details:
                    coder.io.tool_output(
                        f"✓ Retrieved context for {len(new_context_details)} operation(s)",
                        type="tool-result",
                    )

                    detail_str = "\n".join(new_context_details)
                    result_parts.append(
                        f"Retrieved context for {len(new_context_details)} operation(s):\n\n"
                        f"{detail_str}\n"
                        "Full results for these reads will be given in a follow up message.\n"
                    )
                if already_up_to_details:
                    coder.io.tool_output(
                        (
                            "Earlier contents still valid for"
                            f" {len(already_up_to_details)} operation(s)"
                        ),
                        type="tool-result",
                    )

                    detail_str = "\n".join(already_up_to_details)
                    result_parts.append(
                        "Earlier contents still valid from previous read for "
                        f"{len(already_up_to_details)} operation(s):\n\n"
                        f"{detail_str}\n"
                        "Relevant contents for these reads available in previous message."
                    )
                if already_up_to_date and not new_context_retrieved:
                    result_parts.append(
                        "Do not call `ReadRange` again with these parameters again unless you edit"
                        " the relevant files."
                    )

            if all_outputs:
                result_parts.append("\n".join(all_outputs))
                result_parts.append("\nUse these outlines to refine your search.\n")

            if error_outputs:
                coder.io.tool_error(
                    f"Errors encountered for {len(error_outputs)} operation(s)", type="tool-result"
                )

                result_parts.append("Errors:\n" + "\n".join(error_outputs))

            if not result_parts:
                return "No files could be processed."

            return "\n---\n".join(result_parts)

        except ToolError as e:
            # Handle expected errors raised by utility functions or validation
            return handle_tool_error(coder, tool_name, e, add_traceback=False)
        except Exception as e:
            # Handle unexpected errors during processing
            return handle_tool_error(coder, tool_name, e)

    @classmethod
    def format_model_response(cls, coder, rel_path, s_idx, e_idx, hashed_lines, current=False):
        """Format a file's context range as hash-prefixed lines for the model."""
        # Read file content for stub lookups
        try:
            from cecli.tools.utils.helpers import resolve_paths

            abs_path, _ = resolve_paths(coder, rel_path)
            last_turn = cls._last_read_turn[abs_path] or 0
        except Exception:
            pass

        # Try to return structural stub information instead of raw hashed lines
        try:
            if hashed_lines and current and coder.turn_count - last_turn <= 2:
                num_lines = len(hashed_lines)

                start_stub_s, start_stub_e = cls._extend_range_with_stub(
                    coder, abs_path, s_idx, s_idx, num_lines
                )
                end_stub_s, end_stub_e = cls._extend_range_with_stub(
                    coder, abs_path, e_idx, e_idx, num_lines
                )

                # start_stub_s, start_stub_e = cls._reposition_indices(s_idx, start_stub_s, start_stub_e)
                # end_stub_s, end_stub_e = cls._reposition_indices(e_idx, end_stub_s, end_stub_e)

                start_found = start_stub_s != s_idx or start_stub_e != s_idx
                end_found = end_stub_s != e_idx or end_stub_e != e_idx

                if end_stub_s != start_stub_s or end_stub_e != start_stub_e:
                    start_stub_s = end_stub_s
                    start_stub_e = end_stub_e
                    start_found = True
                    end_found = False

                if start_found or end_found:
                    snapshot_parts = []
                    if start_found:
                        snapshot_parts.extend(hashed_lines[start_stub_s:start_stub_e])

                    has_second_range = (
                        end_found
                        and start_stub_s != end_stub_s
                        and start_stub_e != end_stub_e
                        and end_stub_e != e_idx
                    )
                    if has_second_range:
                        snapshot_parts.append("...⋮...\n")
                        snapshot_parts.extend(hashed_lines[end_stub_s:end_stub_e])

                    prefixed = "".join(snapshot_parts)
                    result = {
                        "file_path": rel_path,
                        "start_line": start_stub_s + 1,
                        "end_line": end_stub_e if has_second_range else start_stub_e,
                        "partial": True,
                        "expanded": True,
                        "prefixed_contents": prefixed,
                    }
                    return json.dumps(result, ensure_ascii=False)
        except Exception:
            pass

        hashed_content = "\n".join(hashed_lines[s_idx : e_idx + 1])
        token_count = coder.main_model.token_count(hashed_content)

        if token_count <= min(coder.large_file_token_threshold / 16, 512):
            prefixed = hashed_content
        else:
            total = e_idx - s_idx
            if total <= 15:
                prefixed = hashed_content
            else:
                prefixed = cls.content_splitter(coder, hashed_lines, s_idx, e_idx)

        result = {
            "file_path": rel_path,
            "start_line": s_idx + 1,
            "end_line": e_idx + 1,
            "partial": True,
            "expanded": False,
            "prefixed_contents": prefixed,
        }
        return json.dumps(result, ensure_ascii=False)

    @classmethod
    def content_splitter(cls, coder, hashed_lines, s_idx, e_idx):
        """Edges in, middle out: progressively selects lines from edges
        inward and middle outward, tracking token budget until exhausted.

        Returns a string with hashed lines joined by newlines, with
        "...⋮..." separators between non-contiguous groups.
        """
        total_lines = e_idx - s_idx + 1
        max_tokens = min(coder.large_file_token_threshold / 16, 512)

        selected = set()

        # Round 0: first 2 lines
        selected.add(s_idx)
        if s_idx + 1 <= e_idx:
            selected.add(s_idx + 1)

        # Round 0: middle 1 or 2 lines
        if total_lines % 2 == 1:  # odd
            mid_start = s_idx + total_lines // 2
            selected.add(mid_start)
            mid_end = mid_start
        else:  # even
            mid_start = s_idx + total_lines // 2 - 1
            mid_end = s_idx + total_lines // 2
            selected.add(mid_start)
            selected.add(mid_end)

        # Round 0: last 2 lines
        if e_idx - 1 >= s_idx:
            selected.add(e_idx - 1)
        selected.add(e_idx)

        round_num = 1
        while True:
            next_selected = selected.copy()

            # Add 2 lines to the top
            new_top_1 = s_idx + 2 * round_num
            if new_top_1 <= e_idx:
                next_selected.add(new_top_1)
            new_top_2 = s_idx + 2 * round_num + 1
            if new_top_2 <= e_idx:
                next_selected.add(new_top_2)

            # Add 1 line on either end of the middle
            left_mid = mid_start - round_num
            if left_mid >= s_idx:
                next_selected.add(left_mid)
            right_mid = mid_end + round_num
            if right_mid <= e_idx:
                next_selected.add(right_mid)

            # Add 2 lines before the bottom
            new_bottom_1 = e_idx - 1 - 2 * round_num
            if new_bottom_1 >= s_idx:
                next_selected.add(new_bottom_1)
            new_bottom_2 = e_idx - 2 * round_num
            if new_bottom_2 >= s_idx:
                next_selected.add(new_bottom_2)

            # Check token count
            sorted_indices = sorted(next_selected)
            candidate_lines = [hashed_lines[i] for i in sorted_indices]
            candidate_content = "\n".join(candidate_lines)
            candidate_tokens = coder.main_model.token_count(candidate_content)

            if candidate_tokens > max_tokens:
                break

            selected = next_selected
            round_num += 1

            if len(selected) == total_lines:
                break

        # Build output with "...⋮..." between non-contiguous ranges
        sorted_indices = sorted(selected)
        output_parts = []
        current_chunk = [sorted_indices[0]]

        for i in range(1, len(sorted_indices)):
            if sorted_indices[i] == sorted_indices[i - 1] + 1:
                current_chunk.append(sorted_indices[i])
            else:
                output_parts.append(current_chunk)
                current_chunk = [sorted_indices[i]]
        output_parts.append(current_chunk)

        output_lines = []
        for chunk_idx, chunk in enumerate(output_parts):
            if chunk_idx > 0:
                output_lines.append("...⋮...")
            for idx in chunk:
                output_lines.append(hashed_lines[idx])

        return "\n".join(output_lines)

    @classmethod
    def _reposition_indices(
        cls, target_idx: int, start_idx: int, end_idx: int, total_lines: int = 20
    ) -> tuple:
        """
        Calculates the clamped start and end indices for a centered window.
        Returns a tuple of (slice_start, slice_end) compatible with python slicing.
        """
        # 1. Calculate ideal half-window size
        half_window = total_lines // 2

        # 2. Calculate initial left/right bounds
        left = target_idx - half_window
        right = target_idx + half_window

        # 3. Slide the window if it overflows boundaries
        if left < start_idx:
            right += start_idx - left
            left = start_idx

        if right > end_idx:
            left -= right - end_idx
            right = end_idx

        # 4. Final safety clamp in case the range itself is smaller than total_lines
        left = max(start_idx, left)

        # Return right + 1 so it's ready-to-use for standard Python slicing [start:end]
        return left, right + 1

    @classmethod
    def clear_old_messages(cls, coder):
        from cecli.helpers.conversation import ConversationService, MessageTag

        # Clean up stale file_context messages
        # If a file has 5 or more file_context_user messages, remove all but the most recent
        # (and their corresponding assistant messages) to prevent excessive stale context
        file_context_messages = ConversationService.get_manager(coder).get_tag_messages(
            MessageTag.FILE_CONTEXTS
        )
        # Only process the latest 3rd of messages to leave older context alone
        breakpoint = len(file_context_messages) * 2 // 3
        file_context_messages = file_context_messages[breakpoint:]

        # Group user file_context messages by file path
        user_msgs_by_file: Dict[str, List[int]] = {}
        user_msg_indices: List[int] = []
        for msg_idx, msg in enumerate(file_context_messages):
            if msg.hash_key and len(msg.hash_key) == 3 and msg.hash_key[0] == "file_context_user":
                file_path = msg.hash_key[1]
                if file_path not in user_msgs_by_file:
                    user_msgs_by_file[file_path] = []
                user_msgs_by_file[file_path].append(msg_idx)
                user_msg_indices.append(msg_idx)

        # If any file has 5+ user messages, shave all files to latest single context message
        # This prevents repeated cleanup cycles from staggered message accumulation
        hash_keys_to_remove: set = set()
        has_overflow = any(len(indices) >= 5 for indices in user_msgs_by_file.values())

        if has_overflow:
            for file_path, indices in user_msgs_by_file.items():
                # Keep only the latest message for each file
                older_indices = indices[:-1]
                for old_idx in older_indices:
                    old_msg = file_context_messages[old_idx]
                    content_hash = old_msg.hash_key[2]
                    # Mark the user message for removal
                    hash_keys_to_remove.add(("file_context_user", file_path, content_hash))
                    # Mark the corresponding assistant message for removal
                    hash_keys_to_remove.add(("file_context_assistant", file_path, content_hash))

        if hash_keys_to_remove:
            ConversationService.get_manager(coder).remove_messages_by_hash_key_pattern(
                lambda hash_key: hash_key in hash_keys_to_remove
            )

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for ReadRange tool."""
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

        read_ops = params.get("read", [])
        if read_ops:
            coder.io.tool_output("")
            for i, read_op in enumerate(read_ops):
                file_path = read_op.get("file_path", "")
                range_start = strip_hashline(read_op.get("range_start", "")).strip()
                range_end = strip_hashline(read_op.get("range_end", "")).strip()

                # Format as "read: • file_path • range_start • range_end • padding"
                formatted_query = (
                    f"{color_start}range_{i + 1}:{color_end} {file_path} • {range_start} •"
                    f" {range_end}"
                )
                coder.io.tool_output(formatted_query)
            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)

    @classmethod
    def format_error(cls, coder, error_text, file_path, range_start, range_end, operation_index):
        """Format error output for the ReadRange tool."""

        range_start = str(range_start or "")
        range_end = str(range_end or "")

        # Truncate range_start to first line with ellipsis if multiline
        start_line = (range_start or "N/A").split("\n")[0]
        if range_start and range_start.count("\n") > 0:
            start_line = start_line + " ..."

        # Truncate range_end to first line with ellipsis if multiline
        end_line = (range_end or "N/A").split("\n")[0]
        if range_end and range_end.count("\n") > 0:
            end_line = end_line + " ..."

        output = [
            f"[Operation {operation_index + 1}]",
            f"file_path: {file_path or 'N/A'}",
            f"range_start: {start_line}",
            f"range_end: {end_line}",
            "",
            error_text,
        ]

        return "\n".join(output)

    @classmethod
    def on_duplicate_request(cls, coder, **kwargs):
        coder.edit_allowed = True

    @classmethod
    def _extend_range_with_stub(cls, coder, abs_path, s_idx, e_idx, num_lines):
        """
        Extends the range [s_idx, e_idx] to include the stub result before
        and up to the stub result after the specified range.
        """
        from cecli.repomap import RepoMap

        try:
            if not hasattr(RepoMap, "_stub_instance"):
                RepoMap._stub_instance = RepoMap(map_tokens=0, io=coder.io)
            rm = RepoMap._stub_instance
            rel_fname = rm.get_rel_fname(abs_path)
            tags = rm.get_tags(abs_path, rel_fname)
            if not tags:
                return s_idx, e_idx

            # Get all definition lines, plus import lines for structural context
            lois = sorted(
                list(
                    set(
                        tag.line
                        for tag in tags
                        if tag.kind == "def" or tag.specific_kind == "import"
                    )
                )
            )
            if not lois:
                return s_idx, e_idx

            # Find the stub result before or at s_idx
            # We want the largest line in lois that is <= s_idx
            before_lines = [ln for ln in lois if ln <= s_idx]
            new_s_idx = s_idx
            if before_lines:
                new_s_idx = before_lines[-1]

            # Find the stub result after e_idx
            # We want the smallest line in lois that is > e_idx
            after_lines = [ln for ln in lois if ln > e_idx]
            new_e_idx = e_idx
            if after_lines:
                new_e_idx = after_lines[0] - 1
            else:
                new_e_idx = num_lines - 1

            return new_s_idx, new_e_idx
        except Exception:
            # Fallback to original range if anything goes wrong
            return s_idx, e_idx

    @classmethod
    def _get_range_preview(cls, coder, abs_path, start_idx, end_idx, line_numbers=True):
        """Get a preview of a large file range between start_idx and end_idx.

        For code files (where tree-sitter can parse structure), uses
        RepoMap.get_file_stub to generate a structural outline. For non-code files
        (text, logs, markdown, etc.) where get_file_stub returns nothing useful,
        falls back to 20 equally-spaced lines from the range.

        Args:
            abs_path (str): Absolute path to the file
            io (InputOutput): Instance for file operations
            start_idx (int): 0-based start line of the range
            end_idx (int): 0-based end line of the range (inclusive)
            line_numbers (bool): Whether to include line numbers in output

        Returns:
            str: Formatted preview — structural outline for code, sampled lines for text
        """
        from cecli.repomap import RepoMap

        io = coder.io
        abs_path, rel_path = resolve_paths(coder, abs_path)

        stub = RepoMap.get_file_stub(
            abs_path, io, start_line=start_idx, end_line=end_idx, line_numbers=line_numbers
        )

        # If get_file_stub returned a useful structural outline, wrap it as JSON
        if stub and stub != "# No outline available":
            result = json.dumps(
                {
                    "file_path": rel_path,
                    "outline": stub,
                },
                ensure_ascii=False,
            )
            return result, True

        content = io.read_text(abs_path)
        if not content:
            return ""

        lines = content.splitlines()
        num_file_lines = len(lines)
        # Clamp indices to actual file content bounds
        actual_start = max(0, min(start_idx, num_file_lines - 1))
        actual_end = max(0, min(end_idx, num_file_lines - 1))
        total_lines = actual_end - actual_start + 1

        if total_lines <= 0:
            return "", False

        if total_lines <= 20:
            # Return all lines
            sample_lines = [(actual_start + i, lines[actual_start + i]) for i in range(total_lines)]
        else:
            # Pick 20 equally-spaced lines across the range
            spacing = max(1, total_lines // 20)
            sample_lines = []
            for i in range(0, total_lines, spacing):
                if len(sample_lines) >= 20:
                    break
                idx = actual_start + i
                # Deduplicate sequential indices from uneven spacing
                if not sample_lines or idx != sample_lines[-1][0]:
                    sample_lines.append((idx, lines[idx]))

            # Always include the last line
            if sample_lines and sample_lines[-1][0] != actual_end:
                sample_lines.append((actual_end, lines[actual_end]))

        # Format the output
        parts = [
            f"File range too large ({total_lines} lines).",
            f"Showing {len(sample_lines)} equally-spaced lines from the range:",
            "",
        ]

        file_contents = []
        for idx, line_content in sample_lines:
            line_num = idx + 1
            file_contents.append(f"{line_num}|{line_content}")
            file_contents.append("...")

        parts.append(
            json.dumps(
                {
                    "file_path": rel_path,
                    "truncated": "\n".join(file_contents),
                },
                ensure_ascii=False,
            )
        )

        return "\n".join(parts), False
