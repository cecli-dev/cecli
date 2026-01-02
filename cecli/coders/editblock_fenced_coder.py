from ..dump import dump  # noqa: F401
from .editblock_coder import EditBlockCoder


class EditBlockFencedCoder(EditBlockCoder):
    """A coder that uses fenced search/replace blocks for code modifications."""

    edit_format = "diff-fenced"
    prompt_format = "editblock_fenced"
