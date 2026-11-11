"""Reap-agent command - force destroys the active sub-agent."""

import weakref
from typing import List

from cecli.helpers.agents.service import AgentService

from .utils.base_command import BaseCommand


class ReapAgentCommand(BaseCommand):
    NORM_NAME = "reap-agent"
    DESCRIPTION = "Force destroy the active sub-agent"

    @classmethod
    async def execute(cls, io, coder, args, target_agent_uuid=None, **kwargs):
        """Destroy a sub-agent and clean up its resources.

        If an agent identifier is provided, looks up the sub-agent by
        name or UUID prefix (matching switch-agent semantics).  Without
        an argument the currently-active sub-agent is reaped: the visible
        one in the TUI, or the foreground agent for clients without a TUI
        (the desktop app).  Running the command inside a sub-agent reaps
        that sub-agent.
        """
        agent_identifier = args.strip() if args else ""

        # --- Resolve the target UUID -------------------------------- #
        agent_uuid = None
        target_name = None

        if agent_identifier:
            # Lookup logic mirroring switch-agent
            agent_service = AgentService.get_instance(coder)

            # Try parsing "name (uuid_prefix)" format
            if agent_identifier.endswith(")") and " (" in agent_identifier:
                try:
                    uuid_prefix = agent_identifier.rsplit(" (", 1)[1][:-1]
                    for uuid, info in agent_service.sub_agents.items():
                        if uuid.startswith(uuid_prefix):
                            agent_uuid = uuid
                            target_name = info.name
                            break
                except IndexError:
                    pass

            # Try matching by name directly
            if agent_uuid is None:
                for uuid, info in agent_service.sub_agents.items():
                    if info.name == agent_identifier:
                        agent_uuid = uuid
                        target_name = info.name
                        break

            # Try matching by UUID prefix directly
            if agent_uuid is None:
                for uuid, info in agent_service.sub_agents.items():
                    if uuid.startswith(agent_identifier):
                        agent_uuid = uuid
                        target_name = info.name
                        break

            if agent_uuid is None:
                io.tool_error(f"Error: Agent '{agent_identifier}' not found.")
                return

            # Prevent reaping the primary coder
            if agent_uuid == str(coder.uuid):
                io.tool_error("Cannot reap the primary coder.")
                return

        else:
            # Reap whichever sub-agent the user is acting on
            agent_service = AgentService.get_instance(coder)
            active_uuid = target_agent_uuid or cls._active_sub_agent_uuid(coder, agent_service)

            if not active_uuid:
                io.tool_error("No active sub-agent to reap.")
                return

            # Find the sub-agent info by UUID
            for info in agent_service.sub_agents.values():
                if info.coder.uuid == active_uuid:
                    agent_uuid = active_uuid
                    target_name = info.name
                    break
            else:
                io.tool_error("Could not find sub-agent for the active container.")
                return

        # --- Cleanup ------------------------------------------------ #
        try:
            # Cleanup conversation resources
            from cecli.helpers.conversation.service import ConversationService

            ConversationService.destroy_instances(agent_uuid)

            # Remove from tracking and clean up
            agent_service._cleanup_sub_agent(agent_uuid)

            io.tool_output(f"Sub-agent '{target_name}' reaped.")
        except (KeyError, AttributeError, RuntimeError) as e:
            io.tool_error(f"Error reaping sub-agent: {e}")
        except Exception as e:
            io.tool_error(f"Unexpected error reaping sub-agent: {e}")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for reap-agent command."""
        try:
            agent_service = AgentService.get_instance(coder)
            names: List[str] = []

            # Add sub-agent names
            if agent_service and agent_service.sub_agents:
                # First pass: count name occurrences
                name_counts = {}
                for uuid, sub_agent_info in agent_service.sub_agents.items():
                    name_counts[sub_agent_info.name] = name_counts.get(sub_agent_info.name, 0) + 1

                # Second pass: only show UUID prefix when name appears multiple times
                for uuid, sub_agent_info in agent_service.sub_agents.items():
                    name = sub_agent_info.name
                    if name_counts[name] > 1:
                        names.append(f"{name} ({uuid[:3]})")
                    else:
                        names.append(name)

            current_arg = args.strip().lower()
            if current_arg:
                return [name for name in names if name.lower().startswith(current_arg)]
            else:
                return names
        except Exception:
            return []

    @classmethod
    def get_help(cls) -> str:
        help_text = "Force destroy the active sub-agent (/reap-agent)"
        help_text += "\n\nUsage:\n"
        help_text += "  /reap-agent              # Reap the currently active sub-agent\n"
        help_text += "  /reap-agent <name>       # Reap a sub-agent by name\n"
        help_text += "  /reap-agent <uuid>       # Reap a sub-agent by UUID prefix\n"
        help_text += "  /reap-agent <name> (<prefix>)  # Reap by name with UUID disambiguation\n"
        help_text += "\nExamples:\n"
        help_text += "  /reap-agent reviewer\n"
        help_text += "  /reap-agent abc\n"
        return help_text

    @classmethod
    def _active_sub_agent_uuid(cls, coder, agent_service) -> str | None:
        """The UUID of the sub-agent the caller is acting on.

        The TUI tracks a visible container.  Without one, prefer the
        sub-agent whose coder is running the command, then the service's
        foreground agent.
        """
        tui_ref = getattr(coder, "tui", None)
        if tui_ref is not None:
            tui = tui_ref() if isinstance(tui_ref, weakref.ref) else tui_ref
            if tui is not None:
                try:
                    return tui._get_visible_coder().uuid
                except (AttributeError, RuntimeError):
                    pass

        if getattr(coder, "parent_uuid", None):
            return str(coder.uuid)

        return agent_service.foreground_uuid
