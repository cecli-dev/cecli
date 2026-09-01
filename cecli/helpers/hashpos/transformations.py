"""
HashPos transformation utilities.

Centralizes all operations related to searching, processing line hints,
contextual markers, and extracting content from HashPos-encoded files.
Previously scattered across read_file.py, edit_file.py, hashline.py,
and region_resolver.py.
"""

from __future__ import annotations

import re

from cecli.helpers.hashpos.hashpos import UNIQUE_HASH_DELIMITER, HashPos

# ────────────────────────────────────────────────────────────
# Pattern Matching
# ────────────────────────────────────────────────────────────


def search_in_lines(
    lines: list[str],
    pattern: str,
    *,
    return_last_line: bool = False,
) -> list[int]:
    """Search for a multiline pattern in lines.

    Each line of *pattern* must appear as a whole word in the corresponding
    line in *lines* at the match position.  A ``whole word`` means the
    pattern is surrounded by non-word characters (or line boundaries) —
    ``"def"`` matches ``"def foo()"`` but not ``"define"``.

    Args:
        lines: Source lines to search.
        pattern: Pattern string (may span multiple lines via ``\n``).
        return_last_line: When True, returns the index of the **last**
            line of each match instead of the first.

    Returns:
        0-based indices of each match.
    """

    pattern_lines = pattern.split("\n")
    indices: list[int] = []
    offset = len(pattern_lines) - 1 if return_last_line else 0

    for i in range(len(lines) - len(pattern_lines) + 1):
        if all(
            _is_whole_word_match(p_line, lines[i + j]) for j, p_line in enumerate(pattern_lines)
        ):
            indices.append(i + offset)

    return indices


def _is_whole_word_match(pattern: str, line: str) -> bool:
    """Return True if *pattern* appears as a whole word in *line*.

    A match requires that the characters immediately before and after the
    match position are **not** word characters (``[a-zA-Z0-9_]``) — or
    that the match is at the start/end of the line respectively.
    """

    idx = line.find(pattern)

    while idx != -1:
        before_ok = idx == 0 or not (line[idx - 1].isalnum() or line[idx - 1] == "_")
        after_pos = idx + len(pattern)
        after_ok = after_pos >= len(line) or not (
            line[after_pos].isalnum() or line[after_pos] == "_"
        )

        if before_ok and after_ok:
            return True

        idx = line.find(pattern, idx + 1)

    return False


def find_substring_matches(
    lines: list[str],
    value: str,
) -> list[int]:
    """Return 0-based indices of all lines containing *value* as a substring."""

    value_stripped = value.strip()
    return [i for i, line in enumerate(lines) if value_stripped in line]


def find_multiline_match(
    lines: list[str],
    value: str,
) -> int | None:
    """Find the start index where the full multiline *value* matches consecutive lines.

    Returns None if *value* is a single line or no match is found.
    """

    value_lines = value.strip().splitlines()

    if len(value_lines) <= 1:
        return None

    for i in range(len(lines) - len(value_lines) + 1):
        if all(value_lines[j].strip() in lines[i + j] for j in range(len(value_lines))):
            return i

    return None


# ────────────────────────────────────────────────────────────
# Content ID Detection
# ────────────────────────────────────────────────────────────


def is_content_id(value: str) -> bool:
    """Return True if *value* appears to be a content ID rather than text."""

    from cecli.helpers.hashline import ContentHashError, normalize_hashline

    if value in ("@000", "000@"):
        return True

    try:
        normalize_hashline(value)

        return True
    except (ContentHashError, ValueError):
        return False


# ────────────────────────────────────────────────────────────
# @L Line Number Resolution
# ────────────────────────────────────────────────────────────


def resolve_at_l(
    line_spec: str,
    hp: HashPos,
    lines: list[str],
) -> str:
    """Resolve ``@L{{num}}`` notation to a content ID using a HashPos index.

    Returns the input unchanged if it is not an @L{{num}} spec.
    Raises ValueError if the line number is out of range.
    """

    if not (
        isinstance(line_spec, str)
        and line_spec.startswith("@L")
        and len(line_spec) > 2
        and line_spec[2:].isdigit()
    ):
        return line_spec

    line_num = int(line_spec[2:]) - 1

    if line_num < 0 or line_num >= len(lines):
        raise ValueError(
            f"@L reference line {int(line_spec[2:])} is out of range "
            f"(file has {len(lines)} lines)"
        )

    line_text = lines[line_num]
    occurrence = 1 + sum(1 for i in range(line_num) if lines[i] == line_text)

    return hp.get_wrapped_id(hp.generate_public_id(line_text, line_num, occurrence))


# ────────────────────────────────────────────────────────────
# Hint Extraction (@L / @A / @B)
# ────────────────────────────────────────────────────────────


def extract_hint(
    pattern: str,
    lines: list[str] | None = None,
) -> tuple[str, int | None, str | None]:
    """Extract a hint suffix from a pattern string.

    Supports three hint types:

    * ``@L<num>``     — direct line number (always resolvable).
    * ``@A{{{{regex}}}}`` — keep only matches **after** the first regex hit.
    * ``@B{{{{regex}}}}`` — keep only matches **before** the last regex hit.

    Returns a ``(stripped_pattern, hint_value, hint_type)`` tuple:

    * ``hint_value`` — 0-based line number, or None.
    * ``hint_type``  — ``'L'``, ``'A'``, ``'B'``, or None.
    """

    # @L hint — direct line number, always resolvable
    m = re.search(r"(?:^|[ \t]+)@L([0-9]+)[ \t]*$", pattern)

    if m:
        stripped = pattern[: m.start()]
        return (stripped if stripped else pattern), int(m.group(1)) - 1, "L"

    # @A{{regex}} hint — first regex match, filter to lines AFTER
    m = re.search(r"(?:^|[ \t]+)@A\{\{(.+?)\}\}[ \t]*$", pattern)

    if m:
        stripped = pattern[: m.start()]

        if lines is not None:
            regex_str = m.group(1)

            try:
                for i, line in enumerate(lines):
                    if re.search(regex_str, line):
                        return stripped, i, "A"
            except re.error:
                pass

        return stripped, None, None

    # @B{{regex}} hint — last regex match, filter to lines BEFORE
    m = re.search(r"(?:^|[ \t]+)@B\{\{(.+?)\}\}[ \t]*$", pattern)

    if m:
        stripped = pattern[: m.start()]

        if lines is not None:
            regex_str = m.group(1)

            try:
                last_match = None

                for i, line in enumerate(lines):
                    if re.search(regex_str, line):
                        last_match = i

                if last_match is not None:
                    return stripped, last_match, "B"
            except re.error:
                pass

        return stripped, None, None

    return pattern, None, None


# ────────────────────────────────────────────────────────────
# Search Type Classification
# ────────────────────────────────────────────────────────────


def classify_search_type(
    range_start: str,
    range_end: str,
) -> dict[str, bool]:
    """Classify range markers into structured, text, mixed, or contextual types.

    The returned dict contains boolean flags usable by downstream resolvers
    to decide how to find start/end line indices.
    """

    def _is_line_ref(s: str) -> bool:
        return s.startswith("@L") and s[2:].isdigit() and len(s) > 2

    start_is_lr = _is_line_ref(range_start)
    end_is_lr = _is_line_ref(range_end)
    start_is_sp = range_start in ("@000", "000@")
    end_is_sp = range_end in ("@000", "000@")

    return {
        "start_is_line_ref": start_is_lr,
        "end_is_line_ref": end_is_lr,
        "start_is_special": start_is_sp,
        "end_is_special": end_is_sp,
        "start_is_text": not start_is_lr and not start_is_sp,
        "end_is_text": not end_is_lr and not end_is_sp,
        "both_structured": (start_is_lr or start_is_sp) and (end_is_lr or end_is_sp),
        "mixed_special": (
            (start_is_sp and not end_is_lr and not end_is_sp)
            or (end_is_sp and not start_is_lr and not start_is_sp)
        ),
        "end_is_contextual": (
            range_end.startswith(("@C", "@P", "@N"))
            and len(range_end) > 2
            and range_end[2:].isdigit()
        ),
    }


# ────────────────────────────────────────────────────────────
# Contextual Markers (@C / @P / @N)
# ────────────────────────────────────────────────────────────


def apply_contextual_marker(
    start_indices: list[int],
    range_start: str,
    range_end: str,
    num_lines: int,
) -> tuple[list[int], list[int]]:
    """Expand range using @C{{num}}, @P{{num}}, or @N{{num}} contextual markers.

    Requires exactly one start match.  Raises ValueError when the number
    of start matches is not 1 (the caller is expected to format the error
    message with its own context like file path / operation index).

    Returns ``(new_start_indices, new_end_indices)``.
    """

    if len(start_indices) != 1:
        raise ValueError(
            f"Start pattern '{range_start}' must match exactly one"
            f" location when using @C/@P/@N end markers."
            f" Found {len(start_indices)} matches."
        )

    ctx_s_idx = start_indices[0]
    ctx_num = int(range_end[2:])
    marker_type = range_end[1]

    if marker_type == "C":
        s_idx = max(0, ctx_s_idx - ctx_num)
        e_idx = min(num_lines - 1, ctx_s_idx + ctx_num)
    elif marker_type == "P":
        s_idx = max(0, ctx_s_idx - ctx_num)
        e_idx = ctx_s_idx
    else:  # 'N'
        s_idx = ctx_s_idx
        e_idx = min(num_lines - 1, ctx_s_idx + ctx_num)

    return [s_idx], [e_idx]


# ────────────────────────────────────────────────────────────
# Proximity / Narrowing
# ────────────────────────────────────────────────────────────


def narrow_by_proximity(
    indices: list[int],
    target: int,
    max_results: int = 5,
) -> list[int]:
    """Return up to *max_results* indices closest to *target* (0-based).

    Results are sorted by ascending distance from *target*.
    """

    if not indices:
        return []

    scored = [(abs(i - target), i) for i in indices]
    scored.sort(key=lambda x: x[0])

    return [idx for _, idx in scored[:max_results]]


# ────────────────────────────────────────────────────────────
# Pair / Range Computation
# ────────────────────────────────────────────────────────────


def compute_best_pair(
    start_indices: list[int],
    end_indices: list[int],
    *,
    allow_inverted: bool = False,
) -> tuple[int, int] | None:
    """Find the smallest-range valid (start, end) pair.

    When *allow_inverted* is True, also considers pairs where end < start
    (the LLM may have swapped the order) and returns them in correct order.
    """

    min_dist = float("inf")
    best_pair: tuple[int, int] | None = None

    for s in start_indices:
        valid_ends = end_indices if allow_inverted else [e for e in end_indices if e >= s]

        for e in valid_ends:
            dist = abs(e - s)

            if dist < min_dist:
                min_dist = dist
                best_pair = (s, e)

    if allow_inverted and best_pair and best_pair[1] < best_pair[0]:
        best_pair = (best_pair[1], best_pair[0])

    return best_pair


def reposition_indices(
    target_idx: int,
    start_idx: int,
    end_idx: int,
    total_lines: int = 20,
) -> tuple[int, int]:
    """Calculate clamped start/end indices for a centered window.

    Returns ``(slice_start, slice_end)`` compatible with Python slicing
    (i.e. *slice_end* is exclusive).
    """

    half_window = total_lines // 2

    left = target_idx - half_window
    right = target_idx + half_window

    if left < start_idx:
        right += start_idx - left
        left = start_idx

    if right > end_idx:
        left -= right - end_idx
        right = end_idx

    left = max(start_idx, left)

    return left, right + 1


# ────────────────────────────────────────────────────────────
# Prefix / Content ID Utilities
# ────────────────────────────────────────────────────────────


def strip_hashline_prefix(value: str) -> str:
    """Strip the virtual prefix from a ReadFile output line reference."""
    if not isinstance(value, str):
        return value

    # Unique-line delimiter (——): not spatially resolvable, so strip it and match
    # the remaining content as text.
    if value.startswith(UNIQUE_HASH_DELIMITER):
        return value[len(UNIQUE_HASH_DELIMITER) :]

    # Valid canonical duplicate content ID (—XXXX—): keep it intact so that
    # resolve_content_to_hashline_ids() can target a specific occurrence.
    if HashPos.HASH_PREFIX_RE.match(value):
        return value

    # Malformed marker: a short string immediately followed by an em-dash (e.g.
    # 'о‘星—'). This is not a valid content ID, so strip it.
    stripped = HashPos._LOOSE_PREFIX_RE.sub("", value, count=1)
    if stripped != value:
        return stripped

    return value


def try_resolve_as_unique_line(
    hp: HashPos,
    value: str,
) -> str | None:
    """Try to resolve a value by matching it against unique lines in the source.

    If *value* (after stripping) matches exactly one line in the source
    **and** that line appears only once (unique), returns a tilde-wrapped
    hash ID that can be resolved to line indices by the HashPos engine.

    Returns None if resolution fails.
    """

    if not hp or not value:
        return None

    value_stripped = value.strip()

    if not value_stripped:
        return None

    matching_lines: list[tuple[int, str]] = []

    for i, line in enumerate(hp.lines):
        if line.strip() == value_stripped:
            matching_lines.append((i, line))

    if len(matching_lines) == 1:
        idx, matched_line = matching_lines[0]

        if hp.line_counts.get(matched_line, 0) == 1:
            hash_id = hp.generate_public_id(matched_line, idx, 1)

            return hp.get_wrapped_id(hash_id)

    return None
