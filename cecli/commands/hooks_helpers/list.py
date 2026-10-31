"""Subcommand helper for ``/hooks list``."""

import argparse

from cecli.hooks.service import HookService
from cecli.hooks.types import HookType


def cmd_list(io, coder, args):
    """List all registered hooks grouped by type."""
    parsed_args = _parse_args(args)

    hook_manager = HookService.get_manager(coder)
    all_hooks = hook_manager.get_all_hooks()

    if parsed_args.type:
        filtered_hooks = {}
        if parsed_args.type in all_hooks:
            filtered_hooks[parsed_args.type] = all_hooks[parsed_args.type]
        all_hooks = filtered_hooks

    if not all_hooks:
        io.tool_output("No hooks registered")
        return 0

    total_hooks = 0
    total_enabled = 0

    for hook_type, hooks in sorted(all_hooks.items(), reverse=True):
        filtered_hooks = []
        for hook in hooks:
            if parsed_args.enabled_only and not hook.enabled:
                continue
            if parsed_args.disabled_only and hook.enabled:
                continue
            filtered_hooks.append(hook)

        if not filtered_hooks:
            continue

        io.tool_output(f"\n{hook_type.upper()} hooks:")
        io.tool_output("-" * 40)

        for hook in filtered_hooks:
            status = "✓ ENABLED" if hook.enabled else "✗ DISABLED"
            io.tool_output(f"  {hook.name:30} {status}")

            if hasattr(hook, "description") and hook.description:
                io.tool_output(f"    Description: {hook.description}")
            if hasattr(hook, "priority"):
                io.tool_output(f"    Priority: {hook.priority}")

            total_hooks += 1
            if hook.enabled:
                total_enabled += 1

    io.tool_output(
        f"\nTotal hooks: {total_hooks} ({total_enabled} enabled,"
        f" {total_hooks - total_enabled} disabled)"
    )
    return 0


def _parse_args(args_string):
    """Parse ``list`` flags."""
    parser = argparse.ArgumentParser(prog="/hooks list", add_help=False)
    parser.add_argument(
        "--type",
        choices=[t.value for t in HookType],
        help="Filter hooks by type (start, on_message, end_message, pre_tool, post_tool, end)",
    )
    parser.add_argument("--enabled-only", action="store_true", help="Show only enabled hooks")
    parser.add_argument("--disabled-only", action="store_true", help="Show only disabled hooks")

    try:
        return parser.parse_args(args_string.split())
    except SystemExit:
        return argparse.Namespace(type=None, enabled_only=False, disabled_only=False)
