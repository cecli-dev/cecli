"""Compact virtual line storage backing SelectableRichLog."""

from __future__ import annotations

from array import array
from bisect import bisect_right

from rich.console import RenderableType
from rich.style import Style
from textual.strip import Strip


class LineBlock:
    """Compact, virtualized representation of one written renderable.

    Stores the rendered lines as a single string plus character offsets and
    style spans instead of retaining one Strips/Segments graph per line.
    """

    __slots__ = (
        "renderable",
        "explicit_width",
        "expand",
        "shrink",
        "text",
        "starts",
        "span_starts",
        "span_ends",
        "span_styles",
        "width",
        "line_count",
    )

    def __init__(
        self,
        renderable: RenderableType,
        explicit_width: int | None,
        expand: bool,
        shrink: bool,
        text: str,
        starts: array,
        span_starts: array,
        span_ends: array,
        span_styles: list[Style],
        width: int,
        line_count: int,
    ) -> None:
        self.renderable = renderable
        self.explicit_width = explicit_width
        self.expand = expand
        self.shrink = shrink
        self.text = text
        self.starts = starts
        self.span_starts = span_starts
        self.span_ends = span_ends
        self.span_styles = span_styles
        self.width = width
        self.line_count = line_count

    def line_range(self, line_index: int) -> tuple[int, int]:
        """Return the character range of a visual line within ``text``."""
        start = self.starts[line_index]
        if line_index + 1 < len(self.starts):
            end = self.starts[line_index + 1] - 1
        else:
            end = len(self.text)
        return start, end

    def line_text(self, line_index: int) -> str:
        """Return the plain text of a visual line."""
        start, end = self.line_range(line_index)
        return self.text[start:end]

    @classmethod
    def from_strips(
        cls,
        renderable: RenderableType,
        explicit_width: int | None,
        expand: bool,
        shrink: bool,
        strips: list[Strip],
        width: int,
    ) -> "LineBlock":
        """Build a compact block from rendered strips, discarding the strips."""
        text_parts: list[str] = []
        starts: array = array("I")
        span_starts: array = array("I")
        span_ends: array = array("I")
        span_styles: list[Style] = []
        text_pos = 0

        for strip in strips:
            segments = list(strip)
            # Drop unstyled padding added by Strip.adjust_cell_length.
            while segments and segments[-1].text.isspace() and segments[-1].style is None:
                segments.pop()

            starts.append(text_pos)
            line_pos = 0
            line_parts: list[str] = []
            for segment in segments:
                if segment.control:
                    continue
                segment_text = segment.text
                if not segment_text:
                    continue
                line_parts.append(segment_text)
                if segment.style is not None:
                    span_starts.append(text_pos + line_pos)
                    span_ends.append(text_pos + line_pos + len(segment_text))
                    span_styles.append(segment.style)
                line_pos += len(segment_text)

            line = "".join(line_parts)
            text_parts.append(line)
            text_pos += len(line) + 1

        if not text_parts:
            text_parts.append("")
            starts.append(0)

        return cls(
            renderable,
            explicit_width,
            expand,
            shrink,
            "\n".join(text_parts),
            starts,
            span_starts,
            span_ends,
            span_styles,
            width,
            len(text_parts),
        )


class VirtualLineStore:
    """Ordered blocks of rendered lines addressed by virtual line index."""

    def __init__(self) -> None:
        self.blocks: list[LineBlock] = []
        self._prefix: array = array("Q", [0])
        self._line_count = 0

    @property
    def line_count(self) -> int:
        """Total number of virtual lines across all blocks."""
        return self._line_count

    def clear(self) -> None:
        """Remove all blocks."""
        self.blocks.clear()
        self._prefix = array("Q", [0])
        self._line_count = 0

    def append(self, block: LineBlock) -> None:
        """Append a block to the end of the store."""
        self.blocks.append(block)
        self._prefix.append(self._prefix[-1] + block.line_count)
        self._line_count += block.line_count

    def block_at(self, line_index: int) -> tuple[LineBlock, int] | None:
        """Return the block and in-block offset for a virtual line index."""
        if line_index < 0 or line_index >= self._line_count:
            return None
        block_index = bisect_right(self._prefix, line_index) - 1
        return self.blocks[block_index], line_index - self._prefix[block_index]

    def line_text(self, line_index: int) -> str:
        """Return the plain text of a virtual line."""
        found = self.block_at(line_index)
        if found is None:
            return ""
        block, offset = found
        return block.line_text(offset)

    def block_anchor(self, line_index: int | None) -> tuple[int, int] | None:
        """Map a virtual line index to a block index and in-block offset."""
        if line_index is None or not self.blocks:
            return None
        if line_index < 0 or line_index >= self._line_count:
            return None
        block_index = bisect_right(self._prefix, line_index) - 1
        return block_index, line_index - self._prefix[block_index]

    def line_from_anchor(self, anchor: tuple[int, int] | None) -> int | None:
        """Map a block index and in-block offset back to a virtual line index."""
        if anchor is None or not self.blocks:
            return None
        block_index, offset = anchor
        if block_index >= len(self.blocks):
            return None
        block = self.blocks[block_index]
        return self._prefix[block_index] + min(offset, block.line_count - 1)
