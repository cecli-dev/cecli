"""MCP servers passed by the ACP client in ``session/new``.

Editors hand the agent the MCP servers they have configured (Zed's context
servers) so it can use the same tools. They join cecli's own servers in the
shared McpServerManager, as if they were listed in an MCP config file.
"""

from __future__ import annotations

from typing import Any, Callable


def _pairs(items: Any) -> dict[str, str]:
    """ACP ``[{name, value}]`` lists (env vars, headers) as a dict."""
    pairs = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            pairs[item["name"]] = str(item.get("value", ""))
    return pairs


def to_cecli_configs(mcp_servers: Any) -> dict[str, dict]:
    """ACP McpServer entries as cecli MCP server configs, keyed by lowercased name."""
    configs = {}
    for entry in mcp_servers if isinstance(mcp_servers, list) else []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        transport = entry.get("type", "stdio")
        if transport == "stdio" and entry.get("command"):
            config = {
                "transport": "stdio",
                "command": entry["command"],
                "args": [str(arg) for arg in entry.get("args") or []],
                "env": _pairs(entry.get("env")),
            }
        elif transport in ("http", "sse") and entry.get("url"):
            config = {
                "transport": transport,
                "url": entry["url"],
                "headers": _pairs(entry.get("headers")),
            }
        else:
            continue
        config["name"] = str(entry["name"])
        configs[config["name"].lower()] = config
    return configs


def _make_server(config: dict, io: Any, verbose: bool) -> Any:
    from cecli.mcp.server import HttpStreamingServer, McpServer, SseServer

    server_class = {"stdio": McpServer, "http": HttpStreamingServer, "sse": SseServer}
    return server_class[config["transport"]](dict(config), io=io, verbose=verbose)


class ClientMcpServers:
    """Keeps the manager's client-provided servers in line with the latest session."""

    def __init__(self, log: Callable[[str], None]):
        self._log = log
        self._wanted: dict[str, dict] | None = None
        self._ours: dict[str, dict] = {}  # servers this class added, by name

    def want(self, mcp_servers: Any) -> None:
        """Record a session's servers; ``sync`` applies them on the coder's loop."""
        self._wanted = to_cecli_configs(mcp_servers)

    @property
    def pending(self) -> bool:
        return self._wanted is not None

    async def sync(self, manager: Any, io: Any = None, verbose: bool = False) -> None:
        wanted, self._wanted = self._wanted, None
        if wanted is None or manager is None:
            return

        for name in set(self._ours) - set(wanted):
            # No longer offered by the client (a later session dropped it)
            await manager.disconnect_server(name)

        for name, config in wanted.items():
            server = manager.get_server(name)
            if server is None:
                self._ours[name] = config
                if await manager.add_server(_make_server(config, io, verbose), connect=True):
                    self._log(f"connected MCP server from the client: {config['name']}")
                continue
            if name not in self._ours:
                self._log(f"skipped the client's MCP server {name!r}: cecli has one by that name")
                continue
            if config != self._ours[name]:
                self._log(f"the client changed MCP server {name!r}; restart the agent to apply it")
            if server not in manager.connected_servers:
                await manager.connect_server(name)
