from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ResetCommand(BaseCommand):
    NORM_NAME = "reset"
    DESCRIPTION = "Drop all files and clear the chat history"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        try:
            # Drop all files
            cls._drop_all_files(io, coder, kwargs.get("original_read_only_fnames"))

            # Clear chat history
            coder.done_messages = []
            coder.cur_messages = []

            # Clear TUI output if available
            if coder.tui and coder.tui():
                coder.tui().action_clear_output()
            else:
                io.tool_output("All files dropped and chat history cleared.")

            # Recalculate context block tokens after dropping all files
            if hasattr(coder, "use_enhanced_context") and coder.use_enhanced_context:
                if hasattr(coder, "_calculate_context_block_tokens"):
                    coder._calculate_context_block_tokens()

            return format_command_result(io, "reset", "Dropped all files and cleared chat history")

        finally:
            # This mimics the SwitchCoder behavior in the original cmd_drop
            if coder.repo_map:
                map_tokens = coder.repo_map.max_map_tokens
                map_mul_no_files = coder.repo_map.map_mul_no_files
            else:
                map_tokens = 0
                map_mul_no_files = 1

            # Raise SwitchCoderSignal to trigger coder recreation
            from . import SwitchCoderSignal

            raise SwitchCoderSignal(
                edit_format=coder.edit_format,
                summarize_from_coder=False,
                from_coder=coder,
                map_tokens=map_tokens,
                map_mul_no_files=map_mul_no_files,
                show_announcements=False,
            )

    @classmethod
    def _drop_all_files(cls, io, coder, original_read_only_fnames):
        coder.abs_fnames = set()
        coder.abs_read_only_stubs_fnames = set()

        # When dropping all files, keep those that were originally provided via args.read
        if original_read_only_fnames:
            # Keep only the original read-only files
            to_keep = set()
            for abs_fname in coder.abs_read_only_fnames:
                rel_fname = coder.get_rel_fname(abs_fname)
                if abs_fname in original_read_only_fnames or rel_fname in original_read_only_fnames:
                    to_keep.add(abs_fname)
            coder.abs_read_only_fnames = to_keep
        else:
            coder.abs_read_only_fnames = set()

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for reset command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the reset command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /reset  # Drop all files and clear chat history\n"
        help_text += (
            "\nNote: This command removes all files from the chat and clears the conversation"
            " history.\n"
        )
        help_text += "Files originally provided via --read will be kept as read-only.\n"
        return help_text
