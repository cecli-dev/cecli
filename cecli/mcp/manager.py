import logging

from cecli.mcp.server import McpServer
from cecli.mcp.utils import load_mcp_servers


class McpServerManager:
    """
    Centralized manager for MCP server connections.

    Handles connection lifecycle for all MCP servers, ensuring
    connections are established once and reused across all Coder instances.
    """

    def __init__(
        self,
        mcp_servers: str | None = None,
        mcp_servers_file: str | None = None,
        io=None,
        verbose: bool = False,
        mcp_transport: str = "stdio",
    ):
        """
        Initialize the MCP server manager.

        Args:
            mcp_servers: JSON string containing MCP server configurations
            mcp_servers_file: Path to a JSON file containing MCP server configurations
            io: InputOutput instance for user interaction
            verbose: Whether to output verbose logging
            mcp_transport: Default transport type for MCP servers
        """
        self.io = io
        self.verbose = verbose
        self._servers: list["McpServer"] = []
        self._connected = False

        self._servers = load_mcp_servers(mcp_servers, mcp_servers_file, io, verbose, mcp_transport)

    @property
    def servers(self) -> list["McpServer"]:
        """Get the list of managed MCP servers."""
        return self._servers

    @property
    def is_connected(self) -> bool:
        """Check if servers are connected."""
        return self._connected

    def get_server(self, name: str) -> McpServer | None:
        """
        Get a server by name.

        Args:
            name: Name of the server to retrieve

        Returns:
            The server instance or None if not found
        """
        try:
            return next(server for server in self._servers if server.name == name)
        except StopIteration:
            return None

    async def connect_all(self) -> None:
        """Connect to all MCP servers."""
        if self._connected:
            if self.verbose and self.io:
                self.io.tool_output("MCP servers already connected")
            return

        if self.verbose and self.io:
            self.io.tool_output(f"Connecting to {len(self._servers)} MCP servers")

        for server in self._servers:
            try:
                await server.connect()
                if self.verbose and self.io:
                    self.io.tool_output(f"Connected to MCP server: {server.name}")
            except Exception as e:
                logging.error(f"Error connecting to MCP server {server.name}: {e}")
                if self.io:
                    self.io.tool_error(f"Failed to connect to MCP server {server.name}: {e}")

        self._connected = True

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        if not self._connected:
            if self.verbose and self.io:
                self.io.tool_output("MCP servers already disconnected")
            return

        if self.verbose and self.io:
            self.io.tool_output("Disconnecting from all MCP servers")

        for server in self._servers:
            try:
                await server.disconnect()
                if self.verbose and self.io:
                    self.io.tool_output(f"Disconnected from MCP server: {server.name}")
            except Exception as e:
                logging.error(f"Error disconnecting from MCP server {server.name}: {e}")

        self._connected = False

    def __iter__(self):
        for server in self._servers:
            yield server
