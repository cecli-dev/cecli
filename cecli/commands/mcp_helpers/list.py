"""Implementation of ``/mcp list``."""

from cecli.commands.utils.helpers import format_command_result

# Legacy command name, kept so the returned status string does not change.
RESULT_NAME = "list-mcp"


async def cmd_list(io, coder):
    """List all loaded and configured MCP servers."""
    if not coder.mcp_manager:
        return format_command_result(io, RESULT_NAME, "MCP manager is not configured.")

    all_servers = coder.mcp_manager.servers
    connected_servers = coder.mcp_manager.connected_servers

    connected_server_names = {s.name for s in connected_servers}

    # Apply per-coder registered_servers filtering to determine active status
    incl = coder.registered_servers["included"]
    excl = coder.registered_servers["excluded"]

    active_servers = []
    inactive_servers = []

    for server in connected_servers:
        name = server.name
        # Same filtering logic used in base_coder.get_tool_list()
        if incl and name not in incl:
            inactive_servers.append(name)
        elif name in excl:
            inactive_servers.append(name)
        else:
            active_servers.append(name)

    configured_servers = [
        server for server in all_servers if server.name not in connected_server_names
    ]

    result = []
    if active_servers:
        result.append("Active MCP Servers:")
        for name in sorted(active_servers):
            result.append(f"- {name}")
    else:
        result.append("No MCP servers are active for this coder.")

    if inactive_servers:
        result.append("")
        result.append("Inactive (Filtered) MCP Servers:")
        for name in sorted(inactive_servers):
            result.append(f"- {name}")

    result.append("")
    if configured_servers:
        result.append("Configured MCP Servers:")
        for server in sorted(configured_servers, key=lambda s: s.name):
            result.append(f"- {server.name}")
    else:
        result.append("No other MCP servers are configured.")

    return format_command_result(io, RESULT_NAME, "\n".join(result))


def get_completions(io, coder):
    """``/mcp list`` takes no arguments, so there is nothing to complete."""
    return []
