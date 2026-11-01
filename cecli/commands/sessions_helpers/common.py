"""Shared lookups for the ``/sessions`` subcommands."""


def session_names(coder, io):
    """Return the names of all saved sessions."""
    from cecli.helpers import sessions

    session_manager = sessions.SessionManager(coder, io)
    return [session_info["name"] for session_info in session_manager.list_sessions()]
