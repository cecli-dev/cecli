import xxhash


def hashline(text: str, start_line: int = 1) -> str:
    """
    Add a hash scheme to each line of text.

    For each line in the input text, returns a string where each line is prefixed with:
    "{line number}:{2-digit base36 of xxhash mod 36^2}|{line contents}"

    Args:
        text: Input text (most likely representing a file's text)
        start_line: Starting line number (default: 1)

    Returns:
        String with hash scheme added to each line
    """
    lines = text.splitlines(keepends=True)
    result_lines = []

    for i, line in enumerate(lines, start=start_line):
        # Calculate xxhash for the line content
        hash_value = xxhash.xxh3_64_intdigest(line.encode("utf-8"))

        # Use mod 36^2 (1296) for faster computation
        mod_value = hash_value % 1296  # 36^2 = 1296

        # Convert to 2-digit base36 using helper function
        last_two_str = int_to_2digit_36(mod_value)

        # Format the line
        formatted_line = f"{i}:{last_two_str}|{line}"
        result_lines.append(formatted_line)

    return "".join(result_lines)


def int_to_2digit_36(n: int) -> str:
    """
    Convert integer to 2-digit base36 with zero-padding.

    Args:
        n: Integer in range 0-1295 (36^2 - 1)

    Returns:
        2-character base36 string
    """
    # Ensure n is in valid range
    n = n % 1296  # 36^2

    # Convert to base36
    if n == 0:
        return "00"

    digits = []
    while n > 0:
        n, remainder = divmod(n, 36)
        if remainder < 10:
            digits.append(chr(remainder + ord("0")))
        else:
            digits.append(chr(remainder - 10 + ord("a")))

    # Pad to 2 digits
    while len(digits) < 2:
        digits.append("0")

    # Return in correct order (most significant first)
    return "".join(reversed(digits))


def strip_hashline(text: str) -> str:
    """
    Remove hashline-like sequences from the start of every line.

    Removes prefixes that match the pattern: "{line number}:{2-digit base36}|"
    where line number can be any integer (positive, negative, or zero) and
    the 2-digit base36 is exactly 2 characters from the set [0-9a-z].

    Args:
        text: Input text with hashline prefixes

    Returns:
        String with hashline prefixes removed from each line
    """
    import re

    # Pattern to match: {optional minus sign}{digits}:{2 base36 chars}|
    # The line number can be any integer (positive, negative, or zero)
    # The hash is exactly 2 characters from [0-9a-z]
    pattern = r"^-?\d+:[0-9a-z]{2}\|"

    lines = text.splitlines(keepends=True)
    result_lines = []

    for line in lines:
        # Remove the hashline prefix if present
        stripped_line = re.sub(pattern, "", line, count=1)
        result_lines.append(stripped_line)

    return "".join(result_lines)
