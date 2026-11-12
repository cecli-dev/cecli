import asyncio
from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import RichLog

from cecli.commands.btw import BtwCommand
from cecli.helpers.asides import Asides, add_aside, get_aside, get_asides
from cecli.tui.widgets.btw_panel import BtwPanel


def _log_text(panel: BtwPanel) -> str:
    log = panel.query_one("#btw-output", RichLog)
    return "\n".join(getattr(line, "text", str(line)) for line in log.lines)


class _BtwApp(App):
    CSS = """
    #btw-panel { width: 80%; height: 70%; }
    #btw-output { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield BtwPanel(id="btw-panel")


def test_asides_append_only():
    start = len(get_asides())
    first = add_aside("first question", "first answer")
    second = add_aside("second question", "second answer")

    assert get_asides()[start:] == [first, second]
    assert first["prompt"] == "first question"
    assert first["response"] == "first answer"
    assert get_aside(start) is first
    assert get_aside(-1) is second
    assert list(Asides.get_instance()) == get_asides()


def test_btw_command_uses_full_context_and_opens_panel():
    calls = {}

    class FakeModel:
        async def simple_send_with_retries(self, messages):
            calls["messages"] = messages
            return "the answer", None

    class FakeTui:
        def call_from_thread(self, callback, *args):
            callback(*args)

        def open_panel(self, name):
            calls["panel"] = name

    coder = SimpleNamespace(
        main_model=FakeModel(),
        tui=lambda: FakeTui(),
        format_chat_chunks=lambda: [{"role": "system", "content": "system prompt"}],
    )
    messages = []
    io = SimpleNamespace(
        tool_output=messages.append,
        tool_error=lambda *a, **k: None,
    )

    result = asyncio.run(BtwCommand.execute(io, coder, "what is this?"))

    assert result == "the answer"
    assert calls["messages"][:-1] == [{"role": "system", "content": "system prompt"}]
    assert calls["messages"][-1] == {"role": "user", "content": "what is this?"}
    assert calls["panel"] == "asides"
    assert get_asides()[-1]["prompt"] == "what is this?"
    assert get_asides()[-1]["response"] == "the answer"
    assert messages == []


def test_btw_command_requires_a_question():
    errors = []
    coder = SimpleNamespace(main_model=object(), tui=None)
    io = SimpleNamespace(
        tool_output=lambda *a, **k: None,
        tool_error=errors.append,
    )

    assert asyncio.run(BtwCommand.execute(io, coder, "   ")) is None
    assert errors == ["Usage: /btw [-n|--no-context] <question>"]


def test_btw_command_no_context_flag():
    calls = {}

    class FakeModel:
        async def simple_send_with_retries(self, messages):
            calls["messages"] = messages
            return "isolated answer", None

    def fail_format():
        raise AssertionError("no-context mode must not format chat context")

    coder = SimpleNamespace(
        main_model=FakeModel(),
        tui=None,
        format_chat_chunks=fail_format,
    )
    output = []
    io = SimpleNamespace(tool_output=output.append, tool_error=lambda *a, **k: None)

    assert asyncio.run(BtwCommand.execute(io, coder, "-n what is this?")) == "isolated answer"
    assert calls["messages"][-1] == {"role": "user", "content": "what is this?"}
    assert [message["role"] for message in calls["messages"]] == ["system", "user"]
    assert output == ["isolated answer"]


def test_btw_panel_shows_latest_and_navigates():
    start = len(get_asides())
    add_aside("older question", "older answer")
    add_aside("newer question", "newer answer")
    app = _BtwApp()

    async def run():
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#btw-panel", BtwPanel)
            panel.display = True
            panel.refresh_data()
            await pilot.pause()

            assert panel.border_title == f"asides {start + 2} of {start + 2}"
            log_text = _log_text(panel)
            assert "Prompt: newer question" in log_text
            assert "-----" in log_text
            assert "Answer: newer answer" in log_text

            panel.action_previous_aside()
            await pilot.pause()

            assert panel.border_title == f"asides {start + 1} of {start + 2}"
            log_text = _log_text(panel)
            assert "Prompt: older question" in log_text
            assert "Answer: older answer" in log_text

            panel.action_next_aside()
            await pilot.pause()

            assert "Prompt: newer question" in _log_text(panel)
            assert "Answer: newer answer" in _log_text(panel)


def test_tui_handle_btw_command_schedules_immediately():
    from cecli.tui.app import TUI

    calls = {}
    opened = []

    class FakeModel:
        async def simple_send_with_retries(self, messages):
            calls["messages"] = messages
            return "immediate answer", None

    class FakeTui:
        def call_from_thread(self, callback, *args):
            callback(*args)

        def open_panel(self, name):
            opened.append(name)

    coder = SimpleNamespace(
        main_model=FakeModel(),
        tui=lambda: FakeTui(),
        format_chat_chunks=lambda: [{"role": "system", "content": "system"}],
        io=SimpleNamespace(tool_output=lambda *a, **k: None, tool_error=lambda *a, **k: None),
    )

    class FakeLoop:
        def __init__(self):
            self.tasks = []

        def call_soon_threadsafe(self, callback):
            callback()

        def create_task(self, coro):
            self.tasks.append(coro)

    loop = FakeLoop()
    input_area = SimpleNamespace(
        value="typed",
        saved=[],
        save_to_history=lambda text: input_area.saved.append(text),
    )
    echoes = []
    tui = object.__new__(TUI)
    tui.worker = SimpleNamespace(coder=coder, loop=loop)
    tui.query_one = lambda selector, *args: input_area
    tui.show_error = lambda message: calls.setdefault("error", message)
    tui.add_user_message = echoes.append
    tui._get_visible_coder = lambda: coder

    tui._handle_btw_command("/btw while generating", "/btw while generating")

    assert input_area.value == ""
    assert input_area.saved == ["/btw while generating"]
    assert echoes == ["/btw while generating"]
    assert len(loop.tasks) == 1

    asyncio.run(loop.tasks[0])

    assert opened == ["asides"]
    assert calls["messages"][-1] == {"role": "user", "content": "while generating"}


def test_overlay_shortcuts_and_subtitles():
    from textual.widgets import Static

    from cecli.tui.widgets.overlay import refresh_overlay_subtitles

    class ShortcutApp(App):
        CSS = "#btw-panel { width: 80%; height: 70%; }"
        PANELS = {
            "commands": "#commands-panel",
            "plans": "#plans-panel",
            "asides": "#btw-panel",
        }

        def __init__(self):
            super().__init__()
            self.opened = []

        def compose(self) -> ComposeResult:
            yield Static("commands", id="commands-panel")
            yield Static("plans", id="plans-panel")
            yield BtwPanel(id="btw-panel")

        def open_panel(self, name):
            self.opened.append(name)

    async def run():
        app = ShortcutApp()

        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#btw-panel", BtwPanel)
            panel.display = True
            panel.focus()
            refresh_overlay_subtitles(app)

            subtitle = "commands (shift+1) • plans (shift+2) • asides (shift+3)"
            assert panel.border_subtitle == subtitle
            assert app.query_one("#commands-panel").border_subtitle == subtitle
            assert app.query_one("#plans-panel").border_subtitle == subtitle

            await pilot.press("shift+1")
            await pilot.press("shift+2")
            await pilot.press("shift+3")

            assert app.opened == ["commands", "plans", "asides"]

    asyncio.run(run())
