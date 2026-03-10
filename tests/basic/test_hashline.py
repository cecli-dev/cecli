"""Tests for hashline.py functions."""

import pytest

from cecli.helpers.hashline import (
    HashlineError,
    apply_hashline_operation,
    extract_hashline_range,
    find_hashline_by_exact_match,
    find_hashline_by_fragment,
    get_hashline_content_diff,
    get_hashline_diff,
    hashline,
    int_to_2digit_52,
    normalize_hashline,
    parse_hashline,
    strip_hashline,
)


def test_int_to_2digit_52_basic():
    """Test basic integer to 2-digit base52 conversion."""
    assert int_to_2digit_52(0) == "aa"
    assert int_to_2digit_52(1) == "ab"
    assert int_to_2digit_52(25) == "az"
    # Note: We now lower case all output, so values >= 26 are lowercase too
    assert int_to_2digit_52(26) == "aa"  # Was "aA", now lowercase
    assert int_to_2digit_52(51) == "az"  # Was "aZ", now lowercase
    assert int_to_2digit_52(52) == "ba"
    assert int_to_2digit_52(2703) == "zz"  # Was "ZZ", now lowercase


def test_int_to_2digit_52_wraparound():
    """Test that values wrap around modulo 2704."""
    assert int_to_2digit_52(2704) == "aa"  # wraps around
    assert int_to_2digit_52(2705) == "ab"
    assert int_to_2digit_52(5408) == "aa"  # 2 * 2704


def test_hashline_basic():
    """Test basic hashline functionality."""
    text = "Hello\nWorld\nTest"
    result = hashline(text)

    # Check that we have 3 lines
    lines = result.splitlines()
    assert len(lines) == 3

    # Check each line has the format "|line_numberhash|content" (correct format)
    for i, line in enumerate(lines, start=1):
        assert "|" in line
        # Format should be "|{line_num}{hash_fragment}|{content}"
        # So splitting by "|" should give 3 parts: empty string, line_num+hash, content
        parts = line.split("|", 2)
        assert len(parts) == 3
        # First part should be empty (leading pipe)
        assert parts[0] == ""
        # Second part should be line number + hash fragment
        line_num_hash = parts[1]
        # Extract line number (all digits at the beginning)
        line_num_str = ""
        for char in line_num_hash:
            if char.isdigit():
                line_num_str += char
            else:
                break
        assert line_num_str == str(i)
        # Check hash fragment is 2 characters
        hash_fragment = line_num_hash[len(line_num_str) :]
        assert len(hash_fragment) == 2
        # Check all hash characters are valid base52
        for char in hash_fragment:
            assert char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def test_hashline_with_start_line():
    """Test hashline with custom start line."""
    text = "Line 1\nLine 2"
    result = hashline(text, start_line=10)

    lines = result.splitlines()
    assert len(lines) == 2
    # Check format is |line_numberhash|content (correct format)
    assert "|10" in lines[0]
    assert "|11" in lines[1]
    # Extract hash fragments to verify they're valid
    # Format is |line_numhash|content, so split by "|" gives ["", "line_numhash", "content"]
    hash1 = lines[0].split("|")[1]
    hash2 = lines[1].split("|")[1]
    # Remove line number from hash to get just the hash fragment
    hash_fragment1 = hash1[2:]  # Skip "10"
    hash_fragment2 = hash2[2:]  # Skip "11"
    assert len(hash_fragment1) == 2
    assert len(hash_fragment2) == 2
    for char in hash_fragment1 + hash_fragment2:
        assert char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def test_hashline_empty_string():
    """Test hashline with empty string."""
    result = hashline("")
    assert result == ""


def test_hashline_single_line():
    """Test hashline with single line."""
    text = "Single line"
    result = hashline(text)
    lines = result.splitlines()
    assert len(lines) == 1
    # Check format is |line_numberhash|content (correct format)
    assert "|1" in lines[0]
    assert lines[0].endswith("|Single line")
    # Extract hash fragment to verify it's valid
    # Format is |line_numhash|content, so split by "|" gives ["", "line_numhash", "content"]
    line_num_hash = lines[0].split("|")[1]
    # Remove line number from hash to get just the hash fragment
    hash_fragment = line_num_hash[1:]  # Skip "1"
    for char in hash_fragment:
        assert char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def test_hashline_preserves_newlines():
    """Test that hashline preserves newline characters."""
    text = "Line 1\nLine 2\n"
    result = hashline(text)
    # Should end with newline since input ended with newline
    assert result.endswith("\n")
    lines = result.splitlines(keepends=True)
    # splitlines(keepends=True) doesn't preserve trailing empty lines
    # So we should have 2 lines, both ending with newline
    assert len(lines) == 2
    assert lines[0].endswith("\n")
    assert lines[1].endswith("\n")


def test_strip_hashline_basic():
    """Test basic strip_hashline functionality."""
    # Create a hashline-formatted text with correct format: |line_numberhash|content
    text = "|1ab|Hello\n|2cd|World\n|3ef|Test"
    stripped = strip_hashline(text)
    assert stripped == "Hello\nWorld\nTest"


def test_strip_hashline_with_negative_line_numbers():
    """Test strip_hashline with negative line numbers."""
    # Note: Negative line numbers are no longer supported since line numbers in files are always positive
    # But the regex still handles them if they appear
    text = "|-1ab|Hello\n|0cd|World\n|1ef|Test"
    stripped = strip_hashline(text)
    assert stripped == "Hello\nWorld\nTest"


def test_strip_hashline_mixed_lines():
    """Test strip_hashline with mixed hashline and non-hashline lines."""
    text = "|1ab|Hello\nPlain line\n|3cd|World"
    stripped = strip_hashline(text)
    assert stripped == "Hello\nPlain line\nWorld"


def test_strip_hashline_preserves_newlines():
    """Test that strip_hashline preserves newline characters."""
    text = "|1ab|Line 1\n|2cd|Line 2\n"
    stripped = strip_hashline(text)
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

    # Extract hashes (hash is second part in new format: line_num|hash|content)
    hash1 = result1.split("|")[1]
    hash2 = result2.split("|")[1]

    # Hashes should be different (very high probability)
    assert hash1 != hash2


def test_parse_hashline():
    """Test parse_hashline function."""
    # Test basic parsing (new format: |line_numhash|)
    hash_fragment, line_num_str, line_num = parse_hashline("|10ab|")
    assert hash_fragment == "ab"
    assert line_num_str == "10"
    assert line_num == 10

    # Test with trailing pipe
    hash_fragment, line_num_str, line_num = parse_hashline("|5cd|")
    assert hash_fragment == "cd"
    assert line_num_str == "5"
    assert line_num == 5

    # Test with old order but new separator (hash|line_num)
    hash_fragment, line_num_str, line_num = parse_hashline("ef|3")
    assert hash_fragment == "ef"
    assert line_num_str == "3"
    assert line_num == 3

    # Test invalid format
    with pytest.raises(HashlineError, match="Invalid hashline format"):
        parse_hashline("invalid")

    with pytest.raises(HashlineError, match="Invalid hashline format"):
        parse_hashline("ab")  # Missing line number

    # Test that colons are no longer supported
    with pytest.raises(HashlineError, match="Invalid hashline format"):
        parse_hashline("10:ab")


def test_normalize_hashline():
    """Test normalize_hashline function."""
    # Test new format (should return unchanged)
    assert normalize_hashline("|10ab|") == "|10ab|"

    # Test old order with new separator (should normalize to new order)
    assert normalize_hashline("ab|10") == "|10ab|"

    # Test that colons are no longer supported
    with pytest.raises(HashlineError, match="Invalid hashline format"):
        normalize_hashline("10:ab")


def test_find_hashline_by_exact_match():
    """Test find_hashline_by_exact_match function."""
    hashed_lines = [
        "|1ab|Hello",
        "|2cd|World",
        "|3ef|Test",
    ]

    # Test exact match found
    index = find_hashline_by_exact_match(hashed_lines, "cd", "2")
    assert index == 1

    # Test exact match not found
    index = find_hashline_by_exact_match(hashed_lines, "wrong", "2")
    assert index is None

    # Test line number doesn't match
    index = find_hashline_by_exact_match(hashed_lines, "cd", "5")
    assert index is None


def test_find_hashline_by_fragment():
    """Test find_hashline_by_fragment function."""
    hashed_lines = [
        "|1ab|Hello",
        "|2cd|World",
        "|3ab|Test",  # Same hash fragment as line 1
        "|4ef|Another",
    ]

    # Test fragment found
    index = find_hashline_by_fragment(hashed_lines, "cd")
    assert index == 1

    # Test fragment found (first occurrence)
    index = find_hashline_by_fragment(hashed_lines, "ab")
    assert index == 0  # Should return first occurrence

    # Test fragment not found
    index = find_hashline_by_fragment(hashed_lines, "zz")
    assert index is None


def test_apply_hashline_operation_insert():
    """Test apply_hashline_operation with insert operation."""
    original = "Line 1\nLine 2\nLine 3"
    hashed = hashline(original)

    # Get hash fragment for line 2
    # Format is |line_numhash|content, so split by "|" gives ["", "line_numhash", "content"]
    hashed_lines = hashed.splitlines()
    line2_hash = hashed_lines[1].split("|")[1]  # This gives "2Fy" (line number + hash fragment)
    # Extract just the hash fragment (last 2 characters)
    hash_fragment = line2_hash[-2:]  # This gives "Fy"

    # Insert after line 2
    # Construct hashline string in correct format: |line_numhash_fragment|
    new_content = apply_hashline_operation(
        original,
        f"|2{hash_fragment}|",
        operation="insert",
        text="Inserted line",
    )

    expected = "Line 1\nLine 2\nInserted line\nLine 3"
    assert new_content == expected


def test_apply_hashline_operation_delete():
    """Test apply_hashline_operation with delete operation."""
    original = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    hashed = hashline(original)

    # Get hash fragments
    # Format is |line_numhash|content, so split by "|" gives ["", "line_numhash", "content"]
    hashed_lines = hashed.splitlines()
    line2_hash = hashed_lines[1].split("|")[1]  # This gives "2Fy" (line number + hash fragment)
    line4_hash = hashed_lines[3].split("|")[1]  # This gives "4Xj" (line number + hash fragment)
    # Extract just the hash fragments (last 2 characters)
    hash_fragment2 = line2_hash[-2:]  # This gives "Fy"
    hash_fragment4 = line4_hash[-2:]  # This gives "Xj"

    # Delete lines 2-4
    # Construct hashline strings in correct format: |line_numhash_fragment|
    new_content = apply_hashline_operation(
        original,
        f"|2{hash_fragment2}|",
        f"|4{hash_fragment4}|",
        operation="delete",
    )

    expected = "Line 1\nLine 5"
    assert new_content == expected


def test_extract_hashline_range():
    """Test extract_hashline_range function."""
    original = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    hashed = hashline(original)

    # Get hash fragments
    # Format is |line_numhash|content, so split by "|" gives ["", "line_numhash", "content"]
    hashed_lines = hashed.splitlines()
    line2_hash = hashed_lines[1].split("|")[1]  # This gives "2Fy" (line number + hash fragment)
    line4_hash = hashed_lines[3].split("|")[1]  # This gives "4Xj" (line number + hash fragment)
    # Extract just the hash fragments (last 2 characters)
    hash_fragment2 = line2_hash[-2:]  # This gives "Fy"
    hash_fragment4 = line4_hash[-2:]  # This gives "Xj"

    # Extract lines 2-4
    # Construct hashline strings in correct format: |line_numhash_fragment|
    extracted = extract_hashline_range(
        original,
        f"|2{hash_fragment2}|",
        f"|4{hash_fragment4}|",
    )

    # Extract should return hashed content
    expected_hashed_range = "\n".join(hashed_lines[1:4]) + "\n"
    assert extracted == expected_hashed_range


def test_get_hashline_diff():
    """Test get_hashline_diff function."""
    original = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    hashed = hashline(original)

    # Get hash fragments
    # Format is |line_numhash|content, so split by "|" gives ["", "line_numhash", "content"]
    hashed_lines = hashed.splitlines()
    line2_hash = hashed_lines[1].split("|")[1]  # This gives "2Fy" (line number + hash fragment)
    line4_hash = hashed_lines[3].split("|")[1]  # This gives "4Xj" (line number + hash fragment)
    # Extract just the hash fragments (last 2 characters)
    hash_fragment2 = line2_hash[-2:]  # This gives "Fy"
    hash_fragment4 = line4_hash[-2:]  # This gives "Xj"

    # Get diff for replace operation
    # Construct hashline strings in correct format: |line_numhash_fragment|
    diff = get_hashline_diff(
        original,
        f"|2{hash_fragment2}|",
        f"|4{hash_fragment4}|",
        operation="replace",
        text="New line 2\nNew line 3\nNew line 4",
    )

    # Diff should not be empty
    assert diff != ""
    # Diff should contain the changed lines
    assert "Line 2" in diff or "New line 2" in diff


def test_get_hashline_content_diff():
    """Test get_hashline_content_diff function."""
    old_content = "1|ab|Hello\n2|cd|World\n3|ef|Test"
    new_content = "1|ab|Hello\n2|cd|Changed\n3|ef|Test"

    diff = get_hashline_content_diff(old_content, new_content)

    # Diff should not be empty
    assert diff != ""
    # Diff should show the change
    assert "World" in diff or "Changed" in diff

    # Test with identical content
    diff = get_hashline_content_diff(old_content, old_content)
    assert diff == ""


def test_apply_hashline_operations_complex_sequence():
    """Test 1: Sequence of 5+ mixed operations on 20+ lines."""
    from cecli.helpers.hashline import apply_hashline_operations

    original = "\n".join([f"Line {i + 1}" for i in range(25)])
    print(f"\nTest: Complex sequence\nOriginal (first 10 lines): {original.splitlines()[:10]}")
    hashed = hashline(original)
    h_lines = hashed.splitlines()

    # Get hashes for lines 2, 5, 10, 15, 20
    h2 = h_lines[1].split("|")[1]
    h5 = h_lines[4].split("|")[1]
    h10 = h_lines[9].split("|")[1]
    h15 = h_lines[14].split("|")[1]
    h20 = h_lines[19].split("|")[1]

    ops = [
        {
            "operation": "replace",
            "start_line_hash": f"|2{parse_hashline(f'|{h2}|')[0]}|",
            "end_line_hash": f"|2{parse_hashline(f'|{h2}|')[0]}|",
            "text": "New Line 2",
        },
        {
            "operation": "insert",
            "start_line_hash": f"|5{parse_hashline(f'|{h5}|')[0]}|",
            "text": "Inserted after 5",
        },
        {
            "operation": "delete",
            "start_line_hash": f"|10{parse_hashline(f'|{h10}|')[0]}|",
            "end_line_hash": f"|10{parse_hashline(f'|{h10}|')[0]}|",
        },
        {
            "operation": "replace",
            "start_line_hash": f"|15{parse_hashline(f'|{h15}|')[0]}|",
            "end_line_hash": f"|15{parse_hashline(f'|{h15}|')[0]}|",
            "text": "New Line 15",
        },
        {
            "operation": "insert",
            "start_line_hash": f"|20{parse_hashline(f'|{h20}|')[0]}|",
            "text": "Inserted after 20",
        },
    ]

    print(f"Operations: {ops}")

    modified, success, failed = apply_hashline_operations(original, ops)

    print(f"Success indices: {success}")
    print(f"Failed: {len(failed)}")
    print(f"Modified (first 15 lines): {modified.splitlines()[:15]}")

    assert len(success) == 5
    assert len(failed) == 0
    mod_lines = modified.splitlines()
    assert "New Line 2" in mod_lines
    assert "Inserted after 5" in mod_lines
    assert "Line 10" not in mod_lines
    assert "New Line 15" in mod_lines
    assert "Inserted after 20" in mod_lines


def test_apply_hashline_operations_overlapping():
    """Test 2: Overlapping ranges."""
    from cecli.helpers.hashline import apply_hashline_operations

    original = "\n".join([f"Line {i + 1}" for i in range(20)])
    print(f"\nTest: Overlapping ranges\nOriginal (first 15 lines): {original.splitlines()[:15]}")
    hashed = hashline(original)
    h_lines = hashed.splitlines()

    h5 = h_lines[4].split("|")[1]
    h10 = h_lines[9].split("|")[1]
    h15 = h_lines[14].split("|")[1]

    # Op 1: Replace 5-15
    # Op 2: Replace 8-12 (inside Op 1)
    # Since it applies bottom-to-top, we need to see how it handles it.
    # Actually, apply_hashline_operations resolves indices on the ORIGINAL hashed content.
    ops = [
        {
            "operation": "replace",
            "start_line_hash": f"|5{parse_hashline(f'|{h5}|')[0]}|",
            "end_line_hash": f"|15{parse_hashline(f'|{h15}|')[0]}|",
            "text": "Big Replace",
        },
        {
            "operation": "replace",
            "start_line_hash": f"|10{parse_hashline(f'|{h10}|')[0]}|",
            "end_line_hash": f"|10{parse_hashline(f'|{h10}|')[0]}|",
            "text": "Small Replace",
        },
    ]

    print(f"Operations: {ops}")

    modified, success, failed = apply_hashline_operations(original, ops)

    print(f"Success indices: {success}")
    print(f"Failed: {len(failed)}")
    print(f"Modified lines: {modified.splitlines()}")

    # Bottom-to-top application:
    # 1. Small Replace at index 9
    # 2. Big Replace at indices 4-14
    # The Big Replace will overwrite the Small Replace if they are applied in that order on the same string.
    # However, the implementation applies them sequentially to the content.
    mod_lines = modified.splitlines()
    assert "Big Replace" in mod_lines
    # If Op 1 is applied after Op 2 (reverse order), Op 1 replaces the range that included Op 2's result.
    assert "Small Replace" not in mod_lines


def test_apply_hashline_operations_duplicate_hashes():
    """Test 3: Duplicate hash values resolution with empty lines and content."""
    from cecli.helpers.hashline import apply_hashline_operations

    original = "Same\n\nNormal Content 1\nSame\n\nNormal Content 2\nSame\n\nNormal Content 3\nSame"
    print(f"\nTest: Duplicate hashes\nOriginal: {original.splitlines()}")
    hashed = hashline(original)
    h_lines = hashed.splitlines()

    # Get actual hashes for each "Same" line
    h_val_2 = h_lines[3].split("|")[1]
    h_val_4 = h_lines[9].split("|")[1]

    # Target the 2nd (line 4) and 4th (line 10) "Same" using their specific hashes
    ops = [
        {
            "operation": "replace",
            "start_line_hash": f"|4{parse_hashline(f'|{h_val_2}|')[0]}|",
            "end_line_hash": f"|4{parse_hashline(f'|{h_val_2}|')[0]}|",
            "text": "Changed 2",
        },
        {
            "operation": "replace",
            "start_line_hash": f"|10{parse_hashline(f'|{h_val_4}|')[0]}|",
            "end_line_hash": f"|10{parse_hashline(f'|{h_val_4}|')[0]}|",
            "text": "Changed 4",
        },
    ]

    print(f"Operations: {ops}")

    modified, success, failed = apply_hashline_operations(original, ops)

    print(f"Success indices: {success}")
    print(f"Failed: {len(failed)}")
    print(f"Modified: {modified.splitlines()}")

    mod_lines = modified.splitlines()
    assert mod_lines[3] == "Changed 2"
    assert mod_lines[9] == "Changed 4"
    assert mod_lines[0] == "Same"
    assert mod_lines[6] == "Same"


def test_apply_hashline_operations_empty_lines_duplicates():
    """Test 6: Complex empty lines and duplicate hashes with multiple operations."""
    from cecli.helpers.hashline import apply_hashline_operations

    original = "Header\n\nBlock 1\n\nContent\n\nBlock 2\n\nFooter"
    print(f"\nTest: Empty lines duplicates\nOriginal: {original.splitlines()}")
    # In this case, all empty lines will likely have the same hash fragment
    # because they have the same content (empty string).
    hashed = hashline(original)
    h_lines = hashed.splitlines()

    # Find hash for an empty line (e.g., line 2)
    empty_hash = h_lines[1].split("|")[1]
    print(f"Empty line hash: {empty_hash}")

    # Operations targeting specific empty lines by their line number
    ops = [
        {
            "operation": "replace",
            "start_line_hash": f"|2{parse_hashline(f'|{empty_hash}|')[0]}|",
            "end_line_hash": f"|2{parse_hashline(f'|{empty_hash}|')[0]}|",
            "text": "# Comment 1",
        },
        {
            "operation": "replace",
            "start_line_hash": f"|6{parse_hashline(f'|{empty_hash}|')[0]}|",
            "end_line_hash": f"|6{parse_hashline(f'|{empty_hash}|')[0]}|",
            "text": "# Comment 2",
        },
        {
            "operation": "insert",
            "start_line_hash": f"|8{parse_hashline(f'|{empty_hash}|')[0]}|",
            "text": "# Inserted after empty line 8",
        },
    ]

    print(f"Operations: {ops}")

    modified, success, failed = apply_hashline_operations(original, ops)

    print(f"Success indices: {success}")
    print(f"Failed: {len(failed)}")
    print(f"Modified: {modified.splitlines()}")

    assert len(success) == 3
    assert len(failed) == 0

    mod_lines = modified.splitlines()
    # Line 2 (index 1) should be replaced
    assert mod_lines[1] == "# Comment 1"
    # Line 4 (index 3) should still be empty
    assert mod_lines[3] == ""
    # Line 6 (index 5) should be replaced
    assert mod_lines[5] == "# Comment 2"
    # Line 8 (index 7) should still be empty, followed by insertion
    assert mod_lines[7] == ""
    assert mod_lines[8] == "# Inserted after empty line 8"


def test_apply_hashline_operations_multiline_non_contiguous():
    """Test 7: Non-contiguous multiline replaces on a 40+ line file with duplicates."""
    from cecli.helpers.hashline import apply_hashline_operations

    # Create a 45-line file with interspersed duplicates
    lines = []
    for i in range(1, 46):
        if i % 10 == 0:
            lines.append("Duplicate Block")
            lines.append("Common Content")
        else:
            lines.append(f"Unique Line {i}")
    original = "\n".join(lines)

    print(
        f"\nTest: Multiline non-contiguous\nOriginal (first 20 lines): {original.splitlines()[:20]}"
    )

    hashed = hashline(original)
    h_lines = hashed.splitlines()

    # We want to perform three non-contiguous multiline replacements
    # Op 1: Lines 5-8 (Unique Line 5 to Unique Line 8)
    # Op 2: Lines 16-22 (Unique Line 15 to Common Content)
    # Op 3: Lines 35-42 (Unique Line 32 to Unique Line 39)

    def get_h(ln):
        return h_lines[ln - 1].split("|")[1]

    ops = [
        {
            "operation": "replace",
            "start_line_hash": f"|5{parse_hashline(f'|{get_h(5)}|')[0]}|",
            "end_line_hash": f"|8{parse_hashline(f'|{get_h(8)}|')[0]}|",
            "text": "Replacement Alpha",
        },
        {
            "operation": "replace",
            "start_line_hash": f"|16{parse_hashline(f'|{get_h(16)}|')[0]}|",
            "end_line_hash": f"|22{parse_hashline(f'|{get_h(22)}|')[0]}|",
            "text": "Replacement Beta\nMore Beta",
        },
        {
            "operation": "replace",
            "start_line_hash": f"|35{parse_hashline(f'|{get_h(35)}|')[0]}|",
            "end_line_hash": f"|42{parse_hashline(f'|{get_h(42)}|')[0]}|",
            "text": "Replacement Gamma",
        },
    ]

    print(f"Operations: {ops}")

    modified, success, failed = apply_hashline_operations(original, ops)

    print(f"Success indices: {success}")
    print(f"Failed: {len(failed)}")
    print(f"Modified (first 25 lines): {modified.splitlines()[:25]}")

    assert len(success) == 3
    assert len(failed) == 0

    mod_lines = modified.splitlines()

    # Verify Alpha
    assert "Replacement Alpha" in mod_lines
    assert "Unique Line 4" in mod_lines
    assert "Unique Line 9" in mod_lines

    # Verify Beta
    assert "Replacement Beta" in mod_lines
    assert "More Beta" in mod_lines
    # Line 15 (Unique Line 14) should be there, line 23 (Unique Line 21) should be there
    assert "Unique Line 14" in mod_lines
    assert "Unique Line 21" in mod_lines

    # Verify Gamma
    assert "Replacement Gamma" in mod_lines
    assert "Unique Line 31" in mod_lines
    assert "Unique Line 41" in mod_lines

    # Verify a duplicate block that wasn't touched (the one at line 10-11)
    assert "Duplicate Block" in mod_lines
    assert "Common Content" in mod_lines
    """Test 4: Operations at file boundaries."""
    from cecli.helpers.hashline import apply_hashline_operations

    original = "First\nMiddle\nLast"
    hashed = hashline(original)
    h_lines = hashed.splitlines()
    h_first = h_lines[0].split("|")[1]
    h_last = h_lines[2].split("|")[1]

    ops = [
        {
            "operation": "insert",
            "start_line_hash": f"|1{parse_hashline(f'|{h_first}|')[0]}|",
            "text": "Before First",
        },
        {
            "operation": "insert",
            "start_line_hash": f"|3{parse_hashline(f'|{h_last}|')[0]}|",
            "text": "After Last",
        },
    ]

    modified, success, failed = apply_hashline_operations(original, ops)
    mod_lines = modified.splitlines()
    assert mod_lines[0] == "First"
    assert mod_lines[1] == "Before First"
    assert mod_lines[2] == "Middle"
    assert mod_lines[3] == "Last"
    assert mod_lines[4] == "After Last"


def test_apply_hashline_operations_mixed_success():
    """Test 5: Mix of successful and failing operations."""
    from cecli.helpers.hashline import apply_hashline_operations

    original = "Line 1\nLine 2\nLine 3"
    print(f"\nTest: Mixed success\nOriginal: {original.splitlines()}")
    hashed = hashline(original)
    h_lines = hashed.splitlines()
    h1 = h_lines[0].split("|")[1]

    ops = [
        {
            "operation": "replace",
            "start_line_hash": f"|1{parse_hashline(f'|{h1}|')[0]}|",
            "end_line_hash": f"|1{parse_hashline(f'|{h1}|')[0]}|",
            "text": "New 1",
        },
        {
            "operation": "replace",
            "start_line_hash": "|99zz|",
            "end_line_hash": "|99zz|",
            "text": "Fail",
        },
    ]

    print(f"Operations: {ops}")

    modified, success, failed = apply_hashline_operations(original, ops)

    print(f"Success indices: {success}")
    print(f"Failed: {len(failed)}")
    for f in failed:
        print(f"  Failed op {f['index']}: {f['error'][:50]}...")
    print(f"Modified: {modified.splitlines()}")

    assert len(success) == 1
    assert len(failed) == 1
    assert "New 1" in modified
    assert "Fail" not in modified
    assert failed[0]["index"] == 1
    assert "not found" in failed[0]["error"]


def test_apply_hashline_operations_bidirectional_stitching():
    """Test bidirectional non-contiguous stitching.

    Tests that the algorithm correctly stitches at both start and end
    when replacement text contains lines that exist before and after
    the replacement range.

    Based on user's test case:
    Original Contents:
    A
    B
    A
    B
    B
    C
    D
    E
    E
    F
    G
    H
    I
    H
    I
    J
    K
    L

    Replacement lines 7-10 (D through F) with:
    B
    C
    M
    N
    H
    I

    Expected Result:
    A
    B
    A
    B
    B
    C
    M
    N
    H
    I
    H
    I
    J
    K
    L
    """
    from cecli.helpers.hashline import apply_hashline_operations, hashline

    original_content = """A
B
A
B
B
C
D
E
E
F
G
H
I
H
I
J
K
L"""

    # Generate hashlines for the content
    hashed_content = hashline(original_content)
    hashed_lines = hashed_content.splitlines(keepends=True)

    # Find hash fragments for lines 7-10 (D through F)
    # Lines are 0-indexed, so:
    # Line 7 (D) is index 6
    # Line 10 (F) is index 9
    line_7_hash = hashed_lines[6].split("|", 2)[1]
    line_10_hash = hashed_lines[9].split("|", 2)[1]

    # Replacement text
    replacement_text = """B
C
M
N
H
I"""

    operations = [
        {
            "start_line_hash": (
                f"|7{parse_hashline(f'|{line_7_hash}|')[0]}|"
            ),  # Line 7 (1-indexed) - D
            "end_line_hash": (
                f"|10{parse_hashline(f'|{line_10_hash}|')[0]}|"
            ),  # Line 10 (1-indexed) - F
            "operation": "replace",
            "text": replacement_text,
        }
    ]

    # Expected result from user
    expected_result = """A
B
A
B
B
C
M
N
H
I
H
I
J
K
L"""

    # Apply the operation
    result, resolved_ops, errors = apply_hashline_operations(original_content, operations)

    # Check for errors
    assert not errors, f"Errors occurred: {errors}"

    # Check if result matches expected
    assert (
        result == expected_result
    ), f"Result doesn't match expected.\nExpected:\n{expected_result}\nGot:\n{result}"
