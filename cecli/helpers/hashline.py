import difflib
import json
import re
from collections import Counter

from cecli.helpers.hashpos.hashpos import (  # noqa
    HASH_DELIMITER,
    UNIQUE_HASH_DELIMITER,
    HashPos,
)

HASHLINE_PREFIX_RE = HashPos.HASH_PREFIX_RE


class ContentHashError(Exception):
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


def hashline_formatted(
    text: str, file_name: str, total_lines: int = 0, start_line: int = 1
) -> tuple[str, str]:
    """
    Generate hashline-formatted content and return it as both raw hashline text and a JSON structure.

    Args:
        text: Input text
        file_name: The file name or path
        partial: Whether the content represents a partial file
        start_line: Starting line number (default 1)

    Returns:
        A tuple of (raw_hashline_text, json_text):
        - raw_hashline_text: The HashPos-prefixed content (same as hashline())
        - json_text: JSON-formatted string with file_name, start_line, end_line, partial, and
          prefixed_contents
    """
    hp = HashPos(text)
    prefixed = hp.format_content(start_line=start_line)
    end_line = start_line + hp.total - 1

    result = {
        "file_name": file_name,
        "start_line": start_line,
        "end_line": end_line,
        "total_lines": total_lines if total_lines else hp.total,
        "prefixed_contents": prefixed,
    }

    return prefixed, json.dumps(result, ensure_ascii=False)


# int_to_2digit_52 removed as it is no longer used by the HashPos engine.


def strip_hashline(text: str) -> str:
    """
    Remove HashPos prefixes from the start of every line.
    """
    if text is None:
        return ""
    return HashPos.strip_prefix(text)


def normalize_hashline(hashline_str: str, throw=True) -> str:
    """
    Normalize a hashline string to the content id hash fragment.
    """
    if hashline_str in ("@000", "000@"):
        return hashline_str
    try:
        return HashPos.normalize(hashpos_str=hashline_str, throw=throw)
    except ValueError as e:
        raise ContentHashError(str(e))


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
        ContentHashError: If range cannot be found or is invalid
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
            raise ContentHashError(f"End line hash fragment '{end_hash}' not found in file")
        return 0, ends[0]

    # Handle special marker "000@" (bottom of file) for end position
    if end_hash == "000@":
        # We need to resolve start hash normally, then set end to bottom of file
        source_text = HashPos.strip_prefix("".join(hashed_lines))
        hp = HashPos(source_text)
        starts = hp.resolve_to_lines(start_hash)
        if not starts:
            raise ContentHashError(f"Start line hash fragment '{start_hash}' not found in file")
        found_start = starts[0]

        # Set end to bottom of file
        if not hashed_lines:
            return 0, 0
        found_end = len(hashed_lines) - 1

        # Verify start <= end
        if found_start > found_end:
            raise ContentHashError(
                f"Invalid range: start line {found_start} is after end line {found_end}"
            )
        return found_start, found_end

    source_text = HashPos.strip_prefix("".join(hashed_lines))
    hp = HashPos(source_text)

    try:
        found_start, found_end = hp.resolve_range(start_hash, end_hash)
        return found_start, found_end
    except ValueError as e:
        raise ContentHashError(str(e))


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
        ContentHashError: If hashline verification fails
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


def resolve_content_to_hashline_ids(
    original_content: str,
    start_value: str,
    end_value: str = None,
    start_hint_line: int | None = None,
    exact: bool = True,
) -> tuple:
    """
    Resolve potential line content values to proper hashline content IDs.

    If start_value or end_value does not look like a content ID (hash),
    search for the content in the original file using exact line matching
    (or substring matching when exact=False).

    For start_value: Only resolves if exactly one line exactly matches it as a
    substring (unique match).

    For end_value: Resolves by finding the closest line (by position) to
    the resolved start line that exactly matches it.

    This handles the case where LLMs return entire line content or fragments
    instead of content IDs in edit parameters.

    Args:
        original_content: Original file content (without hash prefixes)
        start_value: The start_line value from the edit
        end_value: The end_line value from the edit (optional)
        start_hint_line: 0-based line number hint used to disambiguate
                        non-unique start_value matches (optional)

    Returns:
        tuple: (resolved_start, resolved_end) with hash IDs or original values
               unchanged if resolution is not possible
    """
    if not original_content:
        return start_value, end_value

    def _looks_like_content_id(value: str) -> bool:
        """Check if value looks like a content ID rather than line content."""
        if value in ("@000", "000@"):
            return True
        # Try to normalize - if it succeeds, it's a valid content ID
        try:
            normalize_hashline(value)
            return True
        except (ContentHashError, ValueError):
            return False

    def _find_exact_line_matches(lines, value):
        """Find all line indices where the value matches the line content."""
        if exact:
            return [i for i, line in enumerate(lines) if line == value]
        value_stripped = value.strip()
        return [i for i, line in enumerate(lines) if value_stripped in line]

    def _find_multiline_match(lines, value):
        """Find the start index where the full multiline value matches consecutive lines."""
        if exact:
            value_lines = value.splitlines()
        else:
            value_lines = value.strip().splitlines()
        if len(value_lines) <= 1:
            return None
        for i in range(len(lines) - len(value_lines) + 1):
            if exact:
                if all(lines[i + j] == value_lines[j] for j in range(len(value_lines))):
                    return i
            else:
                if all(value_lines[j].strip() in lines[i + j] for j in range(len(value_lines))):
                    return i
        return None

    def _resolve_to_hash_id(lines, idx, hp):
        """Generate a hash ID for the line at the given index."""
        line_text = lines[idx]
        # Compute the occurrence number (1-based) of this line instance
        occurrence = 1 + sum(1 for i in range(idx) if lines[i] == line_text)
        hash_id = hp.generate_public_id(line_text, idx, occurrence)
        return HashPos.get_wrapped_id(hash_id)

    lines = original_content.splitlines()
    hp = HashPos(original_content)

    # Resolve start_value first (must be unique substring match)
    resolved_start = start_value
    resolved_start_idx = None

    if start_value is not None and not _looks_like_content_id(start_value):
        # For multiline values, try full multiline match first
        first_line = start_value.splitlines()[0] if start_value.splitlines() else start_value
        multiline_start_idx = _find_multiline_match(lines, start_value)
        if multiline_start_idx is not None:
            resolved_start_idx = multiline_start_idx
            resolved_start = _resolve_to_hash_id(lines, resolved_start_idx, hp)
        else:
            # Fall back to first line substring matching
            containing_indices = _find_exact_line_matches(lines, first_line)
            if len(containing_indices) == 1:
                resolved_start_idx = containing_indices[0]
                resolved_start = _resolve_to_hash_id(lines, resolved_start_idx, hp)
            elif len(containing_indices) > 1 and start_hint_line is not None:
                # Multiple matches - pick closest to hint line
                resolved_start_idx = min(
                    containing_indices,
                    key=lambda idx: abs(idx - start_hint_line),
                )
                resolved_start = _resolve_to_hash_id(lines, resolved_start_idx, hp)
            else:
                # Fallback: the value may be line content whose whitespace was
                # normalized (e.g. stripped indentation). Resolve it against a
                # single unique line — mirroring apply_hashline_operations — so
                # the preview resolves exactly like the actual edit.
                unique_resolved = _try_resolve_as_unique_line(hp, first_line)
                if unique_resolved is not None:
                    resolved_start = unique_resolved
                    try:
                        candidates = hp.resolve_to_lines(normalize_hashline(unique_resolved))
                        if candidates:
                            resolved_start_idx = candidates[0]
                    except (ContentHashError, ValueError):
                        pass
    elif start_value is not None and _looks_like_content_id(start_value):
        # Already a content ID - try to resolve it to find the line position
        # for proximity matching with end_value
        try:
            normalized = normalize_hashline(start_value)
            candidates = hp.resolve_to_lines(normalized)
            if candidates:
                resolved_start_idx = candidates[0]
        except (ContentHashError, ValueError):
            # The value looks like a content ID but normalized to UNIQUE_HASH_DELIMITER which can't
            # be spatially resolved. Fall back: strip the UNIQUE_HASH_DELIMITER prefix and treat the
            # remaining content as line content to match.
            content = HashPos.strip_prefix(start_value)
            if content != start_value and content.strip():
                containing_indices = _find_exact_line_matches(lines, content)
                if len(containing_indices) == 1:
                    resolved_start_idx = containing_indices[0]
                    resolved_start = _resolve_to_hash_id(lines, resolved_start_idx, hp)
                elif len(containing_indices) > 1 and start_hint_line is not None:
                    # Multiple matches - pick closest to hint line
                    resolved_start_idx = min(
                        containing_indices,
                        key=lambda idx: abs(idx - start_hint_line),
                    )
                    resolved_start = _resolve_to_hash_id(lines, resolved_start_idx, hp)

    # Resolve end_value based on proximity to start position
    resolved_end = end_value

    if end_value is not None and not _looks_like_content_id(end_value):
        # For multiline values, try full multiline match first
        first_line = end_value.splitlines()[0] if end_value.splitlines() else end_value
        multiline_end_idx = _find_multiline_match(lines, end_value)
        if multiline_end_idx is not None:
            idx = multiline_end_idx
            resolved_end = _resolve_to_hash_id(lines, idx, hp)
        else:
            # Fall back to first line substring matching
            containing_indices = _find_exact_line_matches(lines, first_line)
            if len(containing_indices) == 1:
                # Unique match - resolve directly
                idx = containing_indices[0]
                resolved_end = _resolve_to_hash_id(lines, idx, hp)
            elif len(containing_indices) > 1 and resolved_start_idx is not None:
                # Multiple matches - pick closest to start position
                closest_idx = min(
                    containing_indices,
                    key=lambda idx: abs(idx - resolved_start_idx),
                )
                resolved_end = _resolve_to_hash_id(lines, closest_idx, hp)
            else:
                # Fallback: the value may be line content whose whitespace was
                # normalized (e.g. stripped indentation). Resolve it against a
                # single unique line — mirroring apply_hashline_operations — so
                # the preview resolves exactly like the actual edit.
                unique_resolved = _try_resolve_as_unique_line(hp, first_line)
                if unique_resolved is not None:
                    resolved_end = unique_resolved
    elif end_value is not None and _looks_like_content_id(end_value):
        # Already a content ID - try to resolve it
        try:
            normalized = normalize_hashline(end_value)
            candidates = hp.resolve_to_lines(normalized)
            if candidates and resolved_start_idx is not None:
                # Pick candidate closest to start position
                resolved_end = _resolve_to_hash_id(lines, candidates[0], hp)
        except (ContentHashError, ValueError):
            # The value looks like a content ID but normalized to UNIQUE_HASH_DELIMITER which can't
            # be spatially resolved. Fall back: strip the UNIQUE_HASH_DELIMITER prefix and treat the
            # remaining content as line content to match.
            content = HashPos.strip_prefix(end_value)
            if content != end_value and content.strip():
                containing_indices = _find_exact_line_matches(lines, content)
                if len(containing_indices) == 1:
                    idx = containing_indices[0]
                    resolved_end = _resolve_to_hash_id(lines, idx, hp)
                elif len(containing_indices) > 1 and resolved_start_idx is not None:
                    closest_idx = min(
                        containing_indices,
                        key=lambda idx: abs(idx - resolved_start_idx),
                    )
                    resolved_end = _resolve_to_hash_id(lines, closest_idx, hp)

    return resolved_start, resolved_end


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
    pretty=False,
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
        pretty: When True, color removed lines in magenta (\x1b[95m) and added lines
               in light green (\033[32m). When False, all diff lines use \033[92m.

    Returns:
        str: A formatted diff snippet showing changes, or empty string if no changes

    Raises:
        ContentHashError: If hashline verification fails or operation is invalid
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
        # with surrounding context for proper neighborhood-based hashing
        if text:
            original_lines = original_content.splitlines()
            text_lines = text.splitlines()
            # Get up to 3 lines of context before (ending at found_end) and after the insertion point
            ctx_before = original_lines[max(0, found_end - 6) : found_end]
            ctx_after = original_lines[found_end + 1 : min(len(original_lines), found_end + 7)]
            # Build a mini document with context so HashPos computes correct neighborhood hashes
            mini_lines = ctx_before + text_lines + ctx_after
            mini_text = "\n".join(mini_lines)
            hashed_mini = hashline(mini_text)
            hashed_mini_lines = hashed_mini.splitlines(keepends=True)
            # Extract only the replacement text portion's hashlines
            replace_lines_hashed = hashed_mini_lines[
                len(ctx_before) : len(ctx_before) + len(text_lines)
            ]
            replace_text = "".join(replace_lines_hashed)
        else:
            replace_text = ""
    # For replace operation, we're replacing the range
    elif operation == "replace":
        find_text = original_range_content
        # For replace operations, the replacement text should be hashed
        # with surrounding context for proper neighborhood-based hashing
        if text:
            original_lines = original_content.splitlines()
            text_lines = text.splitlines()
            # Get up to 3 lines of context before and after the range
            ctx_before = original_lines[max(0, found_start - 6) : found_start]
            ctx_after = original_lines[found_end + 1 : min(len(original_lines), found_end + 7)]
            # Build a mini document with context so HashPos computes correct neighborhood hashes
            mini_lines = ctx_before + text_lines + ctx_after
            mini_text = "\n".join(mini_lines)
            hashed_mini = hashline(mini_text)
            hashed_mini_lines = hashed_mini.splitlines(keepends=True)
            # Extract only the replacement text portion's hashlines
            replace_lines_hashed = hashed_mini_lines[
                len(ctx_before) : len(ctx_before) + len(text_lines)
            ]
            replace_text = "".join(replace_lines_hashed)
        else:
            replace_text = ""
    else:
        raise ContentHashError(
            f"Invalid operation '{operation}'. Must be one of: replace, insert, delete"
        )

    # Generate diff in the same format as original format_output
    # Use splitlines(keepends=True) to preserve line endings for accurate hash comparison
    find_lines = find_text.splitlines(keepends=True)
    replace_lines = replace_text.splitlines(keepends=True)

    # Strip line endings for difflib comparison but keep them in the actual lines
    diff = difflib.unified_diff(
        [strip_hashline(line.rstrip("\r\n")) for line in find_lines],
        [strip_hashline(line.rstrip("\r\n")) for line in replace_lines],
        lineterm="",
        n=1,
    )

    # Skip header lines (first 2 lines) as in original format_output
    diff_lines = list(diff)[2:]

    if diff_lines:
        if pretty:
            colored_lines = []
            for line in diff_lines:
                if line.startswith("-"):
                    colored_lines.append(f"\033[38;5;96m{line}\x1b[0m")
                elif line.startswith("+"):
                    colored_lines.append(f"\033[32m{line}\x1b[0m")
                else:
                    colored_lines.append(line)
            return "\n".join(colored_lines)
        else:
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

                # Require 2 consecutive matching lines to avoid false positives
                # (single boilerplate lines like "import sys" or "def foo():"
                # are too likely to be coincidental)
                if line_idx + 1 < len(replacement_lines) and match_index + 1 < len(
                    lines_before_range_normalized
                ):
                    next_repl = replacement_lines[line_idx + 1]
                    next_repl_stripped = strip_hashline(next_repl)
                    if not next_repl_stripped.endswith("\n"):
                        next_repl_stripped += "\n"
                    if next_repl_stripped != lines_before_range_normalized[match_index + 1]:
                        continue  # Only 1 line matches — likely coincidental

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
                    # Can't extend backward due to overlap with another operation
                    # Don't truncate without extending — that would silently lose content
                    continue  # Try next line instead

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

                # Require 2 consecutive matching lines to reduce false positives
                if line_idx - 1 >= 0 and match_index - 1 >= 0:
                    prev_repl = replacement_lines[line_idx - 1]
                    prev_repl_stripped = strip_hashline(prev_repl)
                    if not prev_repl_stripped.endswith("\n"):
                        prev_repl_stripped += "\n"
                    if prev_repl_stripped != lines_after_range_normalized[match_index - 1]:
                        continue  # Only 1 line matches — likely coincidental
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
                # Normalize trailing newlines for comparison so that
                # e.g. ["c"] matches ["c\n"] when the last line of prev
                # doesn't have a trailing newline but the first line of curr does.
                max_check = min(len(prev_lines), len(curr_lines))
                overlap_len = 0
                for i in range(1, max_check + 1):
                    prev_suffix = [line.rstrip("\n") for line in prev_lines[-i:]]
                    curr_prefix = [line.rstrip("\n") for line in curr_lines[:i]]
                    if prev_suffix == curr_prefix:
                        overlap_len = i

                if overlap_len > 0:
                    # Build merged result:
                    # Take all of prev's lines, then curr's remaining lines.
                    # Ensure the last line of prev and first line of curr
                    # are properly separated by a newline.
                    result_lines = list(prev_lines)
                    remaining = list(curr_lines[overlap_len:])
                    if remaining:
                        # Ensure proper newline separation between the overlapping
                        # content and the remaining lines from curr.
                        # If the last overlapping line in prev doesn't end with \n
                        # and the first remaining line doesn't start with \n,
                        # add a newline to keep them on separate lines.
                        if (
                            result_lines
                            and not result_lines[-1].endswith("\n")
                            and not remaining[0].startswith("\n")
                        ):
                            result_lines[-1] = result_lines[-1] + "\n"
                    result_lines.extend(remaining)
                    new_text = "".join(result_lines)
                else:
                    # No overlap, concatenate with newline separator if needed
                    # Adjacent operations that replace consecutive line ranges
                    # must keep their content on separate lines.
                    is_adjacent = prev["end_idx"] + 1 == current["start_idx"]
                    needs_newline = (
                        is_adjacent
                        and prev_text
                        and curr_text
                        and not prev_text.endswith("\n")
                        and not curr_text.startswith("\n")
                    )
                    if needs_newline:
                        new_text = prev_text + "\n" + curr_text
                    else:
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
    Deduplicate operations that target the same line and operation type.

    Inserts are anchored after their target line, so an insert and a replace
    sharing a start index are independent operations and must both be retained.
    Multiple operations of the same type still keep only the latest one.

    Returns:
        tuple: (deduplicated_ops, dropped_ops) where dropped_ops describes the
        operations that were removed so callers can surface them as failures.
    """
    deduplicated_ops = []
    dropped = []
    ops_by_key = {}

    for op in resolved_ops:
        key = (op["start_idx"], op["op"]["operation"])
        ops_by_key.setdefault(key, []).append(op)

    for ops in ops_by_key.values():
        ops.sort(key=lambda x: x["index"], reverse=True)
        kept = ops[0]
        deduplicated_ops.append(kept)

        for dropped_op in ops[1:]:
            dropped.append(
                {
                    "index": dropped_op["index"],
                    "error": (
                        f"Edit {dropped_op['index'] + 1} targets the same start line and "
                        f"operation type as Edit {kept['index'] + 1} and was not applied"
                    ),
                    "operation": dropped_op["op"],
                    "failure_type": "not_applied",
                }
            )

    return deduplicated_ops, dropped


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

    Returns:
        tuple: (remaining_ops, dropped_ops) where dropped_ops describes the
        operations removed by the special markers so callers can surface them
        as failures instead of silently discarding them.
    """
    if not resolved_ops:
        return resolved_ops, []

    def _drop(op, reason):
        return {
            "index": op["index"],
            "error": f"Edit {op['index'] + 1} {reason}",
            "operation": op["op"],
        }

    # Check for full file replacement (@000 to 000@)
    for op in resolved_ops:
        original_op = op["op"]
        start_hash = original_op.get("start_line_hash", "")
        end_hash = original_op.get("end_line_hash", "")

        if start_hash == "@000" and end_hash == "000@":
            # This operation replaces the entire file, keep only this one
            dropped = [
                _drop(other, "was superseded by a full-file replacement (@000..000@)")
                for other in resolved_ops
                if other is not op
            ]
            return [op], dropped

    # Track which operations have special markers
    has_special_marker = [False] * len(resolved_ops)
    for i, op in enumerate(resolved_ops):
        original_op = op["op"]
        start_hash = original_op.get("start_line_hash", "")
        end_hash = original_op.get("end_line_hash", "")
        if start_hash == "@000" or end_hash == "000@":
            has_special_marker[i] = True

    # Mark operations for removal, along with the reason they were removed
    ops_to_remove = {}

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
                        ops_to_remove.setdefault(
                            j,
                            "was superseded by an operation starting at the top of the file (@000)",
                        )
        elif end_hash == "000@":
            # Operation ends at end of file
            # Remove any operations ending at or after this operation's start_idx
            # (except other operations with special markers)
            start_idx = op["start_idx"]
            for j, other_op in enumerate(resolved_ops):
                if j != i and not has_special_marker[j]:
                    other_end_idx = other_op["end_idx"]
                    if other_end_idx >= start_idx:
                        ops_to_remove.setdefault(
                            j,
                            "was superseded by an operation ending at the bottom of the file (000@)",
                        )

    # Filter out operations marked for removal
    result = []
    dropped = []
    for i, op in enumerate(resolved_ops):
        if i not in ops_to_remove:
            result.append(op)
        else:
            dropped.append(_drop(op, ops_to_remove[i]))

    return result, dropped


def _merged_contained_ranges(resolved_ops):
    """
    Discard inner ranges that are completely contained within outer ranges.
    This prevents redundant operations and potential errors.

    Returns:
        tuple: (optimized_ops, dropped_ops) where dropped_ops describes the
        contained operations that were removed so callers can surface them
        as failures instead of silently discarding them.
    """
    optimized_ops = []
    dropped = []
    # Loop to remove operations that are completely contained within other operations
    for i, op_a in enumerate(resolved_ops):
        keep_op = True
        container = None

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
                container = op_b
                keep_op = False
                break

        if keep_op:
            optimized_ops.append(op_a)
        else:
            dropped.append(
                {
                    "index": op_a["index"],
                    "error": (
                        f"Edit {op_a['index'] + 1} range is contained within "
                        f"Edit {container['index'] + 1} and was not applied"
                    ),
                    "operation": op_a["op"],
                }
            )

    return optimized_ops, dropped


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


def _would_create_duplicate_content(source_lines, candidate_start, candidate_end, repl_lines):
    """
    Check if applying the edit would create duplicate adjacent content at boundaries.
    """
    if not repl_lines:
        return False

    # Check start boundary: first replacement line matches line before edit range
    if candidate_start > 0:
        line_before = source_lines[candidate_start - 1].strip()
        first_repl = repl_lines[0].strip()
        # Ensure the line actually contains text to prevent eating blank lines
        if line_before and line_before == first_repl:
            return True

    # Check end boundary: last replacement line matches line after edit range
    if candidate_end < len(source_lines) - 1:
        line_after = source_lines[candidate_end + 1].strip()
        last_repl = repl_lines[-1].strip()
        if line_after and line_after == last_repl:
            return True

    return False


def _fix_duplicate_content_boundaries(source_lines, resolved_ops):
    """
    Expand edit boundaries when replacement content duplicates adjacent lines.
    """
    for resolved in resolved_ops:
        op = resolved["op"]
        if op["operation"] not in {"replace", "insert", "delete"}:
            continue
        repl_text = op.get("text", "") or ""
        repl_lines = repl_text.splitlines()
        if not repl_lines:
            continue

        start_idx = resolved["start_idx"]
        end_idx = resolved["end_idx"]

        # Expand start backward if first replacement line duplicates line before
        while start_idx > 0:
            line_before = source_lines[start_idx - 1].strip()
            first_repl = repl_lines[0].strip()
            if line_before and line_before == first_repl:
                start_idx -= 1
            else:
                break

        # Expand end forward if last replacement line duplicates line after
        while end_idx < len(source_lines) - 1:
            line_after = source_lines[end_idx + 1].strip()
            last_repl = repl_lines[-1].strip()
            if line_after and line_after == last_repl:
                end_idx += 1
            else:
                break

        resolved["start_idx"] = start_idx
        resolved["end_idx"] = end_idx

    return resolved_ops


def _apply_closure_safeguard(
    original_content: str,
    resolved_ops: list,
    file_path: str = None,
) -> tuple[list, list]:
    """
    Use tree-sitter to heal edit boundaries by simulating edits and scoring by AST health.
    Evicts edits that strictly increase the number of syntax errors.

    Returns:
        tuple: (safe_resolved_ops, rejected_ops)
        - safe_resolved_ops: Operations with healed boundaries
        - rejected_ops: List of dicts with {"index": int, "error": str} for evicted operations
    """
    if not resolved_ops or not file_path:
        return resolved_ops, []

    from cecli.helpers.grep_ast.parsers import filename_to_lang
    from cecli.helpers.grep_ast.tsl import get_language, get_parser

    lang = filename_to_lang(file_path)
    if not lang:
        return resolved_ops, []

    try:
        language = get_language(lang)  # noqa
        parser = get_parser(lang)
    except Exception:
        return resolved_ops, []

    source_lines = original_content.splitlines()
    source_bytes = original_content.encode("utf-8")

    def apply_edit(
        lines: list[str],
        start: int,
        end: int,
        replacement: list[str],
    ) -> bytes:
        """Applies the edit and returns the new source code as bytes."""
        new_lines = lines[:start] + replacement + lines[end + 1 :]
        return "\n".join(new_lines).encode("utf-8")

    def count_ast_errors(node) -> int:
        """
        Recursively counts MISSING or ERROR nodes in the AST.
        """
        errors = 0
        if node.is_missing or node.type == "ERROR":
            errors += 1
        for child in node.children:
            errors += count_ast_errors(child)
        return errors

    def _detect_indent_unit(source_lines: list) -> int:
        """Detect the common indentation unit from non-empty source lines."""
        indents = []
        for line in source_lines:
            if line.strip():  # non-empty
                indent = len(line) - len(line.lstrip())
                indents.append(indent)

        if len(indents) < 2:
            return 0

        # Compute differences between consecutive non-empty lines
        diffs = []
        for i in range(1, len(indents)):
            diff = abs(indents[i] - indents[i - 1])
            if diff > 0:
                diffs.append(diff)

        if not diffs:
            return 0

        # Most common non-zero difference is the indentation unit
        return Counter(diffs).most_common(1)[0][0]

    def _has_indent_jump(test_lines: list, unit: int) -> bool:
        """Check if the edit result creates an indentation jump of 2+ units."""
        if unit == 0:
            return False

        prev_indent = None
        for line in test_lines:
            if line.strip():  # non-empty
                indent = len(line) - len(line.lstrip())
                if prev_indent is not None:
                    diff = abs(indent - prev_indent)
                    if diff > unit:
                        return True
                prev_indent = indent

        return False

    # Establish the baseline syntax health of the original file
    base_tree = parser.parse(source_bytes)
    baseline_error_count = count_ast_errors(base_tree.root_node)

    # Detect if the original source follows normal indentation (steps of 1 unit)
    indent_unit = _detect_indent_unit(source_lines)
    is_normally_indented = indent_unit > 0

    safe_resolved_ops = []
    rejected_ops = []

    for resolved in resolved_ops:
        op = resolved["op"]
        if op["operation"] not in {"replace", "insert", "delete"}:
            safe_resolved_ops.append(resolved)
            continue

        llm_start = resolved["start_idx"]
        llm_end = resolved["end_idx"]

        if llm_start < 0 or llm_start >= len(source_lines):
            safe_resolved_ops.append(resolved)
            continue
        if llm_end < llm_start:
            safe_resolved_ops.append(resolved)
            continue

        replacement_text = op.get("text", "") or ""
        if op["operation"] == "delete":
            replacement_text = ""
        repl_lines = replacement_text.splitlines()

        llm_end = min(llm_end, len(source_lines) - 1)

        offsets = [0, 1, -1, 2, -2]
        all_candidates = []

        for start_shift in offsets:
            for end_shift in offsets:
                candidate_start = max(0, llm_start - start_shift)
                candidate_end = min(len(source_lines) - 1, llm_end + end_shift)

                if candidate_end < candidate_start:
                    continue

                overlaps = False
                for other_op in resolved_ops:
                    if other_op is resolved:
                        continue
                    other_start = other_op["start_idx"]
                    other_end = other_op["end_idx"]
                    if candidate_start <= other_end and candidate_end >= other_start:
                        overlaps = True
                        break

                if overlaps:
                    continue

                if _would_create_duplicate_content(
                    source_lines, candidate_start, candidate_end, repl_lines
                ):
                    continue

                test_source_bytes = apply_edit(
                    source_lines,
                    candidate_start,
                    candidate_end,
                    repl_lines,
                )

                # Parse the candidate to get structural truth
                edited_tree = parser.parse(test_source_bytes)
                ast_error_count = count_ast_errors(edited_tree.root_node)

                is_partial = (start_shift == 0) ^ (end_shift == 0)
                is_downward = start_shift <= 0
                is_both = start_shift == end_shift
                start_line_match = source_lines[candidate_start] == source_lines[llm_start]
                end_line_match = source_lines[candidate_end] == source_lines[llm_end]
                cumulative_movement = abs(start_shift) + abs(end_shift)

                # Check for indentation jumps in the resulting edit
                if is_normally_indented:
                    test_lines = test_source_bytes.decode("utf-8").splitlines()
                    has_indent_jump = _has_indent_jump(test_lines, indent_unit)
                else:
                    has_indent_jump = False

                all_candidates.append(
                    {
                        "start_idx": candidate_start,
                        "end_idx": candidate_end,
                        "ast_error_count": ast_error_count,
                        "start_line_match": start_line_match,
                        "end_line_match": end_line_match,
                        "cumulative_movement": cumulative_movement,
                        "has_indent_jump": has_indent_jump,
                        "is_partial": is_partial,
                        "is_downward": is_downward,
                        "is_both": is_both,
                    }
                )

        if all_candidates:
            # 1. AST Health is the absolute highest priority.
            # 2. Cumulative movement acts as the tie-breaker for equally valid ASTs.
            all_candidates.sort(
                key=lambda r: (
                    r["ast_error_count"],  # Ascending: fewer syntax errors wins
                    not r["start_line_match"],  # Descending: True first
                    not r["end_line_match"],  # Descending: True first
                    r.get("has_indent_jump", False),  # Ascending: False (no jump) first
                    r["cumulative_movement"],  # Ascending: smaller is better
                    not r["is_partial"],  # Booleans: False comes before True
                    not r["is_downward"],  # Booleans: False comes before True
                    r["is_both"],  # Booleans: False comes before True
                )
            )

            best = all_candidates[0]

            # EVICTION GATE: If the absolute best boundary still introduces NEW
            # syntax errors compared to the original file, discard the edit entirely.
            if best["ast_error_count"] > baseline_error_count:

                rejected_ops.append(
                    {
                        "index": resolved["index"],
                        "error": (
                            f"Edit introduces new syntax error(s) (baseline: {baseline_error_count}, "
                            f"after edit: {best['ast_error_count']}) and none of the "
                            f"{len(all_candidates)} candidate boundary adjustments could resolve it"
                        ),
                        "operation": op,
                    }
                )
                continue

            resolved["start_idx"] = best["start_idx"]
            resolved["end_idx"] = best["end_idx"]

        safe_resolved_ops.append(resolved)

    return safe_resolved_ops, rejected_ops


def _try_resolve_as_unique_line(
    hp: HashPos,
    value: str,
) -> str | None:
    """
    Try to resolve a value by matching it against unique lines in the source content.

    If the value (after stripping) matches exactly one line in the source
    AND that line appears only once (unique), returns a tilde-wrapped hash ID
    that can be resolved to line indices by the HashPos engine.

    This serves as a preliminary resolution step that can salvage operations
    whose hash references could not be normalized, by checking if the value
    corresponds to unique line content in the file.

    Args:
        hp: HashPos instance for the source content
        value: The value to resolve (typically line content rather than a hash)

    Returns:
        A tilde-wrapped hash ID if resolution succeeds, None otherwise
    """
    if not hp or not value:
        return None

    value_stripped = value.strip()
    if not value_stripped:
        return None

    # Find all lines that exactly match this value
    matching_lines = []
    for i, line in enumerate(hp.lines):
        if line.strip() == value_stripped:
            matching_lines.append((i, line))

    # Only resolve if it matches exactly one unique line
    if len(matching_lines) == 1:
        idx, matched_line = matching_lines[0]
        # Verify the line is actually unique in the source (appears only once)
        if hp.line_counts.get(matched_line, 0) == 1:
            hash_id = hp.generate_public_id(matched_line, idx, 1)
            return HashPos.get_wrapped_id(hash_id)

    return None


def _raise_clear_hash_error(hp, op, key):
    """Raise a ContentHashError with a clear message explaining why a value couldn't be resolved.

    Checks if the value matches line content in the file and provides specific guidance
    about how to fix the reference (use hashed ID prefix, check for duplicates, etc.).
    """
    value = op.get(key, "")
    value_stripped = value.strip() if value else ""

    if not hp or not value_stripped:
        raise ContentHashError(
            f"Could not resolve '{value}' as a content ID. "
            "Use a hashed ID prefix (e.g., `—XXXX—`) to target the line."
        )

    # Count how many lines contain this value as a substring
    matching_count = 0
    for line in hp.lines:
        if value_stripped in line:
            matching_count += 1

    if matching_count > 1:
        raise ContentHashError(
            f"Line '{value_stripped}' appears {matching_count} times in the file. "
            "Use the hashed ID prefix (e.g., `—XXXX—`) to disambiguate "
            "which occurrence to target."
        )
    elif matching_count == 1:
        raise ContentHashError(
            f"Line '{value_stripped}' was found once in the file but could not be "
            "resolved as a unique content ID. Use the hashed ID prefix (e.g., `—XXXX—`) "
            "to target it precisely."
        )
    else:
        raise ContentHashError(
            f"Line '{value_stripped}' was not found in the file. "
            "Use the exact line content or a hashed ID prefix (e.g., `—XXXX—`) "
            "to target the desired line."
        )


def _detect_overlapping_ranges(resolved_ops):
    """Check resolved operations for genuinely overlapping ranges.

    Detects operations where ranges overlap in a way that can't be resolved
    by simple deduplication (same-start) or containment. These non-trivial
    overlaps (e.g., a delete range partially overlapping a replace range)
    are flagged and returned as failed operations with a clear message.
    The overlapping operations' indices are also returned so the caller
    can exclude them from `resolved_ops`.

    Returns a tuple of (failed_ops, indices_to_remove).
    - failed_ops: list of failed operation dicts with overlap errors
    - indices_to_remove: set of operation indices to remove from resolved_ops
    """
    if len(resolved_ops) < 2:
        return [], set()

    failed_ops = []
    indices_to_remove = set()
    for i in range(len(resolved_ops)):
        a = resolved_ops[i]
        a_start = a["start_idx"]
        a_end = a["end_idx"]

        for j in range(i + 1, len(resolved_ops)):
            b = resolved_ops[j]
            b_start = b["start_idx"]
            b_end = b["end_idx"]

            # Skip trivial cases handled elsewhere:
            # 1. Same start line - handled by _deduplicate_ranges
            if a_start == b_start:
                continue

            # 2. One range fully contained within the other - handled by _merged_contained_ranges
            if (a_start <= b_start and b_end <= a_end) or (b_start <= a_start and a_end <= b_end):
                continue

            # Check if ranges genuinely overlap (not just adjacent/contiguous)
            # Two ranges [a_start, a_end] and [b_start, b_end] overlap if
            # a_start <= b_end and b_start <= a_end
            if a_start <= b_end and b_start <= a_end:
                op_a = a["op"]
                op_b = b["op"]
                error_msg = (
                    f"Operation {a['index'] + 1} ({op_a['operation']}, lines "
                    f"{a_start}-{a_end}) overlaps with operation {b['index'] + 1} "
                    f"({op_b['operation']}, lines {b_start}-{b_end}). "
                    "Edits with overlapping ranges are not supported. "
                    "Combine them into a single edit or use non-overlapping ranges."
                )
                failed_ops.append({"index": a["index"], "error": error_msg, "operation": op_a})
                failed_ops.append({"index": b["index"], "error": error_msg, "operation": op_b})
                indices_to_remove.add(i)
                indices_to_remove.add(j)

    return failed_ops, indices_to_remove


def apply_hashline_operations(
    original_content: str,
    operations: list,
    file_path: str = None,
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
    # Create a single HashPos instance for preliminary resolution and content hashing
    hp = HashPos(original_content) if original_content else HashPos("")
    # Loop through each operation to normalize hashline strings
    for i, op in enumerate(operations):
        try:
            normalized_op = op.copy()
            # Normalize start line hash to ensure consistent format
            try:
                normalized_op["start_line_hash"] = normalize_hashline(op["start_line_hash"])
            except (ContentHashError, ValueError):
                # Preliminary resolution: check if the value matches a unique line
                resolved = _try_resolve_as_unique_line(hp, op["start_line_hash"])
                if resolved is not None:
                    normalized_op["start_line_hash"] = resolved
                else:
                    _raise_clear_hash_error(hp, op, "start_line_hash")

            if "end_line_hash" in op:
                # Normalize end line hash if present
                try:
                    normalized_op["end_line_hash"] = normalize_hashline(op["end_line_hash"])
                except (ContentHashError, ValueError):
                    # Preliminary resolution: check if the value matches a unique line
                    resolved = _try_resolve_as_unique_line(hp, op["end_line_hash"])
                    if resolved is not None:
                        normalized_op["end_line_hash"] = resolved
                    else:
                        _raise_clear_hash_error(hp, op, "end_line_hash")

            normalized_operations.append(normalized_op)
        except Exception as e:
            failed_ops.append({"index": i, "error": str(e), "operation": op})

    if not normalized_operations:
        return original_content, [], failed_ops

    # Apply hashline to original content once
    # This converts content to hashed lines for line tracking
    hashed_content = hp.format_content()
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
                elif start_hash_fragment == "000@":
                    # Bottom-of-file anchor - insert after the last line
                    found_start = len(hashed_lines) - 1 if hashed_lines else -1
                else:
                    # Try exact match first for insert operations
                    found_start = find_hashline_by_exact_match(
                        hashed_lines, start_hash_fragment, start_line_num_str
                    )

                    if found_start is None:
                        raise ContentHashError(
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
                    raise ContentHashError(
                        f"Could not resolve hash range {start_hash}...{end_hash}: {str(e)}"
                    )

        except Exception as e:
            failed_ops.append({"index": i, "error": str(e), "operation": op})

    # Check for overlapping ranges among resolved operations
    overlap_failures, overlap_indices = _detect_overlapping_ranges(resolved_ops)
    for overlap_failure in overlap_failures:
        failed_ops.append(overlap_failure)
    # Remove overlapping operations from resolved_ops so they don't get applied
    if overlap_indices:
        resolved_ops = [op for i, op in enumerate(resolved_ops) if i not in overlap_indices]

    # Honor cancellations: remove operations that are cancelled by later cancel operations
    resolved_ops = _honor_cancellations(resolved_ops)
    # Deduplicate: if multiple operations start on the same line, keep only the latest one.
    # This handles cases where a model might generate multiple operations for the same line while "thinking".
    # Dropped operations are surfaced as failures instead of being silently discarded.
    resolved_ops, dropped = _deduplicate_ranges(resolved_ops)
    for drop in dropped:
        failed_ops.append(drop)

    # Honor special markers: handle @000 and 000@ special markers for whole-file or partial-file operations
    resolved_ops, dropped = _honor_special_markers(resolved_ops)
    for drop in dropped:
        failed_ops.append(drop)

    # Optimize: discard inner ranges that are completely contained within outer ranges.
    # This prevents redundant operations and potential errors.
    resolved_ops, dropped = _merged_contained_ranges(resolved_ops)
    for drop in dropped:
        failed_ops.append(drop)
    # Merge contiguous replace operations
    resolved_ops = _merge_replace_operations(resolved_ops)

    # Sort by start_idx descending to apply from bottom to top
    # When operations have same start_idx, apply in order: insert, replace, delete
    # This ensures correct behavior when multiple operations target the same line
    resolved_ops.sort(key=sort_ranges)

    if file_path:
        # Apply tree-sitter based closure safeguard to snap boundaries to AST nodes
        safe_ops, rejected_ops = _apply_closure_safeguard(original_content, resolved_ops, file_path)
        resolved_ops = safe_ops
        for rejected in rejected_ops:
            failed_ops.append(
                {
                    "index": rejected["index"],
                    "error": rejected["error"],
                    "operation": rejected["operation"],
                }
            )

        # Fix edit boundaries where replacement content duplicates adjacent lines
        source_lines = original_content.splitlines()
        resolved_ops = _fix_duplicate_content_boundaries(source_lines, resolved_ops)

    successful_ops = []
    # Loop to apply operations in sorted order (bottom-to-top)
    for resolved in resolved_ops:
        try:
            op = resolved["op"]
            start_idx = resolved["start_idx"]
            end_idx = resolved["end_idx"]
            changed = True

            if op["operation"] == "insert":
                text = op["text"]
                if not text:
                    changed = False
                else:
                    if not text.endswith("\n"):
                        text += "\n"
                    # Special handling for empty hashed_lines (genesis anchor case)
                    if hashed_lines:
                        if not hashed_lines[start_idx].endswith("\n"):
                            hashed_lines[start_idx] += "\n"
                        hashed_lines.insert(start_idx + 1, text)
                    else:
                        hashed_lines.append(text)
            elif op["operation"] == "delete":
                del hashed_lines[start_idx : end_idx + 1]
            elif op["operation"] == "replace":
                # If operation ends with "000@", ensure end_idx is at actual end of file
                if op.get("end_line_hash") == "000@":
                    end_idx = len(hashed_lines) - 1

                text = op["text"]
                # Snapshot the pre-edit range content so no-op replacements are
                # not counted as successful edits. Normalize line endings because
                # the apply path enforces a trailing newline on replacement lines.
                before_range = [
                    strip_hashline(line).rstrip("\r\n")
                    for line in hashed_lines[start_idx : end_idx + 1]
                ]
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
                    # max_overlap_check = 2  # Check up to 2 lines for overlap

                    # Check for overlapping lines BEFORE the range (bidirectional stitching)
                    # start_idx, replacement_lines = _apply_start_stitching(
                    #    hashed_lines,
                    #    start_idx,
                    #    end_idx,
                    #    replacement_lines,
                    #    resolved_ops,
                    #    resolved,
                    #    max_overlap_check,
                    # )

                    # Now check for overlapping lines AFTER the range
                    # end_idx, replacement_lines = _apply_end_stitching(
                    #    hashed_lines, start_idx, end_idx, replacement_lines, max_overlap_check
                    # )
                    # Preserve empty lines after the edit range
                    # If there is an empty line immediately after the edit boundary,
                    # track it so it can be restored if consumed by the replacement
                    next_idx = end_idx + 1
                    preserve_trailing_empty = (
                        next_idx < len(hashed_lines) and hashed_lines[next_idx].strip() == ""
                    )

                    hashed_lines[start_idx : end_idx + 1] = replacement_lines

                    # Ensure the trailing empty line is preserved after replacement
                    if preserve_trailing_empty:
                        check_idx = start_idx + len(replacement_lines)
                        if check_idx >= len(hashed_lines) or hashed_lines[check_idx].strip() != "":
                            hashed_lines.insert(check_idx, "\n")

                else:
                    # Empty text - replace with nothing (delete)
                    replacement_lines = []
                    hashed_lines[start_idx : end_idx + 1] = []

                replacement_content = [line.rstrip("\r\n") for line in replacement_lines]
                if before_range == replacement_content:
                    changed = False

            if changed:
                if "merged_indices" in resolved:
                    successful_ops.extend(resolved["merged_indices"])
                else:
                    successful_ops.append(resolved["index"])
            else:
                # No-op edit: report it as failed so the caller's success count
                # reflects edits that actually changed the file
                indices = resolved.get("merged_indices") or [resolved["index"]]
                for idx in indices:
                    failed_ops.append(
                        {
                            "index": idx,
                            "error": "Edit resulted in no changes to the file content",
                            "operation": op,
                            "failure_type": "no_change",
                        }
                    )
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
        ContentHashError: If hashline verification fails or operation is invalid
    """
    # Handle empty content as a special case
    if original_content == "" or original_content is None:
        if operation == "insert" or operation == "replace":
            if text is None:
                raise ContentHashError(
                    f"Text parameter is required for '{operation}' operation on empty file"
                )
            # For empty files, just return the text to insert/replace with
            return text if text.endswith("\n") else text + "\n"
        elif operation == "delete":
            # Deleting from empty file returns empty
            return ""
        else:
            # Should not happen due to validation above, but handle anyway
            raise ContentHashError(f"Invalid operation '{operation}' for empty file")

    # Validate operation
    valid_operations = {"replace", "insert", "delete"}
    if operation not in valid_operations:
        raise ContentHashError(
            f"Invalid operation '{operation}'. Must be one of: {', '.join(valid_operations)}"
        )

    # Validate text parameter for replace/insert operations
    if operation in {"replace", "insert"} and text is None:
        raise ContentHashError(f"Text parameter is required for '{operation}' operation")

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
        raise ContentHashError(failed_ops[0]["error"])

    return modified_content
