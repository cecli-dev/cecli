"""Main Textual application for cecli TUI."""

import concurrent.futures
import json
import queue
import time
from functools import lru_cache
from pathlib import Path

import textual.strip
from rich.color import ColorSystem
from rich.style import Style
from textual import events
from textual.app import App, ComposeResult

# from textual.binding import Binding
from textual.theme import Theme

from cecli.editor import pipe_editor
from cecli.io import CommandCompletionException

from .widgets import (
    CompletionBar,
    FileList,
    InputArea,
    InputContainer,
    KeyHints,
    MainFooter,
    OutputContainer,
    StatusBar,
)
from .widgets.output import CostUpdate


class TUI(App):
    """Main Textual application for cecli TUI."""

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        # Binding("ctrl+c", "quit", "Quit", show=True),
        # Binding("ctrl+l", "clear_output", "Clear", show=True),
        # Binding("escape", "interrupt", "Interrupt", show=True),
    ]

    def __init__(self, coder_worker, output_queue, input_queue, args):
        """Initialize the cecli TUI app."""
        super().__init__()
        self.worker = coder_worker
        self.output_queue = output_queue
        self.input_queue = input_queue
        self.args = args  # Store args for _get_config
        # Cache for code symbols (functions, classes, variables)
        self._symbols_cache = None
        self._symbols_files_hash = None
        self._mouse_hold_timer = None
        self._currently_generating = False

        self.tui_config = self._get_config()

        # Register and set cecli theme using config colors
        colors = self.tui_config.get("colors", {})
        other = self.tui_config.get("other", {})
        BASE_THEME = Theme(
            name="cecli",
            primary=colors.get("primary", "#00ff5f"),
            secondary=colors.get("secondary", "#888888"),
            accent=colors.get("accent", "#00ff87"),  # Cecli green
            foreground=colors.get("foreground", "#ffffff"),
            background=colors.get("background", "#1e1e1e"),
            success=colors.get("success", "#00aa00"),
            warning=colors.get("warning", "#ffd700"),
            error=colors.get("error", "#ff3333"),
            surface=colors.get("surface", "transparent"),  # Slightly lighter than background
            panel=colors.get("panel", "transparent"),
            dark=other.get("dark", True),
            variables={
                "input-cursor-foreground": colors.get("input-cursor-foreground", "#00ff87"),
                "input-cursor-text-style": other.get("input-cursor-text-style", "underline"),
            },
        )

        if other.get("use_terminal_background", True):
            patch_textual_strip_render_with_cache()

        self.bind(
            self._encode_keys(self.get_keys_for("newline")),
            "noop",
            description="New Line",
            show=True,
        )
        self.bind(
            self._encode_keys(self.get_keys_for("submit")), "noop", description="Submit", show=True
        )
        self.bind(
            self._encode_keys(self.get_keys_for("cycle_forward")),
            "noop",
            description="Cycle Forward",
            show=True,
        )
        self.bind(
            self._encode_keys(self.get_keys_for("cycle_backward")),
            "noop",
            description="Cycle Backward",
            show=True,
        )
        self.bind(
            self._encode_keys(self.get_keys_for("cancel")), "noop", description="Cancel", show=True
        )
        self.bind(
            self._encode_keys(self.get_keys_for("editor")),
            "open_editor",
            description="Editor",
            show=True,
        )
        self.bind(
            self._encode_keys(self.get_keys_for("history")),
            "history_search",
            description="History Search",
            show=True,
        )
        self.bind(
            self._encode_keys(self.get_keys_for("focus")),
            "focus_input",
            description="Focus Input",
            show=True,
        )
        self.bind(
            self._encode_keys(self.get_keys_for("stop")),
            "interrupt",
            description="Interrupt",
            show=True,
        )
        self.bind(
            self._encode_keys(self.get_keys_for("clear")),
            "clear_output",
            description="Clear",
            show=True,
        )
        self.bind(
            self._encode_keys(self.get_keys_for("quit")), "quit", description="Quit", show=True
        )

        self.register_theme(BASE_THEME)
        self.theme = "cecli"

    @property
    def render_markdown(self):
        """Return whether markdown rendering is enabled."""
        return self.tui_config.get("other", {}).get("render_markdown", True)

    def _get_config(self):
        """
        Parse and return TUI configuration from args.tui_config.

        Returns:
            dict: TUI configuration with defaults for missing values
        """
        config = {}

        # Check if tui_config is provided via args
        if (
            hasattr(self, "args")
            and self.args
            and hasattr(self.args, "tui_config")
            and self.args.tui_config
        ):
            try:
                config = json.loads(self.args.tui_config)
            except (json.JSONDecodeError, TypeError) as e:
                # Can't use self.io here since it doesn't exist yet
                # The error will be handled elsewhere if needed
                print(f"Warning: Failed to parse tui-config JSON: {e}")
                # Continue with empty config, will apply defaults below

        # Ensure config has a colors entry with nested structure matching BASE_THEME
        if "banner" not in config:
            config["banner"] = True

        if "colors" not in config:
            config["colors"] = {}

        if "other" not in config:
            config["other"] = {}

        if "key_bindings" not in config:
            config["key_bindings"] = {}

        # Ensure colors dict has all expected keys with default values
        default_colors = {
            "primary": "#00ff5f",
            "secondary": "#888888",
            "accent": "#00ff87",
            "foreground": "#ffffff",
            "background": "#1e1e1e",
            "success": "#00aa00",
            "warning": "#ffd700",
            "error": "#ff3333",
            "surface": "transparent",
            "panel": "transparent",
            "dark": True,
            "variables": {
                "input-cursor-foreground": "#00ff87",
                "input-cursor-text-style": "underline",
            },
        }

        default_key_bindings = {
            "newline": "shift+enter",
            "submit": "enter",
            "stop": "escape",
            "cycle_forward": "tab",
            "cycle_backward": "shift+tab",
            "input_start": "ctrl+home",
            "input_end": "ctrl+end",
            "output_up": "shift+pageup",
            "output_down": "shift+pagedown",
            "editor": "ctrl+o",
            "history": "ctrl+r",
            "focus": "ctrl+f",
            "cancel": "ctrl+c",
            "clear": "ctrl+l",
            "quit": "ctrl+q",
        }

        # Default settings for the "other" section
        default_other = {
            "render_markdown": False,
            "use_terminal_background": False,
        }

        # Merge default other settings with user-provided settings
        for key, default_value in default_other.items():
            if key not in config["other"]:
                config["other"][key] = default_value

        # Merge default colors with user-provided colors
        for key, default_value in default_colors.items():
            if key not in config["colors"]:
                config["colors"][key] = default_value
            elif key == "variables" and isinstance(default_value, dict):
                # Handle nested variables dict
                if "variables" not in config["colors"]:
                    config["colors"]["variables"] = {}
                for var_key, var_default in default_value.items():
                    if var_key not in config["colors"]["variables"]:
                        config["colors"]["variables"][var_key] = var_default

        for key, default_value in default_key_bindings.items():
            if key not in config["key_bindings"]:
                config["key_bindings"][key] = self._encode_keys(default_value)

        for key, value in config["key_bindings"].items():
            config["key_bindings"][key] = self._encode_keys(value)

        return config

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        coder = self.worker.coder
        model_name = coder.main_model.name if coder.main_model else "Unknown"
        coder_mode = getattr(coder, "edit_format", "code") or "code"

        # Get project name (just the folder name, not full path)
        home = str(Path.home())
        cwd = str(Path.cwd())
        if cwd.startswith(home):
            project_name = cwd.replace(home, "~", 1)
        else:
            project_name = cwd

        if len(project_name) >= 64:
            project_name = project_name.split("/")[-1]

        if coder.repo:
            root_path = str(coder.repo.root)
            if root_path.startswith(home):
                root_path = root_path.replace(home, "~", 1)

            if len(root_path) <= 64:
                project_name = root_path
            else:
                project_name = root_path.split("/")[-1]
        # Get history file path from coder's io
        history_file = getattr(coder.io, "input_history_file", None)

        # Simple vertical layout - no header, footer has all info
        # Git info loaded in on_mount to avoid blocking startup
        yield OutputContainer(id="output")
        yield StatusBar(id="status-bar")
        yield InputContainer(
            InputArea(history_file=history_file, id="input"),
            FileList(id="file-list", classes="empty"),
            id="input-container",
            coder_mode=coder_mode,
        )
        yield KeyHints(id="key-hints")
        yield MainFooter(
            model_name=model_name,
            project_name=project_name,
            git_branch="",  # Loaded async in on_mount
            coder_mode=coder_mode,
            id="footer",
        )

    BANNER_COLORS = [
        "spring_green2",
        "spring_green1",
        "medium_spring_green",
        "cyan2",
        "cyan1",
        "bright_white",
    ]

    # ASCII banner for startup
    BANNER = f"""
[bold {BANNER_COLORS[0]}]   ▒▒▒▒▒▒╗▒▒▒▒▒▒▒╗ ▒▒▒▒▒▒╗▒▒╗     ▒▒╗[/bold {BANNER_COLORS[0]}]
[bold {BANNER_COLORS[1]}]  ▒▒╔════╝▒▒╔════╝▒▒╔════╝▒▒║     ▒▒║[/bold {BANNER_COLORS[1]}]
[bold {BANNER_COLORS[2]}]  ▒▒║     ▒▒▒▒▒╗  ▒▒║     ▒▒║     ▒▒║[/bold {BANNER_COLORS[2]}]
[bold {BANNER_COLORS[3]}]  ▒▒║     ▒▒╔══╝  ▒▒║     ▒▒║     ▒▒║[/bold {BANNER_COLORS[3]}]
[bold {BANNER_COLORS[4]}]  ╚▒▒▒▒▒▒╗▒▒▒▒▒▒▒╗╚▒▒▒▒▒▒╗▒▒▒▒▒▒▒╗▒▒║[/bold {BANNER_COLORS[4]}]
[bold {BANNER_COLORS[5]}]   ╚═════╝╚══════╝ ╚═════╝╚══════╝╚═╝[/bold {BANNER_COLORS[5]}]

"""

    def on_mount(self):
        """Called when app starts."""
        # Show startup banner
        output_container = self.query_one("#output", OutputContainer)
        if self.tui_config["banner"]:
            output_container.add_output(self.BANNER, dim=False)
        else:
            output_container.add_output(
                f"[bold {self.BANNER_COLORS[0]}] [/bold {self.BANNER_COLORS[0]}]", dim=False
            )

        self.begin_capture_print(output_container, stdout=True, stderr=True)

        self.set_interval(0.05, self.check_output_queue)
        self.worker.start()
        self.query_one("#input").focus()

        # Initialize key hints
        self.update_key_hints()

        # Load git info in background to avoid blocking startup
        self.call_later(self._load_git_info)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """Handle mouse down events to start the selection hint timer."""
        if self._mouse_hold_timer:
            self._mouse_hold_timer.stop()
        self._mouse_hold_timer = self.set_timer(0.25, self._show_select_hint)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        """Handle mouse up events to clear the selection hint timer."""
        if self._mouse_hold_timer:
            self._mouse_hold_timer.stop()
            self._mouse_hold_timer = None
        self.update_key_hints(generating=self._currently_generating)

    def _show_select_hint(self) -> None:
        """Show the shift+drag to select hint."""
        try:
            hints = self.query_one(KeyHints)
            hints.update_right("shift+drag to select")
        except Exception:
            pass

    def update_key_hints(self, generating=False):
        """Update the key hints below the input area."""
        if self._mouse_hold_timer:
            self._mouse_hold_timer.stop()
            self._mouse_hold_timer = None
        try:
            hints = self.query_one(KeyHints)
            if generating:
                self._currently_generating = True
                stop = self.app.get_keys_for("stop")
                hints.update_right(f"{stop} to cancel")
            else:
                self._currently_generating = False
                submit = self.app.get_keys_for("submit")
                hints.update_right(f"{submit} to submit")
        except Exception:
            pass

    def update_key_hints_left(self, text: str):
        """Update the left sub-panel message."""
        try:
            hints = self.query_one(KeyHints)
            hints.update_left(text)
        except Exception:
            pass

    def update_cost(self, cost_text: str):
        """Update the cost display in the input container's border subtitle."""
        try:
            container = self.query_one(InputContainer)
            container.update_cost(cost_text)
        except Exception:
            pass

    def _update_key_hints_for_commands(self, text: str, is_completion: bool = False):
        """
        Update key hints left area with command description.

        Handles both regular input text and completion suggestions.

        Args:
            text: The text to analyze (input text or completion suggestion)
            is_completion: Whether this is a completion suggestion (default: False)
        """
        # Check if text starts with slash
        if text.startswith("/"):
            # Extract command name
            # For completions, we just need to remove the leading slash
            # For regular input, we need to extract the first word after slash
            if is_completion:
                # Completion suggestion like "/help" - just remove leading slash
                cmd_name = text[1:].strip()
            else:
                # Regular input like "/help arg1 arg2" - extract first word
                parts = text[1:].strip().split()
                cmd_name = parts[0] if parts else ""

            # Get command description if we have a command name
            if cmd_name:
                try:
                    from cecli.commands.utils.registry import CommandRegistry

                    description = CommandRegistry.get_command_description(cmd_name)
                    if description:
                        self.update_key_hints_left(f"{description}")
                        return
                except Exception:
                    pass

        # If not a valid slash command, show default text
        self.update_key_hints_left(KeyHints.DEFAULT_LEFT_TEXT)

    def _load_git_info(self):
        """Load git branch and dirty count (deferred to avoid blocking startup)."""
        footer = self.query_one(MainFooter)
        if self.worker.coder.repo:
            try:
                branch = self.worker.coder.repo.repo.active_branch.name or "main"
                dirty = self.worker.coder.repo.get_dirty_files()
                footer.update_git(branch, len(dirty) if dirty else 0)
            except Exception:
                if self.worker.coder.repo:
                    footer.update_git("main", 0)
                else:
                    footer.update_git("No Repo", 0)

    def check_output_queue(self):
        """Process messages from coder worker."""
        try:
            while True:
                msg = self.output_queue.get_nowait()
                self.handle_output_message(msg)
        except queue.Empty:
            pass

    def handle_output_message(self, msg):
        """Route output messages to appropriate handlers."""
        msg_type = msg["type"]

        if msg_type == "output":
            self.add_output(msg["text"], msg.get("task_id"))
        elif msg_type == "tool_call":
            # Render tool call with styled panel
            output_container = self.query_one("#output", OutputContainer)
            output_container.add_tool_call(msg["lines"])
        elif msg_type == "tool_result":
            # Render tool result with connector prefix
            output_container = self.query_one("#output", OutputContainer)
            output_container.add_tool_result(msg["text"])
        elif msg_type == "start_response":
            # Start a new LLM response with streaming
            self.run_worker(self._start_response())
        elif msg_type == "stream_chunk":
            # Stream a chunk of LLM response
            self.run_worker(self._stream_chunk(msg["text"]))
        elif msg_type == "end_response":
            # End the current LLM response
            self.run_worker(self._end_response())
        elif msg_type == "start_task":
            self.start_task(msg["task_id"], msg["title"], msg.get("task_type"))
        elif msg_type == "confirmation":
            self.show_confirmation(msg)
        elif msg_type == "spinner":
            self.update_spinner(msg)
        elif msg_type == "ready_for_input":
            self.enable_input(msg)
            footer = self.query_one(MainFooter)
            footer.stop_spinner()
        elif msg_type == "error":
            self.show_error(msg["message"])
        elif msg_type == "cost_update":
            footer = self.query_one(MainFooter)
            footer.update_cost(msg.get("cost", 0))
        elif msg_type == "exit":
            # Graceful exit requested - let Textual clean up terminal properly
            self.action_quit()
        elif msg_type == "mode_change":
            # Update footer with new chat mode
            container = footer = self.query_one(InputContainer)
            container.update_mode(msg.get("mode", "code"))

            footer = self.query_one(MainFooter)
            footer.update_mode(msg.get("mode", "code"))

    def add_output(self, text, task_id=None):
        """Add output to the output container."""
        output_container = self.query_one("#output", OutputContainer)
        output_container.add_output(text, task_id)

    async def _start_response(self):
        """Start a new LLM response (async helper)."""
        output_container = self.query_one("#output", OutputContainer)
        await output_container.start_response()

    async def _stream_chunk(self, text: str):
        """Stream a chunk to the current response (async helper)."""
        output_container = self.query_one("#output", OutputContainer)
        await output_container.stream_chunk(text)

    async def _end_response(self):
        """End the current LLM response (async helper)."""
        output_container = self.query_one("#output", OutputContainer)
        await output_container.end_response()

    def add_user_message(self, text: str):
        """Add a user message to output."""
        output_container = self.query_one("#output", OutputContainer)
        output_container.add_user_message(text)

    def start_task(self, task_id, title, task_type="general"):
        """Start a new task section."""
        output_container = self.query_one("#output", OutputContainer)
        output_container.start_task(task_id, title, task_type)

    def show_confirmation(self, msg):
        """Show inline confirmation bar."""
        # Disable input while confirm bar is active
        input_area = self.query_one("#input", InputArea)
        input_area.disabled = True

        # Show confirmation in status bar with all options
        status_bar = self.query_one("#status-bar", StatusBar)
        options = msg.get("options", {})

        # Determine which options to show based on the parameters
        show_all = options.get("group") is not None or options.get("group_response") is not None
        allow_tweak = options.get("allow_tweak", False)
        allow_never = options.get("allow_never", False)

        status_bar.show_confirm(
            msg["question"],
            show_all=show_all,
            allow_tweak=allow_tweak,
            allow_never=allow_never,
            default=options.get("default", "y"),
            explicit_yes_required=options.get("explicit_yes_required", False),
        )

    def enable_input(self, msg):
        """Enable input and update autocomplete data."""
        self.update_key_hints(generating=False)
        input_area = self.query_one("#input", InputArea)
        input_area.disabled = False  # Ensure input is enabled
        files = msg.get("files", [])
        commands = msg.get("commands", [])
        input_area.update_autocomplete_data(files, commands)

        # Update file list
        file_list = self.query_one("#file-list", FileList)
        file_list.update_files(msg.get("chat_files", {}))

        input_area.focus()

    def update_spinner(self, msg):
        """Update spinner in footer."""
        footer = self.query_one(MainFooter)
        action = msg.get("action", "start")

        if action == "start":
            footer.start_spinner(msg.get("text", ""))
        elif action == "update":
            footer.spinner_text = msg.get("text", "")
        elif action == "update_suffix":
            footer.spinner_suffix = msg.get("text", "")
        elif action == "stop":
            footer.stop_spinner()

    def show_error(self, message):
        """Show error notification."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.show_notification(f"Error: {message}", severity="error", timeout=10)

    def on_resize(self) -> None:
        file_list = self.query_one("#file-list", FileList)
        file_list.update_files(file_list.chat_files)

    def on_input_area_text_changed(self, message: InputArea.TextChanged):
        """Handle text changes in input area."""
        self._update_key_hints_for_commands(message.text, is_completion=False)

    def on_input_area_submit(self, message: InputArea.Submit):
        """Handle input submission."""
        user_input = message.value

        if not user_input.strip():
            return

        # Intercept /editor and /edit commands to handle with TUI suspension
        stripped = user_input.strip()
        if (
            stripped in ("/editor", "/edit")
            or stripped.startswith("/editor ")
            or stripped.startswith("/edit ")
        ):
            # Extract initial content if provided (e.g., "/editor some text")
            initial_content = ""
            if stripped.startswith("/editor "):
                initial_content = stripped[8:]
            elif stripped.startswith("/edit "):
                initial_content = stripped[6:]

            # Clear input and open editor with suspend
            input_area = self.query_one("#input", InputArea)
            input_area.value = ""
            self._open_editor_suspended(initial_content)
            return

        # Save to history before clearing
        input_area = self.query_one("#input", InputArea)
        input_area.save_to_history(user_input)

        input_area.value = ""

        # Show user's message in output
        self.add_user_message(user_input)

        # Update footer to show processing
        footer = self.query_one(MainFooter)
        footer.start_spinner("Processing...")

        coder = self.worker.coder

        if coder:
            coder.io.start_spinner("Processing...")

        if coder and self._currently_generating:
            from cecli.helpers.conversation import ConversationService, MessageTag

            ConversationService.get_manager(coder).add_message(
                message_dict=dict(role="user", content=coder.wrap_user_input(user_input)),
                tag=MessageTag.CUR,
                hash_key=("user_message", user_input, str(time.monotonic_ns())),
                promotion=ConversationService.get_manager(coder).DEFAULT_TAG_PROMOTION_VALUE,
                mark_for_demotion=1,
            )
        else:
            self.update_key_hints(generating=True)
            self.input_queue.put({"text": user_input})

    def set_input_value(self, text) -> None:
        """Find the input widget and set focus to it."""
        input_area = self.query_one("#input", InputArea)
        input_area.value = text
        input_area.cursor_position = len(input_area.value)

    def action_focus_input(self) -> None:
        """Find the input widget and set focus to it."""
        input_area = self.query_one("#input", InputArea)
        input_area.focus()

    def action_clear_output(self):
        """Clear all output."""
        output_container = self.query_one("#output", OutputContainer)
        output_container.clear_output()
        if self.tui_config["banner"]:
            output_container.add_output(self.BANNER, dim=False)
        else:
            output_container.add_output(
                f"[bold {self.BANNER_COLORS[0]}] [/bold {self.BANNER_COLORS[0]}]", dim=False
            )

        self.worker.coder.show_announcements()

    def action_output_up(self):
        """Scroll the output area up one page."""
        output_container = self.query_one("#output", OutputContainer)
        output_container.action_page_up()

    def action_output_down(self):
        """Scroll the output area down one page."""
        output_container = self.query_one("#output", OutputContainer)
        output_container.action_page_down()

    def action_interrupt(self):
        """Interrupt the current task."""
        if self.worker:
            self.worker.interrupt()
            # Notify user
            try:
                status_bar = self.query_one("#status-bar", StatusBar)
                status_bar.show_notification("Interrupting...", severity="warning", timeout=3)
            except Exception:
                pass

    def action_quit(self):
        """Quit the application."""
        # Prevent multiple quit attempts
        if hasattr(self, "_quitting") and self._quitting:
            return
        self._quitting = True

        # Show shutdown message
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.show_notification("Shutting down...", severity="warning", timeout=None)

        # Delay exit to allow status bar to render
        self.set_timer(0.3, self._do_quit)

    def action_noop(self):
        pass

    def action_history_search(self):
        """Open an external editor to compose a prompt (keyboard shortcut)."""
        # Get current input text to use as initial content
        input_area = self.query_one("#input", InputArea)
        input_area.post_message(input_area.Submit("/history-search"))

    def action_open_editor(self):
        """Open an external editor to compose a prompt (keyboard shortcut)."""
        # Get current input text to use as initial content
        input_area = self.query_one("#input", InputArea)
        current_text = input_area.value
        self._open_editor_suspended(current_text)

    def _open_editor_suspended(self, initial_content=""):
        """Open an external editor with proper TUI suspension.

        Args:
            initial_content: Initial text to populate the editor with
        """
        # Get editor from coder's commands or default
        editor = getattr(self.worker.coder.commands, "editor", None)

        # Suspend TUI and open editor
        with self.suspend():
            edited_text = pipe_editor(initial_content, suffix="md", editor=editor)

        # Set the edited text back to input
        input_area = self.query_one("#input", InputArea)
        if edited_text and edited_text.strip():
            input_area.value = edited_text.rstrip()
            input_area.focus()

            # Show notification
            try:
                status_bar = self.query_one("#status-bar", StatusBar)
                status_bar.show_notification(
                    "Editor content loaded", severity="information", timeout=2
                )
            except Exception:
                pass
        else:
            input_area.focus()

        return edited_text

    def get_response_from_editor(self, initial_content=""):
        """Open an external editor with proper TUI suspension.

        Args:
            initial_content: Initial text to populate the editor with

        Returns:
            Edited text
        """
        # Get editor from coder's commands or default
        editor = getattr(self.worker.coder.commands, "editor", None)

        # Suspend TUI and open editor
        input_area = self.query_one("#input", InputArea)
        edited_text = ""
        edited_text = self.run_obstructive(pipe_editor, initial_content, suffix="md", editor=editor)
        input_area.focus()

        return edited_text.rstrip()

    def _encode_keys(self, key):
        key = key.replace("shift+enter", "ctrl+j")

        return key

    def _decode_keys(self, key):
        key = key.replace("ctrl+j", "shift+enter")

        return key

    def is_key_for(self, type, key):
        allowed_keys = self.tui_config["key_bindings"][type].split(",")
        if key in allowed_keys:
            return True

        return False

    def get_keys_for(self, type):
        allowed_keys = self.tui_config["key_bindings"][type]
        return self._decode_keys(allowed_keys)

    def _do_quit(self):
        """Perform the actual quit after UI updates."""
        self.worker.stop()
        self.exit()

    def run_obstructive(self, func, *args, **kwargs):
        """Run a function with the TUI suspended, called from a worker thread."""
        future = concurrent.futures.Future()

        def wrapper():
            try:
                with self.suspend():
                    result = func(*args, **kwargs)
                    future.set_result(result)
            except Exception as e:
                future.set_exception(e)

        self.call_from_thread(wrapper)
        return future.result()

    def on_cost_update(self, message: CostUpdate):
        """Handle cost update from output."""
        footer = self.query_one(MainFooter)
        footer.cost = message.cost
        footer.refresh()

    def on_status_bar_confirm_response(self, message: StatusBar.ConfirmResponse):
        """Handle confirmation response from status bar."""
        # Re-enable input
        input_area = self.query_one("#input", InputArea)
        input_area.disabled = False
        input_area.focus()

        self.input_queue.put({"confirmed": message.result})

    # Commands that use path-based completion
    PATH_COMPLETION_COMMANDS = {"/add", "/read-only", "/read-only-stub", "/rules", "/load", "/save"}

    def _extract_symbols(self) -> set[str]:
        """Extract code symbols from files in chat using Pygments."""
        coder = self.worker.coder

        # Get current files in chat
        inchat_files = []
        if hasattr(coder, "abs_fnames"):
            inchat_files.extend(coder.abs_fnames)
        if hasattr(coder, "abs_read_only_fnames"):
            inchat_files.extend(coder.abs_read_only_fnames)

        # Check if cache is still valid
        files_hash = hash(tuple(sorted(inchat_files)))
        if self._symbols_cache is not None and self._symbols_files_hash == files_hash:
            return self._symbols_cache

        symbols = set()

        # Also add filenames as completable symbols
        if hasattr(coder, "get_inchat_relative_files"):
            symbols.update(coder.get_inchat_relative_files())
        if hasattr(coder, "get_all_relative_files"):
            # Add all project files too
            symbols.update(coder.get_all_relative_files())

        # Limit files to tokenize for performance
        files_to_process = inchat_files[:30]

        try:
            from pygments.lexers import guess_lexer_for_filename
            from pygments.token import Token
        except ImportError:
            # Pygments not available, just return filenames
            self._symbols_cache = symbols
            self._symbols_files_hash = files_hash
            return symbols

        for fname in files_to_process:
            try:
                with open(fname, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                lexer = guess_lexer_for_filename(fname, content)
                tokens = lexer.get_tokens(content)

                for token_type, token_value in tokens:
                    # Extract identifiers (function names, class names, variables)
                    if token_type in Token.Name and len(token_value) > 1:
                        symbols.add(token_value)
            except Exception:
                continue

        self._symbols_cache = symbols
        self._symbols_files_hash = files_hash
        return symbols

    def _get_symbol_completions(self, prefix: str) -> list[str]:
        """Get symbol completions for @ mentions."""
        symbols = self._extract_symbols()
        prefix_lower = prefix.lower()

        if prefix:
            matches = [s for s in symbols if prefix_lower in s.lower()]
        else:
            matches = list(symbols)

        return sorted(matches)[:50]

    def _get_path_completions(self, prefix: str) -> list[str]:
        """Get filesystem path completions relative to coder root."""
        coder = self.worker.coder
        root = Path(coder.root) if hasattr(coder, "root") else Path.cwd()

        # Handle the prefix - could be partial path like "src/ma" or just "ma"
        if "/" in prefix:
            # Has directory component
            dir_part, file_part = prefix.rsplit("/", 1)
            search_dir = root / dir_part
            search_prefix = file_part.lower()
            path_prefix = dir_part + "/"
        else:
            search_dir = root
            search_prefix = prefix.lower()
            path_prefix = ""

        completions = []
        try:
            if search_dir.exists() and search_dir.is_dir():
                for entry in search_dir.iterdir():
                    name = entry.name
                    if search_prefix and search_prefix not in name.lower():
                        continue
                    # Add trailing slash for directories
                    if entry.is_dir():
                        completions.append(path_prefix + name + "/")
                    else:
                        completions.append(path_prefix + name)
        except (PermissionError, OSError):
            pass

        return sorted(completions)

    def _get_suggestions(self, text: str) -> list[str]:
        """Get completion suggestions for given text."""
        suggestions = []
        commands = self.worker.coder.commands

        # Only return early for non-commands ending with space
        # For commands, we want to allow completion with empty string partial
        if len(text) and text[-1] == " " and not text.startswith("/"):
            return

        if "@" in text:
            # Symbol completion triggered by @
            # Find the @ and get the prefix after it
            at_index = text.rfind("@")
            prefix = text[at_index + 1 :]
            suggestions = self._get_symbol_completions(prefix)
        elif text.startswith("/"):
            # Command completion
            parts = text.split(maxsplit=1)
            cmd_part = parts[0]

            if len(parts) == 1 and not text.endswith(" "):
                # Complete command name
                all_commands = commands.get_commands()
                if cmd_part == "/":
                    suggestions = all_commands
                else:
                    # First get commands that start with the prefix
                    starts_with = [c for c in all_commands if c.startswith(cmd_part)]
                    # Then get commands that contain the prefix anywhere (excluding those already matched)
                    contains = [
                        c for c in all_commands if cmd_part[1:] in c and not c.startswith(cmd_part)
                    ]

                    suggestions = starts_with + contains
            else:
                # Complete command argument
                # This handles both:
                # 1. len(parts) > 1: command with arguments
                # 2. len(parts) == 1 and text.endswith(" "): command with trailing space
                cmd_name = cmd_part

                if text.endswith(" "):
                    # Command with trailing space, empty argument prefix
                    arg_prefix = ""
                else:
                    # Get the last word as argument prefix
                    end_lookup = text.rsplit(maxsplit=1)
                    arg_prefix = end_lookup[-1]

                arg_prefix_lower = arg_prefix.lower()

                # Check if this command needs path-based completion
                if cmd_name in self.PATH_COMPLETION_COMMANDS:
                    suggestions = self._get_path_completions(arg_prefix)
                    # For /read-only and /read-only-stub, also include add completions
                    if cmd_name in {"/add", "/read-only", "/read-only-stub"}:
                        try:
                            add_completions = commands.get_completions(cmd_name) or []
                            for c in add_completions:
                                if arg_prefix_lower in str(c).lower() and str(c) not in suggestions:
                                    suggestions.append(str(c))
                        except Exception:
                            pass
                else:
                    # Use standard command completions (no file fallback)
                    try:
                        cmd_completions = commands.get_completions(cmd_name)
                        if cmd_completions:
                            if arg_prefix:
                                suggestions = [
                                    c for c in cmd_completions if arg_prefix_lower in str(c).lower()
                                ]
                            else:
                                suggestions = list(cmd_completions)
                    except Exception:
                        pass
        else:
            # Check if last contiguous, no-space separated string contains a forward slash
            # This allows path completions even without a leading slash
            words = text.rsplit(maxsplit=1)

            if words:
                last_word = words[-1]
                if "/" in last_word:
                    # Provide path completions for the partial path
                    suggestions = self._get_symbol_completions(last_word)

        return [str(s) for s in suggestions[:50]]

    def _get_completed_text(self, current_text: str, completion: str) -> str:
        """Calculate the new text after applying completion."""
        if current_text.startswith("/"):
            parts = current_text.rsplit(maxsplit=1)

            # Check if we have a command with trailing space
            # This is when we want to insert argument completions after the space
            if len(parts) == 1 and current_text.endswith(" "):
                # Command with trailing space, insert completion after space
                return current_text + completion
            elif len(parts) == 1:
                # Replace entire command (command name completion)
                # Only add space if command takes arguments
                commands = self.worker.coder.commands
                try:
                    cmd_completions = commands.get_completions(completion)
                    has_completions = cmd_completions is not None
                except Exception as e:
                    # Check if it's a CommandCompletionException
                    if isinstance(e, CommandCompletionException):
                        # For CommandCompletionException, treat it as having completions
                        # so we add a space after the command
                        has_completions = True
                    else:
                        # For other exceptions, assume no completions
                        has_completions = False

                if has_completions:
                    return completion + " "
                else:
                    return completion
            else:
                # Replace argument
                return parts[0] + " " + completion
        elif "@" in current_text:
            # Replace from @ onwards with the symbol
            at_index = current_text.rfind("@")
            return current_text[:at_index] + completion + " "
        else:
            # Replace last word with completion
            words = current_text.rsplit(maxsplit=1)
            if len(words) > 1:
                return words[0] + " " + completion
            else:
                return completion

    def on_input_area_completion_requested(self, message: InputArea.CompletionRequested):
        """Handle completion request - show or update completion bar."""
        input_area = self.query_one("#input", InputArea)
        text = message.text
        suggestions = self._get_suggestions(text)

        # Check if completion bar already exists
        existing_bar = None
        try:
            existing_bar = self.query_one("#completion-bar", CompletionBar)
        except Exception:
            pass

        if suggestions:
            input_area.completion_active = True
            if existing_bar:
                # Update existing bar in place
                existing_bar.update_suggestions(suggestions, text)
            else:
                # Create new completion bar
                completion_bar = CompletionBar(
                    suggestions=suggestions, prefix=text, id="completion-bar"
                )
                self.mount(completion_bar, before=input_area)

            # Update key hints with description for first suggestion
            if suggestions:
                first_suggestion = suggestions[0]
                self._update_key_hints_for_commands(first_suggestion, is_completion=True)
        else:
            # No suggestions - dismiss if active
            input_area.completion_active = False
            if existing_bar:
                existing_bar.remove()

    def on_input_area_completion_cycle(self, message: InputArea.CompletionCycle):
        """Handle Tab to cycle through completions."""
        try:
            completion_bar = self.query_one("#completion-bar", CompletionBar)
            completion_bar.cycle_next()
            selected = completion_bar.current_selection
            if selected:
                input_area = self.query_one("#input", InputArea)
                # Use completion_prefix as base
                base_text = input_area.completion_prefix
                new_text = self._get_completed_text(base_text, selected)
                input_area.set_completion_preview(new_text)
                # Update key hints with command description for selected completion
                self._update_key_hints_for_commands(selected, is_completion=True)
        except Exception:
            pass

    def on_input_area_completion_cycle_previous(self, message: InputArea.CompletionCyclePrevious):
        """Handle Tab to cycle through completions."""
        try:
            completion_bar = self.query_one("#completion-bar", CompletionBar)
            completion_bar.cycle_previous()
            selected = completion_bar.current_selection
            if selected:
                input_area = self.query_one("#input", InputArea)
                # Use completion_prefix as base
                base_text = input_area.completion_prefix
                new_text = self._get_completed_text(base_text, selected)
                input_area.set_completion_preview(new_text)
                # Update key hints with command description for selected completion
                self._update_key_hints_for_commands(selected, is_completion=True)
        except Exception:
            pass

    def on_input_area_completion_accept(self, message: InputArea.CompletionAccept):
        """Handle Enter to accept current completion."""
        try:
            completion_bar = self.query_one("#completion-bar", CompletionBar)
            completion_bar.select_current()
        except Exception:
            pass
        # Update key hints based on accepted completion
        input_area = self.query_one("#input", InputArea)
        self._update_key_hints_for_commands(input_area.text, is_completion=False)

    def on_input_area_completion_dismiss(self, message: InputArea.CompletionDismiss):
        """Handle Escape to dismiss completions."""
        input_area = self.query_one("#input", InputArea)
        input_area.completion_active = False
        try:
            completion_bar = self.query_one("#completion-bar", CompletionBar)
            completion_bar.dismiss()
        except Exception:
            pass
        # Update key hints back to normal based on current input
        self._update_key_hints_for_commands(input_area.text, is_completion=False)

    def on_completion_bar_selected(self, message: CompletionBar.Selected):
        """Handle completion selection."""
        input_area = self.query_one("#input", InputArea)

        # Use stored prefix as base for completion
        current = input_area.completion_prefix
        selected = message.value

        new_text = self._get_completed_text(current, selected)

        # Reset cycling state so the new value is registered as the new prefix
        input_area._cycling = False
        input_area.value = new_text
        input_area.completion_active = False

        input_area.focus()
        input_area.cursor_position = len(input_area.value)

    def on_completion_bar_dismissed(self, message: CompletionBar.Dismissed):
        """Handle completion bar dismissal."""
        input_area = self.query_one("#input", InputArea)

        # Restore original text if we were cycling
        if input_area._cycling:
            input_area.value = input_area.completion_prefix
            input_area._cycling = False

        input_area.completion_active = False
        input_area.focus()


def patch_textual_strip_render_with_cache():
    # 1. Define the logic
    def modified_render_ansi(cls, style: Style, color_system: ColorSystem) -> str:
        """Modified ANSI generator that ignores background colors."""
        sgr: list[str]
        # Handle Attributes
        if attributes := style._attributes & style._set_attributes:
            _style_map = textual.strip.SGR_STYLES
            sgr = [
                _style_map[bit_offset]
                for bit_offset in range(attributes.bit_length())
                if attributes & (1 << bit_offset)
            ]
        else:
            sgr = []

        # Handle Foreground Color
        if (color := style._color) is not None:
            sgr.extend(color.downgrade(color_system).get_ansi_codes())

        # BACKGROUND OVERRIDE: Skip the bgcolor block entirely

        ansi = style._ansi = ";".join(sgr)
        return ansi

    # 2. Re-apply the EXACT cache settings from the original source
    cached_version = lru_cache(maxsize=16384)(modified_render_ansi)

    # 3. Convert to classmethod and inject
    textual.strip.Strip.render_ansi = classmethod(cached_version)


# Execute the patch
# patch_textual_strip_render_with_cache()
