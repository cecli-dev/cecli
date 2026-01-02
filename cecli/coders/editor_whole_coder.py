from .wholefile_coder import WholeFileCoder


class EditorWholeFileCoder(WholeFileCoder):
    "A coder that operates on entire files, focused purely on editing files."

    edit_format = "editor-whole"
    prompt_format = "editor_whole"
