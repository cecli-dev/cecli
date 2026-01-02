from .base_coder import Coder


class AskCoder(Coder):
    """Ask questions about code without making any changes."""

    edit_format = "ask"
    prompt_format = "ask"
