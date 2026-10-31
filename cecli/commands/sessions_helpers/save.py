"""Subcommand helper for ``/sessions save``."""

from cecli.commands.utils.helpers import format_command_result


def cmd_save(io, coder, args):
    """Save the current chat session under a name."""
    if not args.strip():
        io.tool_error("Please provide a session name to save.")
        return format_command_result(io, "save-session", "No session name provided")

    from cecli.helpers import sessions

    session_manager = sessions.SessionManager(coder, io)
    session_manager.save_session(args.strip())

    return format_command_result(io, "save-session", f"Saved session: {args.strip()}")
