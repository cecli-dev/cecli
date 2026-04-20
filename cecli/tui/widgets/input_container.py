from textual.containers import Vertical
from textual.reactive import reactive


class InputContainer(Vertical):
    """Input container widget for input area wrapper"""

    coder_mode = reactive("")

    def __init__(self, *args, coder_mode: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.coder_mode = coder_mode
        self.border_title = self.coder_mode

    def update_mode(self, mode: str):
        """Update the chat mode display."""
        self.coder_mode = mode
        self.border_title = self.coder_mode
        self.refresh()

    def update_cost(self, cost_text: str):
        """Update the cost display in the border subtitle."""
        self.border_subtitle = cost_text
        self.refresh()
