import asyncio
import logging
import os
import webbrowser
from contextlib import AsyncExitStack
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
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.exit_stack = AsyncExitStack()

    async def connect(self):
        """Connect to the MCP server and return the session.

        If a session is already active, returns the existing session.
        Otherwise, establishes a new connection and initializes the session.

        Returns:
            ClientSession: The active session
        """
        if self.session is not None:
            if self.verbose and self.io:
                self.io.tool_output(f"Using existing session for MCP server: {self.name}")
            return self.session

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


class HttpBasedMcpServer(McpServer):
    """Base class for HTTP-based MCP servers (HTTP streaming and SSE)."""

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
                        f"Found existing redirect URI: {existing_redirect_uri}", log_only=True
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
        if self.session is not None:
            if self.verbose and self.io:
                self.io.tool_output(f"Using existing session for {self.name}")
            return self.session

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

            transport = await self.exit_stack.enter_async_context(
                self._create_transport(url, http_client=http_client)
            )

            read, write, _ = transport

            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.session = session

            if oauth_provider.context.oauth_metadata:
                token_endpoint = oauth_provider._get_token_endpoint()
                server_info = get_mcp_oauth_token(self.name)
                if "client_info" not in server_info:
                    server_info["client_info"] = {}

                server_info["client_info"]["token_endpoint"] = token_endpoint

                save_mcp_oauth_token(self.name, server_info)

            return session
        except Exception as e:
            logging.error(f"Error initializing {self.name}: {e}")
            await self.disconnect()
            raise

    async def disconnect(self):
        """Disconnect from the MCP server and clean up resources."""
        async with self._cleanup_lock:
            try:
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


class HttpStreamingServer(HttpBasedMcpServer):
    """HTTP streaming MCP server using mcp.client.streamable_http_client."""

    def _create_transport(self, url, http_client):
        """Create the HTTP streaming transport."""
        return streamable_http_client(url, http_client=http_client)


class SseServer(HttpBasedMcpServer):
    """SSE (Server-Sent Events) MCP server using mcp.client.sse_client."""

    def _create_transport(self, url, http_client):
        """Create the SSE transport."""
        return sse_client(url, http_client=http_client)


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
