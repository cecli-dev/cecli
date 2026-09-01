import pytest

from cecli.helpers.hashline import (
    ContentHashError,
    apply_hashline_operations,
    get_hashline_diff,
    hashline,
    parse_hashline,
    resolve_content_to_hashline_ids,
    strip_hashline,
)


def test_hashline_basic():
    """Test basic hashline functionality."""
    text = "Hello\nWorld\nTest"
    result = hashline(text)

    # Check that we have 3 lines
    lines = result.splitlines()
    assert len(lines) == 3

    # Check each line has HashPos format: unique lines use —— prefix, duplicates use —4char—
    for i, line in enumerate(lines, start=1):
        # Unique lines should use —— prefix
        assert line.startswith("——"), f"Line {i} should have —— prefix but got: {line!r}"
        hash_fragment = line[:2]
        assert hash_fragment == "——"


def test_hashline_with_start_line():
    """Test hashline with custom start line."""
    text = "Line 1\nLine 2"
    result = hashline(text, start_line=10)

    lines = result.splitlines()
    assert len(lines) == 2
    # Check format is HashPos format (start_line is ignored by HashPos)
    for line in lines:
        # Unique lines should use —— prefix
        assert line.startswith("——"), f"Expected —— prefix but got: {line!r}"
        hash_fragment = line[:2]
        assert hash_fragment == "——"
    """Test hashline with empty string."""
    result = hashline("")
    assert result == ""


def test_hashline_single_line():
    """Test hashline with single line."""
    text = "Single line"
    result = hashline(text)
    lines = result.splitlines()
    assert len(lines) == 1
    # Check format is HashPos format: ——content (unique) or —4char—content (duplicate)
    line = lines[0]
    # Unique line should use —— prefix
    assert line.startswith("——"), f"Expected —— prefix but got: {line!r}"
    hash_fragment = line[:2]
    assert hash_fragment == "——"


def test_hashline_preserves_newlines():
    """Test that hashline preserves newline characters."""
    text = "Line 1\nLine 2\n"
    result = hashline(text)
    # HashPos format: {variable-length-hash}::content on each line
    # The result should have hashes on each line but no trailing newline
    lines = result.splitlines()
    assert len(lines) == 2
    # Check each line has HashPos format
    for line in lines:
        # Unique lines should use —— prefix
        assert line.startswith("——"), f"Expected —— prefix but got: {line!r}"
        hash_fragment = line[:2]
        assert hash_fragment == "——"
    # HashPos doesn't preserve trailing newlines in the formatted output
    # The splitlines() above verifies we have the right number of lines


def test_strip_hashline_basic():
    """Test basic strip_hashline functionality."""
    # Create a hashline-formatted text with HashPos format
    text = "——Hello\n——World\n——Test"
    stripped = strip_hashline(text)
    assert stripped == "Hello\nWorld\nTest"


def test_strip_hashline_with_negative_line_numbers():
    """Test strip_hashline with negative line numbers."""
    # HashPos format doesn't support negative line numbers in the prefix
    # Test with standard HashPos format
    # HashPos format: ——content (unique) or —4char—content (duplicate)
    text = "——Hello\n——World\n——Test"
    stripped = strip_hashline(text)
    assert stripped == "Hello\nWorld\nTest"


def test_strip_hashline_mixed_lines():
    """Test strip_hashline with mixed hashline and non-hashline lines."""
    # HashPos format: ——content (unique) or —4char—content (duplicate)
    # Plain lines without hashes should be left unchanged
    text = "——Hello\nPlain line\n——World"
    stripped = strip_hashline(text)
    assert stripped == "Hello\nPlain line\nWorld"


def test_strip_hashline_preserves_newlines():
    """Test that strip_hashline preserves newline characters."""
    # HashPos format: ——content (unique) or —4char—content (duplicate)
    text = "——Line 1\n——Line 2\n"
    stripped = strip_hashline(text)
    # strip_hashline should preserve newlines
    assert stripped == "Line 1\nLine 2\n"


def test_strip_hashline_empty_string():
    """Test strip_hashline with empty string."""
    assert strip_hashline("") == ""


def test_round_trip():
    """Test that strip_hashline can reverse hashline."""
    original = "Hello\nWorld\nTest\nMulti\nLine\nText"
    hashed = hashline(original)
    stripped = strip_hashline(hashed)
    assert stripped == original


def test_hashline_deterministic():
    """Test that hashline produces the same output for the same input."""
    text = "Hello World"
    result1 = hashline(text)
    result2 = hashline(text)
    assert result1 == result2


def test_hashline_different_inputs():
    """Test that different inputs produce different hashes."""
    text1 = "Hello"
    text2 = "World"
    result1 = hashline(text1)
    result2 = hashline(text2)

    # HashPos format: {variable-length-hash}::content
    # Extract hash from each line (there's only one line for single-line inputs)
    lines1 = result1.splitlines()
    lines2 = result2.splitlines()

    # Get the hash from each line (format: hash::content)
    hash1 = lines1[0].split("::", 1)[0] if lines1 else ""  # Extract hash fragment
    hash2 = lines2[0].split("::", 1)[0] if lines2 else ""  # Extract hash fragment

    # Hashes should be different (very high probability)
    assert hash1 != hash2


def test_parse_hashline():
    """Test parse_hashline function."""
    # Test basic parsing (HashPos format)
    hash_fragment, line_num_str, line_num = parse_hashline("—0abc—")
    assert hash_fragment == "—0abc—"
    assert line_num_str is None  # HashPos doesn't include line numbers
    assert line_num is None

    # Test with content after hash
    hash_fragment, line_num_str, line_num = parse_hashline("—bad1—Hello World")
    assert hash_fragment == "—bad1—"
    assert line_num_str is None
    assert line_num is None

    # Test invalid format (should raise ContentHashError)
    try:
        parse_hashline("xxxxxx")
        assert False, "Expected ContentHashError for invalid input"
    except ContentHashError:
        pass  # Expected behavior


def test_resolve_stripped_unique_line_preview_and_edit_aligned():
    """Stripped-whitespace unique line content resolves in preview AND edit paths.

    Regression test for issue #630: EditFile previews (get_hashline_diff) and
    actual edits (apply_hashline_operations) must resolve selectors identically.
    A selector with normalized/stripped whitespace that matches exactly one
    unique line must resolve to a content ID in BOTH paths.
    """
    original_content = "        xyz\n        abc\n        def\n"

    # 'abc' matches exactly one unique line '        abc' (whitespace stripped)
    resolved_start, resolved_end = resolve_content_to_hashline_ids(original_content, "abc", "abc")
    assert resolved_start != "abc"
    assert resolved_end != "abc"
    assert resolved_start == resolved_end

    # Preview path must succeed (previously raised ContentHashError)
    diff = get_hashline_diff(
        original_content=strip_hashline(original_content),
        start_line_hash=resolved_start,
        end_line_hash=resolved_end,
        operation="replace",
        text="NEW\n",
        pretty=False,
    )
    assert diff != ""

    # Actual edit path must succeed identically
    new_content, successful, failed = apply_hashline_operations(
        original_content,
        [
            {
                "start_line_hash": resolved_start,
                "end_line_hash": resolved_end,
                "operation": "replace",
                "text": "NEW",
            }
        ],
    )
    assert successful == [0]
    assert failed == []
    assert "NEW\n" in new_content
    assert "        abc" not in new_content


def test_resolve_stripped_ambiguous_line_stays_unchanged_in_both_paths():
    """Ambiguous stripped selectors remain unresolved in both paths.

    The uniqueness guard must be preserved: a stripped selector matching
    multiple lines must be returned unchanged so the preview and actual
    edit fail consistently instead of guessing which occurrence to target.
    """
    original_content = (
        "        xyz\n" "        abc\n" "        def\n" "        ghi\n" "        xyz\n"
    )

    # 'xyz' appears (stripped) in two lines -> ambiguous
    resolved_start, resolved_end = resolve_content_to_hashline_ids(original_content, "xyz", "xyz")
    assert resolved_start == "xyz"
    assert resolved_end == "xyz"

    # Preview path must fail with ContentHashError
    with pytest.raises(ContentHashError):
        get_hashline_diff(
            original_content=strip_hashline(original_content),
            start_line_hash=resolved_start,
            end_line_hash=resolved_end,
            operation="replace",
            text="NEW\n",
            pretty=False,
        )

    # Actual edit path must fail too (reported as a failed operation)
    new_content, successful, failed = apply_hashline_operations(
        original_content,
        [
            {
                "start_line_hash": resolved_start,
                "end_line_hash": resolved_end,
                "operation": "replace",
                "text": "NEW",
            }
        ],
    )
    assert successful == []
    assert len(failed) == 1
    assert new_content == original_content


def test_noop_replace_last_line_without_trailing_newline_is_failed():
    """An identical replacement of a final unterminated line is a no-op."""
    original_content = "first\nlast"
    _, last_line_id = resolve_content_to_hashline_ids(original_content, "last", "last")

    new_content, successful, failed = apply_hashline_operations(
        original_content,
        [
            {
                "start_line_hash": last_line_id,
                "end_line_hash": last_line_id,
                "operation": "replace",
                "text": "last",
            }
        ],
    )

    assert new_content == original_content
    assert successful == []
    assert failed[0]["failure_type"] == "no_change"


def test_mixed_noop_and_real_replace_reports_only_real_success():
    """A no-op in a batch must not be counted as a successful operation."""
    original_content = "first\nmiddle\nlast"
    first_id, _ = resolve_content_to_hashline_ids(original_content, "first", "first")
    _, last_id = resolve_content_to_hashline_ids(original_content, "last", "last")
    lines = [first_id, last_id]

    new_content, successful, failed = apply_hashline_operations(
        original_content,
        [
            {
                "start_line_hash": lines[0],
                "end_line_hash": lines[0],
                "operation": "replace",
                "text": "changed",
            },
            {
                "start_line_hash": lines[1],
                "end_line_hash": lines[1],
                "operation": "replace",
                "text": "last",
            },
        ],
    )

    assert new_content == "changed\nmiddle\nlast"
    assert successful == [0]
    assert [op["index"] for op in failed] == [1]
    assert failed[0]["failure_type"] == "no_change"


def test_insert_and_replace_same_anchor_are_both_applied():
    """Insert and replace operations sharing an anchor remain independent."""
    original_content = "anchor\nend\n"
    anchor_id, _ = resolve_content_to_hashline_ids(original_content, "anchor", "anchor")

    new_content, successful, failed = apply_hashline_operations(
        original_content,
        [
            {
                "start_line_hash": anchor_id,
                "end_line_hash": anchor_id,
                "operation": "replace",
                "text": "replaced",
            },
            {
                "start_line_hash": anchor_id,
                "operation": "insert",
                "text": "inserted",
            },
        ],
    )

    assert new_content == "replaced\ninserted\nend\n"
    assert sorted(successful) == [0, 1]
    assert failed == []


def test_empty_insert_is_a_noop():
    """An empty insert must not mutate content or anchor formatting."""
    original_content = "anchor\n"
    anchor_id, _ = resolve_content_to_hashline_ids(original_content, "anchor", "anchor")

    new_content, successful, failed = apply_hashline_operations(
        original_content,
        [{"start_line_hash": anchor_id, "operation": "insert", "text": ""}],
    )

    assert new_content == original_content
    assert successful == []
    assert failed[0]["failure_type"] == "no_change"
