import json
import os
from typing import Dict, List

from cecli.helpers import nested
from cecli.helpers.hashline import hashline_formatted, strip_hashline
from cecli.helpers.hashpos.transformations import (
    apply_contextual_marker,
    classify_search_type,
    compute_best_pair,
    extract_hint,
    narrow_by_proximity,
    reposition_indices,
    search_in_lines,
)
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import (
    ToolError,
    is_provided,
    resolve_paths,
)
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "readfile"
    RESULT_TYPE = "list"
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
            "name": "ReadFile",
            "description": (
                "Read lines from one or more files. Each returned line carries a virtual identifier "
                "you can pass straight to EditFile. Batch reads by passing an array of "
                "{file_path, range_start, range_end} objects."
                ""
                "Markers for range_start / range_end:"
                "  - exact text patterns (preferred usage) (up to 5 lines; anchor on meaningful names like function signatures)"  # noqa
                "  - '@000' / '000@' for the first / last line"
                "  - hint suffixes to disambiguate repeated patterns: ' @L<num>' (nearest match), "
                "    '@A{{regex}}' (closest match after the regex hit), '@B{{regex}}' (closest match before)"
                "  - when range_start matches one location, range_end accepts '@C{num}' (context both sides), "
                "    '@P{num}' (lines before the match), '@N{num}' (lines after the match)"
                ""
                "File edits may update prefixes of identical lines, requiring re-reading to get fresh identifiers."
                ""
                "Large structured ranges (line-number or boundary reads) return a structural outline "
                "instead of full contents; read in smaller targeted ranges for full detail."
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
                                    "description": (
                                        "The file to read, absolute or relative to the project root."
                                    ),
                                },
                                "range_start": {
                                    "type": "string",
                                    "description": (
                                        "The start of the range: an exact text pattern (up to 5 lines), "
                                        "'@000' for the first line. "
                                        "Append ' @L<num>' (e.g., 'my_func @L1506') to pick among multiple matches, "
                                        "or '@A{{regex}}' / '@B{{regex}}' for closest match after/before the regex hit."
                                    ),
                                },
                                "range_end": {
                                    "type": "string",
                                    "description": (
                                        "The end of the range: an exact text pattern (up to 5 lines), '000@' for "
                                        "the last line. When range_start "
                                        "matches one location, use '@C{num}' for context on both sides, "
                                        "'@P{num}' for lines before the match, or '@N{num}' for lines after the match."
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

        already_up_to_date = []
        new_context_retrieved = []
        error_outputs = []

        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)

        try:
            # 1. Validate read parameter
            if not isinstance(read, list):
                read = [read] if isinstance(read, dict) else read

            if len(read) == 0:
                raise ToolError("read array cannot be empty")

            all_outputs = []
            already_up_to_details = []
            new_context_details = []
            seen_files = set()
            all_outputs_set = set()
            new_context_set = set()
            already_up_to_set = set()
            ranges = {}

            for read_index, read_op in enumerate(read):
                # Extract parameters for this read operation
                file_path = read_op.get("file_path")
                range_start = nested.getter(
                    read_op, ["range_start", "start_line", "line_start", "start"]
                )
                range_end = nested.getter(read_op, ["range_end", "end_line", "line_end", "end"])
                padding = 0

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

                start_hint = None
                end_hint = None

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

                if abs_path not in seen_files:
                    seen_files.add(abs_path)

                    if abs_path not in coder.file_read_cache:
                        coder.file_read_cache.add(abs_path)
                        ConversationService.get_files(coder).clear_ranges(abs_path)

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

                # Resolve hints after file content available (@A/@B regex hints need lines)
                range_start, start_hint, start_hint_type = cls._extract_l_hint(range_start, lines)
                range_end, end_hint, end_hint_type = cls._extract_l_hint(range_end, lines)

                if num_lines == 0:
                    new_context_details.append(
                        {
                            "file_path": rel_path,
                            "status": "full",
                            "total_lines": 0,
                            "prefixed_contents": "",
                            "outline": "",
                            "note": (
                                f"File {rel_path} is empty. Next: use EditFile with start_line @000 and"
                                " end_line @000 to write content, or ResourceManager to scaffold —"
                                " do not call ReadFile again on this empty file."
                            ),
                        }
                    )
                    new_context_retrieved.append(rel_path)
                    cls._last_read_turn[abs_path] = coder.turn_count
                    continue
                # 4. Determine line range
                start_line_idx = -1
                end_line_idx = -1
                both_structured = False
                both_special = False

                if range_start is not None and range_end is not None:
                    # Step 1: Classify the search type
                    rt = cls._classify_search_type(range_start, range_end)

                    # Step 2: Find start and end indices
                    start_indices = cls._find_start_indices(lines, range_start, rt, num_lines)
                    end_indices = cls._find_end_indices(lines, range_end, rt, num_lines)

                    # Step 2a: Apply @A/@B directional filtering — keep only closest match in direction
                    if start_hint_type == "A" and start_hint is not None:
                        after = [i for i in start_indices if i > start_hint]
                        start_indices = [min(after)] if after else []
                        start_hint = None
                    elif start_hint_type == "B" and start_hint is not None:
                        before = [i for i in start_indices if i < start_hint]
                        start_indices = [max(before)] if before else []
                        start_hint = None

                    if end_hint_type == "A" and end_hint is not None:
                        after = [i for i in end_indices if i > end_hint]
                        end_indices = [min(after)] if after else []
                        end_hint = None
                    elif end_hint_type == "B" and end_hint is not None:
                        before = [i for i in end_indices if i < end_hint]
                        end_indices = [max(before)] if before else []
                        end_hint = None
                        end_indices = [i for i in end_indices if i < end_hint]
                        end_hint = None

                    # Step 3: Apply contextual marker (@C/@P/@N)
                    if rt["end_is_contextual"]:
                        result, ctx_error = cls._apply_contextual_marker(
                            start_indices,
                            range_start,
                            range_end,
                            num_lines,
                            coder,
                            file_path,
                            read_index,
                        )
                        if ctx_error:
                            error_outputs.append(ctx_error)
                            continue
                        start_indices, end_indices = result

                    # Step 4: Disambiguate if too many matches
                    start_indices = cls._disambiguate_start_indices(
                        start_indices,
                        end_indices,
                        abs_path,
                        range_start,
                        num_lines,
                        rel_path,
                        read_index,
                        coder,
                        response,
                        start_hint=start_hint,
                    )

                    # Step 5: Resolve to final indices with pair selection + fallbacks
                    s_idx, e_idx, resolve_errors = cls._resolve_to_final_indices(
                        start_indices,
                        end_indices,
                        num_lines,
                        coder,
                        abs_path,
                        range_start,
                        range_end,
                        file_path,
                        read_index,
                    )
                    if resolve_errors:
                        for err in resolve_errors:
                            error_outputs.append(err)
                        continue

                    both_special = rt["start_is_special"] and rt["end_is_special"]
                    both_structured = rt["both_structured"]
                    mixed_special_search = rt["mixed_special"]

                # Check for repeat patterns BEFORE overwriting _last_invocation
                last = cls._last_invocation.get(abs_path)
                skip_truncation = (
                    last is not None
                    and last.get("range_start") == range_start
                    and last.get("range_end") == range_end
                )

                # Store the found indices for future disambiguation
                cls._last_invocation[abs_path] = {
                    "start_idx": s_idx,
                    "end_idx": e_idx,
                    "range_start": range_start,
                    "range_end": range_end,
                }

                # For structured searches (line numbers, special markers) or mixed searches
                # (one special marker, one text pattern), cap large ranges with preview
                # Text pattern searches are not subject to capping
                sliced_contents = "\n".join(content.splitlines()[s_idx:e_idx])
                token_count = coder.main_model.token_count(content)
                sliced_token_count = coder.main_model.token_count(sliced_contents)
                is_small_file = token_count <= max(coder.large_file_token_threshold / 4, 2048)
                is_small_range = sliced_token_count <= max(
                    coder.large_file_token_threshold / 8, 1024
                )
                if (
                    both_structured or (mixed_special_search and is_small_file)
                ) and not is_small_range:

                    preview, has_stub = cls._get_range_preview(
                        coder, abs_path, start_idx=s_idx, end_idx=e_idx, line_numbers=True
                    )

                    if abs_path not in coder.abs_fnames and both_special:
                        # Track special marker usage for auto-editable detection
                        if token_count <= coder.large_file_token_threshold:
                            cls._special_marker_count[abs_path] = (
                                cls._special_marker_count.get(abs_path, 0) + 1
                            )
                            if cls._special_marker_count[abs_path] > 1:
                                coder.abs_fnames.add(abs_path)
                                preview = {
                                    "file_path": rel_path,
                                    "status": "placeholder",
                                    "total_lines": num_lines,
                                    "prefixed_contents": "",
                                    "outline": "",
                                    "note": (
                                        f"Full contents of {rel_path} will be added to context in future message."
                                    ),
                                }
                                if abs_path in coder.abs_read_only_fnames:
                                    coder.abs_read_only_fnames.remove(abs_path)

                    preview_key = json.dumps(preview, sort_keys=True)
                    if preview_key not in all_outputs_set:
                        all_outputs_set.add(preview_key)
                        if len(all_outputs):
                            all_outputs.append("")
                        all_outputs.append(preview)

                    # If the range was large and we're showing a preview, add explicit guidance
                    range_lines = e_idx - s_idx + 1
                    if not has_stub:
                        note_text = (
                            f"read operation {read_index + 1}: {rel_path} range "
                            f"({range_lines} lines) is large. "
                            f"Use @L ranges (e.g., @L{s_idx + 1}, @L{e_idx + 1}) for precise reads."
                        )
                        response.append_result(
                            content=note_text,
                            metadata={
                                "file_path": rel_path,
                                "status": "placeholder",
                                "total_lines": num_lines,
                                "outline": "",
                            },
                        )

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
                hashed_content, _ = hashline_formatted(content, file_name=abs_path)
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
                        coder,
                        rel_path,
                        s_idx,
                        e_idx,
                        hashed_lines,
                        current=is_already_up_to_date,
                        skip_truncation=skip_truncation,
                    )

                    if is_already_up_to_date:
                        if str(model_response) not in already_up_to_set:
                            already_up_to_set.add(str(model_response))
                            already_up_to_details.append(model_response)
                    else:
                        if str(model_response) not in new_context_set:
                            new_context_set.add(str(model_response))
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

            if new_context_details:
                ConversationService.get_chunks(coder).add_file_context_messages()

            # if (
            #    ConversationService.get_chunks(coder).last_clear_count > 20
            #    and coder.context_compaction_current_ratio > 0.8
            # ):
            #    cls.clear_old_messages(coder)

            # Log success and return the formatted context directly
            coder.edit_allowed = True

            if already_up_to_details or new_context_details:
                if new_context_details:
                    coder.io.tool_output(
                        f"✓ Retrieved context for {len(new_context_details)} operation(s)",
                        type="tool-result",
                    )

                    note_text = (
                        f"Retrieved context for {len(new_context_details)} operation(s). "
                        "Full results for these reads will be given in a follow up message."
                        " Note: Full contents contain aggregated content across multiple reads."
                    )
                    response.append_result(
                        content=note_text,
                        metadata={
                            "file_path": "",
                            "status": "placeholder",
                            "total_lines": 0,
                            "outline": "",
                        },
                    )
                    for d in new_context_details:
                        content_text = d.pop("prefixed_contents", "")
                        response.append_result(content=content_text, metadata=d)
                if already_up_to_details:
                    coder.io.tool_output(
                        (
                            "Earlier contents still valid for"
                            f" {len(already_up_to_details)} operation(s)"
                        ),
                        type="tool-result",
                    )

                    note_text = (
                        "Earlier contents still valid from previous read for "
                        f"{len(already_up_to_details)} operation(s). "
                        "Relevant contents for these reads available in previous message."
                    )
                    response.append_result(
                        content=note_text,
                        metadata={
                            "file_path": "",
                            "status": "placeholder",
                            "total_lines": 0,
                            "outline": "",
                        },
                    )
                    for d in already_up_to_details:
                        content_text = d.pop("prefixed_contents", "")
                        response.append_result(content=content_text, metadata=d)
                if already_up_to_date and not new_context_retrieved:
                    response.append_result(
                        content=(
                            "Do not call `ReadFile` again with these parameters again"
                            " unless you edit the relevant files."
                        ),
                        metadata={
                            "file_path": "",
                            "status": "placeholder",
                            "total_lines": 0,
                            "outline": "",
                        },
                    )

            if all_outputs:
                for output in all_outputs:
                    if output:
                        if isinstance(output, dict):
                            outline_content = output.pop("outline", "")
                            prefixed_content = output.pop("prefixed_contents", "")
                            preview_content = prefixed_content or outline_content
                            response.append_result(content=preview_content, metadata=output)
                        else:
                            response.append_result(output)
                response.append_result(
                    content="Use these outlines to refine your search.",
                    metadata={
                        "file_path": "",
                        "status": "placeholder",
                        "total_lines": 0,
                        "outline": "",
                    },
                )

            if error_outputs:
                coder.io.tool_error(
                    f"Errors encountered for {len(error_outputs)} operation(s)", type="tool-result"
                )

                for err in error_outputs:
                    response.append_error(err)

            response.append_result(
                content=f"File Context Turn {coder.turn_count}",
                metadata={
                    "file_path": "",
                    "status": "placeholder",
                    "total_lines": 0,
                    "outline": "",
                },
            )
            return response

        except ToolError as e:
            # Handle expected errors raised by utility functions or validation
            response.append_error(str(e))
            return response
        except Exception as e:
            # Handle unexpected errors during processing
            response.append_error(str(e))
            return response

    @classmethod
    def format_model_response(
        cls, coder, rel_path, s_idx, e_idx, hashed_lines, current=False, skip_truncation=False
    ):
        """Format a file's context range as hash-prefixed lines for the model."""

        hashed_content = "\n".join(hashed_lines[s_idx : e_idx + 1])
        token_count = coder.main_model.token_count(hashed_content)

        if skip_truncation or token_count <= min(coder.large_file_token_threshold / 16, 512):
            prefixed = hashed_content
        else:
            total = e_idx - s_idx
            if total <= 15:
                prefixed = hashed_content
            else:
                prefixed = cls.content_splitter(coder, hashed_lines, s_idx, e_idx)

        result = {
            "file_path": rel_path,
            "status": "full",
            "start_line": s_idx + 1,
            "end_line": e_idx + 1,
            "total_lines": len(hashed_lines),
            "prefixed_contents": prefixed,
            "outline": "",
            "note": "",
        }
        return result

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
                prev_end = output_parts[chunk_idx - 1][-1] + 1
                next_start = chunk[0] + 1
                omitted = next_start - prev_end - 1
                output_lines.append(
                    f"...⋮... [{omitted} lines omitted (L{prev_end + 1}–L{next_start - 1})]"
                )
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

        return reposition_indices(target_idx, start_idx, end_idx, total_lines)

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
        """Format output for ReadFile tool."""
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
                range_start = strip_hashline(
                    nested.getter(read_op, ["range_start", "start_line", "line_start", "start"])
                ).strip()
                range_end = strip_hashline(
                    nested.getter(read_op, ["range_end", "end_line", "line_end", "end"])
                ).strip()

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
        """Format error output for the ReadFile tool."""

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
    def ptc_format(cls, result):
        """Strip placeholder entries from the result before sandbox exposure."""
        if isinstance(result, ToolResponse) and result.result_type == "list":
            result._result = [
                item
                for item in result._result
                if not (
                    isinstance(item, dict)
                    and isinstance(item.get("_"), dict)
                    and item["_"].get("status") == "placeholder"
                )
            ]
        return result

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
    def _try_fuzzy_narrow_indices(
        cls, coder, abs_path, start_indices, num_lines, search_pattern=None
    ):
        """Try to narrow down ambiguous pattern matches using structural features.

        First attempts exact structural proximity (indices near def/class/import
        lines). If that fails, falls back to rapidfuzz fuzzy matching the search
        pattern against tag names from the repo map outline.

        Returns narrowed list of indices, or None if narrowing wasn't possible.
        """
        try:
            from cecli.repomap import RepoMap

            if not hasattr(RepoMap, "_stub_instance"):
                RepoMap._stub_instance = RepoMap(map_tokens=0, io=coder.io)
            rm = RepoMap._stub_instance
            rel_fname = rm.get_rel_fname(abs_path)
            tags = rm.get_tags(abs_path, rel_fname)

            if not tags:
                return None

            # Build structural line set for proximity matching
            structural_lines = {
                tag.line for tag in tags if tag.kind == "def" or tag.specific_kind == "import"
            }

            if structural_lines:
                narrowed = []
                for si in start_indices:
                    for sl in structural_lines:
                        if abs(si - sl) <= 3:
                            narrowed.append(si)
                            break

                if narrowed:
                    return sorted(set(narrowed))

            # Structural proximity didn't narrow — try fuzzy name matching
            if search_pattern:
                from rapidfuzz import fuzz

                # Collect def tags with their names and lines
                def_tags = [
                    (tag.name, tag.line)
                    for tag in tags
                    if tag.kind == "def" and getattr(tag, "name", None)
                ]

                if def_tags:
                    # Fuzzy match the search pattern against each tag name
                    matched_lines = []
                    for tag_name, tag_line in def_tags:
                        score = fuzz.partial_ratio(search_pattern.lower(), tag_name.lower())
                        if score >= 70:
                            matched_lines.append(tag_line)

                    if matched_lines:
                        # Return start_indices that are near fuzzy-matched structural lines
                        narrowed = []
                        for si in start_indices:
                            for ml in matched_lines:
                                if abs(si - ml) <= 5:
                                    narrowed.append(si)
                                    break

                        if narrowed:
                            return sorted(set(narrowed))

                        # No start_indices near fuzzy-matched lines —
                        # return the matched lines themselves as anchors
                        return sorted(set(matched_lines))

            return None
        except Exception:
            return None

    @classmethod
    def _classify_search_type(cls, range_start, range_end):
        """Classify range markers into structured, text, mixed, or contextual search types."""

        return classify_search_type(range_start, range_end)

    @classmethod
    def _extract_l_hint(cls, pattern, lines=None):
        """Extract hint suffix from a pattern string.

        Supports @L<num> (direct line number), @A{{regex}} (filter to matches AFTER
        the first regex match), and @B{{regex}} (filter to matches BEFORE the last
        regex match) hints.

        Returns (stripped_pattern, hint_value, hint_type) where:
          - hint_value is a 0-based line number or None
          - hint_type is 'L', 'A', 'B', or None
        """

        return extract_hint(pattern, lines)

    @classmethod
    def _search_in_lines(cls, lines, pattern, return_last_line=False):
        """Search for a multiline pattern in lines.

        Returns list of matching indices. When return_last_line is True,
        returns the index of the last line of each match instead of the first.

        Delegates to the core ``search_in_lines`` in
        ``cecli.helpers.hashpos.transformations`` for unified matching.
        """

        return search_in_lines(lines, pattern, return_last_line=return_last_line)

    @classmethod
    def _find_start_indices(cls, lines, range_start, classification, num_lines):
        """Resolve start indices based on the classified search type."""
        if classification["start_is_line_ref"]:
            line_num = int(range_start[2:]) - 1
            return [max(0, min(line_num, num_lines - 1))]

        if classification["start_is_special"]:
            return [0] if range_start == "@000" else [num_lines - 1]

        return cls._search_in_lines(lines, range_start)

    @classmethod
    def _find_end_indices(cls, lines, range_end, classification, num_lines):
        """Resolve end indices based on the classified search type."""
        if classification["end_is_line_ref"]:
            line_num = int(range_end[2:]) - 1
            return [max(0, min(line_num, num_lines - 1))]

        if classification["end_is_special"]:
            return [0] if range_end == "@000" else [num_lines - 1]

        return cls._search_in_lines(lines, range_end, return_last_line=True)

    @classmethod
    def _apply_contextual_marker(
        cls,
        start_indices,
        range_start,
        range_end,
        num_lines,
        coder,
        file_path,
        read_index,
    ):
        """Expand range using @C/@P/@N contextual markers.

        Returns ((new_start_indices, new_end_indices), error).
        Error is None on success, or a formatted error string on failure.
        """

        try:
            result = apply_contextual_marker(start_indices, range_start, range_end, num_lines)

            return result, None

        except ValueError as e:
            error = cls.format_error(
                coder,
                str(e),
                file_path,
                range_start,
                range_end,
                read_index,
            )

            return None, error

    @classmethod
    def _disambiguate_start_indices(
        cls,
        start_indices,
        end_indices,
        abs_path,
        range_start,
        num_lines,
        rel_path,
        read_index,
        coder,
        response,
        start_hint=None,
    ):
        """Narrow ambiguous start_indices when there are too many matches.

        Tries @L hint proximity narrowing first, then fuzzy structural
        narrowing, falls back to first 5 with a warning listing
        line numbers. Last-invocation disambiguation is handled separately
        in _resolve_to_final_indices.
        """

        if len(start_indices) <= 5:
            return start_indices

        last = cls._last_invocation.get(abs_path)
        if last is not None:
            # Last-invocation disambiguation happens in _resolve_to_final_indices
            return start_indices

        # @L hint: filter to indices closest to the hinted line
        if start_hint is not None:
            proximity_narrowed = cls._narrow_by_proximity(start_indices, start_hint, max_results=5)
            if proximity_narrowed and len(proximity_narrowed) <= 5:
                line_nums = [str(i + 1) for i in sorted(proximity_narrowed)]
                note_text = (
                    f"read operation {read_index + 1}: start pattern "
                    f"'{range_start}' matched many locations in {rel_path}; "
                    f"narrowed to {len(proximity_narrowed)} closest to @L hint "
                    f"at lines {', '.join(line_nums)}. "
                    f"Tip: append ' @L<num>' to any pattern (e.g., "
                    f"'{range_start} @L{start_hint + 1}') to target a specific match."
                )
                response.append_result(
                    content=note_text,
                    metadata={
                        "file_path": rel_path,
                        "status": "placeholder",
                        "total_lines": num_lines,
                        "outline": "",
                    },
                )
                return proximity_narrowed

        narrowed = cls._try_fuzzy_narrow_indices(
            coder,
            abs_path,
            start_indices,
            num_lines,
            search_pattern=range_start,
        )

        if narrowed and len(narrowed) <= 5:
            line_nums = [str(i + 1) for i in sorted(narrowed)]
            note_text = (
                f"read operation {read_index + 1}: start pattern "
                f"'{range_start}' matched many locations in {rel_path}; "
                f"narrowed to {len(narrowed)} structural match(es) "
                f"at lines {', '.join(line_nums)}. "
                f"Tip: append ' @L<num>' to a pattern (e.g., "
                f"'{range_start} @L{line_nums[0]}') to target a specific match."
            )
            response.append_result(
                content=note_text,
                metadata={
                    "file_path": rel_path,
                    "status": "placeholder",
                    "total_lines": num_lines,
                    "outline": "",
                },
            )
            return narrowed

        line_nums = [str(i + 1) for i in sorted(start_indices[:5])]
        note_text = (
            f"read operation {read_index + 1}: start pattern "
            f"'{range_start}' too broad ({len(start_indices)} matches) "
            f"in {rel_path}. Using first 5 (lines {', '.join(line_nums)}). "
            f"Refine with specific names or @L ranges for precision."
        )
        response.append_result(
            content=note_text,
            metadata={
                "file_path": rel_path,
                "status": "placeholder",
                "total_lines": num_lines,
                "outline": "",
            },
        )
        return start_indices[:5]

    @classmethod
    def _narrow_by_proximity(cls, indices, target, max_results=5):
        """Narrow a list of indices to those closest to a target index.

        Returns up to max_results indices sorted by ascending distance
        from the target (0-based line number).
        """

        return narrow_by_proximity(indices, target, max_results=max_results)

    @classmethod
    def _resolve_to_final_indices(
        cls,
        start_indices,
        end_indices,
        num_lines,
        coder,
        abs_path,
        range_start,
        range_end,
        file_path,
        read_index,
    ):
        """Find the best (start, end) pair and handle fallbacks.

        Returns (s_idx, e_idx, errors) where errors is a list of formatted
        error strings. On success, errors is empty and s_idx/e_idx are set.
        """
        errors = []
        last = cls._last_invocation.get(abs_path)

        # Find best pair (with last-invocation disambiguation if available)
        if last and len(start_indices) > 5:
            last_s, last_e = last["start_idx"], last["end_idx"]
            candidates = []
            for s in start_indices:
                for e in [idx for idx in end_indices if idx >= s]:
                    dist_sum = abs(s - last_s) + abs(e - last_e)
                    candidates.append((dist_sum, s, e))
            candidates.sort(key=lambda x: (x[0], x[1] < last_s, x[1], x[2]))
            best_pair = (candidates[0][1], candidates[0][2]) if candidates else None
        else:
            best_pair = cls._compute_best_pair(start_indices, end_indices)

        # Inverted matching: LLM may have swapped start/end pattern order
        if best_pair is None and (len(start_indices) == 1 or len(end_indices) == 1):
            best_pair = cls._compute_best_pair(start_indices, end_indices, allow_inverted=True)

        # Error: start pattern not found
        if not start_indices:
            errors.append(
                cls.format_error(
                    coder,
                    f"Start pattern '{range_start}' not found in {file_path}. Refine your search.",
                    file_path,
                    range_start,
                    range_end,
                    read_index,
                )
            )
            return None, None, errors

        # Error: end pattern not found — expand from start
        if not end_indices:
            if start_indices:
                s_idx = start_indices[0]
                try:
                    s_idx, e_idx = cls._extend_range_with_stub(
                        coder,
                        abs_path,
                        s_idx,
                        num_lines - 1,
                        num_lines,
                    )
                except Exception:
                    e_idx = num_lines - 1
                return s_idx, e_idx, []
            else:
                errors.append(
                    cls.format_error(
                        coder,
                        f"End pattern '{range_end}' not found in {file_path}. Refine your search.",
                        file_path,
                        range_start,
                        range_end,
                        read_index,
                    )
                )
                return None, None, errors

        # Both matched but no valid pair — expand from start
        if best_pair is None:
            if start_indices:
                s_idx = start_indices[0]
                try:
                    s_idx, e_idx = cls._extend_range_with_stub(
                        coder,
                        abs_path,
                        s_idx,
                        num_lines - 1,
                        num_lines,
                    )
                except Exception:
                    e_idx = num_lines - 1
                return s_idx, e_idx, []
            else:
                errors.append(
                    cls.format_error(
                        coder,
                        (
                            f"End pattern '{range_end}' not found after start pattern"
                            f" in {file_path}."
                        ),
                        file_path,
                        range_start,
                        range_end,
                        read_index,
                    )
                )
                return None, None, errors

        return best_pair[0], best_pair[1], []

    @classmethod
    def _compute_best_pair(cls, start_indices, end_indices, allow_inverted=False):
        """Find the smallest-range valid (start, end) pair.

        When allow_inverted is True, also considers pairs where end < start
        (LLM swapped the order) and returns them in correct order.
        """

        return compute_best_pair(start_indices, end_indices, allow_inverted=allow_inverted)

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

        content = io.read_text(abs_path)

        stub = RepoMap.get_file_stub(
            abs_path, io, start_line=start_idx, end_line=end_idx, line_numbers=line_numbers
        )

        # If get_file_stub returned a useful structural outline, wrap it as JSON
        if stub and stub != "# No outline available":
            return {
                "file_path": rel_path,
                "status": "outline",
                "total_lines": len(content.splitlines()),
                "prefixed_contents": "",
                "outline": stub,
                "note": (
                    f"Large File. Tip: use @L ranges for precise reads"
                    f" (e.g., @L{start_idx + 1}, @L{end_idx + 1})."
                ),
            }, True

        content = io.read_text(abs_path)
        if not content:
            return {
                "file_path": rel_path,
                "status": "outline",
                "total_lines": 0,
                "prefixed_contents": "",
                "outline": "",
                "note": "Empty file.",
            }, False

        lines = content.splitlines()
        num_file_lines = len(lines)
        # Clamp indices to actual file content bounds
        actual_start = max(0, min(start_idx, num_file_lines - 1))
        actual_end = max(0, min(end_idx, num_file_lines - 1))
        total_lines = actual_end - actual_start + 1

        if total_lines <= 0:
            return {
                "file_path": rel_path,
                "status": "outline",
                "total_lines": 0,
                "prefixed_contents": "",
                "outline": "",
                "note": "Invalid range.",
            }, False

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

        parts = [
            f"File range too large ({total_lines} lines).",
            (
                f"Tip: use @L ranges for precise reads"
                f" (e.g., @L{actual_start + 1}, @L{actual_end + 1})."
            ),
            f"Showing {len(sample_lines)} equally-spaced lines from the range:",
            "",
        ]
        file_contents = []
        for idx, line_content in sample_lines:
            line_num = idx + 1
            file_contents.append(f"{line_num}|{line_content}")
            file_contents.append("...")

        parts.append(f"file_path: {rel_path}")
        parts.append("truncated:")
        parts.append("\n".join(file_contents))

        return {
            "file_path": rel_path,
            "status": "outline",
            "total_lines": num_file_lines,
            "prefixed_contents": "",
            "outline": "\n".join(parts),
            "note": (
                f"Tip: use @L ranges for precise reads"
                f" (e.g., @L{actual_start + 1}, @L{actual_end + 1})."
            ),
        }, False
