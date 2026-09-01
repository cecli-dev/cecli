"""Footer widget for cecli TUI."""

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class MainFooter(Static):
    """Footer showing mode, model, project, git, and cost."""

    # Left side info
    coder_mode = reactive("code")
    agent_name = reactive("")
    model_name = reactive("")

    # Right side info
    project_name = reactive("")
    git_branch = reactive("")
    cost = reactive(0.0)

    # Spinner state
    spinner_text = reactive("")
    spinner_suffix = reactive("")
    spinner_visible = reactive(False)
    _spinner_frame = 0
    _spinner_chars = "⠏⠛⠹⠼⠶⠧"

    def __init__(
        self,
        model_name: str = "",
        project_name: str = "",
        git_branch: str = "",
        coder_mode: str = "code",
        **kwargs,
    ):
        """Initialize footer.

        Args:
            model_name: Name of the AI model
            project_name: Name of the project folder
            git_branch: Current git branch name
            coder_mode: Current edit mode (code, agent, architect, etc.)
        """
        super().__init__(**kwargs)
        self.model_name = model_name
        self.project_name = project_name
        self.git_branch = git_branch
        self.coder_mode = coder_mode
        self.agent_name = ""
        self._spinner_interval = None

    def on_mount(self):
        """Start spinner animation interval."""
        self._spinner_interval = self.set_interval(0.1, self._animate_spinner)

    def _animate_spinner(self):
        """Animate the spinner character."""
        if self.spinner_visible:
            self._spinner_frame = (self._spinner_frame + 1) % len(self._spinner_chars)
            self.refresh()

    def _get_display_model(self) -> str:
        """Get shortened model name for display.

        Uses the foreground coder's model (resolved via AgentService) so that
        when a sub-agent is active, its model is shown instead of the parent's.
        """
        if not self.model_name:
            return ""
        try:
            from cecli.helpers.agents.service import AgentService

            coder = self.app.worker.coder
            agent_service = AgentService.get_instance(coder)
            fc = agent_service.foreground_coder
            if fc and fc is not coder and hasattr(fc, "get_active_model"):
                name = fc.get_active_model().name
            else:
                name = coder.get_active_model().name
        except Exception:
            name = self.model_name

        # Strip common prefixes like "openrouter/x-ai/"
        if len(name) > 40:
            if "/" in name:
                name = name.split("/")[-1]

            if len(name) > 35:
                name = name[:35] + "..."

        return name

    def render(self) -> Text:
        """Render the footer with left/right split."""

        # Build left side: spinner/mode + model
        left = Text()

        if self.spinner_visible:
            spinner_char = self._spinner_chars[self._spinner_frame]
            left.append(f"{spinner_char} ")
            if self.agent_name:
                left.append(f"({self.agent_name}) ")
            if self.spinner_text:
                left.append(self.spinner_text)
            # When a sub-agent is generating, show its model alongside the spinner
            # if self._has_running_sub_agent():
            #     model_display = self._get_display_model()
            #     if model_display:
            #         left.append(" • ")
            #         left.append(model_display)

            if self.spinner_suffix:
                left.append(" • ")
                left.append(self.spinner_suffix)
        else:
            left.append("cecli")
            left.append(" • ")
            left.append(self._get_display_model())
        # Build right side: mode + model + project + git
        right = Text()

        # if self.coder_mode:
        #     right.append(f"{self.coder_mode}")
        #     right.append(" • ")

        # model_display = self._get_display_model()
        # if model_display:
        #     right.append(f"{model_display}")
        #     right.append(" • ")

        if self.project_name:
            right.append(f"{self.project_name}")

            if self.git_branch:
                right.append(" • ")

        if self.git_branch:
            right.append(self.git_branch)
            # right.append("  ")

        # Always show cost
        # right.append(f"${self.cost:.2f}")

        # Calculate padding to right-align
        try:
            total_width = self.size.width
        except Exception:
            total_width = 80

        left_len = len(left.plain)
        right_len = len(right.plain)
        padding = max(1, total_width - left_len - right_len)

        # Combine: left + padding + right
        result = Text()
        result.append_text(left)
        result.append(" " * padding)
        result.append_text(right)

        return result

    def update_cost(self, cost: float):
        """Update the displayed cost."""
        self.cost = cost
        self.refresh()

    def update_git(self, branch: str):
        """Update git status display."""
        self.git_branch = branch
        self.refresh()

    def update_info(self, project_name: str, branch: str):
        """Update the project/root and git status display together."""
        self.project_name = project_name
        self.git_branch = branch
        self.refresh()

    def update_mode(self, mode: str):
        """Update the chat mode display."""
        self.coder_mode = mode
        self.refresh()

    def start_spinner(self, text: str = "", agent_name: str = ""):
        """Show spinner with optional text."""
        self.spinner_text = text
        self.agent_name = agent_name
        self.spinner_visible = True
        self.refresh()

    def stop_spinner(self):
        """Hide spinner, unless a sub-agent is still generating."""
        # Check if any agent is still actively generating output
        try:
            coder = self.app.worker.coder
            from cecli.helpers.agents.service import AgentService
            from cecli.helpers.coroutines import is_active

            # Check if primary coder is generating
            if is_active(getattr(coder.io, "output_task", None)):
                return

            # Check if any sub-agent is still generating
            agent_service = AgentService.get_instance(coder)
            for info in agent_service.sub_agents.values():
                if is_active(info.generate_task):
                    return  # Don't stop spinner; a sub-agent is still generating
        except Exception:
            pass

        self.spinner_visible = False
        self.spinner_text = ""
        self.agent_name = ""
        self.refresh()

    def _has_running_sub_agent(self) -> bool:
        """Check if any agent is currently generating output."""
        try:
            coder = self.app.worker.coder
            from cecli.helpers.agents.service import AgentService
            from cecli.helpers.coroutines import is_active

            # Check if primary coder is generating
            if is_active(getattr(coder.io, "output_task", None)):
                return True

            # Check if any sub-agent is still generating
            agent_service = AgentService.get_instance(coder)
            return any(is_active(info.generate_task) for info in agent_service.sub_agents.values())
        except Exception:
            return False
