"""Tests for closure safeguard and content boundary functions in hashline."""

from cecli.helpers.hashline import (
    _apply_closure_safeguard,
    _fix_duplicate_content_boundaries,
    _merge_replace_operations,
    _would_create_duplicate_content,
)

# =============================================================================
# Tests for _would_create_duplicate_content
# =============================================================================


def test_would_create_duplicate_no_duplicate():
    """No duplicate content at boundaries — should return False."""
    source = ["line1", "line2", "line3", "line4", "line5"]
    result = _would_create_duplicate_content(source, 1, 2, ["new_line", "other"])
    assert result is False


def test_would_create_duplicate_start_boundary():
    """First replacement line matches line before edit range — should return True."""
    source = ["keep_me", "old1", "old2", "after"]
    # Replacement starts with "keep_me" which is the line at index 0 (start-1)
    result = _would_create_duplicate_content(source, 1, 2, ["keep_me", "new_line"])
    assert result is True


def test_would_create_duplicate_end_boundary():
    """Last replacement line matches line after edit range — should return True."""
    source = ["before", "old1", "old2", "keep_me"]
    # Replacement ends with "keep_me" which is the line at index 3 (end+1)
    result = _would_create_duplicate_content(source, 1, 2, ["new1", "keep_me"])
    assert result is True


def test_would_create_duplicate_both_boundaries():
    """Both start and end boundaries have duplicate content."""
    source = ["start_dup", "old1", "old2", "end_dup"]
    result = _would_create_duplicate_content(source, 1, 2, ["start_dup", "middle", "end_dup"])
    assert result is True


def test_would_create_duplicate_empty_repl_lines():
    """Empty replacement lines — should return False."""
    source = ["line1", "line2", "line3"]
    result = _would_create_duplicate_content(source, 0, 1, [])
    assert result is False


def test_would_create_duplicate_start_at_zero():
    """candidate_start is 0 (no line before) — should not check start."""
    source = ["first", "second", "third"]
    # Even though repl[0] matches source[0], start is 0 so no check
    result = _would_create_duplicate_content(source, 0, 1, ["first", "new"])
    assert result is False


def test_would_create_duplicate_end_at_end_of_file():
    """candidate_end is last line (no line after) — should not check end."""
    source = ["first", "second", "last"]
    result = _would_create_duplicate_content(source, 0, 2, ["new", "last"])
    assert result is False


def test_would_create_duplicate_whitespace_insensitive():
    """Comparison uses rstrip(), so trailing whitespace differences are ignored."""
    source = ["spaced  ", "old1", "old2", "end"]
    # repl[0] has no trailing spaces but rstrip() matches
    result = _would_create_duplicate_content(source, 1, 2, ["spaced", "new"])  # noqa


def test_would_create_duplicate_single_line_replace():
    """Single-line replace that duplicates both adjacent lines."""
    source = ["dup", "old", "dup"]
    result = _would_create_duplicate_content(source, 1, 1, ["dup", "dup"])
    # repl[0] matches source[0], repl[-1] matches source[2]
    assert result is True


def test_would_create_duplicate_delete_operation():
    """Delete operation with empty repl_lines — should return False."""
    source = ["a", "b", "c", "d"]
    result = _would_create_duplicate_content(source, 1, 2, [])
    assert result is False


# =============================================================================
# Tests for _fix_duplicate_content_boundaries
# =============================================================================


def _make_op(operation, text, start_idx, end_idx, index=0):
    """Helper to create a resolved operation dict."""
    return {
        "index": index,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "op": {
            "operation": operation,
            "text": text,
        },
    }


def test_fix_boundaries_no_duplicate():
    """No duplicate content at boundaries — indices should remain unchanged."""
    source = ["a", "b", "c", "d", "e"]
    ops = [_make_op("replace", "x\ny", 1, 2)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 1
    assert result[0]["end_idx"] == 2


def test_fix_boundaries_start_expansion():
    """First replacement line duplicates line before — start_idx should decrement."""
    source = ["dup", "old1", "old2", "after"]
    ops = [_make_op("replace", "dup\nnew", 1, 2)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 0  # Expanded backward to consume "dup"
    assert result[0]["end_idx"] == 2


def test_fix_boundaries_end_expansion():
    """Last replacement line duplicates line after — end_idx should increment."""
    source = ["before", "old1", "old2", "dup"]
    ops = [_make_op("replace", "new\ndup", 1, 2)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 1
    assert result[0]["end_idx"] == 3  # Expanded forward to consume "dup"


def test_fix_boundaries_both_sides():
    """Both start and end have duplicates — both indices should adjust."""
    source = ["start_dup", "old1", "old2", "end_dup"]
    ops = [_make_op("replace", "start_dup\nnew\nend_dup", 1, 2)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 0  # Expanded backward
    assert result[0]["end_idx"] == 3  # Expanded forward


def test_fix_boundaries_start_at_zero():
    """start_idx is 0 — cannot expand backward, should stay 0."""
    source = ["dup", "old", "after"]
    ops = [_make_op("replace", "dup\nnew", 0, 1)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 0  # Already at 0
    assert result[0]["end_idx"] == 1


def test_fix_boundaries_end_at_last_line():
    """end_idx is last line — cannot expand forward, should stay."""
    source = ["before", "old", "dup"]
    ops = [_make_op("replace", "new\ndup", 1, 2)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 1
    assert result[0]["end_idx"] == 2  # Already at last line


def test_fix_boundaries_skip_insert():
    """Insert operations should be skipped entirely."""
    source = ["a", "b", "c"]
    ops = [_make_op("insert", "new_line", 1, 1)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 1
    assert result[0]["end_idx"] == 1


def test_fix_boundaries_empty_replacement():
    """Empty replacement text — should skip (no repl_lines)."""
    source = ["a", "b", "c"]
    ops = [_make_op("delete", "", 1, 1)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 1
    assert result[0]["end_idx"] == 1


def test_fix_boundaries_chained_duplicates_start():
    """Multiple consecutive duplicate lines at start — while loop should consume all."""
    source = ["dup", "dup", "dup", "old", "after"]
    # Replacement starts with "dup" repeated — should consume all 3 "dup" lines
    ops = [_make_op("replace", "dup\nnew", 3, 3)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 0  # All 3 "dup" lines consumed
    assert result[0]["end_idx"] == 3


def test_fix_boundaries_chained_duplicates_end():
    """Multiple consecutive duplicate lines at end — while loop should consume all."""
    source = ["before", "old", "dup", "dup", "dup"]
    ops = [_make_op("replace", "new\ndup", 1, 1)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 1
    assert result[0]["end_idx"] == 4  # All 3 "dup" lines consumed


def test_fix_boundaries_multiple_ops():
    """Multiple operations — each should be processed independently."""
    source = ["dup1", "old1", "old2", "dup2", "old3", "old4"]
    ops = [
        _make_op("replace", "dup1\nnew", 1, 2, index=0),  # Should expand start to 0
        _make_op("replace", "new\ndup2", 3, 3, index=1),  # Should expand end to 3
    ]
    result = _fix_duplicate_content_boundaries(source, ops)
    # First op: start expanded backward from 1 to 0
    assert result[0]["start_idx"] == 0
    assert result[0]["end_idx"] == 2
    # Second op: end expanded forward from 3 to 3 (dup2 at index 4... wait, no)
    # Actually source[3]="dup2", repl[-1]="dup2" → end_idx goes from 3 to...
    # dup2 is at index 3, source[4]="old3" is not "dup2", so end stays at 3
    assert result[1]["start_idx"] == 3
    assert result[1]["end_idx"] == 3


def test_fix_boundaries_whitespace_insensitive():
    """Boundary fix uses rstrip() — should match despite trailing whitespace differences."""
    source = ["dup  ", "old1", "old2", "after"]
    ops = [_make_op("replace", "dup\nnew", 1, 2)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 0


def test_fix_boundaries_partial_match_does_not_trigger():
    """Only exact (rstripped) match triggers expansion, not partial/substring."""
    source = ["different", "old1", "old2", "after"]
    ops = [_make_op("replace", "diff\nnew", 1, 2)]
    result = _fix_duplicate_content_boundaries(source, ops)
    assert result[0]["start_idx"] == 1  # No change
    assert result[0]["end_idx"] == 2


# =============================================================================
# Tests for _apply_closure_safeguard (tree-sitter boundary healing)
# =============================================================================


def _make_closure_op(operation, text, start_idx, end_idx, index=0):
    """Helper to create a resolved operation for _apply_closure_safeguard."""
    op = {
        "operation": operation,
        "text": text,
    }
    return {
        "index": index,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "op": op,
    }


def test_closure_safeguard_no_file_path():
    """Without file_path, ops should be returned unchanged."""
    ops = [_make_closure_op("replace", "pass", 0, 0)]
    result, rejected = _apply_closure_safeguard("x = 1", ops, file_path=None)
    assert result == ops
    assert rejected == []


def test_closure_safeguard_unsupported_language():
    """File path with unsupported language — ops returned unchanged."""
    ops = [_make_closure_op("replace", "xyz", 0, 0)]
    result, rejected = _apply_closure_safeguard("some content", ops, file_path="test.xyz")
    assert result == ops
    assert rejected == []


def test_closure_safeguard_empty_ops():
    """Empty ops list — returned as-is."""
    result, rejected = _apply_closure_safeguard("x = 1", [], file_path="test.py")
    assert result == []
    assert rejected == []


def test_closure_safeguard_valid_code_no_change():
    """Edit that produces valid Python should keep original bounds."""
    source = """x = 1
y = 2
z = 3
"""
    # Replace all 3 lines with 2 valid lines
    ops = [_make_closure_op("replace", "a = 10\nb = 20", 0, 2)]
    result, rejected = _apply_closure_safeguard(source, ops, file_path="test.py")
    assert result[0]["start_idx"] == 0
    assert result[0]["end_idx"] == 2


def test_closure_safeguard_heals_outer_scope():
    """
    When an edit eats outer scope (e.g., removes opening brace but leaves
    closing brace), the safeguard should expand boundaries to consume the stray brace.
    """
    source = """def foo():
    return {
        "key": "value"
    }
"""
    # Lines: 0="def foo():", 1="    return {", 2='        "key": "value"',
    #        3="    }"
    # Replacing lines 1-2 with '    return "value"' leaves a stray '}' on line 3,
    # which tree-sitter finds as an ERROR.
    # The safeguard should expand end_idx to include line 3.
    ops = [_make_closure_op("replace", '    return "value"', 1, 2)]
    result, rejected = _apply_closure_safeguard(source, ops, file_path="test.py")
    assert result[0]["start_idx"] == 1
    assert result[0]["end_idx"] == 3  # Expanded to consume stray closing brace


def test_closure_safeguard_simple_python_replace():
    """Simple replace that maintains valid Python syntax."""
    source = """x = 1
y = 2
z = 3
"""
    # Replace line 1 ("y = 2") with "y = 99"
    ops = [_make_closure_op("replace", "y = 99", 1, 1)]
    result, rejected = _apply_closure_safeguard(source, ops, file_path="test.py")
    assert result[0]["start_idx"] == 1
    assert result[0]["end_idx"] == 1


def test_closure_safeguard_delete_valid():
    """Delete operation that maintains valid syntax."""
    source = """x = 1
y = 2
z = 3
"""
    # Delete line 1 ("y = 2") — result is "x = 1\nz = 3" which is valid
    ops = [_make_closure_op("delete", None, 1, 1)]
    result, rejected = _apply_closure_safeguard(source, ops, file_path="test.py")
    assert result[0]["start_idx"] == 1
    assert result[0]["end_idx"] == 1


def test_closure_safeguard_heals_stray_except():
    """
    When an edit eats the 'try' header but leaves the 'except' block,
    the safeguard should expand boundaries to consume the stray 'except'.
    """
    source = """try:
    pass
except:
    pass
"""
    # Lines: 0="try:", 1="    pass", 2="except:", 3="    pass"
    # Replacing lines 0-1 with 'x = 1' leaves a stray 'except:' on line 2.
    # The safeguard should expand the boundary to avoid the parse error.
    ops = [_make_closure_op("replace", "x = 1", 0, 1)]
    result, rejected = _apply_closure_safeguard(source, ops, file_path="test.py")
    healed_start = result[0]["start_idx"]
    healed_end = result[0]["end_idx"]
    # Boundaries should have changed from original (0, 1)
    assert (healed_start, healed_end) != (0, 1), "Expected safeguard to heal stray except error"
    # Verify the healed result parses correctly via tree-sitter (what the safeguard uses)
    from cecli.helpers.grep_ast.tsl import get_parser

    parser = get_parser("python")
    lines = source.splitlines()
    new_lines = lines[:healed_start] + ["x = 1"] + lines[healed_end + 1 :]
    new_source = "\n".join(new_lines)
    tree = parser.parse(new_source.encode("utf-8"))
    assert (
        not tree.root_node.has_error
    ), f"Healed source still has tree-sitter errors: {new_source!r}"


# =============================================================================
# Tests for eviction gate (edits that introduce syntax errors are rejected)
# =============================================================================


def test_closure_safeguard_evicts_syntax_error_edit():
    """
    Edit that produces invalid Python syntax should be evicted by the gate.
    The eviction gate checks if ast_error_count > baseline_error_count and
    discards the edit entirely when even the best candidate boundary fails.
    """
    source = """x = 1
y = 2
z = 3
"""
    # Replace "z = 3" with "]][][[[]" — broken syntax that no boundary adjustment can fix.
    ops = [_make_closure_op("replace", "]][][[[]", 2, 2)]
    result, rejected = _apply_closure_safeguard(source, ops, file_path="test.py")
    # The edit should be evicted (not in result, present in rejected)
    assert len(result) == 0, f"Expected no ops to survive, got {len(result)}"
    assert len(rejected) == 1, f"Expected 1 rejected op, got {len(rejected)}"
    assert "syntax error" in rejected[0]["error"].lower()
    assert rejected[0]["index"] == 0


def test_closure_safeguard_evicts_incompatible_replacement():
    """
    An edit that fundamentally breaks the grammar (e.g., replacing a function
    body with something syntactically incompatible) should be evicted.
    No amount of boundary shifting can fix it.
    """
    source = """def foo():
    return 1

def bar():
    return 2
"""
    # Replace the entire function + middle with just hard-to-parse junk
    ops = [_make_closure_op("replace", "]]]]broken[[[[", 0, 3)]
    result, rejected = _apply_closure_safeguard(source, ops, file_path="test.py")
    assert len(result) == 0, f"Expected no ops to survive, got {len(result)}"
    assert len(rejected) == 1
    assert rejected[0]["index"] == 0


def test_closure_safeguard_edit_with_off_by_one_healing():
    """
    An edit that is slightly off (off-by-one line) should be healed by
    expanding boundaries to include the missing context.
    """
    source = """def foo():
    return {
        "key": "value",
    }

def bar():
    return 42
"""
    # Replace just line 1 ("    return {") with '    return "value"' — but
    # leave lines 2-3 (the dict contents and closing brace) orphaned.
    # The safeguard should expand end_idx to consume the orphaned lines.
    ops = [_make_closure_op("replace", '    return "value"', 1, 1)]
    result, rejected = _apply_closure_safeguard(source, ops, file_path="test.py")
    assert len(result) == 1, f"Expected 1 healed op, got {len(result)}"
    assert len(rejected) == 0, f"Expected no rejected ops, got {len(rejected)}"
    # Boundaries should have expanded from (1, 1) to include lines 2-3
    healed_start = result[0]["start_idx"]
    healed_end = result[0]["end_idx"]
    assert (
        healed_end >= 3
    ), f"Expected end_idx >= 3 (to consume orphaned dict lines), got {healed_end}"
    # Verify the healed result parses correctly
    from cecli.helpers.grep_ast.tsl import get_parser

    parser = get_parser("python")
    lines = source.splitlines()
    new_lines = lines[:healed_start] + ['    return "value"'] + lines[healed_end + 1 :]
    new_source = "\n".join(new_lines)
    tree = parser.parse(new_source.encode("utf-8"))
    assert (
        not tree.root_node.has_error
    ), f"Healed source still has tree-sitter errors: {new_source!r}"


def test_closure_safeguard_off_by_one_start():
    """
    When an edit's start_idx is one line too late (doesn't include a
    statement that opens a scope), the safeguard should expand it backward.
    """
    source = """def foo():
    return {
        "key": "value",
    }
"""
    # Line 0: "def foo():"
    # Line 1: "    return {"
    # Line 2: '        "key": "value",'
    # Line 3: "    }"
    # Replace lines 2-3 with '    pass' — this leaves line 0 and 1
    # (the function header and the opening brace) but replaces the
    # content and closing brace. Result has a stray opening brace
    # that cannot be parsed.
    # The safeguard should expand start_idx from 2 backward to 1
    # to include the "    return {" line.
    ops = [_make_closure_op("replace", "    pass", 2, 3)]
    result, rejected = _apply_closure_safeguard(source, ops, file_path="test.py")
    assert len(result) == 1
    assert len(rejected) == 0
    # start_idx should have expanded from 2 to at most 1
    assert result[0]["start_idx"] <= 1, (
        f"Expected start_idx <= 1 (expanded for opening brace), " f"got {result[0]['start_idx']}"
    )


def test_apply_closure_safeguard_passes_rejected_ops_to_failed():
    """
    Integration test: apply_hashline_operations should propagate rejected
    operations (from _apply_closure_safeguard) into the failed_ops list.
    """
    from cecli.helpers.hashline import apply_hashline_operations

    source = """x = 1
y = 2
"""
    # Try to replace a line with broken syntax — this should fail via eviction
    # Get the correct hashline ID for the first line using HashPos API
    # New format uses —4chars— (tilde-wrapped 4-char hash), no :: separator
    from cecli.helpers.hashpos.hashpos import HashPos

    hp = HashPos(source)
    first_line_hash = hp.get_wrapped_id(hp.generate_public_id("x = 1", 0, 1))

    ops = [
        {
            "start_line_hash": first_line_hash,
            "end_line_hash": first_line_hash,
            "operation": "replace",
            "text": "]][[[[broken",
        }
    ]
    new_content, successful_ops, failed_ops = apply_hashline_operations(
        source, ops, file_path="test.py"
    )
    # Content should be unchanged since the edit was rejected
    assert new_content == source, "Expected content unchanged when all edits are rejected"
    assert len(failed_ops) >= 1, f"Expected at least 1 failed_ops from eviction, got {failed_ops}"
    # Error message should mention syntax errors
    assert any(
        "syntax error" in op["error"].lower() for op in failed_ops
    ), f"Expected syntax error mention in failed_ops, got {failed_ops}"


# =============================================================================
# Tests for _merge_replace_operations


def _make_merge_op(operation, text, start_idx, end_idx, index=0):
    """Helper to create a resolved operation dict for merge tests."""
    return {
        "index": index,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "op": {
            "operation": operation,
            "text": text,
        },
    }


def test_merge_non_adjacent_ops():
    """Non-adjacent operations with a gap should NOT be merged."""
    ops = [
        _make_merge_op("replace", "first block", 0, 1, index=0),
        _make_merge_op("replace", "second block", 3, 4, index=1),
    ]
    result = _merge_replace_operations(ops)
    # Should remain separate (2 items)
    assert len(result) == 2
    assert result[0]["op"]["text"] == "first block"
    assert result[1]["op"]["text"] == "second block"


def test_merge_overlapping_with_text_overlap():
    """Overlapping ops with overlapping text should merge and deduplicate."""
    ops = [
        _make_merge_op("replace", "a\nb\nc", 0, 2, index=0),
        _make_merge_op("replace", "c\nd\ne", 2, 4, index=1),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    # The overlapping line "c" should appear only once
    assert result[0]["op"]["text"] == "a\nb\nc\nd\ne"
    # Range should cover both
    assert result[0]["start_idx"] == 0
    assert result[0]["end_idx"] == 4


def test_merge_adjacent_no_overlap_with_trailing_newline():
    """
    Adjacent ops where prev_text ends with \\n.
    This should merge correctly without needing an extra newline.
    """
    ops = [
        _make_merge_op("replace", "def foo():\n    pass\n", 0, 1, index=0),
        _make_merge_op("replace", "def bar():\n    pass", 2, 3, index=1),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    merged_text = result[0]["op"]["text"]
    assert "def foo():" in merged_text
    assert "def bar():" in merged_text
    # The trailing \n on prev_text provides the necessary separator
    assert "    pass\ndef bar():" in merged_text or "pass\ndef bar():" in merged_text


def test_merge_adjacent_no_overlap_leading_newline_in_curr():
    """
    Adjacent ops where curr_text starts with \\n.
    This should merge correctly without needing an extra newline.
    """
    ops = [
        _make_merge_op("replace", "def foo():\n    pass", 0, 1, index=0),
        _make_merge_op("replace", "\ndef bar():\n    pass", 2, 3, index=1),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    merged_text = result[0]["op"]["text"]
    assert "def foo():" in merged_text
    assert "def bar():" in merged_text


def test_merge_adjacent_no_overlap_missing_newline_separator():
    """
    ADJACENT ops where NEITHER text provides the newline separator.
    This is the bug case: "    pass" + "def bar():" should have a newline between them.
    Expected: "def foo():\n    pass\ndef bar():\n    pass"
    """
    ops = [
        _make_merge_op("replace", "def foo():\n    pass", 0, 1, index=0),
        _make_merge_op("replace", "def bar():\n    pass", 2, 3, index=1),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    merged_text = result[0]["op"]["text"]
    # Expect content to be on separate lines
    expected = "def foo():\n    pass\ndef bar():\n    pass"
    assert merged_text == expected, (
        f"Expected lines to be separated by newline.\n"
        f"  Expected: {expected!r}\n"
        f"  Got:      {merged_text!r}\n"
        f"  Problem:  'pass' and 'def bar()' are smushed together"
    )


def test_merge_adjacent_single_line_texts_no_newline_separator():
    """
    Adjacent ops with single-line texts and no newline separator.
    If one op replaces line 1 with 'line_a' and another replaces line 2 with 'line_b',
    the merged result should be 'line_a\nline_b'.
    """
    ops = [
        _make_merge_op("replace", "line_a", 0, 0, index=0),
        _make_merge_op("replace", "line_b", 1, 1, index=1),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    merged_text = result[0]["op"]["text"]
    expected = "line_a\nline_b"
    assert merged_text == expected, (
        f"Expected single-line texts to be separated by newline.\n"
        f"  Expected: {expected!r}\n"
        f"  Got:      {merged_text!r}\n"
    )


def test_merge_adjacent_multi_line_without_separator():
    """
    Adjacent ops, each with multi-line text, where neither provides the
    newline separator between the two blocks.
    """
    ops = [
        _make_merge_op("replace", "line1\nline2", 0, 1, index=0),
        _make_merge_op("replace", "line3\nline4", 2, 3, index=1),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    merged_text = result[0]["op"]["text"]
    expected = "line1\nline2\nline3\nline4"
    assert merged_text == expected, (
        f"Expected all 4 lines to be on separate lines.\n"
        f"  Expected: {expected!r}\n"
        f"  Got:      {merged_text!r}\n"
        f"  Problem:  'line2' and 'line3' are likely on the same line"
    )


def test_merge_adjacent_complete_lines_with_separator():
    """
    Adjacent ops where both texts end with \\n (complete lines).
    This should already work correctly.
    """
    ops = [
        _make_merge_op("replace", "line1\nline2\n", 0, 1, index=0),
        _make_merge_op("replace", "line3\nline4\n", 2, 3, index=1),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    merged_text = result[0]["op"]["text"]
    expected = "line1\nline2\nline3\nline4\n"
    assert merged_text == expected


def test_merge_three_adjacent_ops_no_separator():
    """
    Three adjacent ops where none provides the newline separator between blocks.
    """
    ops = [
        _make_merge_op("replace", "block1", 0, 0, index=0),
        _make_merge_op("replace", "block2", 1, 1, index=1),
        _make_merge_op("replace", "block3", 2, 2, index=2),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    merged_text = result[0]["op"]["text"]
    expected = "block1\nblock2\nblock3"
    assert merged_text == expected, (
        f"Expected 3 blocks on separate lines.\n"
        f"  Expected: {expected!r}\n"
        f"  Got:      {merged_text!r}"
    )


def test_merge_overlapping_no_text_overlap():
    """
    Overlapping ops (same or overlapping line ranges) but with no
    overlapping text. This shouldn't normally happen, but the function
    should handle it gracefully.
    """
    ops = [
        _make_merge_op("replace", "aaa\nbbb", 0, 1, index=0),
        _make_merge_op("replace", "ccc\nddd", 1, 2, index=1),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    merged_text = result[0]["op"]["text"]
    # No overlap in text, so they get concatenated
    # Since they overlap on line 1, we need a newline
    assert "aaa\nbbb" in merged_text
    assert "ccc\nddd" in merged_text


def test_merge_different_op_types_not_merged():
    """
    Adjacent ops of different types (replace vs insert) should NOT be merged.
    """
    ops = [
        _make_merge_op("replace", "replacement", 0, 0, index=0),
        _make_merge_op("insert", "insertion", 1, 1, index=1),
    ]
    result = _merge_replace_operations(ops)
    assert len(result) == 2


def test_merge_single_op_returns_as_is():
    """A single operation should be returned unchanged."""
    ops = [_make_merge_op("replace", "text", 0, 0, index=0)]
    result = _merge_replace_operations(ops)
    assert len(result) == 1
    assert result[0]["op"]["text"] == "text"
