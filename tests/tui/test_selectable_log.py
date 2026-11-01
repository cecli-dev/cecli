from rich.text import Text
from textual.app import App, ComposeResult

from cecli.tui.widgets.selectable_log import SelectableRichLog


class LogApp(App):
    """Minimal app hosting a SelectableRichLog."""

    CSS = """
    SelectableRichLog { width: 60; height: 8; }
    """

    def __init__(self, **log_kwargs):
        super().__init__()
        self.log_kwargs = log_kwargs

    def compose(self) -> ComposeResult:
        yield SelectableRichLog(id="log", **self.log_kwargs)


class DeferredWriteApp(App):
    """App that writes before the widget size is known."""

    CSS = """
    SelectableRichLog { width: 60; height: 8; }
    """

    def compose(self) -> ComposeResult:
        yield SelectableRichLog(id="log")

    def on_mount(self) -> None:
        log = self.query_one(SelectableRichLog)
        log.write("first")
        log.write("second")


class AutoScrollOffDeferredApp(App):
    """App that defers writes without auto-scrolling."""

    CSS = """
    SelectableRichLog { width: 60; height: 8; }
    """

    def compose(self) -> ComposeResult:
        yield SelectableRichLog(id="log", auto_scroll=False)

    def on_mount(self) -> None:
        log = self.query_one(SelectableRichLog)
        for i in range(30):
            log.write(f"{i:02d}-line")


class MaxLinesApp(App):
    """App hosting a log in stock RichLog max_lines mode."""

    CSS = """
    SelectableRichLog { width: 60; height: 8; }
    """

    def compose(self) -> ComposeResult:
        yield SelectableRichLog(id="log", max_lines=3)


async def test_write_plain_text():
    app = LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        log.write("hello")
        log.write("world")
        await pilot.pause()

        assert log.line_count == 2
        assert log._line_text(0) == "hello"
        assert log._line_text(1) == "world"


async def test_write_styled_text():
    app = LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        log.write(Text("warning", style="bold red"))
        await pilot.pause()

        assert log.line_count == 1
        assert log._line_text(0) == "warning"
        assert log._store.blocks[0].span_styles[0].bold


async def test_write_wrapped_text():
    app = LogApp(wrap=True, min_width=20)
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        content = "y" * 120
        log.write(content)
        await pilot.pause()

        width = log.scrollable_content_region.width
        assert log.line_count > 1
        assert all(len(log._line_text(i)) <= width for i in range(log.line_count))
        assert "".join(log._line_text(i) for i in range(log.line_count)) == content


async def test_select_all_and_get_selected_text():
    app = LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        log.write("one")
        log.write("two")
        log.write("three")
        await pilot.pause()

        log.select_all()

        assert log._select_start == 0
        assert log._select_end == 2
        assert log.get_selected_text() == "one\ntwo\nthree"


async def test_reflow_wraps_text_and_preserves_select_all():
    app = LogApp(wrap=True, min_width=20)
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        _write_wrapped_lines(log, count=10)
        await pilot.pause()
        lines_before = log.line_count
        log.select_all()

        log.styles.width = 40
        await pilot.pause()
        await pilot.pause()

        width = log.scrollable_content_region.width
        assert log.line_count > lines_before
        assert all(len(log._line_text(i)) <= width for i in range(log.line_count))
        assert log._select_start == 0
        assert log._select_end == log.line_count - 1
        selected = log.get_selected_text()
        assert selected is not None
        assert selected.split("\n") == [log._line_text(i).rstrip() for i in range(log.line_count)]


async def test_reflow_remaps_selection_across_blocks():
    app = LogApp(wrap=True, min_width=20)
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        _write_wrapped_lines(log, count=2)
        await pilot.pause()
        assert log._store.blocks[0].line_count == log._store.blocks[1].line_count

        log._select_start = 1
        log._select_end = log._store.blocks[0].line_count + 1

        log.styles.width = 40
        await pilot.pause()
        await pilot.pause()

        block_line_count = log._store.blocks[0].line_count
        assert log._select_start == 1
        assert log._select_end == block_line_count + 1


async def test_reflow_keeps_scroll_pinned_to_end():
    app = LogApp(wrap=True, min_width=20)
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        _write_wrapped_lines(log, count=10)
        await pilot.pause()
        assert log.is_vertical_scroll_end

        log.styles.width = 40
        await pilot.pause()
        await pilot.pause()

        assert log.line_count > 1
        assert log.is_vertical_scroll_end
        assert log.scroll_offset.y == log.max_scroll_y


async def test_reflow_preserves_viewport_when_scrolled():
    app = LogApp(wrap=True, min_width=20)
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        for i in range(40):
            log.write(f"{i:02d}-" + "x" * 25)
        await pilot.pause()

        log.styles.width = 30
        await pilot.pause()
        await pilot.pause()
        log.scroll_to(y=5, animate=False, immediate=True)
        await pilot.pause()

        log.styles.width = 20
        await pilot.pause()
        await pilot.pause()

        assert log.scroll_offset.y > 5
        assert log._line_text(log.scroll_offset.y).startswith("05-")


async def test_deferred_writes_are_flushed_in_order():
    app = DeferredWriteApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        assert log._size_known
        assert log.line_count == 2
        assert [log._line_text(i) for i in range(2)] == ["first", "second"]
        assert len(log._store.blocks) == 2
        assert not log.lines


async def test_deferred_writes_respect_auto_scroll_false():
    app = AutoScrollOffDeferredApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        assert log.line_count == 30
        assert log.scroll_offset.y == 0
        assert not log.is_vertical_scroll_end


async def test_max_lines_falls_back_to_stock_storage():
    app = MaxLinesApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        for text in ["one", "two", "three", "four"]:
            log.write(text)
        await pilot.pause()

        assert log.line_count == 3
        assert [log._line_text(i) for i in range(3)] == ["two", "three", "four"]
        assert log._store.line_count == 0
        assert len(log.lines) == 3

        log.select_all()
        assert log.get_selected_text() == "two\nthree\nfour"
        assert log.copy_selection()
        assert app._clipboard == "two\nthree\nfour"


async def test_reflow_preserves_explicit_width_and_style():
    app = LogApp(wrap=True, min_width=20)
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        log.write(Text("fixed", style="bold red"), width=10)
        log.write("y" * 120)
        await pilot.pause()

        fixed_block = log._store.blocks[0]
        fixed_text = fixed_block.text
        implicit_lines = log._store.blocks[1].line_count

        log.styles.width = 40
        await pilot.pause()
        await pilot.pause()

        assert log._store.blocks[0] is fixed_block
        assert log._store.blocks[0].text == fixed_text
        assert log._store.blocks[1].line_count > implicit_lines

        strip = log.render_line(0)
        assert "".join(segment.text for segment in strip).strip() == "fixed"
        assert any(segment.style is not None and segment.style.bold for segment in strip)


async def test_scrolled_render_uses_absolute_virtual_lines():
    app = LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        for i in range(40):
            log.write(f"{i:02d}-line")
        await pilot.pause()

        log.scroll_to(y=5, animate=False, immediate=True)
        await pilot.pause()

        assert log.scroll_offset.y == 5
        strip = log.render_line(0)
        assert "".join(segment.text for segment in strip).rstrip() == "05-line"


async def test_clear_resets_store_selection_and_drag_state():
    app = LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        log.write("old")
        await pilot.pause()
        log.select_all()
        log._mouse_is_down = True

        log.clear()

        assert log.line_count == 0
        assert not log.has_selection
        assert log._store.line_count == 0
        assert not log.lines
        assert not log._mouse_is_down

        log.write("new")
        await pilot.pause()

        assert log.line_count == 1
        assert log._line_text(0) == "new"


async def test_get_selected_text_copy_returns_text_and_clears_selection():
    app = LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        log.write("one")
        log.write("two")
        log.write("three")
        await pilot.pause()
        log.select_all()

        copied = log.get_selected_text(copy=True)

        assert copied == "one\ntwo\nthree"
        assert app._clipboard == "one\ntwo\nthree"
        assert not log.has_selection


async def test_reflow_pins_to_end_when_width_and_height_shrink_together():
    app = LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        for i in range(40):
            log.write(f"{i:02d}-line")
        await pilot.pause()
        assert log.is_vertical_scroll_end

        log.styles.width = 20
        log.styles.height = 4
        await pilot.pause()
        await pilot.pause()

        assert log.is_vertical_scroll_end
        assert log.scroll_offset.y == log.max_scroll_y


async def test_height_shrink_keeps_scroll_pinned_to_end():
    app = LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one(SelectableRichLog)
        await pilot.pause()

        for i in range(40):
            log.write(f"{i:02d}-line")
        await pilot.pause()
        assert log.is_vertical_scroll_end

        log.styles.height = 2
        await pilot.pause()
        await pilot.pause()

        assert log.is_vertical_scroll_end
        assert log.scroll_offset.y == log.max_scroll_y


def _write_wrapped_lines(log: SelectableRichLog, count: int, length: int = 120) -> None:
    for _ in range(count):
        log.write("x" * length)
