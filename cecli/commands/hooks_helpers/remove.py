"""Subcommand helper for ``/hooks remove``."""

from cecli.hooks.service import HookService


def cmd_remove(io, coder, args):
    """Disable one or more hooks by name."""
    if not args.strip():
        io.tool_error("Usage: /hooks remove <hook-name>")
        return 1

    hook_names = args.strip().split()
    hook_manager = HookService.get_manager(coder)
    errors = 0

    for hook_name in hook_names:
        if not hook_manager.hook_exists(hook_name):
            io.tool_error(f"Error: Hook '{hook_name}' not found")
            errors += 1
            continue

        success = hook_manager.disable_hook(hook_name)
        if success:
            io.tool_output(f"Hook '{hook_name}' disabled successfully")
        else:
            io.tool_error(f"Error: Failed to disable hook '{hook_name}'")
            errors += 1

    return 0 if errors == 0 else 1
