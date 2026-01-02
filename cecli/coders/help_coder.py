from ..dump import dump  # noqa: F401
from .base_coder import Coder


class HelpCoder(Coder):
    """Interactive help and documentation about cecli."""

    edit_format = "help"
    prompt_format = "help"

    def get_edits(self, mode="update"):
        return []

    def apply_edits(self, edits):
        pass
