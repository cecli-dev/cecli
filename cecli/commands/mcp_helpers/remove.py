"""Implementation of ``/mcp remove``."""

from cecli.commands.utils.helpers import (
    format_command_result,
    is_server_globally_excluded,
    update_server_registration,
)

# Legacy command name, kept so the returned status string does not change.
RESULT_NAME = "remove-mcp"


async def cmd_remove(io, coder, args):
    """Remove (unload) MCP server(s) by name, or use '*' to remove all."""
    if not args.strip():
        return format_command_result(io, RESULT_NAME, "Usage: /mcp remove <mcp-name>")

    if not coder.mcp_manager or not coder.mcp_manager.servers:
        return format_command_result(
            io, RESULT_NAME, "No MCP servers connected, nothing to remove."
        )

    server_names = args.strip().split()

    results = []
    servers_to_disconnect = []

    # Handle '*' wildcard to disconnect all servers
    if server_names == ["*"]:
        connected = [s for s in coder.mcp_manager.servers if s.is_connected]

        if not connected:
            results.append("No MCP servers connected, nothing to remove.")
        else:
            servers_to_disconnect.extend(connected)
    else:
        for server_name in server_names:
            servers_to_disconnect.append(server_name)

    # Early exit if nothing to process
    if not servers_to_disconnect and results:
        return format_command_result(io, RESULT_NAME, "", "\n".join(results))

    # Process disconnections with interrupt support
    for item in servers_to_disconnect:
        server_name = item.name if hasattr(item, "name") else item

        # Never remove the "local" server
        if server_name.lower() == "local":
            results.append("Cannot remove 'Local' server")
            continue

        # Force-exclude on the primary (active) coder
        update_server_registration(coder, server_name, "exclude", force=True)
        # Check if all coders in the hierarchy have this server excluded
        all_excluded = is_server_globally_excluded(coder, server_name)

        if all_excluded:
            was_disconnected, interrupted = await coder.coroutines.interruptible(
                coder.mcp_manager.disconnect_server(server_name),
                coder.interrupt_event,
            )

            if interrupted:
                io.tool_warning(f"MCP disconnection interrupted: {server_name}")
                results.append(f"Interrupted: {server_name}")
                continue

            if was_disconnected:
                results.append(f"Removed server: {server_name}")
            else:
                results.append(f"Unable to remove server: {server_name}")
        else:
            io.tool_output(
                f"Server '{server_name}' still in use by other coders, "
                f"keeping connection active."
            )
            results.append(f"Removed from active coder, still active for others: {server_name}")

    io.tool_output("\n".join(results))

    from cecli.commands import SwitchCoderSignal

    raise SwitchCoderSignal(
        edit_format=coder.edit_format,
        summarize_from_coder=False,
        from_coder=coder,
        show_announcements=True,
        mcp_manager=coder.mcp_manager,
    )


def get_completions(io, coder):
    """Completion options for remove: currently connected servers."""
    if not coder.mcp_manager or not coder.mcp_manager.servers:
        return []

    try:
        server_names = [server.name for server in coder.mcp_manager if server.is_connected]
        return server_names
    except Exception:
        return []
