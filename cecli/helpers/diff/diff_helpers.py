"""Generic unified-diff helpers.

These helpers are independent of hashline/HashPos formatting: they operate on
plain text lines and only use :mod:`difflib`.
"""

import difflib


def unified_diff_compacted(old_lines, new_lines, fromfile="", tofile="", context_lines=3):
    """Build a unified diff with git-style change-group compaction.

    ``difflib`` can anchor a change to the first of several identical blocks,
    which makes unchanged lines look added or removed. Git compacts change
    groups to their last possible position; this mirrors that for pure
    insertions and deletions.

    Returns:
        list[str]: Unified diff lines without trailing newlines, or an empty
            list when the inputs are identical.
    """
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    opcodes = _compact_diff_opcodes(matcher.get_opcodes(), old_lines, new_lines)
    diff_lines = []

    for group in _group_diff_opcodes(opcodes, context_lines):
        first = group[0]
        last = group[-1]
        diff_lines.append(
            f"@@ -{_format_diff_range(first[1], last[2])} +"
            f"{_format_diff_range(first[3], last[4])} @@"
        )

        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                diff_lines.extend(" " + line for line in old_lines[i1:i2])
            elif tag in ("replace", "delete"):
                diff_lines.extend("-" + line for line in old_lines[i1:i2])
            if tag in ("replace", "insert"):
                diff_lines.extend("+" + line for line in new_lines[j1:j2])

    if not diff_lines:
        return []

    return [f"--- {fromfile}", f"+++ {tofile}"] + diff_lines


def _compact_diff_opcodes(opcodes, old_lines, new_lines):
    """Slide pure insert/delete groups down over repeated lines."""
    ops = [list(op) for op in opcodes]
    index = 0

    while index < len(ops):
        if ops[index][0] == "equal":
            index += 1
            continue

        start = index
        while index < len(ops) and ops[index][0] != "equal":
            index += 1

        end = index

        if end - start != 1:
            continue

        tag = ops[start][0]
        if tag not in ("insert", "delete"):
            continue

        while end < len(ops) and ops[end][0] == "equal":
            equal = ops[end]

            if tag == "insert":
                if ops[start][3] >= ops[start][4] or equal[3] >= equal[4]:
                    break
                if new_lines[ops[start][3]] != new_lines[equal[3]]:
                    break
            else:
                if ops[start][1] >= ops[start][2] or equal[1] >= equal[2]:
                    break
                if old_lines[ops[start][1]] != old_lines[equal[1]]:
                    break

            if start == 0 or ops[start - 1][0] != "equal":
                ops.insert(
                    start,
                    ["equal", ops[start][1], ops[start][1], ops[start][3], ops[start][3]],
                )
                start += 1
                end += 1

            previous = ops[start - 1]
            previous[2] += 1
            previous[4] += 1

            ops[start][1] += 1
            ops[start][2] += 1
            ops[start][3] += 1
            ops[start][4] += 1

            equal[1] += 1
            equal[3] += 1

            if equal[1] == equal[2]:
                del ops[end]

        index = end

    return [tuple(op) for op in ops]


def _group_diff_opcodes(opcodes, context_lines):
    """Group opcodes into hunks with ``context_lines`` of surrounding context."""
    codes = [list(op) for op in opcodes]
    if not codes:
        codes = [["equal", 0, 1, 0, 1]]

    if codes[0][0] == "equal":
        tag, i1, i2, j1, j2 = codes[0]
        codes[0] = [tag, max(i1, i2 - context_lines), i2, max(j1, j2 - context_lines), j2]

    if codes[-1][0] == "equal":
        tag, i1, i2, j1, j2 = codes[-1]
        codes[-1] = [tag, i1, min(i2, i1 + context_lines), j1, min(j2, j1 + context_lines)]

    spacing = context_lines * 2
    group = []

    for tag, i1, i2, j1, j2 in codes:
        if tag == "equal" and i2 - i1 > spacing:
            group.append((tag, i1, min(i2, i1 + context_lines), j1, min(j2, j1 + context_lines)))
            yield group
            group = []
            i1, j1 = max(i1, i2 - context_lines), max(j1, j2 - context_lines)

        group.append((tag, i1, i2, j1, j2))

    if group and not (len(group) == 1 and group[0][0] == "equal"):
        yield group


def _format_diff_range(start, stop):
    """Format a unified-diff range the same way :mod:`difflib` does."""
    beginning = start + 1
    length = stop - start

    if length == 1:
        return str(beginning)

    if not length:
        beginning -= 1

    return f"{beginning},{length}"
