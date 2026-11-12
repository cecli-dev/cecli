import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Static, Tab, Tabs

from cecli.commands.open import OpenCommand
from cecli.helpers.background_commands import BackgroundCommandManager
from cecli.tui.widgets.background_commands_panel import BackgroundCommandsPanel

COMMANDS = {
    "bg_0_1111": {
        "command": "npm run dev",
        "running": True,
        "persist": False,
        "buffer_size": 40,
        "total_chars": 40,
    },
    "bg_1_2222": {
        "command": "pytest -q",
        "running": True,
        "persist": False,
        "buffer_size": 20,
        "total_chars": 20,
    },
    "bg_2_3333": {
        "command": "cargo build",
        "running": False,
        "persist": False,
        "buffer_size": 10,
        "total_chars": 10,
    },
    "bg_3_4444": {
        "command": "timeout-tool",
        "running": True,
        "persist": True,
        "continued_in_background": True,
        "buffer_size": 10,
        "total_chars": 10,
    },
    "bg_4_5555": {
        "command": "foreground-tool",
        "running": True,
        "persist": True,
        "continued_in_background": False,
        "buffer_size": 10,
        "total_chars": 10,
    },
}

OUTPUTS = {
    "bg_0_1111": "ready in 231 ms\nlistening on 5173",
    "bg_1_2222": "14 passed\n2 skipped",
    "bg_3_4444": "still compiling",
}


class _PanelApp(App):
    CSS = """
    #background-commands-panel { width: 80%; height: 70%; }
    #bg-command-tabs { height: 2; }
    #bg-command-line { height: 1; }
    #bg-command-output { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield BackgroundCommandsPanel(id="background-commands-panel")


def _log_text(panel: BackgroundCommandsPanel) -> str:
    log = panel.query_one("#bg-command-output", RichLog)
    return "\n".join(getattr(line, "text", str(line)) for line in log.lines)


def _tab_ids(panel: BackgroundCommandsPanel):
    tabs = panel.query_one("#bg-command-tabs", Tabs)
    return [tab.id for tab in tabs.query(Tab)]


async def _run_panel_checks():
    app = _PanelApp()

    with (
        patch.object(
            BackgroundCommandManager,
            "list_background_commands",
            return_value=COMMANDS,
        ),
        patch.object(
            BackgroundCommandManager,
            "get_command_output",
            side_effect=lambda key: OUTPUTS.get(key, ""),
        ),
        patch.object(
            BackgroundCommandManager,
            "get_new_command_output",
            side_effect=AssertionError("panel must not consume agent output"),
        ),
    ):
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#background-commands-panel", BackgroundCommandsPanel)
            panel.refresh_data()
            await pilot.pause()

            assert _tab_ids(panel) == ["bg_0_1111", "bg_1_2222", "bg_3_4444"]

            tabs = panel.query_one("#bg-command-tabs", Tabs)
            log = panel.query_one("#bg-command-output", RichLog)
            assert tabs.region.height == 2
            assert log.region.height > 2

            command_line = panel.query_one("#bg-command-line", Static)
            assert "npm run dev" in str(command_line.render())

            assert panel.border_title == "background commands (3)"
            assert panel._active_key == "bg_0_1111"
            assert "listening on 5173" in _log_text(panel)

            tabs = panel.query_one("#bg-command-tabs", Tabs)
            tabs.active = "bg_1_2222"
            await pilot.pause()

            assert panel._active_key == "bg_1_2222"
            assert "2 skipped" in _log_text(panel)

            panel.action_toggle_follow()
            await pilot.pause()
            assert panel._follow is False

            tabs.active = "bg_0_1111"
            await pilot.pause()
            assert panel._rendered_signature == (40, 40)

            panel.refresh_data()
            await pilot.pause()
            assert "listening on 5173" in _log_text(panel)

            tabs.active = "bg_3_4444"
            await pilot.pause()

            assert panel._active_key == "bg_3_4444"
            assert "timeout-tool" in str(command_line.render())
            assert "timed out, still running" in str(command_line.render())
            assert "still compiling" in _log_text(panel)


def test_background_commands_panel_tabs_output_and_follow():
    asyncio.run(_run_panel_checks())


def test_background_commands_panel_empty_state():
    app = _PanelApp()

    with patch.object(
        BackgroundCommandManager,
        "list_background_commands",
        return_value={},
    ):

        async def run():
            async with app.run_test(size=(120, 40)) as pilot:
                panel = app.query_one("#background-commands-panel", BackgroundCommandsPanel)
                panel.refresh_data()
                await pilot.pause()

                assert panel.border_title == "background commands"
                assert _tab_ids(panel) == []
                assert panel.query_one("#bg-command-empty").display is True

        asyncio.run(run())


def test_open_command_registration_and_completions():
    from cecli.commands.utils.registry import CommandRegistry

    assert CommandRegistry.get_command("open") is OpenCommand
    assert OpenCommand.SUBCOMMANDS == ("commands", "todo")
    assert OpenCommand.get_completions(None, None, "tod") == ["todo"]
    assert OpenCommand.get_completions(None, None, "com") == ["commands"]


def test_open_command_routes_to_tui():
    calls = []

    class FakeTui:
        def call_from_thread(self, callback, *args):
            callback(*args)

        def open_panel(self, name):
            calls.append(name)

    io = SimpleNamespace(tool_output=lambda *a, **k: None, tool_error=lambda *a, **k: None)
    coder = SimpleNamespace(tui=lambda: FakeTui())

    asyncio.run(OpenCommand.execute(io, coder, "commands"))
    asyncio.run(OpenCommand.execute(io, coder, ""))
    asyncio.run(OpenCommand.execute(io, coder, "todo"))

    assert calls == ["commands", "commands", "todo"]


def test_tui_panel_open_and_close_wiring():
    from cecli.tui.app import TUI

    assert TUI.PANELS["commands"] == "#background-commands-panel"

    panel = SimpleNamespace(
        display=False,
        refresh_data=lambda: setattr(panel, "refreshed", True),
        focus_panel=lambda: setattr(panel, "focused", True),
        refreshed=False,
        focused=False,
    )
    input_area = SimpleNamespace(focus=lambda: setattr(input_area, "focused", True), focused=False)
    tui = object.__new__(TUI)
    tui.query_one = lambda selector, *args: {
        "#background-commands-panel": panel,
        "#input": input_area,
    }[selector]
    tui.call_after_refresh = lambda *args, **kwargs: None
    tui._position_panel = lambda panel=None: setattr(tui, "positioned", True)

    TUI.open_panel(tui, "commands")

    assert panel.display is True
    assert panel.refreshed is True
    assert panel.focused is True
    assert tui.positioned is True

    TUI.action_close_panel(tui)

    assert panel.display is False
    assert input_area.focused is True


def test_tab_underline_patch_removes_track():
    from textual.widgets._tabs import Underline

    from cecli.tui.app import TUI  # noqa: F401  (applies the underline render patch)

    assert Underline.render.__name__ == "render_without_track"

    async def run():
        app = _PanelApp()

        with (
            patch.object(
                BackgroundCommandManager,
                "list_background_commands",
                return_value=COMMANDS,
            ),
            patch.object(
                BackgroundCommandManager,
                "get_command_output",
                return_value="line",
            ),
        ):
            async with app.run_test(size=(120, 40)) as pilot:
                panel = app.query_one("#background-commands-panel", BackgroundCommandsPanel)
                panel.refresh_data()
                panel.query_one("#bg-command-tabs", Tabs).focus()
                await pilot.pause()
                await pilot.pause()

                underline = panel.query_one("#bg-command-tabs", Tabs).query_one(Underline)
                rendered = underline.render()

                assert rendered.background_style.color.is_default

    asyncio.run(run())


def test_tui_panel_cycle_binding_and_action():
    from cecli.tui.app import TUI

    tui = object.__new__(TUI)
    tui.args = SimpleNamespace(tui_config=None)
    config = tui._get_config()

    assert config["key_bindings"]["panel_cycle"] == "alt+o"
    assert hasattr(TUI, "action_cycle_panel")

    first = SimpleNamespace(display=False)
    second = SimpleNamespace(display=False)
    tui.PANELS = {"commands": "#first-panel", "other": "#second-panel"}
    tui.query_one = lambda selector, *args: {
        "#first-panel": first,
        "#second-panel": second,
    }[selector]

    opened = []
    closed = []
    tui.open_panel = lambda name: opened.append(name)
    tui.action_close_panel = lambda: closed.append(True)

    TUI.action_cycle_panel(tui)
    assert opened == ["commands"]

    first.display = True
    TUI.action_cycle_panel(tui)
    assert opened == ["commands", "other"]

    first.display = False
    second.display = True
    TUI.action_cycle_panel(tui)
    assert opened == ["commands", "other"]
    assert closed == [True]


def test_open_command_without_tui():
    messages = []
    io = SimpleNamespace(
        tool_output=messages.append,
        tool_error=lambda *a, **k: None,
    )
    coder = SimpleNamespace(tui=None)

    asyncio.run(OpenCommand.execute(io, coder, "commands"))

    assert messages == ["/open commands is only available in the TUI."]


def test_background_commands_panel_adds_tabs_incrementally():
    """A command appearing after the initial render must not duplicate tab IDs."""
    app = _PanelApp()
    commands = {"bg_0_1111": COMMANDS["bg_0_1111"]}

    with (
        patch.object(
            BackgroundCommandManager,
            "list_background_commands",
            side_effect=lambda: dict(commands),
        ),
        patch.object(
            BackgroundCommandManager,
            "get_command_output",
            side_effect=lambda key: OUTPUTS.get(key, ""),
        ),
        patch.object(
            BackgroundCommandManager,
            "get_new_command_output",
            side_effect=AssertionError("panel must not consume agent output"),
        ),
    ):

        async def run():
            async with app.run_test(size=(120, 40)) as pilot:
                panel = app.query_one("#background-commands-panel", BackgroundCommandsPanel)
                panel.refresh_data()
                await pilot.pause()

                assert _tab_ids(panel) == ["bg_0_1111"]

                commands["bg_3_4444"] = COMMANDS["bg_3_4444"]
                panel.refresh_data()
                await pilot.pause()

                assert _tab_ids(panel) == ["bg_0_1111", "bg_3_4444"]

        asyncio.run(run())
