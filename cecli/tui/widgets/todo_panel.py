"""Centered read-only panel for agent todo lists."""

import os
from typing import Dict, List

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import RichLog, Static, Tab, Tabs


class TodoPanel(Vertical):
    """Overlay with one tab per agent showing its ``todo.txt`` contents.

    Tabs cover the primary agent plus every tracked sub-agent, and are rebuilt
    incrementally from ``AgentService`` on a short interval. Opening the panel
    selects the agent that is currently visible in the TUI, falling back to the
    first tab when that agent is no longer tracked.
    """

    REFRESH_INTERVAL = 1.0
    MAX_TODO_LINES = 500

    BINDINGS = [
        Binding("f", "toggle_follow", "Follow", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._active_key = None
        self._follow = True
        self._keys: List[str] = []
        self._rendered_signature = None

    def compose(self) -> ComposeResult:
        yield Tabs(id="todo-tabs")
        yield Static("", id="todo-agent-line")
        yield Static("No agent todo lists.", id="todo-empty")
        yield RichLog(
            id="todo-output",
            wrap=True,
            markup=False,
            auto_scroll=False,
            max_lines=self.MAX_TODO_LINES,
        )

    def on_mount(self):
        """Start polling and render the first snapshot."""
        self.border_title = "todos"
        self.set_interval(self.REFRESH_INTERVAL, self.refresh_data)
        self.call_after_refresh(self.refresh_data)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated):
        """Switch the todo view to the newly selected agent."""
        if event.tab is None:
            return

        self._active_key = event.tab.id
        self._rendered_signature = None
        self.refresh_data()

    def refresh_data(self):
        """Sync tabs and the selected agent's todo list with the service."""
        if not self.is_mounted or not self._is_shown:
            return

        agents = self._agent_snapshots()
        self.border_title = f"todos ({len(agents)})" if agents else "todos"

        if list(agents) != self._keys:
            self._sync_tabs(agents)

        if not agents:
            self._active_key = None
            self._show_empty(True)
            return

        self._show_empty(False)

        if self._active_key not in agents:
            self._active_key = next(iter(agents))
            self._select_tab(self._active_key)
            self._rendered_signature = None

        active = agents[self._active_key]
        self._set_agent_line(active)
        self._render_todo(active)

    def action_toggle_follow(self):
        """Toggle tailing the selected todo list."""
        self._follow = not self._follow
        self._rendered_signature = None
        self.refresh_data()

    def focus_panel(self):
        """Select the active agent, then focus the tab bar for navigation."""
        self._select_active_agent()

        try:
            self.query_one("#todo-tabs", Tabs).focus()
        except Exception:
            self.focus()

    @property
    def _is_shown(self) -> bool:
        """Return True when the panel and its overlay are both displayed."""
        if not self.display:
            return False

        return self.parent is None or self.parent.display

    def _agent_snapshots(self) -> Dict[str, dict]:
        """Return the primary agent and every tracked sub-agent by UUID."""
        from cecli.helpers.agents.service import AgentService

        coder = getattr(getattr(self.app, "worker", None), "coder", None)

        if coder is None:
            return {}

        try:
            service = AgentService.get_instance(coder)
        except Exception:
            return {}

        agents = {}
        primary_uuid = str(getattr(coder, "uuid", ""))

        if primary_uuid:
            agents[primary_uuid] = {
                "uuid": primary_uuid,
                "name": "primary",
                "label": "primary",
                "status": "",
                "coder": coder,
            }

        for uid, info in service.sub_agents.items():
            uid = str(uid)

            if uid == primary_uuid:
                continue

            name = info.name or "sub-agent"
            agents[uid] = {
                "uuid": uid,
                "name": name,
                "label": f"{name} {uid[:3]}",
                "status": info.status.value,
                "coder": info.coder,
            }

        return agents

    def _sync_tabs(self, agents: Dict[str, dict]) -> None:
        """Add and remove tabs so they match the tracked agent set.

        Tabs must be updated incrementally: ``Tabs.clear`` removes its children
        asynchronously, so clearing and immediately re-adding the same IDs
        races with the pending removal and raises ``DuplicateIds``.
        """
        tabs = self.query_one("#todo-tabs", Tabs)
        previous_keys = list(self._keys)
        self._keys = list(agents)

        with self.prevent(Tabs.TabActivated):
            for agent_uuid in previous_keys:
                if agent_uuid not in agents:
                    tabs.remove_tab(agent_uuid)

            for agent_uuid, agent in agents.items():
                if agent_uuid not in previous_keys:
                    tabs.add_tab(Tab(agent["label"], id=agent_uuid, classes="todo-tab"))

            if self._active_key not in agents:
                self._active_key = next(iter(agents), None)

            if self._active_key is not None:
                tabs.active = self._active_key

    def _select_tab(self, agent_uuid: str) -> None:
        """Mark a tab active without relying on a user click."""
        try:
            tabs = self.query_one("#todo-tabs", Tabs)
            tabs.active = agent_uuid
        except Exception:
            pass

    def _select_active_agent(self) -> None:
        """Select the agent currently visible in the TUI, if it has a tab."""
        try:
            active_uuid = str(self.app._get_visible_coder().uuid)
        except Exception:
            return

        if active_uuid not in self._keys:
            return

        self._active_key = active_uuid
        self._rendered_signature = None
        self._select_tab(active_uuid)
        self.refresh_data()

    def _show_empty(self, empty: bool) -> None:
        """Swap between the empty message and the agent view."""
        self.query_one("#todo-empty", Static).display = empty
        self.query_one("#todo-agent-line", Static).display = not empty
        self.query_one("#todo-tabs", Tabs).display = not empty
        self.query_one("#todo-output", RichLog).display = not empty

    def _set_agent_line(self, agent: dict) -> None:
        """Show the selected agent and status, truncated to the panel width."""
        text = f"agent: {agent['name']} ({agent['uuid']})"
        status = agent.get("status")

        if status:
            text += f" · {status}"

        width = max(20, self.size.width - 6)

        if len(text) > width:
            text = text[: width - 1] + "…"

        self.query_one("#todo-agent-line", Static).update(Text(text))

    def _render_todo(self, agent: dict) -> None:
        """Render the selected agent's todo list when it changed."""
        content = self._read_todo(agent.get("coder"))
        signature = (agent.get("uuid"), content)

        if signature == self._rendered_signature:
            return

        self._rendered_signature = signature
        self._write_todo(content)

    def _write_todo(self, content: str) -> None:
        """Write the todo list, following the tail if enabled."""
        log = self.query_one("#todo-output", RichLog)
        log.clear()

        lines = content.splitlines()

        if len(lines) > self.MAX_TODO_LINES:
            lines = lines[-self.MAX_TODO_LINES :]

        if lines:
            log.write("\n".join(lines), scroll_end=self._follow)
        else:
            log.write(Text("no todo list", style="dim"), scroll_end=self._follow)

    @staticmethod
    def _read_todo(coder) -> str:
        """Return the raw todo file for *coder*, or an empty string."""
        if coder is None:
            return ""

        try:
            path = coder.abs_root_path(coder.local_agent_folder("todo.txt"))

            if not os.path.isfile(path):
                return ""

            content = coder.io.read_text(path)

            return content or ""
        except Exception:
            return ""
