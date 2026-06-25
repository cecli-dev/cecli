import asyncio
import logging
import os
import random
import webbrowser
from contextlib import AsyncExitStack
from enum import Enum, auto
from urllib.parse import urlparse

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.auth import OAuthClientProvider
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata

from .oauth import (
    FileBasedTokenStorage,
    create_oauth_callback_server,
    get_mcp_oauth_token,
    save_mcp_oauth_token,
)

MIN_KEEPALIVE_INTERVAL = 5
MAX_KEEPALIVE_INTERVAL = 300
FAILED_PING_THRESHOLD = 3

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    CONNECTED = auto()
    UNHEALTHY = auto()
    DISCONNECTED = auto()


class McpServer:
    """
    A client for MCP servers that provides tools to cecli coders. An McpServer class
    is initialized per configured MCP Server

    Uses the mcp library to create and initialize ClientSession objects.
    """

    def __init__(self, server_config, io=None, verbose=False):
        """Initialize the MCP tool provider.

        Args:
            server_config: Configuration for the MCP server
            io: InputOutput object for user interaction
            verbose: Whether to output verbose logging
        """
        self.config = server_config
        self.name = server_config.get("name", "unnamed-server")
        self.io = io
        self.verbose = verbose
        self.session = None
        self._connection_loop: asyncio.AbstractEventLoop | None = None
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.exit_stack = AsyncExitStack()

    @property
    def is_connected(self) -> bool:
        """Check if this server is currently connected."""
        return self.session is not None

    async def connect(self):
        """Connect to the MCP server and return the session.

        If a session is already active, returns the existing session.
        Otherwise, establishes a new connection and initializes the session.

        Returns:
            ClientSession: The active session if mcp is not disabled
        """
        current_loop = asyncio.get_running_loop()
        if self.session is not None:
            # Event loop affinity check: streams from stdio_client() are bound
            # to the loop that created them.  Reconnect if the loop changed.
            if self._connection_loop is current_loop:
                if self.verbose and self.io:
                    self.io.tool_output(f"Using existing session for MCP server: {self.name}")
                return self.session
            if self.verbose and self.io:
                self.io.tool_output(f"Reconnecting MCP server {self.name} (event loop changed)")
            await self.disconnect()

        if self.verbose and self.io:
            self.io.tool_output(f"Establishing new connection to MCP server: {self.name}")

        command = self.config["command"]

        env = {**os.environ, **self.config["env"]} if self.config.get("env") else None

        server_params = StdioServerParameters(
            command=command,
            args=self.config.get("args"),
            env=env,
        )

        try:
            os.makedirs(".cecli/logs/", exist_ok=True)
            with open(".cecli/logs/mcp-errors.log", "w") as err_file:
                stdio_transport = await self.exit_stack.enter_async_context(
                    stdio_client(server_params, errlog=err_file)
                )
                read, write = stdio_transport
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self.session = session
                self._connection_loop = current_loop
                return session
        except Exception as e:
            logging.error(f"Error initializing server {self.name}: {e}")
            await self.disconnect()
            raise

    async def disconnect(self):
        """Disconnect from the MCP server and clean up resources."""
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
            except (asyncio.CancelledError, RuntimeError, GeneratorExit):
                # Expected during shutdown - anyio cancel scopes don't play
                # well with asyncio teardown. Resources are still cleaned up.
                pass
            except Exception as e:
                logging.error(f"Error during cleanup of server {self.name}: {e}")
            finally:
                self.session = None

    async def reconnect(self):
        """Disconnect and reconnect, establishing a fresh session.

        Used when the server has invalidated the current session (e.g., after
        a server restart), as indicated by an HTTP 404 response per the MCP
        protocol specification.

        Returns:
            ClientSession: The new active session
        """
        if self.io:
            self.io.tool_warning(
                f"MCP session expired for {self.name}, reconnecting..."
            )
        await self.disconnect()
        self.exit_stack = AsyncExitStack()
        return await self.connect()

    @staticmethod
    def is_session_expired_error(exc):
        """Check if an exception indicates an expired MCP session (HTTP 404).

        Per the MCP specification, when a server terminates a session it
        responds with HTTP 404 Not Found.  The client MUST then start a new
        session by sending a new InitializeRequest.

        Args:
            exc: The exception to check

        Returns:
            bool: True if the error indicates a 404 session expiry
        """
        import httpx

        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
            return True

        # Some transports wrap the status in the exception message
        exc_str = str(exc).lower()
        if "404" in exc_str and ("session" in exc_str or "not found" in exc_str):
            return True

        return False

class HttpBasedMcpServer(McpServer):
    """Base class for HTTP-based MCP servers (HTTP streaming and SSE)."""

    def __init__(self, server_config, io=None, verbose=False):
        super().__init__(server_config, io, verbose)
        self._state: ConnectionState = ConnectionState.CONNECTED
        self._failed_pings: int = 0
        self._keepalive_task: asyncio.Task | None = None
        self._http_client: httpx.AsyncClient | None = None

    async def _create_oauth_provider(self):
        """Create an OAuthClientProvider using the MCP SDK."""
        parsed = urlparse(self.config.get("url"))
        server_url = f"{parsed.scheme}://{parsed.netloc}"
        if self.verbose and self.io:
            self.io.tool_output(f"Auto-derived OAuth server URL: {server_url}", log_only=True)

        # Check if we have existing client info with a redirect URI
        server_info = get_mcp_oauth_token(self.name)
        existing_redirect_uri = None

        if "client_info" in server_info and "redirect_uris" in server_info["client_info"]:
            redirect_uris = server_info["client_info"].get("redirect_uris", [])
            if redirect_uris:
                existing_redirect_uri = redirect_uris[0]
                if self.verbose and self.io:
                    self.io.tool_output(
                        f"Found existing redirect URI: {existing_redirect_uri}",
                        log_only=True,
                    )

        from .utils import find_available_port

        # If we have an existing redirect URI, parse it to get the port
        if existing_redirect_uri:
            try:
                parsed_uri = urlparse(existing_redirect_uri)
                port = int(parsed_uri.netloc.split(":")[1])
                if self.verbose and self.io:
                    self.io.tool_output(f"Reusing existing port: {port}", log_only=True)
            except (ValueError, IndexError):
                # If we can't parse the port, find a new one
                port = find_available_port()
        else:
            # No existing redirect URI, find an available port
            port = find_available_port()

        if not port:
            raise Exception("Could not find available port for OAuth callback")

        redirect_uri = f"http://localhost:{port}/callback"

        get_auth_code, shutdown = create_oauth_callback_server(port)

        # Store shutdown function for cleanup
        self._oauth_shutdown = shutdown

        async def handle_redirect(auth_url: str) -> None:
            if self.io:
                self.io.tool_output(f"\nAuthentication required for MCP server: {self.name}")
                self.io.tool_output("\nPlease open this URL in your browser to authenticate:")
                self.io.tool_output(f"\n{auth_url}\n")
                self.io.tool_output("\nWaiting for you to complete authentication...")
                self.io.tool_output("Use Control-C to interrupt.")
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass

        client_metadata = OAuthClientMetadata(
            client_name="Cecli",
            redirect_uris=[redirect_uri],
            grant_types=["authorization_code", "refresh_token"],
        )
        oauth_provider = OAuthClientProvider(
            server_url=server_url,
            client_metadata=client_metadata,
            storage=FileBasedTokenStorage(self.name),
            redirect_handler=handle_redirect,
            callback_handler=get_auth_code,
        )

        return oauth_provider

    def _create_transport(self, url, http_client):
        """
        Create the transport for this server type.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement _create_transport")

    async def connect(self):
        current_loop = asyncio.get_running_loop()
        if self.session is not None:
            if self._connection_loop is current_loop:
                if self.verbose and self.io:
                    self.io.tool_output(f"Using existing session for {self.name}")
                return self.session
            if self.verbose and self.io:
                self.io.tool_output(f"Reconnecting {self.name} (event loop changed)")
            await self.disconnect()

        if self.verbose and self.io:
            self.io.tool_output(f"Establishing new connection to {self.name}")

        try:
            url = self.config.get("url")
            headers = self.config.get("headers", {})
            oauth_provider = await self._create_oauth_provider()

            http_client = await self.exit_stack.enter_async_context(
                httpx.AsyncClient(
                    auth=oauth_provider,
                    follow_redirects=True,
                    headers=headers,
                    timeout=30,
                )
            )
            self._http_client = http_client

            transport = await self.exit_stack.enter_async_context(
                self._create_transport(url, http_client=http_client)
            )

            read, write, _ = transport

            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.session = session
            await self.start_keepalive()
            self._connection_loop = current_loop

            if oauth_provider is not None and oauth_provider.context.oauth_metadata:
                token_endpoint = oauth_provider._get_token_endpoint()
                server_info = get_mcp_oauth_token(self.name)
                if "client_info" not in server_info:
                    server_info["client_info"] = {}

                server_info["client_info"]["token_endpoint"] = token_endpoint

                save_mcp_oauth_token(self.name, server_info)
        except Exception as e:
            logging.error(f"Error initializing {self.name}: {e}")
            await self.disconnect()
            raise

    async def start_keepalive(self):
        """Start the background keepalive loop if configured."""
        interval = self.config.get("keepalive_interval")
        if interval is None:
            return

        try:
            interval = int(interval)
            if not (MIN_KEEPALIVE_INTERVAL <= interval <= MAX_KEEPALIVE_INTERVAL):
                if self.verbose and self.io:
                    self.io.tool_warning(
                        f"Keepalive interval {interval} out of range ({MIN_KEEPALIVE_INTERVAL}-"
                        f"{MAX_KEEPALIVE_INTERVAL}). Ignoring."
                    )
                return
        except (ValueError, TypeError):
            if self.verbose and self.io:
                self.io.tool_warning(f"Invalid keepalive interval {interval}. Must be an integer.")
            return

        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()

        self._keepalive_task = asyncio.create_task(self._keepalive_loop(interval))
        logger.info(f"Keepalive task started for {self.name} (interval: {interval}s)")
        if self.verbose and self.io:
            self.io.tool_output(f"Started keepalive loop for {self.name} (interval: {interval}s)")

    async def _keepalive_loop(self, interval: int):
        """Background loop that sends periodic heartbeats to the MCP server."""
        try:
            while True:
                # Jitter: ±10% to prevent timing analysis
                jitter = interval * 0.1 * (2 * random.random() - 1)
                await asyncio.sleep(interval + jitter)

                if not self._http_client:
                    continue

                try:
                    url = self.config.get("url")
                    headers = self.config.get("headers", {})

                    # Use OPTIONS request as a lightweight heartbeat
                    response = await self._http_client.options(url, headers=headers)
                    if response.status_code == 200:
                        self._state = ConnectionState.CONNECTED
                        self._failed_pings = 0
                    else:
                        raise httpx.HTTPStatusError(
                            f"Unexpected status {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                except Exception:
                    self._failed_pings += 1
                    if self._failed_pings >= FAILED_PING_THRESHOLD:
                        self._state = ConnectionState.DISCONNECTED
                        if self.verbose and self.io:
                            self.io.tool_warning(
                                f"MCP server {self.name} disconnected after {self._failed_pings} failed"
                                " pings. Attempting reconnect..."
                            )
                        await self.reconnect()
                    else:
                        self._state = ConnectionState.UNHEALTHY
                        if self.verbose and self.io:
                            self.io.tool_output(
                                f"MCP server {self.name} unhealthy (ping {self._failed_pings}/{FAILED_PING_THRESHOLD})"
                            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.error(f"Keepalive loop for {self.name} crashed: {e}")

    async def reconnect(self):
        """Attempt to reconnect to the server using exponential backoff."""
        initial_delay = 1
        multiplier = 2
        max_delay = 300

        attempt = 0
        while self._state == ConnectionState.DISCONNECTED:
            delay = min(initial_delay * (multiplier**attempt), max_delay)
            # Jitter: ±20%
            jitter = delay * 0.2 * (2 * random.random() - 1)
            await asyncio.sleep(delay + jitter)

            try:
                if self.verbose and self.io:
                    self.io.tool_output(
                        f"Attempting to reconnect to {self.name} (attempt {attempt + 1})..."
                    )

                # Clean up old session/client without cancelling the keepalive task
                await self.disconnect(cancel_keepalive=False)
                await self.connect()

                self._state = ConnectionState.CONNECTED
                self._failed_pings = 0
                if self.verbose and self.io:
                    self.io.tool_output(f"Successfully reconnected to {self.name}")
                break
            except Exception as e:
                attempt += 1
                if self.verbose and self.io:
                    self.io.tool_warning(
                        f"Reconnection attempt {attempt} failed for {self.name}: {e}"
                    )

    async def disconnect(self, cancel_keepalive: bool = True):
        """Disconnect from the MCP server and clean up resources."""
        async with self._cleanup_lock:
            try:
                if cancel_keepalive and self._keepalive_task:
                    self._keepalive_task.cancel()
                    try:
                        await asyncio.wait_for(self._keepalive_task, timeout=15)
                    except asyncio.CancelledError:
                        pass
                    logger.info(f"Keepalive task stopped for {self.name}")
                if hasattr(self, "_oauth_shutdown"):
                    self._oauth_shutdown()
                await self.exit_stack.aclose()
            except (asyncio.CancelledError, RuntimeError, GeneratorExit):
                # Expected during shutdown - anyio cancel scopes don't play
                # well with asyncio teardown. Resources are still cleaned up.
                pass
            except Exception as e:
                logging.error(f"Error during cleanup of server {self.name}: {e}")
            finally:
                self.session = None
                self._http_client = None


class HttpStreamingServer(HttpBasedMcpServer):
    """HTTP streaming MCP server using mcp.client.streamable_http_client."""

    def _create_transport(self, url, http_client):
        """Create the HTTP streaming transport."""
        return streamable_http_client(url, http_client=http_client)


class SseServer(McpServer):
    """SSE (Server-Sent Events) MCP server using mcp.client.sse_client."""

    async def connect(self):
        current_loop = asyncio.get_running_loop()
        if self.session is not None:
            if self._connection_loop is current_loop:
                logging.info(f"Using existing session for SSE MCP server: {self.name}")
                return self.session
            logging.info(f"Reconnecting SSE MCP server {self.name} (event loop changed)")
            await self.disconnect()

        logging.info(f"Establishing new connection to SSE MCP server: {self.name}")
        try:
            url = self.config.get("url")
            headers = self.config.get("headers", {})
            sse_transport = await self.exit_stack.enter_async_context(
                sse_client(url, headers=headers)
            )
            read, write = sse_transport
            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.session = session
            self._connection_loop = current_loop
            return session
        except Exception as e:
            logging.error(f"Error initializing SSE server {self.name}: {e}")
            await self.disconnect()
            raise


class LocalServer(McpServer):
    """
    A dummy McpServer for executing local, in-process tools
    that are not provided by an external MCP server.
    """

    async def connect(self):
        """Local tools don't need a connection."""
        if self.session is not None:
            if self.verbose and self.io:
                self.io.tool_output(f"Using existing session for local tools: {self.name}")
            return self.session

        self.session = object()  # Dummy session object
        return self.session

    async def disconnect(self):
        """Disconnect from the MCP server and clean up resources."""
        self.session = None
