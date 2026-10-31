"""Subcommand helper for ``/sessions load``."""

from cecli.commands.utils.helpers import format_command_result


async def cmd_load(io, coder, args):
    """Load a saved session by name or file path."""
    if not args.strip():
        io.tool_output("Usage: /sessions load <session-name>")
        return format_command_result(io, "load-session", "No session name provided")

    from cecli.helpers import sessions

    session_manager = sessions.SessionManager(coder, io)
    await session_manager.load_session(args.strip())

    return format_command_result(io, "load-session", f"Loaded session: {args.strip()}")
