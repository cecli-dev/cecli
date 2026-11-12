import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import RichLog, Static, Tab, Tabs

from cecli.helpers.agents.service import AgentService, SubAgentInfo, SubAgentStatus
from cecli.tui.widgets.todo_panel import TodoPanel

PRIMARY_UUID = "primary-uuid-1234"
SUB_UUID = "sub-uuid-5678abcd"


def _make_coder(coder_uuid, todo_path, todo_text):
    return SimpleNamespace(
        uuid=coder_uuid,
        io=SimpleNamespace(read_text=lambda path: todo_text),
        local_agent_folder=lambda path: str(todo_path),
        abs_root_path=lambda path: str(path),
    )


def _build_app(tmp_path):
    primary_todo = tmp_path / "primary-todo.txt"
    primary_todo.write_text("Done:\n✓ setup\n\nRemaining:\n→ primary task", encoding="utf-8")
    sub_todo = tmp_path / "sub-todo.txt"
    sub_todo.write_text("Remaining:\n→ sub task", encoding="utf-8")

    primary_coder = _make_coder(
        PRIMARY_UUID, primary_todo, primary_todo.read_text(encoding="utf-8")
    )
    sub_coder = _make_coder(SUB_UUID, sub_todo, sub_todo.read_text(encoding="utf-8"))
    info = SubAgentInfo(
        name="worker",
        coder=sub_coder,
        parent_uuid=PRIMARY_UUID,
        status=SubAgentStatus.RUNNING,
    )
    service = SimpleNamespace(sub_agents={SUB_UUID: info})

    class _TodoApp(App):
        CSS = """
        #todo-panel { width: 80%; height: 70%; }
        #todo-tabs { height: 2; }
        #todo-agent-line { height: 1; }
        #todo-output { height: 1fr; }
        """

        def __init__(self):
            super().__init__()
            self.worker = SimpleNamespace(coder=primary_coder)

        def compose(self) -> ComposeResult:
            yield TodoPanel(id="todo-panel")

        def _get_visible_coder(self):
            return sub_coder

    p = patch.object(AgentService, "get_instance", return_value=service)

    return p, _TodoApp()


def _tab_ids(panel):
    return [tab.id for tab in panel.query_one("#todo-tabs", Tabs).query(Tab)]


def _log_text(panel):
    log = panel.query_one("#todo-output", RichLog)

    return "\n".join(getattr(line, "text", str(line)) for line in log.lines)


def test_todo_panel_shows_agents_and_defaults_to_active(tmp_path):
    patcher, app = _build_app(tmp_path)

    with patcher:

        async def run():
            async with app.run_test(size=(120, 40)) as pilot:
                panel = app.query_one("#todo-panel", TodoPanel)
                panel.display = True
                panel.refresh_data()
                await pilot.pause()

                assert _tab_ids(panel) == [PRIMARY_UUID, SUB_UUID]
                labels = [tab.label for tab in panel.query_one("#todo-tabs", Tabs).query(Tab)]
                assert labels == ["primary", "worker sub"]
                assert panel.border_title == "todos (2)"

                # focus_panel selects the agent visible in the TUI
                panel.focus_panel()
                await pilot.pause()

                assert panel._active_key == SUB_UUID
                assert "sub task" in _log_text(panel)
                agent_line = panel.query_one("#todo-agent-line", Static)
                assert "· running" in str(agent_line.render())

                tabs = panel.query_one("#todo-tabs", Tabs)
                tabs.active = PRIMARY_UUID
                await pilot.pause()

                assert panel._active_key == PRIMARY_UUID
                assert "primary task" in _log_text(panel)
                agent_line = panel.query_one("#todo-agent-line", Static)
                assert "·" not in str(agent_line.render())

        asyncio.run(run())


def test_todo_panel_empty_without_coder(tmp_path):
    patcher, app = _build_app(tmp_path)

    with patcher:
        app.worker = None

        async def run():
            async with app.run_test(size=(120, 40)) as pilot:
                panel = app.query_one("#todo-panel", TodoPanel)
                panel.display = True
                panel.refresh_data()
                await pilot.pause()

                assert _tab_ids(panel) == []
                assert panel.border_title == "todos"
                assert panel.query_one("#todo-empty").display is True

        asyncio.run(run())
