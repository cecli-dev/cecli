from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class LoadSessionCommand(BaseCommand):
    NORM_NAME = "load-session"
    DESCRIPTION = "Load a saved session by name or file path"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the load-session command with given parameters."""
        if not args.strip():
            io.tool_output("Usage: /load-session <session-name>")
            return format_command_result(io, "load-session", "No session name provided")

        from cecli import sessions

        session_manager = sessions.SessionManager(coder, io)
        session_manager.load_session(args.strip())

        return format_command_result(io, "load-session", f"Loaded session: {args.strip()}")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for load-session command."""
        # Return available session names for completion
        from cecli import sessions

        session_manager = sessions.SessionManager(coder, io)
        sessions_list = session_manager.list_sessions()
        return [session_info["name"] for session_info in sessions_list]

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the load-session command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /load-session <session-name>  # Load a saved session\n"
        help_text += "\nExamples:\n"
        help_text += "  /load-session my-feature      # Load session 'my-feature'\n"
        help_text += "  /load-session bug-fix         # Load session 'bug-fix'\n"
        help_text += "\nSessions are loaded from the .cecli/sessions/ directory.\n"
        help_text += (
            "Use /list-sessions to see saved sessions and /save-session to save a session.\n"
        )
        return help_text
