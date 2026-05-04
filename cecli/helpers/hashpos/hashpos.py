import re

import xxhash


class HashPos:
    B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789~_"
    # The actual coprime period (64 * 63)
    PERIOD = 4032
    # Regex pattern for HashPos format: {4-char-hash}::
    HASH_PREFIX_RE = re.compile(r"^([0-9a-zA-Z\~_@]{4})::")
    # Regex for normalization: 4 hash chars optionally followed by '::'
    NORMALIZE_RE = re.compile(r"^([0-9a-zA-Z\~_@]{4})(?:)?::")
    # Regex for a raw 4-character fragment
    FRAGMENT_RE = re.compile(r"^[0-9a-zA-Z\~_@]{4}$")

    def __init__(self, source_text: str = ""):
        self.lines = source_text.splitlines()
        self.total = len(self.lines)

    def _get_content_bits(self, text: str) -> int:
        return xxhash.xxh3_64_intdigest(text.encode("utf-8")) & 0xFFF

    def _get_anchor_bits(self, line_idx: int) -> int:
        a1 = (line_idx * 53 + 13) % 64
        a2 = (line_idx * 59 + 31) % 63
        return (a1 << 6) | a2

    def _spread_bits(self, x: int) -> int:
        """
        Spreads 12 bits of x into 24 bits by inserting a 0 between each bit.
        Input:  000000000000abcdefghijkl (12 bits)
        Output: 0a0b0c0d0e0f0g0h0i0j0k0l (24 bits)
        """
        x &= 0xFFF  # Ensure we only have 12 bits
        # Shift bits by 8, mask keeps the blocks separated
        # x starts: 000000000000 abcdefgh ijkl
        x = (x | (x << 8)) & 0x00FF00FF  # 0000abcd efgh0000 00000000 ijkl...
        # Shift by 4, then 2, then 1 to create 1-bit gaps
        x = (x | (x << 4)) & 0x0F0F0F0F
        x = (x | (x << 2)) & 0x33333333
        x = (x | (x << 1)) & 0x55555555  # Result: 0a0b0c0d0e0f0g0h0i0j0k0l
        return x

    def _compact_bits(self, x: int) -> int:
        """
        The inverse of spread: pulls every other bit back together.
        Input:  0a0b0c0d0e0f0g0h0i0j0k0l (24 bits)
        Output: 000000000000abcdefghijkl (12 bits)
        """
        x &= 0x55555555  # Mask to ensure we only look at the "active" bits
        x = (x | (x >> 1)) & 0x33333333
        x = (x | (x >> 2)) & 0x0F0F0F0F
        x = (x | (x >> 4)) & 0x00FF00FF
        x = (x | (x >> 8)) & 0x0000FFFF  # Result: abcdefghijkl
        return x

    def _interleave(self, content: int, anchor: int) -> int:
        """
        Weaves content and anchor bits together.
        Content bits occupy the 'odd' positions, Anchor bits occupy the 'even'.
        """
        # Spread content bits and shift by 1 to put them in positions 1, 3, 5...
        # Spread anchor bits and leave them in positions 0, 2, 4...
        return (self._spread_bits(content) << 1) | self._spread_bits(anchor)

    def _deinterleave(self, mixed: int) -> tuple[int, int]:
        """
        Extracts content and anchor bits from a 24-bit interleaved integer.
        """
        # To get content: shift right by 1, then compact
        content = self._compact_bits(mixed >> 1)
        # To get anchor: just compact (the mask inside _compact_bits handles the rest)
        anchor = self._compact_bits(mixed)
        return content, anchor

    def generate_private_id(self, text: str) -> str:
        bits = self._get_content_bits(text)
        return f"{bits:03x}"

    def generate_public_id(self, text: str, line_idx: int) -> str:
        content_bits = self._get_content_bits(text)
        anchor_bits = self._get_anchor_bits(line_idx)
        packed = self._interleave(content_bits, anchor_bits)

        res = ""
        for _ in range(4):
            res += self.B64[packed % 64]
            packed //= 64
        return res

    def unpack_public_id(self, public_id: str) -> tuple[int, int]:
        packed = 0
        for i, char in enumerate(public_id):
            packed |= self.B64.index(char) << (6 * i)

        return self._deinterleave(packed)

    def format_content(self, use_private_ids: bool = False, start_line: int = 1) -> str:
        formatted_lines = []
        for i, line in enumerate(self.lines):
            prefix = (
                self.generate_private_id(line)
                if use_private_ids
                else self.generate_public_id(line, i + start_line)
            )
            formatted_lines.append(f"{prefix}::{line}")
        return "\n".join(formatted_lines)

    def resolve_to_lines(self, public_id: str, start_line: int = 1) -> list[int]:
        target_content, target_anchor = self.unpack_public_id(public_id)
        content_matches = []
        perfect_matches = []

        for i, line in enumerate(self.lines):
            if self._get_content_bits(line) == target_content:
                current_anchor = self._get_anchor_bits(i + start_line)
                if current_anchor == target_anchor:
                    perfect_matches.append(i)
                else:
                    dist = abs(current_anchor - target_anchor)
                    # Use the actual coprime period for the circular logic
                    dist = min(dist, self.PERIOD - dist)

                    if dist <= 5:
                        content_matches.append((dist, i))

        if perfect_matches:
            return perfect_matches

        content_matches.sort(key=lambda x: x[0])
        return [match[1] for match in content_matches]

    def resolve_range(self, start_id: str, end_id: str) -> tuple[int, int]:
        """
        Resolves a block range from two Public IDs.

        Logic:
        1. Resolve all candidates for both IDs.
        2. Find the pair of (start, end) that are logically ordered and
           have the lowest combined distance score.
        3. Returns (start_index, end_index)
        """
        starts = self.resolve_to_lines(start_id)
        ends = self.resolve_to_lines(end_id)

        if not starts or not ends:
            raise ValueError(f"Could not resolve IDs: {start_id}..{end_id}")

        # If both have 'perfect' matches that are logically ordered, use them immediately
        # Note: resolve_to_lines returns perfect matches first.
        for s in starts:
            for e in ends:
                if s <= e:
                    # Return the first logical pair found
                    # (This prioritizes perfect matches or closest heuristics)
                    return s, e

        raise ValueError(
            f"Found matches for {start_id} and {end_id}, but no logically ordered range or unique"
            " matches."
        )

    @staticmethod
    def strip_prefix(text: str) -> str:
        r"""
        Remove HashPos prefixes from the start of every line.

        Removes prefixes that match the pattern: "{4-char-hash}"
        where the hash is exactly 4 characters from the set [0-9a-zA-Z\~_@] followed by '::'.

        Args:
            text: Input text with HashPos prefixes

        Returns:
            String with HashPos prefixes removed from each line
        """
        lines = text.splitlines(keepends=True)
        result_lines = []
        for line in lines:
            # Remove the HashPos prefix if present
            stripped_line = HashPos.HASH_PREFIX_RE.sub("", line, count=1)
            result_lines.append(stripped_line)

        return "".join(result_lines)

    @staticmethod
    def extract_prefix(line: str) -> str:
        """
        Extract the hash prefix from a line if it has a HashPos prefix.

        Args:
            line: A line of text that may contain a HashPos prefix

        Returns:
            The hash prefix (4 characters) if found, otherwise empty string
        """
        match = HashPos.HASH_PREFIX_RE.match(line)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def normalize(hashpos_str: str) -> str:
        """
        Normalize a HashPos string to the 4-character hash fragment.

        Accepts HashPos strings in "{hash_prefix}::" format or a raw "{hash_prefix}" fragment.
        Also extracts HashPos from strings that contain content after the HashPos,
        e.g., "H7M5::Line 1"

        Args:
            hashpos_str: HashPos string in various formats

        Returns:
            str: The 4-character hash fragment

        Raises:
            ValueError: If format is invalid
        """
        if hashpos_str is None:
            raise ValueError("HashPos string cannot be None")

        # Check if it's already a raw fragment
        if HashPos.FRAGMENT_RE.match(hashpos_str):
            return hashpos_str

        match = HashPos.NORMALIZE_RE.match(hashpos_str)
        if match:
            return match.group(1)

        # If no pattern matches, raise error
        raise ValueError(
            f"Invalid HashPos format '{hashpos_str}'. "
            r"Expected \"{hash_prefix}\" "
            r"where hash_prefix is exactly 4 characters from the set [0-9a-zA-Z\~_@]."
        )
