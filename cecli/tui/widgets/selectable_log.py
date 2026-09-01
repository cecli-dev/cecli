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

from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.strip import Strip
from textual.widgets import RichLog


class SelectableRichLog(RichLog):
    """A RichLog widget with built-in text selection.

    Tracks selection as a range of line indices into ``self.lines`` and
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
    """

    SELECTION_STYLE = Style(bgcolor="#ffffff", color="#00aa00")
    """Style applied to selected lines."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Selection state: line indices into self.lines (virtual coordinate space)
        self._select_start: int | None = None
        """Start line of the selection (inclusive)."""
        self._select_end: int | None = None
        """End line of the selection (inclusive)."""
        self._mouse_is_down: bool = False
        """Whether the mouse button is currently pressed."""

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
        if not self.lines:
            return
        self._select_start = 0
        self._select_end = len(self.lines) - 1
        self.refresh()

    def get_selected_text(self, copy=False) -> str | None:
        """Extract selected text as a plain string.

        Returns:
            The selected text, or ``None`` if there is no selection.
        """
        if not self.has_selection:
            return None
        lo, hi = sorted([self._select_start, self._select_end])
        lo = max(0, lo)
        hi = min(hi, len(self.lines) - 1)
        if lo > hi:
            return None
        lines = []
        for i in range(lo, hi + 1):
            text = "".join(seg.text for seg in self.lines[i] if seg.text)
            lines.append(text.rstrip())

        text = "\n".join(lines)
        if not copy:
            return text
        else:
            self.app.copy_to_clipboard(text)
            self.clear_selection()

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
        clamped line index in ``self.lines``.

        Args:
            y_screen: The y-coordinate from a mouse event, relative to the
                      widget's content area.

        Returns:
            The corresponding line index, clamped to ``[0, len(lines)-1]``.
        """
        scroll_y = self.scroll_offset.y
        idx = scroll_y + y_screen
        idx = max(0, idx)
        if self.lines:
            idx = min(idx, len(self.lines) - 1)
        return idx
