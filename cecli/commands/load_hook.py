from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.hooks.manager import HookManager


class LoadHookCommand(BaseCommand):
    NORM_NAME = "load-hook"
    DESCRIPTION = "Enable a specific hook by name"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the load-hook command with given parameters."""
        # Get hook name from args string
        if not args.strip():
            io.tool_error("Usage: /load-hook <hook-name>")
            return 1
        hook_names = args.strip().split()
        hook_manager = HookManager()
        results = []
        errors = 0

        for hook_name in hook_names:
            if not hook_manager.hook_exists(hook_name):
                io.tool_error(f"Error: Hook '{hook_name}' not found")
                results.append(f"Hook '{hook_name}' not found")
                errors += 1
                continue

            success = hook_manager.enable_hook(hook_name)
            if success:
                io.tool_output(f"Hook '{hook_name}' enabled successfully")
                results.append(f"Hook '{hook_name}' enabled")
            else:
                io.tool_error(f"Error: Failed to enable hook '{hook_name}'")
                results.append(f"Failed to enable hook '{hook_name}'")
                errors += 1

        return 0 if errors == 0 else 1

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for load-hook command."""
        hook_manager = HookManager()
        all_hooks = hook_manager.get_all_hooks()

        # Get all hook names
        hook_names = []
        for hooks in all_hooks.values():
            for hook in hooks:
                hook_names.append(hook.name)

        # Filter based on current args
        current_arg = args.strip()
        if current_arg:
            return [name for name in hook_names if name.startswith(current_arg)]
        else:
            return hook_names

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the load-hook command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /load-hook <hook-name>...  # Enable one or more hooks\n"
        help_text += "\nExamples:\n"
        help_text += "  /load-hook my_start_hook\n"
        help_text += "  /load-hook check_commands my_start_hook\n"
        help_text += "\nThis command enables one or more hooks that were previously disabled.\n"
        help_text += "Use /hooks to see all available hooks and their current state.\n"
        return help_text
