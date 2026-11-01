"""Creator command - spawns the creator sub-agent with a prompt."""

from .utils.base_command import BaseCommand


class CreatorCommand(BaseCommand):
    NORM_NAME = "creator"
    DESCRIPTION = "Spawn the creator sub-agent to build or configure extensions"
    show_completion_notification = True

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Spawn the creator sub-agent with the supplied prompt."""
        from cecli.helpers.agents.service import AgentService

        prompt = args.strip() or None

        try:
            agent_service = AgentService.get_instance(coder)
            new_coder, info = await agent_service.spawn(
                "creator", prompt, parent=coder, auto_reap=False, independent=True
            )

            agent_service.foreground_uuid = info.coder.uuid

            if coder.tui and coder.tui():
                tui = coder.tui()
                switch_key = tui.get_keys_for("next_agent")
                io.tool_output(f"Creator agent spawned and active. Switch with {switch_key}")

                try:
                    tui.call_from_thread(tui._switch_to_container, info.coder.uuid)
                except Exception:
                    pass
        except ValueError as e:
            io.tool_error(f"Error: {e}")
        except RuntimeError as e:
            io.tool_error(f"Error: {e}")
        except Exception as e:
            io.tool_error(f"Error spawning creator sub-agent: {e}")

    @classmethod
    def get_help(cls) -> str:
        return "Spawn the creator sub-agent, optionally with a prompt (/creator [prompt])"
