"""Half-height horizontal scrollbar renderer for the TUI."""

from math import ceil

from rich.color import Color
from rich.segment import Segment, Segments
from rich.style import Style as RichStyle
from textual.scrollbar import ScrollBarRender


class ThinScrollBarRenderer(ScrollBarRender):
    """Render the horizontal scrollbar with half-block track and thumb glyphs."""

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
        if vertical:
            return super().render_bar(
                size=size,
                virtual_size=virtual_size,
                window_size=window_size,
                position=position,
                thickness=thickness,
                vertical=vertical,
                back_color=back_color,
                bar_color=bar_color,
            )

        if size <= 0:
            return Segments([])

        track_style = RichStyle(color=back_color, meta={"@mouse.down": "scroll_up"})
        thumb_style = RichStyle(color=bar_color, meta={"@mouse.down": "grab"})
        segments = [Segment("▄", track_style) for _ in range(size)]

        if window_size and virtual_size and window_size < virtual_size:
            thumb_size = max(1, min(size, ceil(size * window_size / virtual_size)))
            position_ratio = position / (virtual_size - window_size)
            start = int((size - thumb_size) * position_ratio)
            start = max(0, min(start, size - thumb_size))
            end = start + thumb_size

            segments[start:end] = [Segment("▄", thumb_style)] * thumb_size
            for index in range(end, size):
                segments[index] = Segment(
                    "▄", RichStyle(color=back_color, meta={"@mouse.down": "scroll_down"})
                )

        return Segments(segments)
