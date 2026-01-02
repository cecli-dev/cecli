from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class SaveSessionCommand(BaseCommand):
    NORM_NAME = "save-session"
    DESCRIPTION = "Save the current chat session to a named file in .cecli/sessions/"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the save-session command with given parameters."""
        if not args.strip():
            io.tool_error("Please provide a session name to save.")
            return format_command_result(io, "save-session", "No session name provided")

        from cecli import sessions

        session_manager = sessions.SessionManager(coder, io)
        session_manager.save_session(args.strip())

        return format_command_result(io, "save-session", f"Saved session: {args.strip()}")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for save-session command."""
        # For save-session, we could return existing session names for completion
        # For now, return empty list
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the save-session command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /save-session <session-name>  # Save current chat session\n"
        help_text += "\nExamples:\n"
        help_text += "  /save-session my-feature      # Save session as 'my-feature'\n"
        help_text += "  /save-session bug-fix         # Save session as 'bug-fix'\n"
        help_text += "\nSessions are saved in the .cecli/sessions/ directory as JSON files.\n"
        help_text += "Use /list-sessions to see saved sessions and /load-session to load them.\n"
        return help_text
