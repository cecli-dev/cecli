from textual.containers import Vertical
from textual.reactive import reactive


class InputContainer(Vertical):
    """Input container widget for input area wrapper"""

    coder_mode = reactive("")

    show_squares = reactive(False)

    def __init__(self, *args, coder_mode: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.coder_mode = coder_mode
        self.border_title = self.coder_mode

    def on_mount(self):
        """Start periodic refresh of sub-agent pill display."""
        self.set_interval(1.0, self._refresh_sub_agents)

    def _refresh_sub_agents(self):
        """Re-render the border title with current sub-agent status."""
        self.show_squares = not self.show_squares
        self.update_mode(self.coder_mode)

    def update_mode(self, mode: str):
        """Update the chat mode display, with sub-agent pills in border title.

        Queries the AgentService via self.app to get active sub-agents
        and renders them as pills in the border title.
        E.g. "code | ○ primary ● reviewer" where ● marks the active/foreground agent.

        When no sub-agents exist, the border_title shows just the mode.

        Args:
            mode: The coder edit format (e.g. "code", "agent").
        """
        self.coder_mode = mode
        sub_agents = self._get_sub_agents()
        if sub_agents:
            pills_text = self._format_sub_agent_pills(sub_agents, self.show_squares)
            self.border_title = f"agent: {pills_text}"
        else:
            self.border_title = mode
        self.refresh()

    def _get_sub_agents(self) -> list:
        """Query AgentService via self.app to build sub-agent pill data.

        Returns:
            List of dicts with ``name``, ``uuid``, ``active``, and ``generating`` keys,
            or empty list.
        """
        try:
            app = self.app
            coder = app.worker.coder
            from cecli.helpers.agents.service import AgentService
            from cecli.helpers.coroutines import is_active

            agent_service = AgentService.get_instance(coder)

            sub_agents = []
            primary_uuid = str(agent_service.coder.uuid)
            active_uuid = agent_service.foreground_uuid or primary_uuid

            # Primary is never "generating" in the sub-agent sense
            sub_agents.append(
                {
                    "name": "primary",
                    "uuid": primary_uuid,
                    "active": active_uuid == primary_uuid,
                    "generating": is_active(getattr(coder.io, "output_task", None)),
                }
            )

            for info in agent_service.sub_agents.values():
                coder_uuid = str(info.coder.uuid)
                sub_agents.append(
                    {
                        "name": info.name,
                        "uuid": coder_uuid,
                        "active": coder_uuid == active_uuid,
                        "generating": is_active(info.generate_task),
                    }
                )

            if len(sub_agents) <= 1:
                return []

            return sub_agents
        except Exception:
            return []

    @staticmethod
    def _format_sub_agent_pills(sub_agents: list, show_squares: bool = False) -> str:
        """Format sub-agent info into a compact pill string for the border title.

        Uses four distinct icons based on generating/active state:
          - ○ (not generating, not active)
          - ● (not generating, active)
          - ◇/□ (generating, not active) — alternates for animation
          - ◆/■ (generating, active) — alternates for animation

        Args:
            sub_agents: List of dicts with ``name``, ``uuid``, ``active``, and ``generating`` keys.
            show_squares: If True, use square icons (□/■) instead of diamonds (◇/◆) for generating agents.

        Returns:
            A string like ``"◍ primary ◆ reviewer (a6b)"``.
        """
        parts = []
        name_counts = {}
        for sa in sub_agents:
            name_counts[sa["name"]] = name_counts.get(sa["name"], 0) + 1

        for sa in sub_agents:
            active = sa.get("active", False)
            gen = sa.get("generating", False)
            if gen:
                if show_squares:
                    icon = "■" if active else "□"
                else:
                    icon = "◆" if active else "◇"
            else:
                icon = "●" if active else "○"

            name = sa["name"]
            display_name = name
            if name != "primary" and name_counts[name] > 1:
                display_name = f"{name} ({sa['uuid'][:3]})"

            parts.append(f"{icon} {display_name}")
        return " ".join(parts)

    def update_cost(self, cost_text: str):
        """Update the cost display in the border subtitle."""
        self.border_subtitle = cost_text
        self.refresh()
