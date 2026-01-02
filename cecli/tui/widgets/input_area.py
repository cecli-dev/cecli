"""Input widget for cecli TUI."""

from prompt_toolkit.history import FileHistory
from textual.message import Message
from textual.widgets import TextArea


class InputArea(TextArea):
    """Input widget with autocomplete and history support."""

    class Submit(Message):
        """User submitted the input (Enter key)."""

        def __init__(self, value: str):
            self.value = value
            super().__init__()

    class CompletionRequested(Message):
        """User requested completion (Tab key or auto-trigger)."""

        def __init__(self, text: str):
            self.text = text
            super().__init__()

    class CompletionCycle(Message):
        """User wants to cycle through completions."""

        pass

    class CompletionCyclePrevious(Message):
        """User wants to cycle through completions backwards."""

        pass

    class CompletionAccept(Message):
        """User wants to accept current completion."""

        pass

    class CompletionDismiss(Message):
        """User wants to dismiss completions."""

        pass

    def __init__(self, history_file: str = None, **kwargs):
        """Initialize input area.

        Args:
            history_file: Path to input history file for up/down navigation
        """
        super().__init__(show_line_numbers=False, **kwargs)
        # Note: placeholder is not a constructor argument in some versions of Textual TextArea,
        # but it is a reactive property. We set it here.
        # Check if placeholder was passed in kwargs, if not use default
        # (kwargs are passed to super, so if it WAS passed, it might be handled or ignored depending on version)
        # To be safe, we set it explicitly if not in kwargs, but we can't easily check what super did.
        # We'll just set it.
        # But wait, kwargs might have had it.
        # Let's assume kwargs might handle it or we set it.
        # Actually, let's just set the default if it's empty.
        if not self.placeholder:
            submit = self.app.get_keys_for("submit")
            newline = self.app.get_keys_for("newline")

            self.placeholder = (
                f"> Type your message... ({submit} to submit, {newline} for new line)"
            )

        self.files = []
        self.commands = []
        self.completion_active = False

        self._cycling = False
        self._completion_prefix = ""

        # History support - lazy loaded
        self.history_file = history_file
        self._history: list[str] | None = None  # None = not loaded yet
        self._history_index = -1  # -1 = not navigating, 0+ = position in history
        self._saved_input = ""  # Saves current input when navigating history

    @property
    def value(self) -> str:
        """Alias for text property to maintain compatibility."""
        return self.text

    @property
    def completion_prefix(self) -> str:
        return self._completion_prefix

    @property
    def cursor_position(self) -> int:
        """
        Get cursor position as an index (compatibility wrapper).
        Note: This is approximate/incomplete for multi-line but helps compat.
        It returns the offset from start of text.
        """
        # Calculate offset based on cursor_location (row, col)
        # This is expensive, but necessary for compat if used heavily.
        # Or we can just ignore getters if not used.
        # app.py uses `len(input_area.value)` to set it.
        # So it uses setter.
        return 0  # Dummy getter

    @value.setter
    def value(self, new_value: str):
        """Alias for text property to maintain compatibility."""
        self.text = new_value

    @cursor_position.setter
    def cursor_position(self, pos: int):
        """
        Set cursor position (compatibility wrapper).
        If pos is len(text), move to end.
        """
        if pos >= len(self.text):
            # Move cursor to the very end
            lines = self.text.split("\n")
            row = max(0, len(lines) - 1)
            col = len(lines[row])
            self.cursor_location = (row, col)

    def _ensure_history_loaded(self) -> list[str]:
        """Lazily load history on first access.

        Returns history with most recent at the end (index -1).
        """
        if self._history is None:
            self._history = []
            if self.history_file:
                try:
                    # FileHistory returns most recent first, so reverse it
                    self._history = list(
                        reversed(list(FileHistory(self.history_file).load_history_strings()))
                    )
                except (OSError, IOError):
                    pass  # History file doesn't exist yet or can't be read
        return self._history

    def update_autocomplete_data(self, files, commands):
        """Update autocomplete suggestions.

        Args:
            files: List of file paths for autocomplete
            commands: List of command names for autocomplete
        """
        self.files = files
        self.commands = commands

    def save_to_history(self, text: str) -> None:
        """Save input to history file and in-memory list.

        Args:
            text: The input text to save
        """
        # Skip empty, whitespace-only, or very short inputs
        if not text or not text.strip() or len(text.strip()) <= 1:
            return

        # Skip if same as last history entry
        history = self._ensure_history_loaded()
        if history and history[-1] == text:
            return

        # Save to file
        if self.history_file:
            try:
                FileHistory(self.history_file).append_string(text)
            except (OSError, IOError):
                pass

        # Add to in-memory history
        history.append(text)

        # Reset navigation state
        self._history_index = -1
        self._saved_input = ""

    def _history_prev(self) -> None:
        """Navigate to previous (older) history entry."""
        history = self._ensure_history_loaded()
        if not history:
            return

        # Save current input when first entering history
        if self._history_index == -1:
            self._saved_input = self.text
            self._history_index = len(history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        else:
            return  # Already at oldest

        self.text = history[self._history_index]
        self.cursor_position = len(self.text)  # Will move to end

    def _history_next(self) -> None:
        """Navigate to next (newer) history entry."""
        if self._history_index == -1:
            return  # Not navigating history

        history = self._ensure_history_loaded()
        if self._history_index < len(history) - 1:
            self._history_index += 1
            self.text = history[self._history_index]
        else:
            # Back to current input
            self._history_index = -1
            self.text = self._saved_input

        self.cursor_position = len(self.text)  # Will move to end

    def set_completion_preview(self, text: str):
        self._cycling = True
        self.value = text
        self.cursor_position = len(text)

    def on_key(self, event) -> None:
        """Handle keys for completion and history navigation."""
        if self.disabled:
            return

        # Reset cycling if not a cycle command
        is_cycle = self.app.is_key_for("cycle_forward", event.key) or self.app.is_key_for(
            "cycle_backward", event.key
        )
        if not is_cycle:
            self._cycling = False

        if event.key == "space" and self.completion_active:
            self.completion_active = False
            self.post_message(self.CompletionDismiss())

        if self.app.is_key_for("cancel", event.key):
            event.stop()
            event.prevent_default()
            if self.text.strip():
                self.save_to_history(self.text)
            self.text = ""
            return

        if self.app.is_key_for("submit", event.key):
            # Submit message
            event.stop()
            event.prevent_default()
            self.post_message(self.Submit(self.text))
            return

        if self.app.is_key_for("newline", event.key):
            if self.app.get_keys_for("newline") != "enter":
                self.insert("\n")

                current_row, current_col = self.cursor_location
                self.cursor_location = (current_row + 1, 0)

            return

        if self.app.is_key_for("cycle_forward", event.key):
            event.stop()
            event.prevent_default()
            if self.completion_active:
                # Cycle through completions
                self.post_message(self.CompletionCycle())
            else:
                # Request completions
                self.post_message(self.CompletionRequested(self.text))
        elif self.app.is_key_for("cycle_backward", event.key):
            event.stop()
            event.prevent_default()
            if self.completion_active:
                # Cycle through completions
                self.post_message(self.CompletionCyclePrevious())
            else:
                # Request completions
                self.post_message(self.CompletionRequested(self.text))
        elif self.app.is_key_for("stop", event.key) and self.completion_active:
            event.stop()
            event.prevent_default()
            self.post_message(self.CompletionDismiss())
        elif event.key == "up":
            # If on first line, navigate history
            # Or use Ctrl+Up? Let's use Up if on first line for convenience, similar to typical shell
            # BUT this is a text editor.
            # Let's try: if cursor is at (0,0) or just row 0.
            if self.cursor_location[0] == 0:
                event.stop()
                event.prevent_default()
                self._history_prev()
        elif event.key == "down":
            # If on last line, navigate history
            if self.cursor_location[0] == self.document.line_count - 1:
                event.stop()
                event.prevent_default()
                self._history_next()

    def on_text_area_changed(self, event) -> None:
        """Update completions as user types."""
        # Note: Event name for TextArea change is 'Changed' but handler is on_text_area_changed
        if self.disabled:
            return

        if self._cycling:
            return

        self._completion_prefix = self.text

        if not self.disabled:
            val = self.text
            possible_path = False

            # Auto-trigger for slash commands, @ symbols, or update existing completions
            words = val.rsplit(maxsplit=1)

            if words:
                last_word = words[-1]
                if "/" in last_word:
                    possible_path = True

            if val.startswith("/") or "@" in val or possible_path or self.completion_active:
                self.post_message(self.CompletionRequested(val))
