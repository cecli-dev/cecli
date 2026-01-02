"""Unified status bar widget for notifications and confirmations."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatusBar(Widget, can_focus=True):
    """Unified status bar for notifications, confirmations, and prompts.

    Modes:
        - hidden: Bar is not displayed
        - notification: Shows a transient message (auto-dismisses)
        - confirm: Shows a y/n/a confirmation prompt
    """

    DEFAULT_CSS = """
    StatusBar {
        height: auto;
        background: $surface;
        margin: 0 0;
        padding: 0;
    }

    StatusBar.hidden {
        display: none;
    }

    /* Content container */
    StatusBar .status-content {
        height: 3;
        padding: 1 0 0 2;
        layout: horizontal;
        align: left middle;
        background: $surface;
    }

    /* Notification styles */
    StatusBar .notification-text {
        width: 1fr;
        height: 1;
        color: $secondary;
        content-align: left middle;
        background: $surface;
    }

    StatusBar .notification-text.info {
        color: $secondary;
    }

    StatusBar .notification-text.warning {
        color: $warning;
    }

    StatusBar .notification-text.error {
        color: $error;
    }

    StatusBar .notification-text.success {
        color: $success;
    }

    /* Confirmation styles */
    StatusBar .confirm-question {
        width: 1fr;
        height: 1;
        color: $foreground;
        content-align: left middle;
        background: $surface;
    }

    StatusBar .confirm-hints {
        width: auto;
        height: 1;
        dock: right;
        background: $surface;
    }

    StatusBar .hint {
        width: auto;
        height: 1;
        margin-left: 2;
        color: $secondary;
        background: $surface;
    }

    StatusBar .hint-yes {
        color: $success;
    }

    StatusBar .hint-no {
        color: $warning;
    }

    StatusBar .hint-all {
        color: $secondary;
    }

    StatusBar .hint-skip {
        color: $secondary;
    }

    StatusBar .hint-tweak {
        color: $accent;
    }

    StatusBar .hint-never {
        color: $warning;
    }
    """

    # Current mode
    mode: reactive[str] = reactive("hidden")

    class ConfirmResponse(Message):
        """Confirmation response message."""

        def __init__(self, result: bool | str):
            self.result = result
            super().__init__()

    def __init__(self, **kwargs):
        """Initialize status bar."""
        super().__init__(**kwargs)
        self._text = ""
        self._severity = "info"
        self._show_all = False
        self._allow_tweak = False
        self._allow_never = False
        self._default = "y"
        self._explicit_yes_required = False
        self._timer = None

    def compose(self) -> ComposeResult:
        """Create empty container - content added dynamically."""
        yield Horizontal(classes="status-content")

    def watch_mode(self, mode: str) -> None:
        """React to mode changes."""
        self.remove_class("hidden")
        if mode == "hidden":
            self.add_class("hidden")
            self.can_focus = False
        else:
            self.can_focus = mode == "confirm"

    def _rebuild_content(self) -> None:
        """Rebuild the content based on current mode."""
        container = self.query_one(".status-content")
        container.remove_children()

        if self.mode == "notification":
            container.mount(Static(self._text, classes=f"notification-text {self._severity}"))
        elif self.mode == "confirm":
            container.mount(Static(self._text, classes="confirm-question"))
            hints = Horizontal(classes="confirm-hints")
            container.mount(hints)
            hints.mount(Static("\\[y]es", classes="hint hint-yes"))
            hints.mount(Static("\\[n]o", classes="hint hint-no"))
            if self._show_all:
                hints.mount(Static("\\[a]ll", classes="hint hint-all"))
                hints.mount(Static("\\[s]kip", classes="hint hint-skip"))
            if self._allow_tweak:
                hints.mount(Static("\\[t]weak", classes="hint hint-tweak"))
            if self._allow_never:
                hints.mount(Static("\\[d]on't ask", classes="hint hint-never"))

    def show_notification(
        self, text: str, severity: str = "info", timeout: float | None = 3.0
    ) -> None:
        """Show a transient notification message.

        Args:
            text: Message to display
            severity: One of "info", "warning", "error", "success"
            timeout: Auto-dismiss after this many seconds (None = no auto-dismiss)
        """
        # Cancel any existing timer
        if self._timer:
            self._timer.stop()
            self._timer = None

        self._text = text
        self._severity = severity
        self.mode = "notification"
        self._rebuild_content()

        if timeout:
            self._timer = self.set_timer(timeout, self.hide)

    def show_confirm(
        self,
        question: str,
        show_all: bool = False,
        allow_tweak: bool = False,
        allow_never: bool = False,
        default: str = "y",
        explicit_yes_required: bool = False,
    ) -> None:
        """Show a confirmation prompt.

        Args:
            question: Question to display
            show_all: Whether to show "all" option
            allow_tweak: Whether to show "tweak" option
            allow_never: Whether to show "don't ask again" option
            default: Default response ("y" or "n")
            explicit_yes_required: Whether explicit yes is required
        """
        # Cancel any existing timer
        if self._timer:
            self._timer.stop()
            self._timer = None

        self._text = question
        self._show_all = show_all
        self._allow_tweak = allow_tweak
        self._allow_never = allow_never
        self._default = default
        self._explicit_yes_required = explicit_yes_required
        self.mode = "confirm"
        self._rebuild_content()
        self.focus()

    def hide(self) -> None:
        """Hide the status bar."""
        if self._timer:
            self._timer.stop()
            self._timer = None
        self.mode = "hidden"

    def on_key(self, event) -> None:
        """Handle key shortcuts for confirm mode."""
        if self.mode != "confirm":
            return

        key = event.key.lower()
        if key == "y":
            event.stop()
            event.prevent_default()
            self.post_message(self.ConfirmResponse(True))
            self.hide()
        elif key == "n":
            event.stop()
            event.prevent_default()
            self.post_message(self.ConfirmResponse(False))
            self.hide()
        elif key == "a" and self._show_all:
            event.stop()
            event.prevent_default()
            self.post_message(self.ConfirmResponse("all"))
            self.hide()
        elif key == "s" and self._show_all:
            event.stop()
            event.prevent_default()
            self.post_message(self.ConfirmResponse("skip"))
            self.hide()
        elif key == "t" and self._allow_tweak:
            event.stop()
            event.prevent_default()
            self.post_message(self.ConfirmResponse("tweak"))
            self.hide()
        elif key == "d" and self._allow_never:
            event.stop()
            event.prevent_default()
            self.post_message(self.ConfirmResponse("never"))
            self.hide()
        elif key == "escape":
            event.stop()
            event.prevent_default()
            # Return default based on default parameter
            if self._default.lower().startswith("y"):
                self.post_message(self.ConfirmResponse(True))
            else:
                self.post_message(self.ConfirmResponse(False))
            self.hide()
