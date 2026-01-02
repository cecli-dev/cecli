from .editblock_coder import EditBlockCoder


class EditorEditBlockCoder(EditBlockCoder):
    "A coder that uses search/replace blocks, focused purely on editing files."

    edit_format = "editor-diff"
    prompt_format = "editor_editblock"
