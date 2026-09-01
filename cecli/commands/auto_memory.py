"""Auto-memory command - view or toggle automatic memorizer invocation.

Controls the ``coder.auto_memory`` flag, which decides whether the
memorizer sub-agent is fired automatically after context compaction.
``on``/``off`` propagate the setting to every tracked sub-agent so the
whole agent tree stays consistent.
"""

from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.helpers.agents.service import AgentService


class AutoMemoryCommand(BaseCommand):
    NORM_NAME = "auto-memory"
    DESCRIPTION = "View or toggle automatic memory (memorizer) on/off"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """View or toggle automatic memory on/off.

        Syntax:
            /auto-memory           — Show the current status
            /auto-memory on        — Enable for this coder and all sub-agents
            /auto-memory off       — Disable for this coder and all sub-agents
        """
        arg = args.strip().lower()

        if not arg:
            cls._show_status(io, coder)

            return format_command_result(io, cls.NORM_NAME, "Displayed auto-memory status")

        if arg not in ("on", "off"):
            io.tool_error("Usage: /auto-memory [on|off]")

            return format_command_result(
                io,
                cls.NORM_NAME,
                "Unknown option",
                f"Expected 'on' or 'off', got '{arg}'",
            )

        enabled = arg == "on"
        updated = cls._set_auto_memory(coder, enabled)
        state = "ON" if enabled else "OFF"

        io.tool_output(
            f"Auto memory is now {state} for the current coder and {len(updated)} sub-agent(s)."
        )

        return format_command_result(io, cls.NORM_NAME, f"Auto memory set to {state}")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Return completion options for auto-memory."""
        return ["on", "off"]

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the auto-memory command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /auto-memory              # Show the current status\n"
        help_text += "  /auto-memory on           # Enable automatic memory for all agents\n"
        help_text += "  /auto-memory off          # Disable automatic memory for all agents\n"
        help_text += "\nWith 'on' or 'off' the setting is applied to the current coder and\n"
        help_text += "iterated through every sub-agent so the whole tree stays consistent.\n"

        return help_text

    @classmethod
    def _show_status(cls, io, coder) -> None:
        """Print the current auto-memory status for the coder and its sub-agents."""
        state = "ON" if getattr(coder, "auto_memory", True) else "OFF"
        io.tool_output(f"Auto memory is {state} for the current coder.")

        sub_infos = cls._get_sub_agent_infos(coder)

        if not sub_infos:
            return

        io.tool_output(f"Sub-agents ({len(sub_infos)}):")

        for info in sub_infos:
            sub_state = "ON" if getattr(info.coder, "auto_memory", True) else "OFF"
            io.tool_output(f"  {info.name} ({info.coder.uuid}): {sub_state}")

    @classmethod
    def _set_auto_memory(cls, coder, enabled: bool) -> list:
        """Set auto_memory on *coder* and every tracked sub-agent coder.

        Returns the list of sub-agent info objects whose coder was updated.
        """
        coder.auto_memory = enabled
        updated = []

        for info in cls._get_sub_agent_infos(coder):
            try:
                info.coder.auto_memory = enabled
                updated.append(info)
            except Exception:
                continue

        return updated

    @classmethod
    def _get_sub_agent_infos(cls, coder) -> list:
        """Return all sub-agent info objects tracked by the coder's AgentService."""
        try:
            agent_service = AgentService.get_instance(coder)

            return list(agent_service.sub_agents.values())
        except Exception:
            return []
