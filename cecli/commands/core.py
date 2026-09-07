import asyncio
import weakref
from pathlib import Path

from cecli.commands.utils.registry import CommandRegistry
from cecli.helpers import plugin_manager
from cecli.helpers.threading import ThreadSafeEvent
from cecli.signals import SwitchCoderSignal


class Commands:
    scraper = None

    def __init__(
        self,
        io,
        coder,
        voice_language=None,
        voice_input_device=None,
        voice_format=None,
        verify_ssl=True,
        args=None,
        parser=None,
        verbose=False,
        editor=None,
        original_read_only_fnames=None,
    ):
        self.io = io
        self.coder = weakref.proxy(coder) if coder else None
        self.args = args
        self.parser = parser
        self.voice_language = voice_language
        self.voice_input_device = voice_input_device
        self.voice_format = voice_format
        self.verify_ssl = verify_ssl
        self.verbose = verbose
        self.editor = editor
        self.original_read_only_fnames = original_read_only_fnames

        self.cmd_running_event = ThreadSafeEvent()
        self.cmd_running_event.set()
        self.last_command_show_notification = True

        # Prompt queue for CLI-33: in-memory FIFO queue
        self.prompt_queue = []
        self._queue_counter = 0
        self._queue_lock = asyncio.Lock()
        self._processing_queue = False

        # Commands that should NOT trigger auto-processing of the queue
        self._MANAGEMENT_COMMANDS = {"queue", "list-queue", "remove-queue", "insert-queue"}

    # ── Queue Management Methods (CLI-33) ────────────────────────────── #
    #
    # The prompt queue itself lives on the coder (Coder.prompt_queue) and
    # is managed by cecli.helpers.command_queue. These thin wrappers keep
    # the /queue, /list-queue and /remove-queue command implementations
    # stable while operating on the coder that owns this Commands
    # instance, so each sub-agent's commands manage that sub-agent's own
    # queue.

    def _active_coder(self):
        """Resolve the coder queue commands should target.

        Prefers the foreground (sub-agent) coder via
        ``command_queue.get_active_coder``, falling back to ``self.coder``
        when no active coder can be resolved (e.g. no AgentService, or the
        Commands instance is constructed without a coder in tests).
        """
        from cecli.helpers import command_queue

        return command_queue.get_active_coder(self.coder) or self.coder

    def _enqueue_prompt(self, text: str) -> dict:
        """Add a prompt to the active (foreground) coder's queue."""
        from cecli.helpers import command_queue

        return command_queue.enqueue_prompt(self._active_coder(), text)

    async def _process_queued_prompts(self, preproc):
        """Process all queued prompts (FIFO) once the current message completes.

        Runs each queued prompt through ``run_one`` so it is sent to the LLM
        exactly like a user-typed prompt. A single failing queued prompt is
        logged and does not stop the remaining ones (``SwitchCoderSignal`` and
        ``ReloadProgramSignal`` are BaseExceptions and propagate unchanged).
        """
        if self._processing_queue:
            return
        self._processing_queue = True
        try:
            while True:
                item = self._dequeue_prompt()
                if item is None:
                    break
                text = item["text"]
                preview = text if len(text) <= 80 else text[:80] + "..."
                self.io.tool_output(f"Processing queued prompt: {preview}")
                try:
                    await self.coder.run_one(text, preproc)
                except Exception as e:
                    self.io.tool_error(f"Error processing queued prompt: {e}")
        finally:
            self._processing_queue = False

    def _insert_prompt(self, text: str, index: int) -> dict:
        """Insert a prompt at the given index in the active coder's queue."""
        from cecli.helpers import command_queue

        return command_queue.insert_prompt(self._active_coder(), text, index)

    def _dequeue_prompt(self) -> dict | None:
        """Remove and return the first item from the active coder's queue."""
        from cecli.helpers import command_queue

        return command_queue.dequeue_prompt(self._active_coder())

    def _get_queue_length(self) -> int:
        """Return the current number of items in the active coder's queue."""
        from cecli.helpers import command_queue

        return command_queue.get_queue_length(self._active_coder())

    def _remove_from_queue(self, index: int) -> dict | None:
        """Remove and return the item at the given index from the active coder's queue."""
        from cecli.helpers import command_queue

        return command_queue.remove_from_queue(self._active_coder(), index)

    def _clear_queue(self) -> list:
        """Remove all items from the active coder's queue and return them."""
        from cecli.helpers import command_queue

        return command_queue.clear_queue(self._active_coder())

    def _load_custom_commands(self, custom_commands):
        """
        Load custom commands from plugin paths.

        Args:
            custom_commands: List of file or directory paths to load custom commands from.
                             If None or empty, no custom commands are loaded.
        """
        if not custom_commands:
            return

        for path_str in custom_commands:
            path = Path(path_str)
            try:
                if path.is_dir():
                    # Find all Python files in the directory
                    for py_file in path.glob("*.py"):
                        self._load_command_from_file(py_file)
                else:
                    # If it's a file, try to load it directly
                    if path.exists() and path.suffix == ".py":
                        self._load_command_from_file(path)
            except Exception as e:
                # Log error but continue with other paths
                if self.io:
                    self.io.tool_error(f"Error loading custom commands from {path}: {e}")

    def _load_command_from_file(self, file_path):
        """
        Load a command class from a Python file.

        Args:
            file_path: Path to the Python file to load.
        """
        try:
            # Load the module using plugin_manager
            module = plugin_manager.load_module(str(file_path))

            # Look for a class named exactly "CustomCommand" in the module
            if hasattr(module, "CustomCommand"):
                command_class = getattr(module, "CustomCommand")
                if isinstance(command_class, type):
                    # Register the command class
                    CommandRegistry.register(command_class)
                    if self.io and self.verbose:
                        self.io.tool_output(f"Registered custom command: {command_class.NORM_NAME}")

        except Exception as e:
            # Log error but continue with other files
            if self.io:
                self.io.tool_error(f"Error loading command from {file_path}: {e}")

    def is_command(self, inp):
        return inp[0] in "/!"

    def is_run_command(self, inp):
        return inp and (
            inp[0] in "!" or inp[:5] == "/lint" or inp[:5] == "/test" or inp[:4] == "/run"
        )

    def is_test_command(self, inp):
        return inp and (inp[:5] == "/lint" or inp[:5] == "/test")

    def get_raw_completions(self, cmd):
        assert cmd.startswith("/")
        cmd = cmd[1:]
        cmd = cmd.replace("-", "_")
        raw_completer = getattr(self, f"completions_raw_{cmd}", None)
        return raw_completer

    def get_completions(self, cmd, args="", coder=None):
        assert cmd.startswith("/")
        cmd = cmd[1:]
        command_class = CommandRegistry.get_command(cmd)
        if command_class:
            return command_class.get_completions(self.io, coder or self.coder, args)
        return []

    def get_commands(self):
        registry_commands = CommandRegistry.list_commands()
        commands = [f"/{cmd}" for cmd in registry_commands]
        return sorted(commands)

    async def execute(self, cmd_name, args, coder=None, **kwargs):
        from cecli.repo import ANY_GIT_ERROR

        active_coder = coder or self.coder
        command_class = CommandRegistry.get_command(cmd_name)

        if not command_class:
            active_coder.io.tool_output(f"Error: Command {cmd_name} not found.")
            return

        self.last_command_show_notification = command_class.show_completion_notification
        if cmd_name not in self._MANAGEMENT_COMMANDS:
            self.cmd_running_event.clear()

        try:
            kwargs.update(
                {
                    "original_read_only_fnames": self.original_read_only_fnames,
                    "voice_language": self.voice_language,
                    "voice_format": self.voice_format,
                    "voice_input_device": self.voice_input_device,
                    "verify_ssl": self.verify_ssl,
                    "parser": self.parser,
                    "verbose": self.verbose,
                    "editor": self.editor,
                    "system_args": self.args,
                }
            )
            return await CommandRegistry.execute(
                cmd_name, active_coder.io, active_coder, args, **kwargs
            )
        except ANY_GIT_ERROR as err:
            active_coder.io.tool_error(f"Unable to complete {cmd_name}: {err}")
            return
        except SwitchCoderSignal as e:
            raise e
        except Exception as e:
            active_coder.io.tool_error(f"Error executing command {cmd_name}: {str(e)}")
            return
        finally:
            self.cmd_running_event.set()
            if self.coder.tui and self.coder.tui():
                self.coder.tui().refresh()
            # NEW: Queue processing integration
            if (
                self.coder.prompt_queue
                and cmd_name not in self._MANAGEMENT_COMMANDS
                and not self.coder._processing_queue
            ):
                await self.coder._drain_prompt_queue(kwargs.get("preproc", True))
