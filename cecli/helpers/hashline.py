import difflib
import re

from cecli.helpers.hashpos.hashpos import HashPos

HASHLINE_PREFIX_RE = HashPos.HASH_PREFIX_RE


class HashlineError(Exception):
    """Custom exception for hashline-specific errors."""

    pass


def hashline(text: str, start_line: int = 1) -> str:
    """
    Add a hash scheme to each line of text using the HashPos engine.

    Args:
        text: Input text
        start_line: Starting line number (ignored by HashPos, but kept for signature compatibility)

    Returns:
        String with HashPos prefixes added to each line
    """
    hp = HashPos(text)
    return hp.format_content(start_line=start_line)


# int_to_2digit_52 removed as it is no longer used by the HashPos engine.


def strip_hashline(text: str) -> str:
    """
    Remove HashPos prefixes from the start of every line.
    """
    return HashPos.strip_prefix(text)


def normalize_hashline(hashline_str: str) -> str:
    """
    Normalize a hashline string to the 4-character hash fragment.
    """
    if hashline_str in ("@000", "000@"):
        return hashline_str
    try:
        return HashPos.normalize(hashpos_str=hashline_str)
    except ValueError as e:
        raise HashlineError(str(e))


def parse_hashline(hashline_str: str):
    """
    Parse a hashline string.
    Note: HashPos doesn't encode line numbers in the string,
    so this returns (hash_fragment, None, None) for compatibility.
    """
    fragment = normalize_hashline(hashline_str)
    return fragment, None, None


def find_hashline_by_exact_match(hashed_lines, hash_fragment, line_num_str=None):
    """
    Find a hashline by its hash fragment using HashPos engine.
    """
    source_text = HashPos.strip_prefix("".join(hashed_lines))
    hp = HashPos(source_text)
    matches = hp.resolve_to_lines(hash_fragment)
    return matches[0] if matches else None


def find_hashline_by_fragment(hashed_lines, hash_fragment, target_line_num=None):
    """
    Find a hashline by hash fragment only using HashPos engine.
    """
    source_text = HashPos.strip_prefix("".join(hashed_lines))
    hp = HashPos(source_text)
    matches = hp.resolve_to_lines(hash_fragment)

    if not matches:
        return None

    if target_line_num is not None:
        # Return match closest to target_line_num (1-indexed to 0-indexed conversion)
        target_idx = target_line_num - 1
        return min(matches, key=lambda x: abs(x - target_idx))

    return matches[0]


def find_hashline_by_content_match(hashed_lines, hash_str, expected_content):
    """
    Find a hashline by fragment and verify it matches the expected content.
    Uses the HashPos engine for resolution.
    """
    try:
        fragment = normalize_hashline(hash_str)
        source_text = HashPos.strip_prefix("".join(hashed_lines))
        hp = HashPos(source_text)

        # Resolve to all candidate lines for this hash
        candidate_indices = hp.resolve_to_lines(fragment)

        # Strip prefixes from lines for content comparison
        stripped_lines = [HashPos.strip_prefix(line).rstrip("\r\n") for line in hashed_lines]
        target_content = expected_content.rstrip("\r\n")

        for idx in candidate_indices:
            if 0 <= idx < len(stripped_lines):
                if stripped_lines[idx] == target_content:
                    return fragment
    except Exception:
        pass
    return None


def find_hashline_range(
    hashed_lines,
    start_line_hash,
    end_line_hash,
    allow_exact_match=True,
    replacement_text=None,
):
    """
    Find start and end line indices in hashed content using HashPos engine.

    Args:
        hashed_lines: List of hashed lines
        start_line_hash: Hashline format for start line
        end_line_hash: Hashline format for end line
        allow_exact_match: Whether to try exact match first (default: True)
        replacement_text: Optional replacement text for heuristic fallback

    Returns:
        tuple: (found_start_line, found_end_line)

    Raises:
        HashlineError: If range cannot be found or is invalid
    """
    # Parse hashes
    start_hash, _, _ = parse_hashline(start_line_hash)
    end_hash, _, _ = parse_hashline(end_line_hash)

    # Handle special marker "@000" (top of file)
    if start_hash == "@000":
        found_start = 0
        # If end is also "@000", it's an empty range at the start
        if end_hash == "@000":
            return 0, 0
        # If end is "000@", it's the entire file
        if end_hash == "000@":
            if not hashed_lines:
                return 0, 0
            return 0, len(hashed_lines) - 1
        # Otherwise, resolve end hash normally
        source_text = HashPos.strip_prefix("".join(hashed_lines))
        hp = HashPos(source_text)
        ends = hp.resolve_to_lines(end_hash)
        if not ends:
            raise HashlineError(f"End line hash fragment '{end_hash}' not found in file")
        return 0, ends[0]

    # Handle special marker "000@" (bottom of file) for end position
    if end_hash == "000@":
        # We need to resolve start hash normally, then set end to bottom of file
        source_text = HashPos.strip_prefix("".join(hashed_lines))
        hp = HashPos(source_text)
        starts = hp.resolve_to_lines(start_hash)
        if not starts:
            raise HashlineError(f"Start line hash fragment '{start_hash}' not found in file")
        found_start = starts[0]

        # Set end to bottom of file
        if not hashed_lines:
            return 0, 0
        found_end = len(hashed_lines) - 1

        # Verify start <= end
        if found_start > found_end:
            raise HashlineError(
                f"Invalid range: start line {found_start} is after end line {found_end}"
            )
        return found_start, found_end

    source_text = HashPos.strip_prefix("".join(hashed_lines))
    hp = HashPos(source_text)

    try:
        found_start, found_end = hp.resolve_range(start_hash, end_hash)
        return found_start, found_end
    except ValueError as e:
        raise HashlineError(str(e))


def extract_hashline_range(
    original_content,
    start_line_hash,
    end_line_hash,
):
    """
    Extract the content between hashline markers.

    Args:
        original_content: Original file content
        start_line_hash: Hashline format for start line: "{4 char hash}" (without the braces)
        end_line_hash: Hashline format for end line: "{4 char hash}" (without the braces)

    Returns:
        str: The extracted content between the hashline markers (with hashline prefixes preserved)

    Raises:
        HashlineError: If hashline verification fails
    """
    # Normalize hashline inputs
    start_line_hash = normalize_hashline(start_line_hash)
    end_line_hash = normalize_hashline(end_line_hash)

    # Apply hashline to original content to find the range
    hashed_original = hashline(original_content)
    hashed_lines = hashed_original.splitlines(keepends=True)

    # Use find_hashline_range to locate the range
    found_start_line, found_end_line = find_hashline_range(
        hashed_lines,
        start_line_hash,
        end_line_hash,
        allow_exact_match=True,
    )

    # Now we have the exact range in the hashed content
    # Extract the original content from the range
    original_range_lines = hashed_lines[found_start_line : found_end_line + 1]
    original_range_content = "".join(original_range_lines)

    # Return the hashed content (with hashline prefixes preserved)
    return original_range_content


def find_best_line(content, target_line_num, content_to_lines, used_lines, hashlines):
    """
    Find the best matching line for given content near target_line_num.

    This helper function is used by get_hashline_content_diff to handle duplicate lines.
    It finds the line number closest to the target position that hasn't been used yet.

    Args:
        content: The content to find
        target_line_num: The target line number we're trying to match
        content_to_lines: Dictionary mapping content to list of line numbers where it appears
        used_lines: Set of line numbers that have already been used
        hashlines: List of hashline-prefixed lines

    Returns:
        tuple: (best_line_num, best_hashline) or None if not found
    """
    if content not in content_to_lines:
        return None

    # Get all line numbers where this content appears
    line_numbers = content_to_lines[content]

    # Filter out already used lines
    available_lines = [ln for ln in line_numbers if ln not in used_lines]

    if not available_lines:
        return None

    # Find the line closest to the target line number
    # For diffs, we want the line that's in the right position
    best_line_num = min(available_lines, key=lambda ln: abs(ln - target_line_num))
    return best_line_num, hashlines[best_line_num - 1]  # Convert to 0-based index


def get_hashline_diff(
    original_content,
    start_line_hash,
    end_line_hash,
    operation,
    text=None,
):
    """
    Generate a diff for a hashline operation in the format used by the original format_output.
    Returns a diff between the original range content and the replacement text.

    Args:
        original_content: Original file content
        start_line_hash: Hashline format for start line: "{4 char hash}" (without the braces)
        end_line_hash: Hashline format for end line: "{4 char hash}" (without the braces)
        operation: One of "replace", "insert", or "delete"
        text: Text to insert or replace with (required for replace/insert operations)

    Returns:
        str: A formatted diff snippet showing changes, or empty string if no changes

    Raises:
        HashlineError: If hashline verification fails or operation is invalid
    """

    start_line_hash = normalize_hashline(start_line_hash)
    end_line_hash = normalize_hashline(end_line_hash)

    if operation == "insert":
        end_line_hash = start_line_hash

    # Extract the original range content using the new helper method
    # This now returns the hashed content with hashlines preserved
    original_range_content = extract_hashline_range(
        original_content=original_content,
        start_line_hash=start_line_hash,
        end_line_hash=end_line_hash,
    )

    # Apply hashline to original content to find the range indices for hashing replacement text
    hashed_original = hashline(original_content)
    hashed_lines = hashed_original.splitlines(keepends=True)
    found_start, found_end = find_hashline_range(
        hashed_lines,
        start_line_hash,
        end_line_hash,
    )

    # For delete operation, we're removing the range
    if operation == "delete":
        find_text = original_range_content
        replace_text = ""
    # For insert operation, we're inserting after the range
    elif operation == "insert":
        find_text = ""
        # For insert operations, we need to calculate hashlines for the text to insert
        # The text should be hashed starting at the line after the end line
        if text:
            # Insert after the end line, so start hashline at found_end + 2 (1-indexed)
            replace_text = hashline(text, start_line=found_end + 2)
        else:
            replace_text = ""
    # For replace operation, we're replacing the range
    elif operation == "replace":
        find_text = original_range_content
        # For replace operations, the replacement text should be hashed starting at the start line
        if text:
            replace_text = hashline(text, start_line=found_start + 1)
        else:
            replace_text = ""
    else:
        raise HashlineError(
            f"Invalid operation '{operation}'. Must be one of: replace, insert, delete"
        )

    # Generate diff in the same format as original format_output
    # Use splitlines(keepends=True) to preserve line endings for accurate hash comparison
    find_lines = find_text.splitlines(keepends=True)
    replace_lines = replace_text.splitlines(keepends=True)

    # Strip line endings for difflib comparison but keep them in the actual lines
    diff = difflib.unified_diff(
        [line.rstrip("\r\n") for line in find_lines],
        [line.rstrip("\r\n") for line in replace_lines],
        lineterm="",
        n=1,
    )

    # Skip header lines (first 2 lines) as in original format_output
    diff_lines = list(diff)[2:]

    if diff_lines:
        return "\n".join([line for line in diff_lines])
    else:
        return ""


CHUNK_HEADER_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_content_for_diff(content: str):
    """Helper to parse hashline content in a single pass."""
    hashlines = []
    content_to_lines = {}
    content_only_lines = []

    for line_num, line in enumerate(content.splitlines(keepends=True), 1):
        match = HASHLINE_PREFIX_RE.match(line)
        if match:
            line_content = line[match.end() :].rstrip("\r\n")
            hashline_prefixed = line.rstrip("\r\n")
            hashlines.append(hashline_prefixed)
            content_only_lines.append(line_content)
            if line_content not in content_to_lines:
                content_to_lines[line_content] = []
            content_to_lines[line_content].append(line_num)
            continue

        # Line without hashline prefix or malformed
        stripped = line.rstrip("\r\n")
        hashlines.append(stripped)
        content_only_lines.append(stripped)
        if stripped not in content_to_lines:
            content_to_lines[stripped] = []
        content_to_lines[stripped].append(line_num)

    return hashlines, content_to_lines, content_only_lines


def get_hashline_content_diff(
    old_content: str, new_content: str, fromfile: str = "", tofile: str = "", context_lines: int = 1
) -> str:
    """
    Generate a unified diff between two hashline-prefixed contents.

    This function generates a content-only diff first, then uses it as a template
    to build a hashline diff that only shows actual content changes.

    Args:
        old_content: Old content with hashline prefixes
        new_content: New content with hashline prefixes
        fromfile: Optional filename for the old content in diff header
        tofile: Optional filename for the new content in diff header

    Returns:
        str: Unified diff string, or empty string if no changes
    """
    if old_content == new_content:
        return ""

    # Generate content-only versions by stripping hashline prefixes
    # Parse the original hashline content into lists for lookup
    old_hashlines, old_content_to_lines, old_content_lines = _parse_content_for_diff(old_content)
    new_hashlines, new_content_to_lines, new_content_lines = _parse_content_for_diff(new_content)

    # Generate content-only diff
    content_diff = difflib.unified_diff(
        old_content_lines,
        new_content_lines,
        fromfile=fromfile,
        tofile=tofile,
        lineterm="",
        n=context_lines,
    )
    content_diff_lines = list(content_diff)

    # If there's no content change, return empty string
    if not content_diff_lines:
        return ""

    # Build the hashline diff using the content diff as a template
    # We need to track which lines have been "used" to handle duplicates
    old_used_lines = set()
    new_used_lines = set()
    hashline_diff_lines = []

    # Parse the content diff to understand line numbers
    current_old_line = 1
    current_new_line = 1

    for line in content_diff_lines:
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            # Keep headers and chunk headers as-is
            hashline_diff_lines.append(line)

            # Parse chunk header to update line numbers
            if line.startswith("@@"):
                match = CHUNK_HEADER_RE.match(line)
                if match:
                    current_old_line = int(match.group(1))
                    current_new_line = int(match.group(3))
        elif line.startswith(" ") or line.startswith("-") or line.startswith("+"):
            # This is a content line
            marker = line[0]
            content = line[1:]

            if marker == " ":
                # Context line - exists in both
                # Try to find matching line in new content first
                result = find_best_line(
                    content, current_new_line, new_content_to_lines, new_used_lines, new_hashlines
                )
                if result:
                    best_line_num, best_hashline = result
                    hashline_diff_lines.append(f" {best_hashline}")
                    # Mark this line as used
                    new_used_lines.add(best_line_num)
                else:
                    # Fallback to old content
                    result = find_best_line(
                        content,
                        current_old_line,
                        old_content_to_lines,
                        old_used_lines,
                        old_hashlines,
                    )
                    if result:
                        best_line_num, best_hashline = result
                        hashline_diff_lines.append(f" {best_hashline}")
                        # Mark this line as used
                        old_used_lines.add(best_line_num)
                    else:
                        # Fallback: use the content as-is
                        hashline_diff_lines.append(line)

                current_old_line += 1
                current_new_line += 1

            elif marker == "-":
                # Line removed - exists in old
                result = find_best_line(
                    content, current_old_line, old_content_to_lines, old_used_lines, old_hashlines
                )
                if result:
                    best_line_num, best_hashline = result
                    hashline_diff_lines.append(f"-{best_hashline}")
                    # Mark this line as used
                    old_used_lines.add(best_line_num)
                else:
                    # Fallback: use the content as-is
                    hashline_diff_lines.append(line)

                current_old_line += 1

            elif marker == "+":
                # Line added - exists in new
                result = find_best_line(
                    content, current_new_line, new_content_to_lines, new_used_lines, new_hashlines
                )
                if result:
                    best_line_num, best_hashline = result
                    hashline_diff_lines.append(f"+{best_hashline}")
                    # Mark this line as used
                    new_used_lines.add(best_line_num)
                else:
                    # Fallback: use the content as-is
                    hashline_diff_lines.append(line)

                current_new_line += 1
        else:
            # Unknown line type, keep as-is
            hashline_diff_lines.append(line)

    diff_text = "\n".join(hashline_diff_lines)
    return diff_text if diff_text.strip() else ""


def _apply_start_stitching(
    hashed_lines,
    start_idx,
    end_idx,
    replacement_lines,
    resolved_ops,
    current_resolved,
    max_overlap_check=3,
):
    """
    Check for overlapping lines BEFORE the replacement range and adjust start_idx and replacement_lines.

    This handles cases where the replacement text contains lines that already exist before the target range.
    It "stitches" the replacement at the matching line to prevent duplicate code structures.

    Args:
        hashed_lines: List of hashed lines from the file
        start_idx: Current start index of the replacement range
        end_idx: Current end index of the replacement range
        replacement_lines: List of replacement lines to insert
        resolved_ops: List of all resolved operations
        current_resolved: The current operation being processed
        max_overlap_check: Maximum number of lines to check for overlap (default: 3)

    Returns:
        tuple: (new_start_idx, new_replacement_lines) - adjusted start index and replacement lines
    """
    if start_idx > 0:
        # Get the lines before the replacement range (up to max_overlap_check lines)
        lines_before_range = hashed_lines[max(0, start_idx - max_overlap_check) : start_idx]

        # Strip hashlines from lines_before_range for comparison
        lines_before_range_stripped = [strip_hashline(line) for line in lines_before_range]

        # Normalize newlines for comparison
        lines_before_range_normalized = []
        for line in lines_before_range_stripped:
            if line.endswith("\n"):
                lines_before_range_normalized.append(line)
            else:
                lines_before_range_normalized.append(line + "\n")

        # Check for overlapping lines from the beginning of replacement_lines
        # We check each line from the beginning of replacement_lines to see if it exists
        # in lines_before_range, starting from the END (closest to replacement range)
        for i in range(min(max_overlap_check, len(replacement_lines))):
            # Check line from the beginning of replacement_lines
            line_idx = i

            # Get the line and strip hashline
            replacement_line = replacement_lines[line_idx]
            replacement_line_stripped = strip_hashline(replacement_line)

            # Normalize newline for comparison
            if not replacement_line_stripped.endswith("\n"):
                replacement_line_stripped += "\n"

            # Skip stitching for empty lines only
            # Empty lines are too common and don't indicate meaningful duplication
            trimmed_line = replacement_line_stripped.strip()
            if not trimmed_line:
                continue

            # Check if this line exists in lines_before_range_normalized
            # We need to find the LAST occurrence (closest to replacement range)
            # by searching from the end of the list
            match_index = -1
            for j in range(len(lines_before_range_normalized) - 1, -1, -1):
                if lines_before_range_normalized[j] == replacement_line_stripped:
                    match_index = j
                    break
            if match_index != -1:
                # Check if the replacement line also matches the line at start_idx
                # If it does, we shouldn't stitch to a line in lines_before_range
                # because we're replacing that line, not inserting before it
                line_at_start_idx = hashed_lines[start_idx] if start_idx < len(hashed_lines) else ""
                line_at_start_idx_stripped = strip_hashline(line_at_start_idx)
                if not line_at_start_idx_stripped.endswith("\n"):
                    line_at_start_idx_stripped += "\n"

                if replacement_line_stripped == line_at_start_idx_stripped:
                    # The replacement line matches the line being replaced
                    # Don't stitch to a line in lines_before_range
                    continue
                # Found a line that already exists before the range!
                # This is a non-contiguous match - we need to "stitch" the replacement
                # at this exact content match to prevent duplicate code structures

                # Truncate replacement_lines to exclude this line and any lines before it
                new_replacement_lines = replacement_lines[line_idx + 1 :]

                # Move the start_idx backward to include lines AFTER the matching line
                # match_index is 0-based in lines_before_range_normalized
                # lines_before_range ends at start_idx - 1
                # We want to include lines from (match_index + 1) onward
                # So we need to move start_idx back by (lines_before_count - match_index - 1)
                # This includes lines AFTER the matching line, not including the matching line itself
                lines_before_count = len(lines_before_range)
                backward_extension = lines_before_count - match_index - 1

                # If backward_extension is negative (shouldn't happen), set to 0
                if backward_extension < 0:
                    backward_extension = 0

                new_start_idx = start_idx - backward_extension

                # Check if extending backward would overlap with any other operation's range
                # We need to check all other resolved operations
                would_overlap = False
                for other_resolved in resolved_ops:
                    # Skip ourselves
                    if other_resolved["index"] == current_resolved["index"]:
                        continue

                    other_start = other_resolved["start_idx"]
                    other_end = other_resolved["end_idx"]

                    # Check if our new range would overlap with this other operation's range
                    # Overlap occurs if: new_start_idx <= other_end AND end_idx >= other_start
                    if new_start_idx <= other_end and end_idx >= other_start:
                        would_overlap = True
                        break

                # Only extend if it wouldn't create an overlap
                if not would_overlap:
                    start_idx = new_start_idx
                    replacement_lines = new_replacement_lines
                else:
                    # Can't extend backward due to overlap, but we can still truncate
                    # the replacement text to avoid duplication
                    replacement_lines = new_replacement_lines

                # We've found our stitching point, break out of the loop
                break
            # If no match found for this line, continue checking next line
            # (implicit continue - no else block needed)

    return start_idx, replacement_lines


def _apply_end_stitching(
    hashed_lines,
    start_idx,
    end_idx,
    replacement_lines,
    max_overlap_check=3,
):
    """
    Check for overlapping lines AFTER the replacement range and adjust end_idx and replacement_lines.

    This handles cases where the replacement text contains lines that already exist after the target range.
    It "stitches" the replacement at the matching line to prevent duplicate code structures.

    Args:
        hashed_lines: List of hashed lines from the file
        start_idx: Current start index of the replacement range
        end_idx: Current end index of the replacement range
        replacement_lines: List of replacement lines to insert
        max_overlap_check: Maximum number of lines to check for overlap (default: 3)

    Returns:
        tuple: (new_end_idx, new_replacement_lines) - adjusted end index and replacement lines
    """
    if end_idx + 1 < len(hashed_lines):
        # Get the lines after the replacement range (up to max_overlap_check lines)
        lines_after_range = hashed_lines[end_idx + 1 : end_idx + 1 + max_overlap_check]

        # Strip hashlines from lines_after_range for comparison
        lines_after_range_stripped = [strip_hashline(line) for line in lines_after_range]

        # Normalize newlines for comparison
        # Some lines might not have newlines (e.g., last line of file)
        lines_after_range_normalized = []
        for line in lines_after_range_stripped:
            if line.endswith("\n"):
                lines_after_range_normalized.append(line)
            else:
                lines_after_range_normalized.append(line + "\n")

        # Check for non-contiguous overlap from the end of replacement_lines
        # We check each line from the end of replacement_lines to see if it exists
        # anywhere in lines_after_range (not just at the beginning)
        # This prevents duplication of lines that already exist after the range
        for i in range(min(max_overlap_check, len(replacement_lines))):
            # Check line from the end of replacement_lines
            line_idx = len(replacement_lines) - 1 - i
            if line_idx < 0:
                break

            # Get the line and strip hashline
            replacement_line = replacement_lines[line_idx]
            replacement_line_stripped = strip_hashline(replacement_line)

            # Normalize newline for comparison
            if not replacement_line_stripped.endswith("\n"):
                replacement_line_stripped += "\n"

            # Skip stitching for empty lines only
            # Empty lines are too common and don't indicate meaningful duplication
            trimmed_line = replacement_line_stripped.strip()
            if not trimmed_line:
                continue

            # Check if this line exists anywhere in lines_after_range_normalized
            try:
                match_index = lines_after_range_normalized.index(replacement_line_stripped)
                # Found a line that already exists after the range!
                # This is a non-contiguous match - we need to "stitch" the replacement
                # at this exact content match to prevent duplicate code structures

                # Truncate replacement_lines to exclude this line and any lines after it
                new_replacement_lines = replacement_lines[:line_idx]

                # Extend the replacement range to include the matching line
                # match_index is 0-based in lines_after_range_normalized
                # lines_after_range starts at end_idx + 1
                # So we need to extend end_idx by match_index to include
                # all lines up to but NOT including the matching line
                # (we stitch AT the matching line, not THROUGH it)
                extension = match_index
                end_idx = end_idx + extension

                replacement_lines = new_replacement_lines

                # We've found our stitching point, break out of the loop
                break
            except ValueError:
                # Line not found in lines_after_range_normalized, continue checking
                pass

    return end_idx, replacement_lines


def _apply_range_shifting(hashed_lines, resolved_ops):
    """
    Apply content-aware range expansion/shifting for replace operations.

    Adjusts ranges if replacement text includes boundary context to prevent
    duplication and ensure proper stitching of code.

    Args:
        hashed_lines: List of hashed lines from the file
        resolved_ops: List of resolved operation dictionaries

    Returns:
        Updated resolved_ops with adjusted ranges
    """
    for i, resolved in enumerate(resolved_ops):
        op = resolved["op"]
        if op["operation"] == "replace" and op.get("text"):
            replacement_lines = op["text"].splitlines(keepends=True)
            if not replacement_lines:
                continue

            # Check for downward expansion/shift (end_idx)
            if resolved["end_idx"] < len(hashed_lines) - 1:
                last_rep_line = strip_hashline(replacement_lines[-1])
                if not last_rep_line.endswith("\n"):
                    last_rep_line += "\n"

                file_line_after = strip_hashline(hashed_lines[resolved["end_idx"] + 1])
                if not file_line_after.endswith("\n"):
                    file_line_after += "\n"

                if last_rep_line == file_line_after:
                    # Only expand/shift if the last line of replacement is NOT the same as the last line of the range
                    file_line_end = strip_hashline(hashed_lines[resolved["end_idx"]])
                    if not file_line_end.endswith("\n"):
                        file_line_end += "\n"

                    if last_rep_line != file_line_end:
                        # Determine if we should expand or shift
                        range_len = resolved["end_idx"] - resolved["start_idx"] + 1
                        should_expand = len(replacement_lines) > range_len

                        new_start = (
                            resolved["start_idx"] if should_expand else resolved["start_idx"] + 1
                        )
                        new_end = resolved["end_idx"] + 1

                        # Safety check: ensure new range doesn't overlap with another operation
                        overlap = False
                        for j, other in enumerate(resolved_ops):
                            if i != j and (
                                (other["start_idx"] <= new_start <= other["end_idx"])
                                or (other["start_idx"] <= new_end <= other["end_idx"])
                            ):
                                overlap = True
                                break
                        if not overlap:
                            resolved["start_idx"] = new_start
                            resolved["end_idx"] = new_end

            # Check for upward expansion/shift (start_idx)
            if resolved["start_idx"] > 0:
                first_rep_line = strip_hashline(replacement_lines[0])
                if not first_rep_line.endswith("\n"):
                    first_rep_line += "\n"

                file_line_before = strip_hashline(hashed_lines[resolved["start_idx"] - 1])
                if not file_line_before.endswith("\n"):
                    file_line_before += "\n"

                if first_rep_line == file_line_before:
                    # Only expand/shift if the first line of replacement is NOT the same as the first line of the range
                    file_line_start = strip_hashline(hashed_lines[resolved["start_idx"]])
                    if not file_line_start.endswith("\n"):
                        file_line_start += "\n"

                    if first_rep_line != file_line_start:
                        # Determine if we should expand or shift
                        # If replacement is longer than range, expand. Otherwise shift.
                        range_len = resolved["end_idx"] - resolved["start_idx"] + 1
                        should_expand = len(replacement_lines) > range_len

                        new_start = resolved["start_idx"] - 1
                        new_end = resolved["end_idx"] if should_expand else resolved["end_idx"] - 1

                        # Safety check: ensure new range doesn't overlap with another operation
                        overlap = False
                        for j, other in enumerate(resolved_ops):
                            if i != j and (
                                (other["start_idx"] <= new_start <= other["end_idx"])
                                or (other["start_idx"] <= new_end <= other["end_idx"])
                            ):
                                overlap = True
                                break
                        if not overlap:
                            resolved["start_idx"] = new_start
                            resolved["end_idx"] = new_end

    return resolved_ops


# Regex configuration
RE_CODE_NOISE = r'(#.*|//.*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')'


def get_brace_balance(lines_to_check: list[str]) -> int:
    """
    Calculates the net curly brace debt of a list of lines.
    Automatically strips hashlines, comments, and string literals.
    """
    text = "".join(lines_to_check)
    clean_code = strip_hashline(text)
    clean_code = re.sub(RE_CODE_NOISE, "", clean_code)
    return clean_code.count("{") - clean_code.count("}")


def _apply_closure_safeguard(hashed_lines, resolved_ops):
    """
    Enhanced closure safeguard with dynamic bidirectional search.
    """
    # Tune these to adjust how far the 'healing' logic searches
    MAX_LOOK_DOWN = 5
    # Note: We'll calculate the actual MAX_LOOK_UP per operation
    # to ensure we don't scan past the start_idx.

    for i, resolved in enumerate(resolved_ops):
        op = resolved["op"]
        if op["operation"] not in {"replace", "delete"}:
            continue

        replacement_text = op.get("text", "") or ""
        replacement_lines = replacement_text.splitlines(keepends=True)

        # --- PHASE 1: BIDIRECTIONAL STRUCTURAL HEALING ---
        if get_brace_balance([replacement_text]) == 0:
            start_idx = resolved["start_idx"]
            orig_end_idx = resolved["end_idx"]

            if get_brace_balance(hashed_lines[start_idx : orig_end_idx + 1]) != 0:
                # Dynamic Search List Generation
                # We limit look-up so we don't scan before the start_idx
                actual_max_up = orig_end_idx - start_idx
                actual_max_down = max(MAX_LOOK_DOWN, orig_end_idx - start_idx)
                search_offsets = []

                # Generate alternating offsets: [1, -1, 2, -2, ... N]
                for dist in range(1, max(actual_max_down, actual_max_up) + 1):
                    if dist <= actual_max_down:
                        search_offsets.append(dist)
                    if dist <= actual_max_up:
                        search_offsets.append(-dist)

                for offset in search_offsets:
                    candidate_end = orig_end_idx + offset

                    # Safety: check bounds and avoid overlapping other ops
                    if candidate_end < start_idx or candidate_end >= len(hashed_lines):
                        continue

                    if any(
                        j != i and (other["start_idx"] <= candidate_end <= other["end_idx"])
                        for j, other in enumerate(resolved_ops)
                    ):
                        continue

                    if get_brace_balance(hashed_lines[start_idx : candidate_end + 1]) == 0:
                        resolved["end_idx"] = candidate_end
                        break

        # --- PHASE 2: CONTRACTION (Indentation Guard) ---
        # Prevents replacing an outer-scope brace if the replacement text already
        # includes its own correctly indented closer.
        if not replacement_lines:
            continue

        last_repl_line = strip_hashline(replacement_lines[-1])
        last_repl_stripped = last_repl_line.strip().rstrip(";,")

        if last_repl_stripped and last_repl_stripped[-1] in "})]":
            # Calculate replacement indent
            repl_indent = len(last_repl_line) - len(last_repl_line.lstrip(" \t"))

            if resolved["end_idx"] < len(hashed_lines):
                end_line = strip_hashline(hashed_lines[resolved["end_idx"]])
                check_end = end_line.strip().rstrip(";,")

                if check_end and check_end[-1] in "})]":
                    # Calculate indent of the existing brace in the file
                    file_indent = len(end_line) - len(end_line.lstrip(" \t"))

                    # If the file's brace is less indented, it belongs to an outer scope
                    if file_indent < repl_indent and resolved["end_idx"] > resolved["start_idx"]:
                        new_end_idx = resolved["end_idx"] - 1

                        # Safety: don't contract into another operation's territory
                        if not any(
                            j != i and (other["start_idx"] <= new_end_idx <= other["end_idx"])
                            for j, other in enumerate(resolved_ops)
                        ):
                            resolved["end_idx"] = new_end_idx

    return resolved_ops


def _merge_replace_operations(resolved_ops):
    """
    Merge contiguous or overlapping replace operations.
    """
    if len(resolved_ops) < 2:
        return resolved_ops

    # Sort by start_idx to find contiguous operations
    resolved_ops.sort(key=lambda x: (x["start_idx"], x["end_idx"]))

    merged = []
    for current in resolved_ops:
        if not merged:
            merged.append(current)
            continue

        prev = merged[-1]

        # Only merge replace operations that have text
        if (
            prev["op"]["operation"] == "replace"
            and current["op"]["operation"] == "replace"
            and prev["op"].get("text") is not None
            and current["op"].get("text") is not None
        ):
            # Check if they are contiguous or overlapping
            # Contiguous: prev.end_idx == current.start_idx OR prev.end_idx + 1 == current.start_idx
            if prev["end_idx"] >= current["start_idx"] - 1:
                prev_text = prev["op"]["text"]
                curr_text = current["op"]["text"]

                prev_lines = prev_text.splitlines(keepends=True)
                curr_lines = curr_text.splitlines(keepends=True)

                # Find longest overlap between suffix of prev and prefix of current
                max_check = min(len(prev_lines), len(curr_lines))
                overlap_len = 0
                for i in range(1, max_check + 1):
                    if prev_lines[-i:] == curr_lines[:i]:
                        overlap_len = i

                if overlap_len > 0:
                    new_text = "".join(prev_lines) + "".join(curr_lines[overlap_len:])
                else:
                    # No overlap, just concatenate
                    new_text = prev_text + curr_text

                # Update prev
                prev["end_idx"] = max(prev["end_idx"], current["end_idx"])
                prev["op"]["text"] = new_text

                # Track merged indices
                if "merged_indices" not in prev:
                    prev["merged_indices"] = [prev["index"]]
                prev["merged_indices"].append(current["index"])
                continue

        merged.append(current)

    return merged


def _honor_cancellations(resolved_ops):
    """
    Handle cancel operations by removing all operations sharing the same start and end hashpos markers.

    Args:
        resolved_ops: List of resolved operations with 'index', 'start_idx', 'end_idx', and 'op' keys

    Returns:
        List of operations with cancel operations processed and appropriate operations removed
    """
    # First, identify all cancel operations
    cancel_ops = []
    other_ops = []

    for op in resolved_ops:
        if op["op"].get("operation") == "cancel":
            cancel_ops.append(op)
        else:
            other_ops.append(op)

    # If there are no cancel operations, return the original list
    if not cancel_ops:
        return resolved_ops

    # Sort cancel operations by their original index (ascending)
    cancel_ops.sort(key=lambda x: x["index"])

    for cancel_op in cancel_ops:
        cancel_start_idx = cancel_op["start_idx"]
        cancel_end_idx = cancel_op["end_idx"]
        cancel_index = cancel_op["index"]

        # Filter out operations that:
        # 1. Have index < cancel_index (come before the cancel operation)
        # 2. Have the same start_idx and end_idx as the cancel operation
        # 3. Are not themselves cancel operations
        filtered_ops = []
        for op in other_ops:
            if op["index"] >= cancel_index:
                # Operations after or at the same index as cancel should be kept
                filtered_ops.append(op)
            elif op["start_idx"] == cancel_start_idx and op["end_idx"] == cancel_end_idx:
                # Operation before cancel with same range - remove it
                continue
            else:
                # Operation before cancel with different range - keep it
                filtered_ops.append(op)

        # Update other_ops for the next cancel operation
        other_ops = filtered_ops

    # Return remaining operations (excluding the cancel operations themselves)
    return other_ops


def _deduplicate_ranges(resolved_ops):
    """
    Deduplicate operations that start on the same line.
    If multiple operations start on the same line, keep only the latest one.
    This handles cases where a model might generate multiple operations for the same line while "thinking"
    """
    deduplicated_ops = []
    # Group operations by start_idx
    start_idx_to_ops = {}
    # Loop to group operations by their start index
    for op in resolved_ops:
        start_idx = op["start_idx"]
        if start_idx not in start_idx_to_ops:
            start_idx_to_ops[start_idx] = []
        start_idx_to_ops[start_idx].append(op)

    # For each start_idx, keep only the operation with the highest original index (latest in the list)
    # Loop to select only the latest operation per start index
    for start_idx, ops in start_idx_to_ops.items():
        # Sort by original index descending and take the first one
        ops.sort(key=lambda x: x["index"], reverse=True)
        deduplicated_ops.append(ops[0])

    return deduplicated_ops


def _honor_special_markers(resolved_ops):
    """
    Honor special markers (@000 and 000@) in operations.

    Rules:
    1. If any operation has "@000" and "000@" as start and end markers,
       keep only that operation since it replaces the whole file.
    2. If an operation has "@000" and a normal end hash, remove any operations
       starting between beginning of file and that end hash.
    3. If an operation has a normal start hash and "000@" as end hash,
       remove any operations ending between that start hash and end of file.
    """
    if not resolved_ops:
        return resolved_ops

    # Check for full file replacement (@000 to 000@)
    for op in resolved_ops:
        original_op = op["op"]
        start_hash = original_op.get("start_line_hash", "")
        end_hash = original_op.get("end_line_hash", "")

        if start_hash == "@000" and end_hash == "000@":
            # This operation replaces the entire file, keep only this one
            return [op]

    # Track which operations have special markers
    has_special_marker = [False] * len(resolved_ops)
    for i, op in enumerate(resolved_ops):
        original_op = op["op"]
        start_hash = original_op.get("start_line_hash", "")
        end_hash = original_op.get("end_line_hash", "")
        if start_hash == "@000" or end_hash == "000@":
            has_special_marker[i] = True

    # Mark operations for removal
    ops_to_remove = set()

    for i, op in enumerate(resolved_ops):
        original_op = op["op"]
        start_hash = original_op.get("start_line_hash", "")
        end_hash = original_op.get("end_line_hash", "")

        if start_hash == "@000":
            # Operation starts at beginning of file
            # Remove any operations starting before or at this operation's end_idx
            # (except other operations with special markers)
            end_idx = op["end_idx"]
            for j, other_op in enumerate(resolved_ops):
                if j != i and not has_special_marker[j]:
                    other_start_idx = other_op["start_idx"]
                    if other_start_idx <= end_idx:
                        ops_to_remove.add(j)
        elif end_hash == "000@":
            # Operation ends at end of file
            # Remove any operations ending at or after this operation's start_idx
            # (except other operations with special markers)
            start_idx = op["start_idx"]
            for j, other_op in enumerate(resolved_ops):
                if j != i and not has_special_marker[j]:
                    other_end_idx = other_op["end_idx"]
                    if other_end_idx >= start_idx:
                        ops_to_remove.add(j)

    # Filter out operations marked for removal
    result = []
    for i, op in enumerate(resolved_ops):
        if i not in ops_to_remove:
            result.append(op)

    return result


def _merged_contained_ranges(resolved_ops):
    """
    Discard inner ranges that are completely contained within outer ranges.
    This prevents redundant operations and potential errors.
    """
    optimized_ops = []
    # Loop to remove operations that are completely contained within other operations
    for i, op_a in enumerate(resolved_ops):
        keep_op = True

        # Check if this operation is contained within any other operation
        for j, op_b in enumerate(resolved_ops):
            if i == j:
                continue

            # Check if op_a is completely inside op_b
            # op_a is inside op_b if:
            # op_b.start_idx <= op_a.start_idx and op_a.end_idx <= op_b.end_idx
            if op_b["start_idx"] <= op_a["start_idx"] and op_a["end_idx"] <= op_b["end_idx"]:
                # Special case: operations with the same indices but different types
                # should both be kept (e.g., replace and insert at same line)
                if (
                    op_a["start_idx"] == op_b["start_idx"]
                    and op_a["end_idx"] == op_b["end_idx"]
                    and op_a["op"]["operation"] != op_b["op"]["operation"]
                ):
                    # Keep both operations if they have different types
                    continue
                # op_a is inside op_b, discard op_a
                keep_op = False
                break

        if keep_op:
            optimized_ops.append(op_a)

    return optimized_ops


def sort_ranges(op):
    start_idx = op["start_idx"]
    # Operation type priority: insert (0), replace (1), delete (2)
    # Lower priority number means applied first
    op_type = op["op"]["operation"]
    if op_type == "insert":
        priority = 0
    elif op_type == "replace":
        priority = 1
    else:  # delete
        priority = 2
    # Sort by start_idx descending, then priority ascending
    return (-start_idx, priority)


def apply_hashline_operations(
    original_content: str,
    operations: list,
) -> tuple[str, list, list]:
    """
    Apply multiple hashline operations sequentially.

    This function hashes the content once, resolves all operations to line indices,
    and applies them in reverse order (bottom-to-top) to avoid line number shifts.

    Args:
        original_content: Original file content
        operations: List of operation dictionaries

    Returns:
        tuple: (modified_content, successful_operations, failed_operations)
        - modified_content: Modified content after applying all operations
        - successful_operations: List of successfully applied operation indices
        - failed_operations: List of dictionaries with failed operation info
          Each dict contains: {"index": int, "error": str, "operation": dict}
    """
    # Normalize hashline inputs in operations
    normalized_operations = []
    failed_ops = []
    # Loop through each operation to normalize hashline strings
    for i, op in enumerate(operations):
        try:
            normalized_op = op.copy()
            # Normalize start line hash to ensure consistent format
            normalized_op["start_line_hash"] = normalize_hashline(op["start_line_hash"])
            if "end_line_hash" in op:
                # Normalize end line hash if present
                normalized_op["end_line_hash"] = normalize_hashline(op["end_line_hash"])
            normalized_operations.append(normalized_op)
        except Exception as e:
            failed_ops.append({"index": i, "error": str(e), "operation": op})

    if not normalized_operations:
        return original_content, [], failed_ops

    # Apply hashline to original content once
    # This converts content to hashed lines for line tracking
    hashed_content = hashline(original_content)
    hashed_lines = hashed_content.splitlines(keepends=True)

    # Resolve all operations to indices first
    resolved_ops = []
    # Loop to convert hashline references to line indices
    for i, op in enumerate(normalized_operations):
        try:
            if op["operation"] == "insert":
                start_hash_fragment, start_line_num_str, start_line_num = parse_hashline(
                    op["start_line_hash"]
                )

                if start_hash_fragment == "@000":
                    # Genesis anchor - if empty, insert at 0. If not empty, insert at -1
                    # so that hashed_lines.insert(found_start + 1, text) inserts at 0.
                    found_start = 0 if not hashed_lines else -1
                else:
                    # Try exact match first for insert operations
                    found_start = find_hashline_by_exact_match(
                        hashed_lines, start_hash_fragment, start_line_num_str
                    )

                    # if found_start is None:
                    #    # Fall back to fragment matching if exact match fails
                    #    found_start = find_hashline_by_fragment(
                    #        hashed_lines, start_hash_fragment, start_line_num
                    #    )

                    if found_start is None:
                        raise HashlineError(
                            f"Start line hash fragment '{start_hash_fragment}' not found in file"
                        )

                resolved_ops.append(
                    {"index": i, "start_idx": found_start, "end_idx": found_start, "op": op}
                )
            else:
                # Use find_hashline_range for replace/delete to leverage its robust logic
                # which handles exact matches (including line numbers) and relative offsets

                start_hash = op["start_line_hash"]
                end_hash = op.get("end_line_hash")

                # if "text" in op and op["text"]:
                #    replacement_lines = op["text"].splitlines(keepends=True)
                #    if replacement_lines:
                #        # Try content match for start line
                #        match = find_hashline_by_content_match(
                #            hashed_lines, start_hash, replacement_lines[0]
                #        )
                #        if match:
                #            start_hash = match
                #
                #        # Try content match for end line
                #        if end_hash:
                #            match = find_hashline_by_content_match(
                #                hashed_lines, end_hash, replacement_lines[-1]
                #            )
                #            if match:
                #                end_hash = match

                # Fall back to original find_hashline_range
                try:
                    # Get replacement text for replace operations, None for delete operations
                    replacement_text = op.get("text")
                    found_start, found_end = find_hashline_range(
                        hashed_lines,
                        start_hash,
                        end_hash,
                        allow_exact_match=True,
                        replacement_text=replacement_text,
                    )
                    resolved_ops.append(
                        {"index": i, "start_idx": found_start, "end_idx": found_end, "op": op}
                    )
                except Exception as e:
                    raise HashlineError(
                        f"Could not resolve hash range {start_hash}...{end_hash}: {str(e)}"
                    )

        except Exception as e:
            failed_ops.append({"index": i, "error": str(e), "operation": op})

    # Honor cancellations: remove operations that are cancelled by later cancel operations
    resolved_ops = _honor_cancellations(resolved_ops)
    # Deduplicate: if multiple operations start on the same line, keep only the latest one
    # This handles cases where a model might generate multiple operations for the same line while "thinking"
    resolved_ops = _deduplicate_ranges(resolved_ops)
    # Honor special markers: handle @000 and 000@ special markers for whole-file or partial-file operations
    resolved_ops = _honor_special_markers(resolved_ops)
    # Optimize: discard inner ranges that are completely contained within outer ranges
    # This prevents redundant operations and potential errors
    resolved_ops = _merged_contained_ranges(resolved_ops)
    # Merge contiguous replace operations
    resolved_ops = _merge_replace_operations(resolved_ops)
    # Apply content-aware range expansion/shifting for replace operations
    # resolved_ops = _apply_range_shifting(hashed_lines, resolved_ops)
    # Apply closure safeguard for braces/brackets
    resolved_ops = _apply_closure_safeguard(hashed_lines, resolved_ops)

    # Sort by start_idx descending to apply from bottom to top
    # When operations have same start_idx, apply in order: insert, replace, delete
    # This ensures correct behavior when multiple operations target the same line
    resolved_ops.sort(key=sort_ranges)

    successful_ops = []
    # Loop to apply operations in sorted order (bottom-to-top)
    for resolved in resolved_ops:
        try:
            op = resolved["op"]
            start_idx = resolved["start_idx"]
            end_idx = resolved["end_idx"]

            if op["operation"] == "insert":
                text = op["text"]
                if text and not text.endswith("\n"):
                    text += "\n"
                # Special handling for empty hashed_lines (genesis anchor case)
                if hashed_lines:
                    if not hashed_lines[start_idx].endswith("\n"):
                        hashed_lines[start_idx] += "\n"
                    hashed_lines.insert(start_idx + 1, text)
                else:
                    # Empty content with genesis anchor - just add the text
                    hashed_lines.append(text)
            elif op["operation"] == "delete":
                del hashed_lines[start_idx : end_idx + 1]
            elif op["operation"] == "replace":
                # If operation ends with "000@", ensure end_idx is at actual end of file
                if op.get("end_line_hash") == "000@":
                    end_idx = len(hashed_lines) - 1

                text = op["text"]
                if text:
                    # Split text into lines, preserving trailing newline behavior
                    # If text doesn't end with newline, we add one to ensure proper line separation
                    if not text.endswith("\n"):
                        text += "\n"
                    # Split into lines and replace the range
                    replacement_lines = text.splitlines(keepends=True)

                    # Check for overlapping lines to prevent duplication
                    # This handles cases where the model underspecifies the range and
                    # the replacement text includes lines that already exist after the range
                    max_overlap_check = 2  # Check up to 2 lines for overlap

                    # Check for overlapping lines BEFORE the range (bidirectional stitching)
                    start_idx, replacement_lines = _apply_start_stitching(
                        hashed_lines,
                        start_idx,
                        end_idx,
                        replacement_lines,
                        resolved_ops,
                        resolved,
                        max_overlap_check,
                    )

                    # Now check for overlapping lines AFTER the range
                    end_idx, replacement_lines = _apply_end_stitching(
                        hashed_lines, start_idx, end_idx, replacement_lines, max_overlap_check
                    )

                    hashed_lines[start_idx : end_idx + 1] = replacement_lines
                else:
                    # Empty text - replace with nothing (delete)
                    hashed_lines[start_idx : end_idx + 1] = []

            if "merged_indices" in resolved:
                successful_ops.extend(resolved["merged_indices"])
            else:
                successful_ops.append(resolved["index"])
        except Exception as e:
            failed_ops.append(
                {"index": resolved["index"], "error": str(e), "operation": resolved["op"]}
            )

    # Join and strip hashlines
    result_with_hashes = "".join(hashed_lines)
    # Remove hashline markers from final result
    result = strip_hashline(result_with_hashes)

    # Respect original trailing newline
    if original_content.endswith("\n") and result and not result.endswith("\n"):
        # Original ends with newline but result doesn't - add one
        result += "\n"
    elif not original_content.endswith("\n") and result.endswith("\n"):
        # Original doesn't end with newline but result does - remove it
        result = result[:-1]

    return result, successful_ops, failed_ops


def apply_hashline_operation(
    original_content,
    start_line_hash,
    end_line_hash=None,
    operation="replace",
    text=None,
):
    """
    Apply an operation (replace, insert, delete) using hashline ranges.

    Uses regex/find to locate hashline ranges in the content and applies
    the specified operation directly.

    Note: Ranges are inclusive of both start and end boundaries.
    For example, a range from line 3 to line 6 includes lines 3, 4, 5, and 6.

    Args:
        original_content: Original file content
        start_line_hash: Hashline format for start line: "{4 char hash}"
        end_line_hash: Hashline format for end line: "{4 char hash}" (optional for insert operations)
        operation: One of "replace", "insert", or "delete"
        text: Text to insert or replace with (required for replace/insert operations)

    Returns:
        Modified content after applying the operation

    Raises:
        HashlineError: If hashline verification fails or operation is invalid
    """
    # Handle empty content as a special case
    if original_content == "" or original_content is None:
        if operation == "insert" or operation == "replace":
            if text is None:
                raise HashlineError(
                    f"Text parameter is required for '{operation}' operation on empty file"
                )
            # For empty files, just return the text to insert/replace with
            return text if text.endswith("\n") else text + "\n"
        elif operation == "delete":
            # Deleting from empty file returns empty
            return ""
        else:
            # Should not happen due to validation above, but handle anyway
            raise HashlineError(f"Invalid operation '{operation}' for empty file")

    # Validate operation
    valid_operations = {"replace", "insert", "delete"}
    if operation not in valid_operations:
        raise HashlineError(
            f"Invalid operation '{operation}'. Must be one of: {', '.join(valid_operations)}"
        )

    # Validate text parameter for replace/insert operations
    if operation in {"replace", "insert"} and text is None:
        raise HashlineError(f"Text parameter is required for '{operation}' operation")

    # Build operation dictionary for apply_hashline_operations
    op_dict = {
        "start_line_hash": start_line_hash,
        "operation": operation,
    }

    if end_line_hash is not None:
        op_dict["end_line_hash"] = end_line_hash

    if text is not None:
        op_dict["text"] = text

    # Call apply_hashline_operations with single operation
    modified_content, successful_ops, failed_ops = apply_hashline_operations(
        original_content, [op_dict]
    )

    # Check if operation failed
    if failed_ops:
        raise HashlineError(failed_ops[0]["error"])

    return modified_content
