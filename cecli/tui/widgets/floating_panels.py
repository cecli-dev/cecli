"""Extensions box showing sub-agents, skills, and MCP servers."""

from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class StatusItemClicked(Message):
    """Posted when a status item is clicked."""

    def __init__(self, category: str, name: str, active: bool):
        super().__init__()
        self.category = category
        self.name = name
        self.active = active


class StatusItem(Static):
    """A clickable item in the extensions box."""

    def __init__(self, display_name, item_name, category, active, **kwargs):
        classes = "status-item active" if active else "status-item inactive"
        super().__init__(
            f"{'●' if active else '○'} {display_name}",
            markup=False,
            classes=classes,
            **kwargs,
        )
        self.item_name = item_name
        self.item_category = category
        self.item_active = active

    def on_click(self, event):
        self.post_message(StatusItemClicked(self.item_category, self.item_name, self.item_active))
        event.stop()


class StatusColumn(Vertical):
    """A reactive vertical column of clickable status items."""

    items = reactive([], recompose=True)

    def __init__(self, category: str, **kwargs):
        super().__init__(**kwargs)
        self.category = category

    def compose(self):
        if not self.items:
            yield Static("(none)", classes="status-empty")
            return

        for display_name, name, active in self.items:
            yield StatusItem(display_name, name, self.category, active)


class FloatingPanels(Vertical):
    """Single box showing sub-agents, skills, and MCP servers.

    Every item is clickable: sub-agents spawn, skills load/unload, and MCP
    servers load/unload. The three categories sit in equal-width columns
    beneath labels embedded in the top border, and share one scroll area.
    """

    MAX_NAME_WIDTH = 10

    DEFAULT_CSS = """
    FloatingPanels {
        height: auto;
        width: 42;
        border: round $accent 50%;
        border-title-align: center;
        border-title-color: $accent 50%;
        border-title-style: bold;
        padding: 0 1;
        background: $surface;
    }

    FloatingPanels > .status-body {
        height: 100%;
        width: 100%;
    }

    FloatingPanels .status-scroll {
        width: 100%;
        height: 1fr;
        overflow-x: hidden;
        overflow-y: auto;
        scrollbar-size: 0 0;
        scrollbar-visibility: hidden;
    }

    FloatingPanels .status-items {
        width: 100%;
        height: auto;
    }

    FloatingPanels .status-column {
        width: 1fr;
        height: auto;
    }

    FloatingPanels .status-spacer {
        width: 1;
        height: 1;
    }

    FloatingPanels .status-item {
        width: 100%;
        height: 1;
        color: $accent;
    }

    FloatingPanels .status-item.inactive {
        color: white;
        text-style: dim;
    }

    FloatingPanels .status-empty {
        width: auto;
        height: 1;
        color: $secondary;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "agents ───── skills ───── servers"
        self._synced_height = None
        self._synced_column_height = None
        self._command_running = False

    def compose(self):
        with Vertical(classes="status-body"):
            with VerticalScroll(classes="status-scroll", id="status-scroll"):
                with Horizontal(classes="status-items"):
                    yield StatusColumn("subagents", id="subagents-column", classes="status-column")
                    yield Static("", classes="status-spacer")
                    yield StatusColumn("skills", id="skills-column", classes="status-column")
                    yield Static("", classes="status-spacer")
                    yield StatusColumn("servers", id="servers-column", classes="status-column")

    def on_mount(self):
        """Start periodic height sync and data refreshes."""
        self.call_after_refresh(self._sync_height)
        self.set_interval(0.25, self._sync_height)
        self.set_interval(1.0, self.refresh_data)
        self.refresh_data()

    def on_status_item_clicked(self, event: StatusItemClicked):
        """Route an item click to the matching coder command."""
        self._run_coder_command(event.category, event.name, event.active)
        self._scroll_to_top()
        self.app.call_after_refresh(self._focus_input)

    def _sync_height(self):
        """Match the box height to the input container's current height."""
        try:
            height = self.app.query_one("#input-container").region.height
        except Exception:
            return

        if height <= 0:
            return

        if height != self._synced_height:
            self._synced_height = height
            self.styles.height = height

        try:
            hints = self.app.query_one("#key-hints")
            column = self.app.query_one("#input-column")
            hints_height = hints.region.height
            hints_height += int(hints.styles.margin.top)
            hints_height += int(hints.styles.margin.bottom)
            column_height = height + hints_height
        except Exception:
            return

        if column_height != self._synced_column_height:
            self._synced_column_height = column_height
            column.styles.height = column_height

    def toggle_visible(self):
        """Hide the whole extensions column, or show it again."""
        target = self.parent
        if getattr(target, "id", None) != "extensions-column":
            target = self

        target.display = not target.display
        if target.display:
            self.refresh_data()

    def refresh_data(self):
        """Refresh the extensions columns from the active coder's state."""
        coder = self._get_active_coder()
        if coder is None:
            self._set_column("#subagents-column", [])
            self._set_column("#skills-column", [])
            self._set_column("#servers-column", [])
            return

        self._set_column("#subagents-column", self._collect_agents())
        self._set_column("#skills-column", self._collect_skills(coder))
        self._set_column("#servers-column", self._collect_mcp(coder))

    def _focus_input(self):
        """Return keyboard focus to the prompt input."""
        try:
            self.app.query_one("#input").focus()
        except Exception:
            pass

    def _scroll_to_top(self):
        """Return the shared list to the top after an item click."""
        try:
            self.query_one("#status-scroll", VerticalScroll).scroll_to(y=0, animate=False)
        except Exception:
            pass

    def _set_column(self, selector, entries):
        """Replace one column's clickable items, skipping unchanged data."""
        try:
            column = self.query_one(selector, StatusColumn)
        except Exception:
            return

        ordered = sorted(entries, key=lambda item: (not item[1], item[0].lower()))
        items = [(self._format_name(name), name, active) for name, active in ordered]
        signature = tuple(items)
        if signature == getattr(column, "_last_signature", None):
            return

        column._last_signature = signature
        column.items = items

    def _run_coder_command(self, category, name, active):
        """Schedule the click's coder command on the worker loop."""
        if self._command_running:
            return

        coder = self._get_primary_coder() if category == "subagents" else self._get_active_coder()
        if coder is None:
            return

        command_cls = self._command_class(category, active)
        if command_cls is None:
            return

        self._command_running = True

        async def runner():
            try:
                await command_cls.execute(coder.io, coder, name)
            finally:
                self._command_running = False
                try:
                    self.app.call_from_thread(self.refresh_data)
                except Exception:
                    pass

        loop = getattr(getattr(self.app, "worker", None), "loop", None)
        if loop is not None:
            loop.call_soon_threadsafe(lambda: loop.create_task(runner()))
            return

        try:
            self.run_worker(runner())
        except Exception:
            self._command_running = False

    def _command_class(self, category, active):
        """Return the command class for an item click."""
        if category == "subagents":
            from cecli.commands.spawn_agent import SpawnAgentCommand

            return SpawnAgentCommand

        if category == "skills":
            if active:
                from cecli.commands.remove_skill import RemoveSkillCommand

                return RemoveSkillCommand

            from cecli.commands.load_skill import LoadSkillCommand

            return LoadSkillCommand

        if category == "servers":
            if active:
                from cecli.commands.remove_mcp import RemoveMcpCommand

                return RemoveMcpCommand

            from cecli.commands.load_mcp import LoadMcpCommand

            return LoadMcpCommand

        return None

    def _get_primary_coder(self):
        """Return the primary coder from the TUI worker, if available."""
        try:
            return self.app.worker.coder
        except Exception:
            return None

    def _get_active_coder(self):
        """Return the foreground coder, falling back to the primary coder."""
        primary = self._get_primary_coder()
        if primary is None:
            return None

        try:
            from cecli.helpers.agents.service import AgentService

            return AgentService.get_instance(primary).foreground_coder or primary
        except Exception:
            return primary

    def _collect_agents(self):
        """Collect agent types, marking the foreground agent's type active."""
        primary = self._get_primary_coder()
        if primary is None:
            return []

        try:
            from cecli.helpers.agents.service import AgentService

            service = AgentService.get_instance(primary)
            registered = set(AgentService.get_registry().keys())
            live = {info.name for info in service.sub_agents.values() if info is not None}
            active_name = None
            foreground_uuid = getattr(service, "foreground_uuid", None)
            if foreground_uuid:
                info = service.sub_agents.get(str(foreground_uuid))
                if info is not None:
                    active_name = info.name
        except Exception:
            return []

        return [(name, name == active_name) for name in registered | live]

    def _collect_skills(self, coder):
        """Collect discoverable skills and mark the loaded ones active."""
        manager = getattr(coder, "skills_manager", None)
        if manager is None:
            return []

        loaded = set(getattr(manager, "_loaded_skills", set()) or set())
        try:
            available = {skill.name for skill in manager.find_skills()}
        except Exception:
            available = set()

        return [(name, name in loaded) for name in available | loaded]

    def _collect_mcp(self, coder):
        """Collect MCP servers and mark connected, unfiltered ones active."""
        manager = getattr(coder, "mcp_manager", None)
        if manager is None:
            return []

        registered = getattr(coder, "registered_servers", None) or {}
        included = set(registered.get("included", set()) or set())
        excluded = set(registered.get("excluded", set()) or set())

        try:
            servers = manager.servers
        except Exception:
            servers = []

        entries = []
        for server in servers:
            name = getattr(server, "name", "")
            if not name:
                continue

            active = bool(getattr(server, "is_connected", False))
            if included and name not in included:
                active = False
            if name in excluded:
                active = False

            entries.append((name, active))

        return entries

    @staticmethod
    def _format_name(name: str) -> str:
        """Shorten a name to keep rows compact."""
        name = str(name)
        if len(name) > FloatingPanels.MAX_NAME_WIDTH:
            return name[: FloatingPanels.MAX_NAME_WIDTH - 1] + "…"
        return name
