import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from cecli.tui.widgets.floating_panels import (
    FloatingPanels,
    StatusColumn,
    StatusItem,
    StatusItemClicked,
)
from cecli.tui.widgets.input_container import InputContainer


class FakeSkill:
    def __init__(self, name):
        self.name = name


class FakeSkills:
    def __init__(self):
        self._loaded_skills = {"pdf"}
        self.names = ["pdf", "docx", "spark"]

    def find_skills(self):
        return [FakeSkill(name) for name in self.names]


class FakeServer:
    def __init__(self, name, connected):
        self.name = name
        self.is_connected = connected


class FakeMcp:
    def __init__(self):
        self.servers = [FakeServer("local", True), FakeServer("github", False)]


class FakeCoder:
    registered_servers = {"included": set(), "excluded": set()}

    def __init__(self):
        self.skills_manager = FakeSkills()
        self.mcp_manager = FakeMcp()


class _PanelApp(App):
    CSS = """
    #input-row { height: auto; width: 100%; align-vertical: top; }
    #input-container { height: 5; width: 1fr; }
    #key-hints { height: 1; margin: 0 0 1 0; }
    """

    BINDINGS = [Binding("alt+p", "toggle_floating_panels", "Toggle panels", show=False)]

    def __init__(self):
        super().__init__()
        self.worker = SimpleNamespace(coder=FakeCoder())

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-row"):
            with Vertical(id="input-column"):
                with InputContainer(id="input-container"):
                    yield Input(id="input")
                yield Static("hints", id="key-hints")
            with Vertical(id="extensions-column"):
                yield FloatingPanels(id="floating-panels")
                yield Static("alt+p to toggle", id="extensions-hint")

    def action_toggle_floating_panels(self):
        self.query_one(FloatingPanels).toggle_visible()


def _column_text(panels: FloatingPanels, column_id: str) -> str:
    column = panels.query_one(f"#{column_id}", StatusColumn)
    return " ".join(str(item.render()) for item in column.query(StatusItem))


async def _run_panel_checks():
    app = _PanelApp()
    async with app.run_test(size=(100, 40)) as pilot:
        panels = app.query_one("#floating-panels", FloatingPanels)
        input_container = app.query_one("#input-container")
        extensions_column = app.query_one("#extensions-column")
        input_column = app.query_one("#input-column")
        input_area = app.query_one("#input", Input)
        panels.refresh_data()
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()

        visible_input_width = input_container.region.width

        assert panels.border_title == "agents ───── skills ───── servers"
        assert panels.region.x >= input_container.region.right
        assert panels.region.bottom == input_container.region.bottom
        assert panels.region.height == input_container.region.height

        columns = list(panels.query(".status-column"))
        assert len(columns) == 3
        column_widths = [column.region.width for column in columns]
        assert len(set(column_widths)) == 1
        assert columns[0].region.x < columns[1].region.x < columns[2].region.x
        assert columns[1].region.x - columns[0].region.right == 1
        assert columns[2].region.x - columns[1].region.right == 1
        assert len({column.region.y for column in columns}) == 1

        assert _column_text(panels, "subagents-column") == "● worker ○ tester"
        assert _column_text(panels, "skills-column") == "● pdf ○ docx ○ spark"
        assert _column_text(panels, "servers-column") == "● local ○ github"

        long_name = "a-very-long-skill-name-that-keeps-going"
        formatted = FloatingPanels._format_name(long_name)
        assert len(formatted) == FloatingPanels.MAX_NAME_WIDTH
        assert formatted.endswith("…")

        captured = []
        panels._run_coder_command = lambda category, name, active: captured.append(
            (category, name, active)
        )
        skill_items = list(panels.query_one("#skills-column", StatusColumn).query(StatusItem))
        input_area.blur()
        await pilot.pause()
        await pilot.click(skill_items[0])
        await pilot.pause()
        await pilot.click(skill_items[1])
        await pilot.pause()
        assert captured == [("skills", "pdf", True), ("skills", "docx", False)]
        assert app.focused is input_area

        panels.on_status_item_clicked(StatusItemClicked("subagents", "worker", False))
        panels.on_status_item_clicked(StatusItemClicked("servers", "github", False))
        assert captured[-2:] == [
            ("subagents", "worker", False),
            ("servers", "github", False),
        ]

        command_cls, command_args = panels._command_for("subagents", "worker", False)
        assert command_cls.__name__ == "SpawnAgentCommand"
        assert command_args == "worker"

        for category, active, expected_args in [
            ("skills", True, "remove pdf"),
            ("skills", False, "load pdf"),
            ("servers", True, "remove github"),
            ("servers", False, "load github"),
        ]:
            command_cls, command_args = panels._command_for(
                category, "pdf" if category == "skills" else "github", active
            )
            expected_cls = "SkillsCommand" if category == "skills" else "McpCommand"
            assert command_cls.__name__ == expected_cls
            assert command_args == expected_args

        panels._collect_skills = lambda coder: [("z", True), ("a", True), ("b", False)]
        panels.refresh_data()
        await pilot.pause()
        assert _column_text(panels, "skills-column") == "● a ● z ○ b"

        panels._collect_skills = lambda coder: [(f"skill-{i}", True) for i in range(20)]
        panels.refresh_data()
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()

        scroll = panels.query_one("#status-scroll", VerticalScroll)
        assert scroll.max_scroll_y > 0
        assert scroll.styles.scrollbar_visibility == "hidden"
        assert "skill-19" in _column_text(panels, "skills-column")
        assert panels.region.height == input_container.region.height

        scroll.scroll_to(y=5, animate=False)
        await pilot.pause()
        assert scroll.scroll_y > 0

        panels.scroll_by(-1)
        await pilot.pause()
        assert scroll.scroll_y == 4

        panels.scroll_by(1)
        await pilot.pause()
        assert scroll.scroll_y == 5

        panels.on_status_item_clicked(StatusItemClicked("skills", "skill-19", True))
        await pilot.pause()
        assert scroll.scroll_y == 0

        input_container.styles.height = 8
        await pilot.pause()
        await asyncio.sleep(0.35)
        await pilot.pause()
        assert panels.region.height == 8
        assert input_column.region.height == 10

        await pilot.press("alt+p")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert extensions_column.display is False
        assert input_container.region.width > visible_input_width

        await pilot.press("alt+p")
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert extensions_column.display is True
        assert input_container.region.width == visible_input_width


def test_floating_panels_layout_scroll_and_toggle():
    agent_service = SimpleNamespace(
        sub_agents={
            "u1": SimpleNamespace(name="worker"),
            "u2": SimpleNamespace(name="wf:demo"),
        },
        foreground_uuid="u1",
        foreground_coder=None,
    )
    with (
        patch(
            "cecli.helpers.agents.service.AgentService.get_instance",
            return_value=agent_service,
        ),
        patch(
            "cecli.helpers.agents.service.AgentService.get_registry",
            return_value={"tester": None, "worker": None, "wf:demo": None},
        ),
    ):
        asyncio.run(_run_panel_checks())


def test_floating_panels_key_registration():
    from cecli.tui.app import TUI

    tui = object.__new__(TUI)
    tui.args = SimpleNamespace(tui_config=None)
    config = tui._get_config()

    assert config["key_bindings"]["panels"] == "alt+p"
    assert config["key_bindings"]["panel_up"] == "alt+ctrl+up"
    assert config["key_bindings"]["panel_down"] == "alt+ctrl+down"
    assert config["key_bindings"]["main_agent"] == "alt+ctrl+home"
    assert hasattr(TUI, "action_toggle_floating_panels")
    assert hasattr(TUI, "action_scroll_panel_up")
    assert hasattr(TUI, "action_scroll_panel_down")
