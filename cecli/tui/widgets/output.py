"""Output widget for cecli TUI using Textual's RichLog widget."""

import re
import textwrap

from rich.markdown import Markdown
from rich.padding import Padding
from rich.style import Style as RichStyle
from rich.text import Text
from textual import events, on
from textual.message import Message
from textual.widgets import RichLog


class CostUpdate(Message):
    """Message to update cost in footer."""

    def __init__(self, cost: float):
        self.cost = cost
        super().__init__()


class OutputContainer(RichLog):
    """Scrollable output area using RichLog widget for rich rendering.

    Uses Textual's RichLog widget for efficient streaming and display
    of LLM responses and system messages.
    """

    DEFAULT_CSS = """
    OutputContainer {
        scrollbar-gutter: stable;
        background: $surface;
        padding: 0 0;
    }
    """

    _last_write_type = None
    _write_history = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Line buffer for streaming text to avoid word-per-line issue
        self._line_buffer = ""
        # Track if we're on the first line of the current response
        self._first_line_of_response = True

        # Enable markup for rich formatting
        self.highlight = True
        self.markup = True
        self.wrap = True

    async def start_response(self):
        """Start a new LLM response section with streaming support."""
        # Clear the line buffer for new response
        self._line_buffer = ""
        # Reset first line flag
        self._first_line_of_response = True

    def _wrap_text_with_prefix(self, text: str, prefix: str = "• ") -> str:
        """Wrap text with prefix and proper indentation.

        Args:
            text: The text to wrap
            prefix: The prefix to use for the first line

        Returns:
            Wrapped text with prefix and indentation
        """
        if not text.strip():
            return ""

        # Get available width for wrapping
        # Subtract 2 to account for potential borders or scrollbars
        width = self.content_size.width - 2 if self.content_size.width else 80
        indent = " " * len(prefix)

        # Wrap the text using textwrap
        wrapped_text = textwrap.fill(
            text, width=width, initial_indent=prefix, subsequent_indent=indent
        )

        return wrapped_text

    async def stream_chunk(self, text: str):
        """Stream a chunk of markdown text."""
        if not text:
            return

        # Check for cost updates in the text
        self._check_cost(text)

        # Add text to line buffer
        self._line_buffer += text

        # Process complete lines from buffer
        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            if line.rstrip():
                self.set_last_write_type("assistant")
                # Format with prefix on first line, proper indentation on subsequent lines
                if self._first_line_of_response:
                    wrapped_line = self._wrap_text_with_prefix(line.rstrip(), prefix="• ")
                    self._first_line_of_response = False
                else:
                    # For subsequent lines, we need to wrap with proper indentation
                    # but without the bullet prefix
                    wrapped_line = self._wrap_text_with_prefix(line.rstrip(), prefix="  ")

                # Output each wrapped line
                for wrapped in wrapped_line.split("\n"):
                    if wrapped.strip():
                        self.output(wrapped, render_markdown=True)

    async def end_response(self):
        """End the current LLM response."""
        await self._stop_stream()

    async def _stop_stream(self):
        """Stop the current markdown stream."""
        # Flush any remaining buffer content
        if self._line_buffer.rstrip():
            # Format remaining content based on whether it's first line or not
            if self._first_line_of_response:
                wrapped_line = self._wrap_text_with_prefix(self._line_buffer.rstrip(), prefix="• ")
            else:
                wrapped_line = self._wrap_text_with_prefix(self._line_buffer.rstrip(), prefix="  ")

            # Output each wrapped line
            for wrapped in wrapped_line.split("\n"):
                if wrapped.strip():
                    self.output(wrapped, render_markdown=True)
            self._line_buffer = ""

    def add_user_message(self, text: str):
        """Add a user message (displayed differently from LLM output)."""
        # User messages shown with > prefix in green color
        self.auto_scroll = True
        self.set_last_write_type("user")

        # Wrap the entire user message with "> " prefix
        wrapped_text = self._wrap_text_with_prefix(text, prefix="> ")

        # Output each wrapped line with green styling
        for line in wrapped_text.split("\n"):
            if line.strip():
                self.output(f"[bold medium_spring_green]{line}[/bold medium_spring_green]")

        self.scroll_end(animate=False)

    def add_system_message(self, text: str, dim=True):
        """Add a system/tool message."""
        if not text.strip():
            return

        # Escape any Rich markup brackets
        text = text.removesuffix("\n")
        start = ""
        end = ""
        # Write system message in secondary color
        if dim:
            start = "[dim]"
            end = "[/dim]"
            text = Padding(f"{start}{text}{end}", (0, 0, 0, 2))

        self.set_last_write_type("system")
        self.output(text)

    def add_output(self, text: str, task_id: str = None, dim=True):
        """Add output text as a system message.

        This handles tool output, status messages, etc.
        LLM streaming is handled separately via start_response/stream_chunk/end_response.
        """
        if not text:
            return

        # Check for cost updates
        self._check_cost(text)

        # Always treat add_output as system messages
        # LLM streaming goes through the dedicated stream_chunk path
        self.add_system_message(text, dim=dim)

    def add_output_styled(self, text: str, styles=None):
        if not styles:
            styles = dict()

        style = RichStyle(**styles)
        with self.app.console.capture() as capture:
            self.app.console.print(Text(text), style=style)
        capture_text = capture.get()

        self.output(Padding(capture_text, (0, 0, 0, 2)))

    def add_tool_call(self, lines: list):
        """Add a tool call with themed styling.

        Args:
            lines: List of lines from the tool call (header, arguments, etc.)
        """
        if not lines:
            return

        self.set_last_write_type("tool_call")
        for i, line in enumerate(lines):
            # Strip Rich markup
            clean_line = line.replace("[bright_cyan]", "").replace("[/bright_cyan]", "")

            if i == 0:
                # First line: reformat "Tool Call: server • function" to "Tool Call · server · function"
                clean_line = clean_line.replace("Tool Call:", "Tool Call •")
                self.output(Padding(Text(clean_line, style="dim bright_cyan"), (0, 0, 0, 2)))
            else:
                # Subsequent lines (arguments) - prefix with corner to show they belong to the call
                arg_string_list = re.split(r"(^\S+:)", clean_line, maxsplit=1)[1:]

                if len(arg_string_list) > 1:
                    tool_property = arg_string_list[0].replace("_", " ").title()
                    content = Text()
                    content.append(f"ᴸ{tool_property}", style="dim bright_cyan")
                    content.append(arg_string_list[1], style="dim")
                    self.output(Padding(content, (0, 0, 0, 2)))
                else:
                    self.output(Padding(Text(clean_line, style="dim"), (0, 0, 0, 3)))

            # self.set_last_write_type("tool_call")
            # self.output(Padding(content, (0, 0, 0, 2)))

    def add_tool_result(self, text: str):
        """Add a tool result.

        Args:
            text: The tool result text
        """
        if not text:
            return

        clean_text = text.strip()

        result = Text()
        result.append(clean_text, style="dim")

        self.set_last_write_type("tool_result")
        self.output(Padding(result, (0, 0, 0, 1)))

    def _check_cost(self, text: str):
        """Extract and emit cost updates."""
        match = re.search(r"\$(\d+\.?\d*)\s*session", text)
        if match:
            try:
                self.post_message(CostUpdate(float(match.group(1))))
            except (ValueError, AttributeError):
                pass

    def start_task(self, task_id: str, title: str, task_type: str = "general"):
        """Start a new task section."""
        self.set_last_write_type(f"{task_id}-{title}-{task_type}")

    def clear_output(self):
        """Clear all output."""
        self._line_buffer = ""
        self.clear()

    def set_last_write_type(self, type):
        if type and self._last_write_type and self._last_write_type != type:
            self.output("")

        self._last_write_type = type

    def output(self, text, check_duplicates=True, render_markdown=False):
        """Write output with duplicate newline checking.

        Args:
            text: The text to write
            check_duplicates: If True, check for duplicate newlines before writing
            render_markdown: If True and app config allows, render as markdown
        """
        # Check if we should render as markdown
        if render_markdown and hasattr(self.app, "render_markdown") and self.app.render_markdown:
            # Only render string content as markdown
            if isinstance(text, str):
                text = Markdown(text)

        with self.app.console.capture() as capture:
            self.app.console.print(text)
        check = Text(capture.get()).plain

        # self.write(str(self._write_history))
        # self.write(repr(check))

        # Check for duplicate newlines

        if check_duplicates and len(self._write_history) >= 2:
            nl_check = check in ["", "\n", "\\n"]
            nl_last = self._write_history[-1] in ["", "\n", "\\n"]
            nl_penultimate = self._write_history[-2] in ["", "\n", "\\n"] or self._write_history[
                -2
            ].endswith("\n")

            if nl_check and nl_last and nl_penultimate:
                return

        # Call the actual write method
        self.write(text)

        # Log the write
        self._write_history.append(check)

        # Keep history size manageable
        if len(self._write_history) > 5:
            self._write_history.pop(0)

    @on(events.Print)
    def log_print(self, event: events.Print) -> None:
        """Writes the captured print output to the RichLog widget."""
        if event.text.strip():
            theme_vars = self.app.get_css_variables()
            color = theme_vars.get("warning")
            write_type = "stdout"

            if event.stderr:
                color = theme_vars.get("error")
                write_type = "stderr"

            self.set_last_write_type(write_type)
            self.add_output_styled(event.text.removesuffix("\n"), {"color": color})

        # Prevent the event from bubbling further
        event.prevent_default()

    @on(events.MouseScrollUp)
    def disable_auto_scroll(self, event: events.MouseScrollUp) -> None:
        """
        Event handler called when the screen is scrolled up.
        Disables automatic scrolling
        """
        self.auto_scroll = False

    @on(events.MouseScrollDown)
    def enable_auto_scroll(self, event: events.MouseScrollDown) -> None:
        """
        Event handler called when the screen is scrolled down.
        Enables automatic scrolling if we are near the end
        """

        # Calculate the relevant dimensions
        scroll_top = self.scroll_y
        view_height = self.size.height
        content_height = self.content_size.height

        # Check if scrolled to the bottom (allowing for minor floating point inaccuracies)
        if scroll_top + view_height >= content_height - 32:
            self.auto_scroll = True
