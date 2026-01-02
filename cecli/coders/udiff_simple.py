from .udiff_coder import UnifiedDiffCoder


class UnifiedDiffSimpleCoder(UnifiedDiffCoder):
    """
    A coder that uses unified diff format for code modifications.
    This variant uses a simpler prompt that doesn't mention specific
    diff rules like using `@@ ... @@` lines or avoiding line numbers.
    """

    edit_format = "udiff-simple"
    prompt_format = "udiff_simple"
