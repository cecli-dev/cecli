"""A SelectableRichLog widget with built-in text selection via render_line override.

Extends Textual's RichLog with line-index-based text selection, avoiding the
coordinate-space issues in Textual's built-in widget-level selection system
(where screen-space selection bounds mismatch virtual-space widget content
regions inside scrollable containers).

Usage:
    log = SelectableRichLog()
    log.write("Some text")
    log.write("More text")
    # User can click-drag to select, shift+click to extend
    text = log.get_selected_text()  # Get selected text
    log.copy_selection()            # Copy to clipboard
    log.clear_selection()           # Clear selection
    log.select_all()                # Select all lines
"""

from __future__ import annotations

from bisect import bisect_right
from typing import TYPE_CHECKING

from rich.console import RenderableType
from rich.measure import measure_renderables
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.geometry import Size
from textual.strip import Strip
from textual.widgets import RichLog

from .helpers.log_virtualizer import LineBlock, VirtualLineStore

if TYPE_CHECKING:
    from typing_extensions import Self


class SelectableRichLog(RichLog):
    """A RichLog widget with built-in text selection.

    Tracks selection as a range of virtual line indices and
    applies a highlight style at render time via ``render_line`` override.
    This completely bypasses Textual's widget-level selection system,
    avoiding the screen-space / virtual-space coordinate mismatch that
    causes scrolled-away children to be omitted from selections.

    Features:
    - Click-and-drag to select a range of lines
    - Shift+click to extend an existing selection
    - Select all lines with ``select_all()``
    - Copy selected text to clipboard with ``copy_selection()``
    - Works correctly regardless of scroll position
    - Does NOT interfere with RichLog's built-in auto-scroll

    Notes:
    ``RichLog.lines`` is intentionally empty in virtual mode. Use
    :attr:`line_count` and the selection API rather than reading ``lines``.
    Passing ``max_lines`` disables virtualization and reflow. Reflow
    re-renders the stored renderables at the new width, so one-shot or
    stateful renderables may not reproduce their original output. Changing
    ``max_lines`` after construction is unsupported, as the virtual store
    and ``lines`` would diverge.
    """

    SELECTION_STYLE = Style(bgcolor="#ffffff", color="#00aa00")
    """Style applied to selected lines."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Selection state: virtual line indices into self._store. RichLog's
        # ``lines`` list stays empty in virtual mode.
        self._select_start: int | None = None
        """Start line of the selection (inclusive)."""
        self._select_end: int | None = None
        """End line of the selection (inclusive)."""
        self._mouse_is_down: bool = False
        """Whether the mouse button is currently pressed."""

        # Virtual line storage. RichLog.lines is intentionally left empty in
        # virtual mode; only the compact block text/style spans are retained.
        self._store = VirtualLineStore()
        self._layout_width = 0
        self._last_viewport_height = 0

    def write(
        self,
        content: RenderableType | object,
        width: int | None = None,
        expand: bool = False,
        shrink: bool = True,
        scroll_end: bool | None = None,
        animate: bool = False,
    ) -> Self:
        """Write content without retaining one Strip per visual line.

        ``max_lines`` and writes before the size is known fall back to
        RichLog's original path, which defers rendering until the widget has
        been laid out.
        """
        if self.max_lines is not None or not self._size_known:
            return super().write(content, width, expand, shrink, scroll_end, animate)

        if isinstance(content, Text):
            content = content.copy()
        renderable = self._make_renderable(content)
        _render_width, strips, widest = self._render_strips(renderable, width, expand, shrink)
        block = LineBlock.from_strips(renderable, width, expand, shrink, strips, widest)

        self._store.append(block)
        self._widest_line_width = max(self._widest_line_width, widest)
        self._layout_width = self.scrollable_content_region.width
        self.virtual_size = Size(self._widest_line_width, self._store.line_count)
        self.refresh()

        auto_scroll = self.auto_scroll if scroll_end is None else scroll_end
        if auto_scroll:
            self.scroll_end(animate=animate, immediate=False, x_axis=False)

        return self

    def on_resize(self, event: events.Resize) -> None:
        """Reflow compact blocks when the available width changes."""
        # Capture before super() so the new size does not pollute the old
        # viewport metrics. ``prev_height`` is the content height before this
        # resize; ``content_size`` itself is not reduced by the horizontal
        # scrollbar, which may be transient until reflow.
        prev_height = self._last_viewport_height or self.content_size.height
        had_content = self._store.line_count > 0
        was_at_end = had_content and (
            self.is_vertical_scroll_end
            or self.scroll_offset.y + prev_height >= self._store.line_count
        )
        super().on_resize(event)
        viewport_height = self.content_size.height or prev_height

        if self.max_lines is not None or not self._size_known or not self._store.blocks:
            self._last_viewport_height = viewport_height
            return

        width = self.scrollable_content_region.width
        if width <= 0:
            self._last_viewport_height = viewport_height
            return

        if width == self._layout_width:
            if was_at_end:
                self.scroll_end(animate=False, immediate=True, x_axis=False)
            self._last_viewport_height = viewport_height
            return

        top_anchor = None if was_at_end else self._store.block_anchor(self.scroll_offset.y)
        self._reflow(width)

        if was_at_end:
            self.scroll_end(animate=False, immediate=True, x_axis=False)
        elif top_anchor is not None:
            top_line = self._store.line_from_anchor(top_anchor)
            if top_line is not None:
                self.scroll_to(y=top_line, animate=False, immediate=True)

        self._last_viewport_height = viewport_height

    def clear(self) -> Self:
        """Clear all virtual content and selection state."""
        self._store.clear()
        self._layout_width = 0
        self.lines.clear()
        self._line_cache.clear()
        self._start_line = 0
        self._widest_line_width = 0
        self._deferred_renders.clear()
        self.virtual_size = Size(0, 0)
        self.clear_selection()
        if self._mouse_is_down:
            self.release_mouse()
            self._mouse_is_down = False
        self.refresh()
        return self

    @property
    def line_count(self) -> int:
        """Number of virtual (rendered) lines in the log."""
        if self.max_lines is not None:
            return len(self.lines)
        return self._store.line_count

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def has_selection(self) -> bool:
        """Whether there is an active selection."""
        return self._select_start is not None and self._select_end is not None

    def clear_selection(self) -> None:
        """Clear the current selection."""
        if self.has_selection:
            self._select_start = None
            self._select_end = None
            self.refresh()

    def select_all(self) -> None:
        """Select all lines in the log."""
        line_count = self.line_count
        if not line_count:
            return
        self._select_start = 0
        self._select_end = line_count - 1
        self.refresh()

    def get_selected_text(self, copy=False) -> str | None:
        """Extract selected text as a plain string.

        Args:
            copy: Copy the text to the clipboard and clear the selection.

        Returns:
            The selected text, or ``None`` if there is no selection.
        """
        if not self.has_selection:
            return None
        lo, hi = sorted([self._select_start, self._select_end])
        lo = max(0, lo)
        hi = min(hi, self.line_count - 1)
        if lo > hi:
            return None
        lines = []
        for i in range(lo, hi + 1):
            lines.append(self._line_text(i).rstrip())

        text = "\n".join(lines)
        if not copy:
            return text
        else:
            self.app.copy_to_clipboard(text)
            self.clear_selection()
            return text

    def copy_selection(self) -> bool:
        """Copy selected text to the system clipboard.

        Returns:
            ``True`` if text was copied, ``False`` if no selection.
        """
        text = self.get_selected_text()
        if not text:
            return False
        self.app.copy_to_clipboard(text)
        return True

    # ------------------------------------------------------------------
    # Selection rendering — override render_line to apply highlight
    # ------------------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        """Render a single line, applying selection highlight if selected.

        We override ``render_line`` (not ``_render_line``) so that the
        selection highlight is applied **after** ``self.rich_style``,
        ensuring it always renders as the topmost visual layer and does
        not interfere with RichLog's internal ``_line_cache``.
        """
        scroll_x, scroll_y = self.scroll_offset
        line = self._render_line(scroll_y + y, scroll_x, self.scrollable_content_region.width)
        strip = line.apply_style(self.rich_style)
        if self._is_selected(scroll_y + y):
            strip = self._highlight_strip(strip)
        return strip

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        """Render one virtual line from the compact block store."""
        if self.max_lines is not None:
            return super()._render_line(y, scroll_x, width)

        key = (y + self._start_line, scroll_x, width, self._widest_line_width)
        if key in self._line_cache:
            return self._line_cache[key]

        found = self._store.block_at(y)
        if found is None:
            return Strip.blank(width, self.rich_style)

        block, line_index = found
        line_start, line_end = block.line_range(line_index)

        line_text = Text(block.text[line_start:line_end])
        span_index = max(bisect_right(block.span_starts, line_start) - 1, 0)
        for index in range(span_index, len(block.span_starts)):
            span_start = block.span_starts[index]
            span_end = block.span_ends[index]
            if span_end <= line_start:
                continue
            if span_start >= line_end:
                break
            start = max(span_start, line_start) - line_start
            end = min(span_end, line_end) - line_start
            if start < end:
                line_text.stylize(block.span_styles[index], start, end)

        console = self.app.console
        render_options = console.options.update_width(width).update(overflow="ignore", no_wrap=True)
        segments = console.render(line_text, render_options)
        lines = list(Segment.split_lines(segments))
        if not lines:
            strip = Strip.blank(width, self.rich_style)
        else:
            strip = Strip.from_lines(lines)[0]

        strip = strip.crop_extend(scroll_x, scroll_x + width, self.rich_style)
        self._line_cache[key] = strip
        return strip

    def _is_selected(self, line_idx: int) -> bool:
        """Check whether a virtual-space line index falls within the selection."""
        if not self.has_selection:
            return False
        lo, hi = sorted([self._select_start, self._select_end])
        return lo <= line_idx <= hi

    @staticmethod
    def _highlight_strip(strip: Strip) -> Strip:
        """Apply the selection highlight style to every segment in a strip.

        Each segment's existing style is preserved and combined with the
        selection style (foreground from selection replaces segment's, but
        existing foreground is kept if selection style doesn't specify one).
        """
        segments = []
        for text, style, *rest in strip:
            if style is not None:
                combined = style + SelectableRichLog.SELECTION_STYLE
            else:
                combined = SelectableRichLog.SELECTION_STYLE
            segments.append(Segment(text, combined, *rest) if rest else Segment(text, combined))
        return Strip(segments)

    # ------------------------------------------------------------------
    # Mouse handling for drag-to-select
    # ------------------------------------------------------------------

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """Handle mouse down: start a new selection or extend existing one.

        - Left-click (no modifiers): start a new selection at the clicked line.
        - Shift+left-click: extend the current selection to the clicked line.
        """
        if event.button != 1:  # Left button only
            return
        event.stop()  # Prevent Textual's own selection system from activating
        self._mouse_is_down = True
        click_line = self._line_from_y(event.y)

        if event.shift and self.has_selection:
            # Extend existing selection from its current start to the click point
            self._select_end = click_line
        else:
            # Clear previous and start fresh
            self._select_start = click_line
            self._select_end = click_line

        self.refresh()
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """Handle mouse move: extend selection during drag."""
        if not self._mouse_is_down or self._select_start is None:
            return
        new_end = self._line_from_y(event.y)
        if new_end != self._select_end:
            self._select_end = new_end
            self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        """Handle mouse up: finalize the selection."""
        if event.button != 1:
            return
        self._mouse_is_down = False
        self.release_mouse()
        event.stop()

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def _line_from_y(self, y_screen: int) -> int:
        """Convert a mouse y-coordinate (relative to widget content) to a
        clamped virtual line index.

        Args:
            y_screen: The y-coordinate from a mouse event, relative to the
                      widget's content area.

        Returns:
            The corresponding line index, clamped to ``[0, line_count-1]``.
        """
        scroll_y = self.scroll_offset.y
        idx = scroll_y + y_screen
        idx = max(0, idx)
        line_count = self.line_count
        if line_count:
            idx = min(idx, line_count - 1)
        return idx

    # ------------------------------------------------------------------
    # Virtual line helpers
    # ------------------------------------------------------------------

    def _line_text(self, line_index: int) -> str:
        """Return the plain text of an absolute virtual line index."""
        if self.max_lines is not None:
            if line_index < 0 or line_index >= len(self.lines):
                return ""
            return "".join(segment.text for segment in self.lines[line_index])

        return self._store.line_text(line_index)

    def _render_strips(
        self,
        renderable: RenderableType,
        width: int | None,
        expand: bool,
        shrink: bool,
        available_width: int | None = None,
    ) -> tuple[int, list[Strip], int]:
        """Render a renderable once to obtain its strips and line width."""
        console = self.app.console
        render_options = console.options

        if isinstance(renderable, Text) and not self.wrap:
            render_options = render_options.update(overflow="ignore", no_wrap=True)

        if width is not None:
            render_width = width
        else:
            renderable_width = measure_renderables(console, render_options, [renderable]).maximum
            render_width = renderable_width
            scrollable_width = (
                available_width
                if available_width is not None
                else self.scrollable_content_region.width
            )

            if expand and renderable_width < scrollable_width:
                render_width = max(renderable_width, scrollable_width)
            if shrink and renderable_width > scrollable_width:
                render_width = min(renderable_width, scrollable_width)

            render_width = max(render_width, self.min_width)

        render_options = render_options.update_width(render_width)
        segments = console.render(renderable, render_options)
        lines = list(Segment.split_lines(segments))

        if not lines:
            return render_width, [Strip.blank(render_width)], render_width

        strips = Strip.from_lines(lines)
        for strip in strips:
            strip.adjust_cell_length(render_width)

        widest = max(sum(segment.cell_length for segment in line) for line in lines)
        return render_width, strips, widest

    def _reflow(self, width: int) -> None:
        """Re-render all non-explicit-width blocks at the new content width."""
        store = self._store
        had_selection = self.has_selection
        start_anchor = store.block_anchor(self._select_start)
        end_anchor = store.block_anchor(self._select_end)
        old_line_count = store.line_count
        was_select_all = had_selection and (
            (self._select_start == 0 and self._select_end == old_line_count - 1)
            or (self._select_end == 0 and self._select_start == old_line_count - 1)
        )

        new_store = VirtualLineStore()
        widest = 0

        for block in store.blocks:
            if block.explicit_width is not None:
                reflowed = block
            else:
                _render_width, strips, block_widest = self._render_strips(
                    block.renderable, None, block.expand, block.shrink, width
                )
                reflowed = LineBlock.from_strips(
                    block.renderable,
                    None,
                    block.expand,
                    block.shrink,
                    strips,
                    block_widest,
                )

            widest = max(widest, reflowed.width)
            new_store.append(reflowed)

        self._store = new_store
        self._widest_line_width = widest
        self._layout_width = width
        self._line_cache.clear()
        self.virtual_size = Size(self._widest_line_width, new_store.line_count)
        self._restore_selection(had_selection, was_select_all, start_anchor, end_anchor)

    def _restore_selection(
        self,
        had_selection: bool,
        was_select_all: bool,
        start_anchor: tuple[int, int] | None,
        end_anchor: tuple[int, int] | None,
    ) -> None:
        """Remap selection endpoints after a reflow."""
        if not had_selection:
            return

        if was_select_all:
            self._select_start = 0
            self._select_end = self._store.line_count - 1
            return

        start = self._store.line_from_anchor(start_anchor)
        end = self._store.line_from_anchor(end_anchor)
        if start is None or end is None:
            self._select_start = None
            self._select_end = None
        else:
            self._select_start = start
            self._select_end = end
