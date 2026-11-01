"""Serialising a coder's state to and from a session payload."""

from __future__ import annotations

import os
from typing import Dict, Optional

from cecli import models
from cecli.helpers.conversation import ConversationService, MessageTag


def build_payload(coder, io, session_name: str, agent_name: Optional[str] = None) -> Dict:
    """Build a session payload dictionary from a coder's current state.

    ``agent_name`` is the sub-agent type when saving a sub-agent and ``None``
    for the primary agent. Workspace agents (``ws:*``) also record their root so
    a later load can rebuild them at the right path. Sub-agent payloads also
    record their independence and lifecycle status so a reload can decide
    whether they should be rebuilt.
    """
    # Sub-agent lifecycle flags come from the AgentService; the primary agent
    # has none and stores ``None`` for both.
    if agent_name:
        from .subagents import sub_agent_state

        independent, status = sub_agent_state(coder)
    else:
        independent, status = None, None

    editable_files = [coder.get_rel_fname(abs_fname) for abs_fname in coder.abs_fnames]
    read_only_files = [coder.get_rel_fname(abs_fname) for abs_fname in coder.abs_read_only_fnames]
    read_only_stubs_files = [
        coder.get_rel_fname(abs_fname) for abs_fname in coder.abs_read_only_stubs_fnames
    ]

    # Flush any queued messages so the saved chat history is complete
    ConversationService.get_manager(coder).flush_queue()

    payload = {
        "version": 1,
        "session_name": session_name,
        "agent_name": agent_name,
        "agent_root": str(coder.root) if agent_name and agent_name.startswith("ws:") else None,
        "independent": independent,
        "status": status,
        "model": coder.main_model.name,
        "weak_model": coder.main_model.weak_model.name,
        "editor_model": coder.main_model.editor_model.name,
        "agent_model": coder.main_model.agent_model.name,
        "editor_edit_format": coder.main_model.editor_edit_format,
        "edit_format": coder.edit_format,
        "chat_history": {
            "done_messages": (
                ConversationService.get_manager(coder).get_messages_dict(MessageTag.DONE)
            ),
            "cur_messages": (
                ConversationService.get_manager(coder).get_messages_dict(MessageTag.CUR)
            ),
        },
        "files": {
            "editable": editable_files,
            "read_only": read_only_files,
            "read_only_stubs": read_only_stubs_files,
        },
        "settings": {
            "auto_commits": coder.auto_commits,
            "auto_lint": coder.auto_lint,
            "auto_test": coder.auto_test,
        },
        "todo_list": _read_todo(coder, io),
        "mcps": _connected_mcps(coder),
        "skills": _skills_data(coder),
        "tools": _agent_config_data(coder),
        "usage": {
            "total_tokens_sent": coder.total_tokens_sent,
            "total_tokens_received": coder.total_tokens_received,
            "total_cached_tokens": coder.total_cached_tokens,
            "total_cost": coder.total_cost,
        },
    }

    return payload


async def apply_payload(
    coder, io, session_data: Dict, session_file, sub_agent: bool = False
) -> tuple[bool, Optional[str]]:
    """Apply a session payload to a coder's state.

    ``sub_agent`` marks a sub-agent restore: progress output is suppressed and
    global environment registries (MCP servers, skills, tools) are left untouched
    so restoring one sub-agent cannot disturb the primary session's shared state.

    Returns:
        A tuple of (success, edit_format).
    """
    try:
        # Clear current state
        coder.abs_fnames = set()
        coder.abs_read_only_fnames = set()
        coder.abs_read_only_stubs_fnames = set()

        # Load files
        files = session_data.get("files", {})
        _restore_files(coder, io, coder.abs_fnames, files.get("editable", []))
        _restore_files(coder, io, coder.abs_read_only_fnames, files.get("read_only", []))
        _restore_files(
            coder, io, coder.abs_read_only_stubs_fnames, files.get("read_only_stubs", [])
        )

        # Load usage stats
        usage = session_data.get("usage", {})
        coder.total_tokens_sent = usage.get("total_tokens_sent", 0)
        coder.total_tokens_received = usage.get("total_tokens_received", 0)
        coder.total_cached_tokens = usage.get("total_cached_tokens", 0)
        coder.total_cost = usage.get("total_cost", 0.0)
        # Loading a session seeds the cumulative counters but does not represent
        # recent API usage, so clear the rolling token-rate buffer.
        coder._reset_token_usage()
        if session_data.get("model"):
            coder.main_model = models.Model(
                session_data.get("model", coder.args.model),
                weak_model=session_data.get("weak_model", coder.args.weak_model),
                editor_model=session_data.get("editor_model", coder.args.editor_model),
                agent_model=session_data.get("agent_model", coder.args.agent_model),
                editor_edit_format=session_data.get(
                    "editor_edit_format", coder.args.editor_edit_format
                ),
                io=io,
                verbose=coder.args.verbose,
                retries=coder.main_model.retries,
                debug=coder.main_model.debug,
            )

        # Load settings
        settings = session_data.get("settings", {})
        if "auto_commits" in settings:
            coder.auto_commits = settings["auto_commits"]
        if "auto_lint" in settings:
            coder.auto_lint = settings["auto_lint"]
        if "auto_test" in settings:
            coder.auto_test = settings["auto_test"]

        _restore_todo(coder, io, session_data)

        # Clear CUR and DONE messages from ConversationManager
        ConversationService.get_manager(coder).reset()
        ConversationService.get_files(coder).reset()
        coder.format_chat_chunks()

        # Load chat history
        chat_history = session_data.get("chat_history", {})
        for msg in chat_history.get("done_messages", []):
            ConversationService.get_manager(coder).add_message(
                message_dict=msg,
                tag=MessageTag.DONE,
            )
        for msg in chat_history.get("cur_messages", []):
            ConversationService.get_manager(coder).add_message(
                message_dict=msg,
                tag=MessageTag.CUR,
            )

        if not sub_agent:
            io.tool_output(f"Session loaded: {session_data.get('session_name', session_file.stem)}")
            io.tool_output(
                f"Model: {session_data.get('model', 'unknown')}, Edit format:"
                f" {session_data.get('edit_format', 'unknown')}"
            )

        # Show summary
        num_messages = len(coder.done_messages) + len(coder.cur_messages)
        num_files = (
            len(coder.abs_fnames)
            + len(coder.abs_read_only_fnames)
            + len(coder.abs_read_only_stubs_fnames)
        )
        if not sub_agent:
            io.tool_output(f"Loaded {num_messages} messages and {num_files} files")

        # Load MCPs
        if not sub_agent and getattr(coder, "mcp_manager", None):
            await _restore_mcps(coder, session_data.get("mcps", []))

        # Load skills
        skills_data = session_data.get("skills")
        if not sub_agent and skills_data and getattr(coder, "skills_manager", None):
            coder.skills_manager.directory_paths = skills_data.get("skills_paths", [])
            coder.skills_manager.include_list = set(skills_data.get("skills_includelist", []))
            coder.skills_manager.exclude_list = set(skills_data.get("skills_excludelist", []))

        # Load tools config
        agent_config_data = session_data.get("tools")
        if not sub_agent and agent_config_data and hasattr(coder, "agent_config"):
            coder.agent_config.update(agent_config_data)
            from cecli.tools.utils.registry import ToolRegistry

            ToolRegistry.build_registry(agent_config=coder.agent_config)
            coder.loaded_custom_tools = ToolRegistry.loaded_custom_tools

        # Return True and the edit format so the Coder can be switched
        edit_format = session_data.get("edit_format")

        return True, edit_format

    except Exception as e:
        io.tool_error(f"Error applying session data: {e}")

        return False, None


def _read_todo(coder, io) -> Optional[str]:
    """Read the agent's todo file so it can be restored with the session."""
    try:
        todo_path = coder.abs_root_path(coder.local_agent_folder("todo.txt"))
        if os.path.isfile(todo_path):
            todo_content = io.read_text(todo_path)

            return todo_content if todo_content is not None else ""

    except Exception as e:
        io.tool_warning(f"Could not read todo list file: {e}")

    return None


def _connected_mcps(coder) -> list:
    """Return the names of the coder's connected MCP servers."""
    if getattr(coder, "mcp_manager", None):
        return [server.name for server in coder.mcp_manager.connected_servers]

    return []


def _skills_data(coder) -> Optional[Dict]:
    """Return the coder's skill path/filter configuration."""
    manager = getattr(coder, "skills_manager", None)
    if not manager:
        return None

    return {
        "skills_paths": [str(p) for p in manager.directory_paths],
        "skills_includelist": (
            list(manager.include_list) if manager.include_list is not None else []
        ),
        "skills_excludelist": (
            list(manager.exclude_list) if manager.exclude_list is not None else []
        ),
    }


def _agent_config_data(coder) -> Optional[Dict]:
    """Return the coder's tool configuration."""
    if not hasattr(coder, "agent_config"):
        return None

    return {
        "tools_paths": coder.agent_config.get("tools_paths", []),
        "tools_includelist": coder.agent_config.get("tools_includelist", []),
        "tools_excludelist": coder.agent_config.get("tools_excludelist", []),
    }


def _restore_files(coder, io, target: set, rel_fnames: list) -> None:
    """Add every existing ``rel_fnames`` entry to ``target``."""
    for rel_fname in rel_fnames:
        abs_fname = coder.abs_root_path(rel_fname)
        if os.path.exists(abs_fname):
            target.add(abs_fname)
        else:
            io.tool_warning(f"File not found, skipping: {rel_fname}")


def _restore_todo(coder, io, session_data: Dict) -> None:
    """Restore (or clear) the agent's todo file from the session."""
    if "todo_list" not in session_data:
        return

    todo_path = coder.abs_root_path(coder.local_agent_folder("todo.txt"))
    todo_content = session_data.get("todo_list")

    try:
        if todo_content is None:
            if os.path.exists(todo_path):
                os.remove(todo_path)
        else:
            io.write_text(todo_path, todo_content)

    except Exception as e:
        io.tool_warning(f"Could not restore todo list: {e}")


async def _restore_mcps(coder, saved_mcps: list) -> None:
    """Reconcile the coder's MCP connections with the saved list."""
    current_mcps = {server.name for server in coder.mcp_manager.connected_servers}
    saved_mcps_set = set(saved_mcps)

    for mcp_name in current_mcps - saved_mcps_set:
        await coder.mcp_manager.disconnect_server(mcp_name)

    for mcp_name in saved_mcps_set - current_mcps:
        await coder.mcp_manager.connect_server(mcp_name)
