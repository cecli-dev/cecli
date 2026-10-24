from cecli.helpers.diff.diff_helpers import unified_diff_compacted


def _added_lines(diff):
    return [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]


def _removed_lines(diff):
    return [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]


def test_compacts_duplicate_insertion_block():
    old = ["def first():", "    return 1", "", "", "def second():", "    return 1"]
    new = [
        "def first():",
        "    return 1",
        "",
        "",
        "def middle():",
        "    return 1",
        "",
        "",
        "def second():",
        "    return 1",
    ]

    diff = unified_diff_compacted(old, new, "a", "b", context_lines=3)
    added = _added_lines(diff)
    first_added = next(line for line in added if line.strip())

    assert "def middle():" in first_added
    assert not any("def first():" in line for line in added)
    assert not any("def second():" in line for line in added)


def test_compacts_duplicate_deletion_block():
    old = [
        "def first():",
        "    return 1",
        "",
        "",
        "def middle():",
        "    return 1",
        "",
        "",
        "def second():",
        "    return 1",
    ]
    new = ["def first():", "    return 1", "", "", "def second():", "    return 1"]

    diff = unified_diff_compacted(old, new, "a", "b", context_lines=3)
    removed = _removed_lines(diff)
    first_removed = next(line for line in removed if line.strip())

    assert "def middle():" in first_removed
    assert not any("def first():" in line for line in removed)
    assert not any("def second():" in line for line in removed)


def test_unchanged_input_returns_empty_diff():
    lines = ["alpha", "beta"]

    assert unified_diff_compacted(lines, list(lines)) == []


def test_replacement_diff_has_correct_ranges():
    diff = unified_diff_compacted(["a", "b", "c"], ["a", "B", "c"], "old", "new")

    assert diff == [
        "--- old",
        "+++ new",
        "@@ -1,3 +1,3 @@",
        " a",
        "-b",
        "+B",
        " c",
    ]


def test_compacts_insertion_at_start():
    diff = unified_diff_compacted(["a", "b"], ["a", "a", "b"], "a", "b", context_lines=3)

    assert diff == ["--- a", "+++ b", "@@ -1,2 +1,3 @@", " a", "+a", " b"]


def test_compacts_deletion_at_start():
    diff = unified_diff_compacted(["a", "a", "b"], ["a", "b"], "a", "b", context_lines=3)

    assert diff == ["--- a", "+++ b", "@@ -1,3 +1,2 @@", " a", "-a", " b"]
