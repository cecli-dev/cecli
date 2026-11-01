"""Slim scrollbar renderer: partial-block thumbs on an invisible track."""

from math import ceil

from rich.color import Color
from rich.segment import Segment, Segments
from rich.style import Style as RichStyle
from textual.scrollbar import ScrollBarRender


class ThinScrollBarRenderer(ScrollBarRender):
    """Render scrollbars as a partial-block thumb on an invisible track."""

    horizontal_glyph = "▃"
    vertical_glyph = "▋"

    @classmethod
    def render_bar(
        cls,
        size: int,
        virtual_size: float,
        window_size: float,
        position: float,
        thickness: int,
        vertical: bool,
        back_color: Color,
        bar_color: Color,
    ) -> Segments:
        if size <= 0:
            return Segments([])

        if vertical:
            thumb_cell = cls.vertical_glyph * max(1, thickness)
        else:
            thumb_cell = cls.horizontal_glyph

        track_cell = " " * (max(1, thickness) if vertical else 1)

        track_style = RichStyle(color=back_color, meta={"@mouse.down": "scroll_up"})
        thumb_style = RichStyle(color=bar_color, meta={"@mouse.down": "grab"})
        segments = [Segment(track_cell, track_style) for _ in range(size)]

        if window_size and virtual_size and window_size < virtual_size:
            thumb_size = max(1, min(size, ceil(size * window_size / virtual_size)))
            position_ratio = position / (virtual_size - window_size)
            start = int((size - thumb_size) * position_ratio)
            start = max(0, min(start, size - thumb_size))
            end = start + thumb_size

            segments[start:end] = [Segment(thumb_cell, thumb_style)] * thumb_size
            down_style = RichStyle(color=back_color, meta={"@mouse.down": "scroll_down"})

            for index in range(end, size):
                segments[index] = Segment(track_cell, down_style)

        return Segments(segments, new_lines=vertical)
