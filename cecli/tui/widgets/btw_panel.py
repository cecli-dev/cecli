"""Centered read-only panel for ``/btw`` aside exchanges."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import RichLog, Static

from cecli.helpers.asides import Asides

from .overlay import OVERLAY_BINDINGS, OverlayPanelActions, refresh_overlay_subtitles


class BtwPanel(OverlayPanelActions, Vertical):
    """Overlay showing side questions and their raw responses.

    Every ``/btw`` exchange is appended to ``Asides`` and rendered here. The
    left and right arrow keys move through the stored prompts and responses.
    """

    can_focus = True

    MAX_OUTPUT_LINES = 500

    BINDINGS = [
        *OVERLAY_BINDINGS,
        Binding("left", "previous_aside", "Previous", show=False, priority=True),
        Binding("right", "next_aside", "Next", show=False, priority=True),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._index = -1
        self._rendered_signature = None

    def compose(self) -> ComposeResult:
        yield Static("No asides yet.", id="btw-empty")
        yield RichLog(
            id="btw-output",
            wrap=True,
            markup=False,
            auto_scroll=False,
            max_lines=self.MAX_OUTPUT_LINES,
        )

    def on_mount(self):
        """Render the latest exchange once the panel is mounted."""
        self.border_title = "asides"
        self.call_after_refresh(self.refresh_data)

    def refresh_data(self):
        """Show the latest exchange, or the empty message when there is none."""
        if not self.is_mounted or not self._is_shown:
            return

        asides = Asides.get_instance().items()
        refresh_overlay_subtitles(self.app)

        if not asides:
            self._index = -1
            self.border_title = "asides"
            self._show_empty(True)
            return

        self._show_empty(False)

        if self._index < 0 or self._index >= len(asides):
            self._index = len(asides) - 1

        self._render_aside(asides[self._index], len(asides))

    def action_previous_aside(self):
        """Move to the previous stored exchange."""
        self._move(-1)

    def action_next_aside(self):
        """Move to the next stored exchange."""
        self._move(1)

    def open_panel(self):
        """Select the newest exchange and render it."""
        self._index = -1
        self.refresh_data()

    def focus_panel(self):
        """Focus the panel so the arrow keys reach its navigation actions."""
        self.focus()

    @property
    def _is_shown(self) -> bool:
        """Return True when the panel and its overlay are both displayed."""
        if not self.display:
            return False

        return self.parent is None or self.parent.display

    def _move(self, offset: int) -> None:
        """Move the selection by *offset* and re-render it."""
        asides = Asides.get_instance().items()

        if not asides:
            return

        index = max(0, min(self._index + offset, len(asides) - 1))

        if index == self._index:
            return

        self._index = index
        self._show_empty(False)
        self._render_aside(asides[index], len(asides))

    def _show_empty(self, empty: bool) -> None:
        """Swap between the empty message and the aside view."""
        self.query_one("#btw-empty", Static).display = empty
        self.query_one("#btw-output", RichLog).display = not empty

    def _render_aside(self, aside, total: int) -> None:
        """Render the selected prompt and raw response."""
        signature = (self._index, total, aside.prompt, aside.response)

        if signature == self._rendered_signature:
            return

        self._rendered_signature = signature
        self.border_title = f"asides {self._index + 1} of {total}"
        body = f"Prompt: {aside.prompt}\n-----\nAnswer: {aside.response}"
        log = self.query_one("#btw-output", RichLog)
        log.clear()
        log.write(body, scroll_end=True)
