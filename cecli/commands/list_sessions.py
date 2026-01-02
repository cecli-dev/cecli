from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ListSessionsCommand(BaseCommand):
    NORM_NAME = "list-sessions"
    DESCRIPTION = "List all saved sessions in .cecli/sessions/"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the list-sessions command with given parameters."""
        from cecli import sessions

        session_manager = sessions.SessionManager(coder, io)
        sessions_list = session_manager.list_sessions()

        if not sessions_list:
            io.tool_output("No saved sessions found.")
            return format_command_result(io, "list-sessions", "No saved sessions found")

        io.tool_output("Saved sessions:")
        for session_info in sessions_list:
            io.tool_output(
                f"  {session_info['name']} (model: {session_info['model']}, "
                f"format: {session_info['edit_format']}, "
                f"{session_info['num_messages']} messages, {session_info['num_files']} files)"
            )

        return format_command_result(
            io, "list-sessions", f"Listed {len(sessions_list)} saved sessions"
        )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for list-sessions command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the list-sessions command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /list-sessions  # List all saved sessions\n"
        help_text += (
            "\nThis command lists all saved chat sessions in the .cecli/sessions/ directory.\n"
        )
        help_text += (
            "Each session shows the name, model, edit format, number of messages, and number of"
            " files.\n"
        )
        help_text += (
            "Use /save-session to save a session and /load-session to load a saved session.\n"
        )
        return help_text
