import asyncio

from cecli.mcp.server import LocalServer, McpServer
from cecli.tools.utils.registry import ToolRegistry


class McpServerManager:
    """
    Centralized manager for MCP server connections.

    Handles connection lifecycle for all MCP servers, ensuring
    connections are established once and reused across all Coder instances.
    """

    def __init__(
        self,
        servers: list[McpServer],
        io=None,
        verbose: bool = False,
    ):
        """
        Initialize the MCP server manager.

        Args:
            servers: List of MCP Servers to manage
            io: InputOutput instance for user interaction
            verbose: Whether to output verbose logging
        """
        self.io = io
        self.verbose = verbose
        self._servers = servers

        self._server_tools: dict[str, list] = {}  # Maps server name to its tools
        self._connected_servers: set[McpServer] = set()
        # Event loop that created the MCP connections (set by connect_all).
        # Loop-bound MCP state must only be torn down on this loop.
        self._connection_loop: asyncio.AbstractEventLoop | None = None

    def _log_verbose(self, message: str) -> None:
        """Log a verbose message if verbose mode is enabled and IO is available."""
        if self.verbose and self.io:
            self.io.tool_output(message)

    def _log_error(self, message: str) -> None:
        """Log an error message if IO is available."""
        if self.io:
            self.io.tool_error(message)

    def _log_warning(self, message: str) -> None:
        """Log a warning message if IO is available."""
        if self.io:
            self.io.tool_warning(message)

    @staticmethod
    def _validate_server_config(config: dict) -> dict:
        """
        Validate keepalive_interval in the server configuration.

        Args:
            config: Server configuration dictionary

        Returns:
            The validated configuration dictionary

        Raises:
            ValueError: If keepalive_interval is invalid
        """
        keepalive_interval = config.get("keepalive_interval")

        if keepalive_interval is not None:
            if not isinstance(keepalive_interval, int) or isinstance(keepalive_interval, bool):
                raise ValueError(
                    f"keepalive_interval must be an integer, got {type(keepalive_interval).__name__}"
                )

            if keepalive_interval < 5:
                raise ValueError(f"keepalive_interval {keepalive_interval} is below minimum of 5")

            if keepalive_interval > 300:
                raise ValueError(f"keepalive_interval {keepalive_interval} is above maximum of 300")

        return config

    @property
    def servers(self) -> list["McpServer"]:
        """Get the list of managed MCP servers."""
        return self._servers

    @property
    def is_connected(self) -> bool:
        """Check if any servers have a live session (including not-yet-registered ones)."""
        if self._connected_servers:
            return True

        return any(server.is_connected for server in self._servers)

    def get_server(self, name: str) -> McpServer | None:
        """
        Get a server by name.

        Args:
            name: Name of the server to retrieve

        Returns:
            The server instance or None if not found
        """
        try:
            return next(server for server in self._servers if server.name.lower() == name.lower())
        except StopIteration:
            return None

    async def disconnect_all(self) -> None:
        """
        Disconnect from all MCP servers.

        Connections are loop-bound: they must only be torn down on the loop that
        created them (see connect_all). Callers on any other loop (e.g. the TUI
        main loop during a reload) skip, because the owning loop's teardown owns
        the cleanup and tearing down cross-loop would raise or leak transports.
        """
        current_loop = asyncio.get_running_loop()
        if self._connection_loop is not None and self._connection_loop is not current_loop:
            self._log_verbose("Skipping disconnect_all: MCP connections live on another event loop")
            return

        # Include servers with a live session that never made it into
        # _connected_servers (e.g. connect_all was cancelled between
        # server.connect() and registering the server).
        if not self._connected_servers and not any(server.is_connected for server in self._servers):
            self._log_verbose("MCP servers already disconnected")
            return

        self._log_verbose("Disconnecting from all MCP servers")

        async def disconnect_server(server: McpServer) -> tuple[McpServer, bool]:
            try:
                await server.disconnect()
                if server.name in self._server_tools:
                    del self._server_tools[server.name]
                self._log_verbose(f"Disconnected from MCP server: {server.name}")
                return (server, True)
            except asyncio.CancelledError:
                # Cancellation is expected during shutdown - anyio cancel scopes
                # used by MCP transports don't play well with asyncio teardown.
                self._log_verbose(f"Disconnect of MCP server {server.name} was cancelled")
                return (server, False)
            except Exception:
                self._log_warning(f"Error disconnected from MCP server: {server.name}")
                return (server, False)

        servers_to_disconnect = [
            server
            for server in self._servers
            if server in self._connected_servers or server.is_connected
        ]
        tasks = [disconnect_server(server) for server in servers_to_disconnect]

        try:
            results = await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            # The whole disconnect was cancelled (e.g. during program shutdown).
            # Treat this as a graceful shutdown instead of crashing the exit path.
            self._log_verbose("MCP disconnect interrupted by shutdown cancellation")
            return

        for server, success in results:
            if success:
                self._connected_servers.discard(server)

    async def connect_server(self, name: str) -> bool:
        """
        Connect to a specific MCP server by name.

        Args:
            name: Name of the server to connect to

        Returns:
            Boolean indicating success or failure
        """

        server = self.get_server(name)
        if not server:
            self._log_warning(f"MCP server not found: {name}")
            return False

        if server in self._connected_servers:
            self._log_verbose(f"MCP server already connected: {name}")
            return True

        # We will handle local server differently since its only used for internal usage
        # We'll pretend we connect and fetched all tools
        if isinstance(server, LocalServer):
            await server.connect()
            self._connected_servers.add(server)
            self._server_tools[server.name] = get_local_tool_schemas()
            return True

        # Retry with exponential backoff for transient connection failures.
        # Note: This also fixes a latent bug where asyncio.CancelledError was
        # silently caught and treated as a connection failure. CancelledError is
        # now re-raised to properly propagate cancellation.
        # When io is None (e.g., during from_servers before IO is assigned),
        # _log_warning and _log_error silently return — retries still happen
        # but with no user-visible feedback. This is intentional.
        max_retries = 3 if server.name != "unnamed-server" else 1
        delay = 1.0
        backoff = 2.0
        max_delay = 30.0

        for attempt in range(1, max_retries + 1):
            try:
                session = await server.connect()
                tools_result = await session.list_tools()
                tools = _mcp_tools_to_openai_tools(tools_result.tools)
                self._server_tools[server.name] = tools
                self._connected_servers.add(server)
                self._log_verbose(f"Connected to MCP server: {name}")
                return True
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if attempt < max_retries and server.name != "unnamed-server":
                    self._log_warning(
                        f"Connection attempt {attempt} failed for {name}, "
                        f"retrying in {delay}s... ({e})"
                    )

                    await asyncio.sleep(delay)
                    delay = min(delay * backoff, max_delay)
                else:
                    if server.name != "unnamed-server":
                        self._log_error(
                            f"Failed to connect to MCP server {name} "
                            f"after {max_retries} attempts: {e}"
                        )
                    if server.is_connected:
                        # Session was established but tool listing failed; tear
                        # it down so the transport/subprocess doesn't leak.
                        await server.disconnect()
                    return False

    async def disconnect_server(self, name: str) -> bool:
        """
        Disconnect from a specific MCP server by name.

        Args:
            name: Name of the server to disconnect from

        Returns:
            Boolean indicating success or failure
        """
        server = self.get_server(name)
        if not server:
            self._log_warning(f"MCP server not found: {name}")
            return False

        if server not in self._connected_servers:
            self._log_verbose(f"MCP server not connected: {name}")
            return True

        try:
            await server.disconnect()
            if server.name in self._server_tools:
                del self._server_tools[server.name]
            self._connected_servers.remove(server)
            self._log_verbose(f"Disconnected from MCP server: {name}")
            return True
        except Exception as e:
            self._log_warning(f"Error disconnecting from MCP server {name}: {e}")
            return False

    async def add_server(self, server: McpServer, connect: bool = False) -> bool:
        """
        Add a new MCP server to the manager.

        Args:
            server: McpServer instance to add
            connect: Whether to immediately connect to the server

        Returns:
            Boolean indicating success or failure
        """
        existing_server = self.get_server(server.name)
        if existing_server:
            if server.name.lower() not in ["unnamed-server", "local"]:
                self._log_warning(f"MCP server with name '{server.name}' already exists")
            return False

        self._servers.append(server)
        self._log_verbose(f"Added MCP server: {server.name}")

        if connect:
            return await self.connect_server(server.name)

        return True

    @property
    def connected_servers(self) -> list["McpServer"]:
        """Get the list of successfully connected servers."""
        return list(self._connected_servers)

    @property
    def failed_servers(self) -> list["McpServer"]:
        """Get the list of servers that failed to connect."""
        return [server for server in self._servers if server not in self._connected_servers]

    def __iter__(self):
        for server in self._servers:
            yield server

    def get_server_tools(self, name: str) -> list:
        """
        Get the tools for a specific server.

        Args:
            name: Name of the server

        Returns:
            List of tools or empty list if server not found or not connected
        """
        return self._server_tools.get(name, list())

    @property
    def all_tools(self) -> dict[str, list]:
        """
        Get all tools from all connected servers.

        Returns:
            Dictionary mapping server names to their tools
        """
        return self._server_tools.copy()

    @classmethod
    async def from_servers(
        cls, servers: list[McpServer], io=None, verbose: bool = False
    ) -> "McpServerManager":
        """
        Create an MCP Server Manager from a list of servers it should manage.
        Automatically connects if the server is set to auto connect (by default it is)
        """
        mcp_manager = cls(servers=servers, io=io, verbose=verbose)
        await mcp_manager.connect_all()

        return mcp_manager

    async def connect_all(self) -> None:
        """
        Connect all configured servers that are enabled (default) and populate their tools.

        Runs on whatever event loop calls it. In TUI mode the coder runs on the worker
        thread's event loop (CoderWorker), so callers should invoke this from the coder's
        loop — otherwise loop-bound MCP state (sessions, asyncio locks, keepalive tasks)
        is created on one loop and migrated to another on first use, which can raise or
        hang.
        """
        self._connection_loop = asyncio.get_running_loop()

        async def _connect(server: McpServer) -> tuple[McpServer, bool, bool]:
            if not server.config.get("enabled", True):
                # Disabled servers are registered but intentionally not connected.
                return (server, False, False)

            success = await self.connect_server(server.name)

            return (server, success, True)

        results = await asyncio.gather(*(_connect(server) for server in self._servers))

        for server, did_connect, attempted in results:
            if (
                attempted
                and not did_connect
                and server.name.lower() not in ["unnamed-server", "local"]
            ):
                self._log_warning(
                    f"MCP tool initialization failed after multiple retries: {server.name}"
                )

        if self.verbose and self.io:
            self.io.tool_output("MCP servers configured:")

            for server, _did_connect, _attempted in results:
                self.io.tool_output(f"  - {server.name}")

                for tool in self.get_server_tools(server.name):
                    tool_name = tool.get("function", {}).get("name", "unknown")
                    tool_desc = tool.get("function", {}).get("description", "").split("\n")[0]
                    self.io.tool_output(f"    - {tool_name}: {tool_desc}")

    async def spawn_child(self, io=None) -> "McpServerManager":
        """Create a new, independent manager for a sub-agent.

        Rebuilds fresh McpServer instances from this manager's server configs
        so the sub-agent sees the same full set of servers it can include or
        exclude (via registered_servers), but with its own connections that
        can be torn down together with the sub-agent instead of being shared
        with the parent. The "Local" server is deliberately left out so
        AgentCoder.initialize_mcp_tools() can create and connect its own
        instance and rebuild the tool list from the sub-agent's own filters
        (the parent may exclude tools a child opts into).
        """
        server_io = io if io is not None else self.io
        servers = [
            _recreate_server(server, io=server_io, verbose=self.verbose)
            for server in self._servers
            if not isinstance(server, LocalServer)
        ]

        child = McpServerManager(servers=servers, io=server_io, verbose=self.verbose)
        child._connection_loop = asyncio.get_running_loop()

        # Mirror the parent's connected set, but with independent connections so
        # the child can be disconnected without affecting the parent.
        connected_names = {
            server.name
            for server in self._servers
            if server in self._connected_servers or server.is_connected
        }
        for server in servers:
            if server.name in connected_names:
                try:
                    await child.connect_server(server.name)
                except Exception as exc:
                    child._log_warning(
                        f"Failed to connect MCP server {server.name} for sub-agent: {exc}"
                    )

        return child


def get_local_tool_schemas():
    """Returns the JSON schemas for all local tools using the tool registry."""
    schemas = []
    for tool_name in ToolRegistry.get_registered_tools():
        tool_module = ToolRegistry.get_tool(tool_name)
        if hasattr(tool_module, "SCHEMA"):
            schemas.append(tool_module.SCHEMA)
    return schemas


def _mcp_tool_input_schema(tool):
    """Return the input schema of an mcp Tool across SDK versions.

    mcp SDK 1.x names the field inputSchema; SDK 2.x renamed it to
    input_schema.
    """
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = getattr(tool, "inputSchema", None)
    return schema


def _normalize_mcp_input_schema(input_schema):
    """Normalize an MCP input schema for OpenAI function calling.

    OpenAI requires function parameters to have type 'object', a
    properties dict, and (recommended) additionalProperties: false.
    Mirrors litellm's _normalize_mcp_input_schema.
    """
    if not input_schema:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    normalized = dict(input_schema)
    if "type" not in normalized:
        normalized["type"] = "object"
    if "properties" not in normalized:
        normalized["properties"] = {}
    if "additionalProperties" not in normalized:
        normalized["additionalProperties"] = False
    return normalized


def _mcp_tools_to_openai_tools(tools):
    """Convert a list of mcp Tool objects to OpenAI 'tools' JSON dicts.

    Uses the SDK's own session.list_tools() output and converts to the
    standard OpenAI chat tools format. Version-aware: mcp SDK 2.x renamed
    Tool.inputSchema to input_schema.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": _normalize_mcp_input_schema(_mcp_tool_input_schema(tool)),
                "strict": False,
            },
        }
        for tool in tools
    ]


def _recreate_server(server, io=None, verbose=False):
    """Rebuild a fresh McpServer of the same type/config as an existing one."""
    import copy

    config = copy.deepcopy(server.config)
    return type(server)(config, io=io, verbose=verbose)
