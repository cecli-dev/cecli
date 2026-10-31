"""Subcommand helper for ``/sessions list``."""

from cecli.commands.utils.helpers import format_command_result


def cmd_list(io, coder, args):
    """List all saved sessions."""
    from cecli.helpers import sessions

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

    return format_command_result(io, "list-sessions", f"Listed {len(sessions_list)} saved sessions")
