from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.commands.utils.registry import CommandRegistry


class HelpCommand(BaseCommand):
    NORM_NAME = "help"
    DESCRIPTION = "Ask questions about cecli"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the help command with given parameters."""
        if not args.strip():
            await cls._basic_help(io, coder)
            return format_command_result(io, "help", "Displayed basic help")

        from cecli.coders.base_coder import Coder
        from cecli.help import Help, install_help_extra

        # Get the Commands instance from kwargs if available
        commands_instance = kwargs.get("commands_instance")

        if not commands_instance or not hasattr(commands_instance, "help"):
            res = await install_help_extra(io)
            if not res:
                io.tool_error("Unable to initialize interactive help.")
                return format_command_result(io, "help", "Unable to initialize interactive help")

            if not commands_instance:
                # Create a minimal Commands instance if not provided
                from cecli.commands import Commands

                commands_instance = Commands(io, coder)
            commands_instance.help = Help()

        help_instance = commands_instance.help

        # Use the editor_model from the main_model if it exists, otherwise use the main_model itself
        editor_model = coder.main_model.editor_model or coder.main_model

        kwargs = dict()
        kwargs["io"] = io
        kwargs["from_coder"] = coder
        kwargs["edit_format"] = "help"
        kwargs["summarize_from_coder"] = False
        kwargs["map_tokens"] = 512
        kwargs["map_mul_no_files"] = 1
        kwargs["main_model"] = editor_model
        kwargs["args"] = coder.args
        kwargs["suggest_shell_commands"] = False
        kwargs["cache_prompts"] = False
        kwargs["num_cache_warming_pings"] = 0

        help_coder = await Coder.create(**kwargs)
        user_msg = help_instance.ask(args)
        user_msg += """
# Announcement lines from when this session of cecli was launched:

"""
        user_msg += "\n".join(coder.get_announcements()) + "\n"

        await help_coder.run(user_msg, preproc=False)

        if coder.repo_map:
            map_tokens = coder.repo_map.max_map_tokens
            map_mul_no_files = coder.repo_map.map_mul_no_files
        else:
            map_tokens = 0
            map_mul_no_files = 1

        from cecli.commands import SwitchCoderSignal

        raise SwitchCoderSignal(
            edit_format=coder.edit_format,
            summarize_from_coder=False,
            from_coder=help_coder,
            map_tokens=map_tokens,
            map_mul_no_files=map_mul_no_files,
            show_announcements=False,
        )

    @classmethod
    async def _basic_help(cls, io, coder):
        """Display basic help with available commands."""
        # Get commands from registry
        CommandRegistry.list_commands()  # Called for side effect, result not used

        # We need to get commands from the Commands class too
        # Since we don't have a Commands instance, we'll create a minimal one
        from cecli.commands import Commands

        commands_instance = Commands(io, coder)
        all_commands = commands_instance.get_commands()

        pad = max(len(cmd) for cmd in all_commands)
        pad_format = "{cmd:" + str(pad) + "}"

        for cmd in sorted(all_commands):
            cmd_name = cmd[1:]  # Remove leading "/"
            cmd_display = pad_format.format(cmd=cmd)

            # Try to get description from registry first
            command_class = CommandRegistry.get_command(cmd_name)
            if command_class:
                description = command_class.DESCRIPTION
                io.tool_output(f"{cmd_display} {description}")
            else:
                # Fall back to old method
                cmd_method_name = f"cmd_{cmd_name}".replace("-", "_")
                if hasattr(commands_instance, cmd_method_name):
                    cmd_method = getattr(commands_instance, cmd_method_name)
                    description = cmd_method.__doc__
                    io.tool_output(f"{cmd_display} {description}")
                else:
                    io.tool_output(f"{cmd_display} No description available.")

        io.tool_output()
        io.tool_output("Use `/help <question>` to ask questions about how to use cecli.")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for help command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the help command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /help              # Show basic help with available commands\n"
        help_text += "  /help <question>   # Ask a question about how to use cecli\n"
        help_text += "\nExamples:\n"
        help_text += "  /help              # List all available commands\n"
        help_text += "  /help how to add files  # Ask how to add files\n"
        help_text += "  /help undo command # Ask about the undo command\n"
        help_text += "\nNote: When asking a question, cecli will switch to a special help mode\n"
        help_text += "to answer your question, then switch back to your original mode.\n"
        return help_text
