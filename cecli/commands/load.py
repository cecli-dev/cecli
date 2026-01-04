from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.commands.utils.save_load_manager import SaveLoadManager


class LoadCommand(BaseCommand):
    NORM_NAME = "load"
    DESCRIPTION = "Load and execute commands from a file"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the load command with given parameters."""
        if not args.strip():
            io.tool_error("Please provide a filename containing commands to load.")
            return format_command_result(io, "load", "No filename provided")

        manager = SaveLoadManager(coder, io)

        try:
            commands = manager.load_commands(args.strip())
        except FileNotFoundError as e:
            io.tool_error(str(e))
            return format_command_result(io, "load", str(e))
        except Exception as e:
            io.tool_error(f"Error reading file: {e}")
            return format_command_result(io, "load", f"Error reading file: {e}")

        # Get the Commands instance from kwargs if available
        commands_instance = kwargs.get("commands_instance")

        if not commands_instance:
            # Create a minimal Commands instance if not provided
            from cecli.commands import Commands

            commands_instance = Commands(io, coder)

        should_raise_at_end = None
        for cmd in commands:
            cmd = cmd.strip()
            if not cmd or cmd.startswith("#"):
                continue

            io.tool_output(f"\nExecuting: {cmd}")
            try:
                await commands_instance.run(cmd)
            except Exception as e:
                # Handle SwitchCoderSignal exception specifically
                if type(e).__name__ == "SwitchCoderSignal":
                    # SwitchCoderSignal is raised when switching between coder types (e.g., /architect, /ask).
                    # This is expected behavior, not an error. But this gets in the way when running `/load` so we
                    # ignore it and continue processing remaining commands.
                    should_raise_at_end = e
                    continue
                else:
                    # Re-raise other exceptions
                    raise

        if should_raise_at_end:
            raise should_raise_at_end

        return format_command_result(
            io, "load", f"Loaded and executed commands from {args.strip()}"
        )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for load command."""
        manager = SaveLoadManager(coder, io)
        return manager.list_files()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the load command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /load <filename>  # Load and execute commands from a file\n"
        help_text += "\nExamples:\n"
        help_text += "  /load commands.txt  # Execute commands from commands.txt\n"
        help_text += (
            "\nThe file should contain one command per line. Lines starting with # are ignored.\n"
        )
        help_text += "Commands are executed sequentially as if they were typed interactively.\n"
        return help_text
