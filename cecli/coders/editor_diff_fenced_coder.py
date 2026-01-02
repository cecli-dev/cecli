from .editblock_fenced_coder import EditBlockFencedCoder


class EditorDiffFencedCoder(EditBlockFencedCoder):
    "A coder that uses search/replace blocks, focused purely on editing files."

    edit_format = "editor-diff-fenced"
    prompt_format = "editor_diff_fenced"
