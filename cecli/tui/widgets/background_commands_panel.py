"""Centered read-only panel for active background shell commands."""

from typing import Dict, List

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import RichLog, Static, Tab, Tabs

from cecli.helpers.background_commands import BackgroundCommandManager

from .overlay import OVERLAY_BINDINGS, OverlayPanelActions, refresh_overlay_subtitles


class BackgroundCommandsPanel(OverlayPanelActions, Vertical):
    """Task manager overlay with one tab per active background command.

    Tabs are rebuilt from ``BackgroundCommandManager`` on a short interval and
    the selected command's output is re-rendered only when its stream offset
    changes. Reading output is non-destructive so the agent keeps its own
    incremental view of the same buffer.

    Commands that exceed their timeout and keep running appear here once the
    timeout fires, so the user can watch them continue.
    """

    REFRESH_INTERVAL = 0.5
    MAX_TAIL_LINES = 500

    BINDINGS = [
        *OVERLAY_BINDINGS,
        Binding("f", "toggle_follow", "Follow", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._active_key = None
        self._follow = True
        self._keys: List[str] = []
        self._rendered_signature = None

    def compose(self) -> ComposeResult:
        yield Tabs(id="bg-command-tabs")
        yield Static("", id="bg-command-line")
        yield Static("No active background commands.", id="bg-command-empty")
        yield RichLog(
            id="bg-command-output",
            wrap=True,
            markup=False,
            auto_scroll=False,
            max_lines=self.MAX_TAIL_LINES,
        )

    def on_mount(self):
        """Start polling and render the first snapshot."""
        self.border_title = "commands"
        self.set_interval(self.REFRESH_INTERVAL, self.refresh_data)
        self.call_after_refresh(self.refresh_data)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated):
        """Switch the output view to the newly selected tab."""
        if event.tab is None:
            return

        self._active_key = event.tab.id
        self._rendered_signature = None
        self.refresh_data()

    def refresh_data(self):
        """Sync tabs and the selected command's output with the manager."""
        if not self.is_mounted or not self._is_shown:
            return

        commands = self._active_commands()
        self.border_title = "commands"
        refresh_overlay_subtitles(self.app)

        if list(commands) != self._keys:
            self._sync_tabs(commands)

        if not commands:
            self._active_key = None
            self._show_empty(True)
            return

        self._show_empty(False)

        if self._active_key not in commands:
            self._active_key = next(iter(commands))
            self._select_tab(self._active_key)
            self._rendered_signature = None

        active = commands[self._active_key]
        self._set_command_line(active)
        self._render_output(active)

    def action_toggle_follow(self):
        """Toggle tailing the selected command's output."""
        self._follow = not self._follow
        self._rendered_signature = None
        self.refresh_data()

    def focus_panel(self):
        """Focus the tab bar so keyboard navigation reaches this panel."""
        try:
            self.query_one("#bg-command-tabs", Tabs).focus()
        except Exception:
            self.focus()

    @property
    def _is_shown(self) -> bool:
        """Return True when the panel and its overlay are both displayed."""
        if not self.display:
            return False

        return self.parent is None or self.parent.display

    def _active_commands(self) -> Dict[str, dict]:
        """Return running commands, including timeouts that continued in the background."""
        commands = {}

        for command_key, info in BackgroundCommandManager.list_background_commands().items():
            if not info.get("running"):
                continue

            # Commands started with background=True are always listed; timeout-managed
            # commands only once their timeout elapsed and they kept running.
            if info.get("persist") and not info.get("continued_in_background"):
                continue

            commands[command_key] = info

        return commands

    def _sync_tabs(self, commands: Dict[str, dict]) -> None:
        """Add and remove tabs so they match the active command set.

        Tabs must be updated incrementally: ``Tabs.clear`` removes its children
        asynchronously, so clearing and immediately re-adding the same IDs
        races with the pending removal and raises ``DuplicateIds``.
        """
        tabs = self.query_one("#bg-command-tabs", Tabs)
        previous_keys = list(self._keys)
        self._keys = list(commands)

        with self.prevent(Tabs.TabActivated):
            for command_key in previous_keys:
                if command_key not in commands:
                    tabs.remove_tab(command_key)

            for command_key in commands:
                if command_key not in previous_keys:
                    tabs.add_tab(Tab(command_key, id=command_key, classes="bg-tab"))

            if self._active_key not in commands:
                self._active_key = next(iter(commands), None)

            if self._active_key is not None:
                tabs.active = self._active_key

    def _select_tab(self, command_key: str) -> None:
        """Mark a tab active without relying on a user click."""
        try:
            tabs = self.query_one("#bg-command-tabs", Tabs)
            tabs.active = command_key
        except Exception:
            pass

    def _show_empty(self, empty: bool) -> None:
        """Swap between the empty message and the command view."""
        self.query_one("#bg-command-empty", Static).display = empty
        self.query_one("#bg-command-line", Static).display = not empty
        self.query_one("#bg-command-tabs", Tabs).display = not empty
        self.query_one("#bg-command-output", RichLog).display = not empty

    def _set_command_line(self, info: dict) -> None:
        """Show the selected command, truncated to the panel width."""
        command = " ".join((info.get("command") or "").split())
        text = f"command: {command}" if command else "command: (none)"

        if info.get("continued_in_background"):
            text += " (timed out, still running)"

        width = max(20, self.size.width - 6)

        if len(text) > width:
            text = text[: width - 1] + "…"

        self.query_one("#bg-command-line", Static).update(Text(text))

    def _render_output(self, info: dict) -> None:
        """Render the selected command's output when its stream advanced."""
        signature = (info.get("total_chars"), info.get("buffer_size"))

        if signature == self._rendered_signature:
            return

        self._rendered_signature = signature
        output = BackgroundCommandManager.get_command_output(self._active_key)
        self._write_output(output)

    def _write_output(self, output: str) -> None:
        """Write the newest lines to the log, following the tail if enabled."""
        log = self.query_one("#bg-command-output", RichLog)
        log.clear()

        lines = output.splitlines()

        if len(lines) > self.MAX_TAIL_LINES:
            lines = lines[-self.MAX_TAIL_LINES :]

        if lines:
            log.write("\n".join(lines), scroll_end=self._follow)
        else:
            log.write(Text("no output yet", style="dim"), scroll_end=self._follow)
