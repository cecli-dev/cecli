from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class LsCommand(BaseCommand):
    NORM_NAME = "ls"
    DESCRIPTION = "List all known files and indicate which are included in the chat session"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        files = coder.get_all_relative_files()

        # other_files = []
        chat_files = []
        read_only_files = []
        read_only_stub_files = []
        for file in files:
            abs_file_path = coder.abs_root_path(file)
            if abs_file_path in coder.abs_fnames:
                chat_files.append(file)
            # else:
            #     other_files.append(file)

        # Add read-only files
        for abs_file_path in coder.abs_read_only_fnames:
            rel_file_path = coder.get_rel_fname(abs_file_path)
            read_only_files.append(rel_file_path)

        # Add read-only stub files
        for abs_file_path in coder.abs_read_only_stubs_fnames:
            rel_file_path = coder.get_rel_fname(abs_file_path)
            read_only_stub_files.append(rel_file_path)

        if not chat_files and not read_only_files and not read_only_stub_files:
            io.tool_output("\nNo files in chat, git repo, or read-only list.")
            return format_command_result(io, "ls", "Listed files")

        # if other_files:
        #     io.tool_output("Repo files not in the chat:\n")
        # for file in other_files:
        #     io.tool_output(f"  {file}")

        # Read-only files:
        if read_only_files or read_only_stub_files:
            io.tool_output("\nRead-only files:\n")
        for file in read_only_files:
            io.tool_output(f"  {file}")
        for file in read_only_stub_files:
            io.tool_output(f"  {file} (stub)")

        if chat_files:
            io.tool_output("\nFiles in chat:\n")
        for file in chat_files:
            io.tool_output(f"  {file}")

        return format_command_result(io, "ls", "Listed files")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for ls command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the ls command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /ls  # List all files in the project and show which are in chat\n"
        help_text += "\nThe command shows:\n"
        help_text += "  - Files in chat (editable)\n"
        help_text += "  - Read-only files (view-only)\n"
        help_text += "  - Read-only stub files (view-only, truncated)\n"
        return help_text
