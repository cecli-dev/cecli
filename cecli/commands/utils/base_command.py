from abc import ABC, ABCMeta, abstractmethod
from typing import List


class CommandMeta(ABCMeta):
    """Metaclass for validating command classes at definition time."""

    def __new__(mcs, name, bases, namespace):
        # Create the class first
        cls = super().__new__(mcs, name, bases, namespace)

        # Skip validation for BaseCommand itself
        if name == "BaseCommand":
            return cls

        if not name.endswith("Command"):
            raise TypeError(f"Command class must end with 'Command', got '{name}'")

        if getattr(cls, "NORM_NAME", None) is None:
            raise TypeError("Command class must define NORM_NAME")

        if getattr(cls, "DESCRIPTION", None) is None:
            raise TypeError("Command class must define DESCRIPTION")

        if "execute" not in namespace:
            raise TypeError("Command class must implement execute method")

        return cls


class BaseCommand(ABC, metaclass=CommandMeta):
    """Abstract base class for all commands."""

    # Class properties (similar to BaseTool)
    NORM_NAME = None  # Normalized command name (e.g., "add", "model")
    DESCRIPTION = None  # Command description for help
    SCHEMA = None  # Optional schema for parameter validation

    @classmethod
    @abstractmethod
    async def execute(cls, io, coder, args, **kwargs):
        """
        Execute the command with given parameters.

        Args:
            io: InputOutput instance
            coder: Coder instance (may be None for some commands)
            args: Command arguments as string
            **kwargs: Additional context (original args, etc.)

        Returns:
            Optional result (most commands return None)
        """
        pass

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """
        Get completion options for this command.

        Args:
            io: InputOutput instance
            coder: Coder instance
            args: Partial arguments for completion

        Returns:
            List of completion strings
        """
        return []

    @classmethod
    def process_command(cls, io, coder, args, **kwargs):
        """
        Process command with validation and error handling.
        Similar to BaseTool.process_response().
        """
        # Validate parameters if SCHEMA is defined
        if cls.SCHEMA:
            # Parameter validation logic
            pass

        try:
            return cls.execute(io, coder, args, **kwargs)
        except Exception as e:
            # Centralized error handling
            return cls.handle_error(io, e)

    @classmethod
    def handle_error(cls, io, error):
        """Centralized error handling for commands."""
        io.tool_error(f"Error in command {cls.NORM_NAME}: {str(error)}")
        return None

    @classmethod
    def get_help(cls) -> str:
        """
        Get help text for this command.

        Returns:
            String containing help text for the command
        """
        help_text = f"Command: /{cls.NORM_NAME}\n"
        help_text += f"Description: {cls.DESCRIPTION}\n"

        if cls.SCHEMA:
            help_text += "\nParameters:\n"
            # Add parameter documentation based on SCHEMA
            # This could be expanded to parse the schema and provide detailed parameter info

        return help_text

    @classmethod
    async def _generic_chat_command(cls, io, coder, args, edit_format, placeholder=None):
        """
        Generic implementation for chat mode switching commands.

        This method handles the common pattern for commands that switch to a specific
        chat mode (ask, code, architect, agent). When called without arguments,
        it switches to the specified mode. When called with arguments, it creates
        a temporary coder in that mode, processes the message, and returns to the
        original mode.
        """
        if not args.strip():
            # Switch to the corresponding chat mode
            from cecli.commands import SwitchCoderSignal

            raise SwitchCoderSignal(edit_format=edit_format)

        from cecli.coders.base_coder import Coder

        user_msg = args

        original_main_model = coder.main_model
        original_edit_format = coder.edit_format
        kwargs = {
            "io": coder.io,
            "from_coder": coder,
            "edit_format": edit_format,
            "summarize_from_coder": False,
            "num_cache_warming_pings": 0,
            "coder_commit_hashes": coder.coder_commit_hashes,
            "args": coder.args,
        }

        new_coder = await Coder.create(**kwargs)

        await new_coder.generate(user_message=user_msg, preproc=False)
        coder.coder_commit_hashes = new_coder.coder_commit_hashes

        from cecli.commands import SwitchCoderSignal

        raise SwitchCoderSignal(
            main_model=original_main_model,
            edit_format=original_edit_format,
            done_messages=new_coder.done_messages,
            cur_messages=new_coder.cur_messages,
        )
