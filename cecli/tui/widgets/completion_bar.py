"""Completion bar widget for autocomplete suggestions."""

import os

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static


class CompletionBar(Widget, can_focus=False):
    """Bar showing autocomplete suggestions above input (non-focusable)."""

    MAX_SUGGESTIONS = 50
    WINDOW_SIZE = 6

    DEFAULT_CSS = """
    CompletionBar {
        height: 1;
        background: $surface;
        margin: 0 0;
        padding: 0 0;
        layout: horizontal;
    }

    CompletionBar .completion-prefix {
        width: auto;
        height: 1;
        margin-right: 1;
        color: $secondary;
        background: $surface;
    }

    CompletionBar .completion-item {
        width: auto;
        height: 1;
        margin-right: 2;
        color: $secondary;
        background: $surface;
    }

    CompletionBar .completion-item.selected {
        color: $primary;
        text-style: bold;
    }

    CompletionBar .completion-item.preselected {
        color: $secondary;
    }

    CompletionBar .completion-more {
        width: auto;
        height: 1;
        margin-right: 1;
        color: $panel;
    }

    CompletionBar .completion-hint {
        width: auto;
        height: 1;
        color: $panel;
        dock: right;
    }
    """

    class Selected(Message):
        """Completion selected message."""

        def __init__(self, value: str):
            self.value = value
            super().__init__()

    class Dismissed(Message):
        """Completion bar dismissed."""

        pass

    def __init__(self, suggestions: list[str] = None, prefix: str = "", **kwargs):
        """Initialize completion bar.

        Args:
            suggestions: List of completion suggestions
            prefix: Current input prefix to complete from
        """
        super().__init__(**kwargs)
        self.suggestions = (suggestions or [])[: self.MAX_SUGGESTIONS]
        self.prefix = prefix
        self.selected_index = 0
        self._has_cycled = False  # Track if user has actively cycled through suggestions
        self._item_widgets: list[Static] = []
        self._prefix_widget: Static | None = None
        self._left_more: Static | None = None
        self._right_more: Static | None = None
        self._hint: Static | None = None

        # Compute common directory prefix and display names
        self._common_prefix = ""
        self._display_names: list[str] = []
        self._compute_display_names()

    @property
    def current_selection(self) -> str | None:
        """Get currently selected suggestion."""
        if self.suggestions and 0 <= self.selected_index < len(self.suggestions):
            return self.suggestions[self.selected_index]
        return None

    def _compute_display_names(self) -> None:
        """Compute common directory prefix and short display names."""
        if not self.suggestions:
            self._common_prefix = ""
            self._display_names = []
            return

        # Check if these look like file paths (contain /)
        has_paths = any("/" in s for s in self.suggestions)

        if not has_paths:
            # Commands or non-path items - show as-is
            self._common_prefix = ""
            self._display_names = self.suggestions[:]
            return

        # Find common directory prefix
        dirs = [os.path.dirname(s) for s in self.suggestions]
        if dirs and all(d == dirs[0] for d in dirs) and dirs[0]:
            # All in same directory
            self._common_prefix = dirs[0] + "/"
            self._display_names = [os.path.basename(s) for s in self.suggestions]
        else:
            # Find longest common path prefix
            common = os.path.commonpath(self.suggestions) if self.suggestions else ""
            if common and "/" in common:
                # Use the directory part of common prefix
                self._common_prefix = common.rsplit("/", 1)[0] + "/" if "/" in common else ""
                if self._common_prefix:
                    self._display_names = [s[len(self._common_prefix) :] for s in self.suggestions]
                else:
                    self._display_names = self.suggestions[:]
            else:
                self._common_prefix = ""
                self._display_names = self.suggestions[:]

    def compose(self) -> ComposeResult:
        """Create the bar layout."""
        # Directory prefix (shown once)
        self._prefix_widget = Static(self._common_prefix, classes="completion-prefix")
        self._prefix_widget.display = bool(self._common_prefix)
        yield self._prefix_widget

        self._left_more = Static("…", classes="completion-more")
        self._left_more.display = False
        yield self._left_more

        self._item_widgets = []
        for i in range(self.WINDOW_SIZE):
            if i < len(self._display_names):
                selected_class = "selected" if self._has_cycled else "preselected"
                classes = f"completion-item {selected_class}" if i == 0 else "completion-item"
                item = Static(self._display_names[i], classes=classes)
            else:
                item = Static("", classes="completion-item")
                item.display = False
            self._item_widgets.append(item)
            yield item

        # Show "+N more" instead of just ellipsis
        remaining = len(self.suggestions) - self.WINDOW_SIZE
        more_text = f"+{remaining}" if remaining > 0 else ""
        self._right_more = Static(more_text, classes="completion-more")
        self._right_more.display = remaining > 0
        yield self._right_more

        self._hint = Static("Tab ↹  Enter ⏎  Esc ✗", classes="completion-hint")
        yield self._hint

    def update_suggestions(self, suggestions: list[str], prefix: str = "") -> None:
        """Update suggestions in place."""
        self.suggestions = suggestions[: self.MAX_SUGGESTIONS]
        self.prefix = prefix
        self.selected_index = 0
        self._has_cycled = False  # Reset cycling flag when suggestions change

        # Recompute display names
        self._compute_display_names()

        # Update prefix widget
        if self._prefix_widget:
            self._prefix_widget.update(self._common_prefix)
            self._prefix_widget.display = bool(self._common_prefix)

        self._refresh_items()
        self._set_selection_classes()

    def _refresh_items(self) -> None:
        """Update visible items - selected item always shown first."""
        # Ensure meta widgets exist
        if self._left_more is None or self._left_more.parent is None:
            self._left_more = Static("", classes="completion-more")
            self.mount(
                self._left_more, before=self._item_widgets[0] if self._item_widgets else None
            )
        if self._right_more is None or self._right_more.parent is None:
            self._right_more = Static("", classes="completion-more")
            self.mount(self._right_more, after=self._left_more if self._left_more else None)
        if self._hint is None or self._hint.parent is None:
            self._hint = Static("Tab ↹  Enter ⏎  Esc ✗", classes="completion-hint")
            self.mount(self._hint)

        # Grow the widget list to the window size
        while len(self._item_widgets) < self.WINDOW_SIZE:
            new_item = Static("", classes="completion-item")
            self._item_widgets.append(new_item)
            target = (
                self._right_more if self._right_more and self._right_more.parent else self._hint
            )
            self.mount(new_item, before=target)

        if not self._display_names:
            for item in self._item_widgets:
                item.display = False
            if self._left_more:
                self._left_more.display = False
            if self._right_more:
                self._right_more.display = False
            return

        # Build display order: selected item first, then others after it
        total = len(self._display_names)
        items_before = self.selected_index
        # items_after = total - self.selected_index - 1

        # Show indicator if there are items before selected
        if self._left_more:
            if items_before > 0:
                self._left_more.update(f"{items_before}+")
                self._left_more.display = True
            else:
                self._left_more.display = False

        # Fill window: selected first, then subsequent items
        window_size = min(self.WINDOW_SIZE, total)
        visible_indices = []

        # Always include selected
        visible_indices.append(self.selected_index)

        # Add items after selected
        for i in range(1, window_size):
            next_idx = self.selected_index + i
            if next_idx < total:
                visible_indices.append(next_idx)

        # Update item widgets
        for i, item in enumerate(self._item_widgets):
            if i < len(visible_indices):
                display_index = visible_indices[i]
                item.update(self._display_names[display_index])
                item.display = True
            else:
                item.display = False

        # Show indicator for remaining items after visible window
        remaining_after = total - (self.selected_index + len(visible_indices))
        if self._right_more:
            if remaining_after > 0:
                self._right_more.update(f"+{remaining_after}")
                self._right_more.display = True
            else:
                self._right_more.display = False

    def _set_selection_classes(self) -> None:
        """Apply selected class - first visible item is always selected."""
        for i, item in enumerate(self._item_widgets):
            if not item.display:
                item.remove_class("selected")
                item.remove_class("preselected")
                continue
            # First item is always the selected one
            if i == 0:
                # Use "preselected" style if we haven't cycled yet and are at index 0
                if not self._has_cycled and self.selected_index == 0:
                    item.add_class("preselected")
                    item.remove_class("selected")
                else:
                    item.add_class("selected")
                    item.remove_class("preselected")
            else:
                item.remove_class("selected")
                item.remove_class("preselected")

    def _update_selection(self) -> None:
        """Update visual selection state."""
        if not self.suggestions:
            return
        self._refresh_items()
        self._set_selection_classes()

    def cycle_next(self) -> None:
        """Cycle to next suggestion."""
        if self.suggestions:
            if not self._has_cycled:
                self._has_cycled = True  # User has actively cycled
            else:
                self.selected_index = (self.selected_index + 1) % len(self.suggestions)

            self._update_selection()

    def cycle_previous(self) -> None:
        """Cycle to previous suggestion."""
        if self.suggestions:
            if not self._has_cycled:
                self._has_cycled = True  # User has actively cycled
            else:
                if not self.selected_index:
                    self.selected_index = len(self.suggestions) - 1
                else:
                    self.selected_index = (self.selected_index - 1) % len(self.suggestions)

            self._update_selection()

    def select_current(self) -> None:
        """Select current suggestion and dismiss."""
        if self.suggestions:
            self.post_message(self.Selected(self.suggestions[self.selected_index]))
        self.remove()

    def dismiss(self) -> None:
        """Dismiss without selecting."""
        self.post_message(self.Dismissed())
        self.remove()
