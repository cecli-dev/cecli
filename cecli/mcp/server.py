import asyncio
import logging
import os
import random
import threading
import webbrowser
from contextlib import AsyncExitStack
from enum import Enum, auto
from urllib.parse import urlparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.auth import OAuthClientProvider
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata

from cecli.decoding import safe_open
from cecli.http import httpx

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
        self.name = str(server_config.get("name", "unnamed-server")).lower()
        self.io = io
        self.verbose = verbose
        self.session = None
        self._connection_loop: asyncio.AbstractEventLoop | None = None
        # threading.Lock (not asyncio.Lock): disconnect can be reached from a
        # different event loop than the one that created the connection (TUI
        # worker thread, ReloadProgramSignal), and asyncio.Lock is loop-bound
        # and raises RuntimeError on a different loop. The lock only guards the
        # short _disconnecting check-and-set below (no awaits while held), so a
        # concurrent disconnect on the same loop never blocks the loop thread.
        self._cleanup_lock: threading.Lock = threading.Lock()
        self._disconnecting = False
        # The session (and its transport context) is owned by a single task so
        # the AnyIO task group inside the transport is entered and exited on the
        # same task, no matter which task calls disconnect().
        self.exit_stack = AsyncExitStack()
        self._cancel_keepalive_on_close = True
        self._session_task: asyncio.Task | None = None
        self._session_ready: asyncio.Future | None = None
        self._shutdown_event: asyncio.Event | None = None

    @property
    def is_connected(self) -> bool:
        """Check if this server is currently connected."""
        return self.session is not None

    async def connect(self):
        """Connect to the MCP server and return the session.

        If a session is already active, returns the existing session. Otherwise,
        establishes a new connection and initializes the session.

        The session is owned by a dedicated task that both opens and closes the
        transport, so the AnyIO task group inside the transport context is always
        entered and exited on the same task, regardless of which task later calls
        disconnect().

        Returns:
            ClientSession: The active session if mcp is not disabled
        """
        current_loop = asyncio.get_running_loop()
        if self.session is not None:
            # Event loop affinity check: streams from the transport are bound to
            # the loop that created them. Reconnect if the loop changed.
            if self._connection_loop is current_loop:
                if self.verbose and self.io:
                    self.io.tool_output(f"Using existing session for MCP server: {self.name}")
                return self.session
            if self.verbose and self.io:
                self.io.tool_output(f"Reconnecting MCP server {self.name} (event loop changed)")
            await self.disconnect()

        if self.verbose and self.io:
            self.io.tool_output(f"Establishing new connection to MCP server: {self.name}")

        self._connection_loop = current_loop
        self._shutdown_event = asyncio.Event()
        self._session_ready = current_loop.create_future()
        self._session_task = asyncio.create_task(self._run_session())

        try:
            session = await self._session_ready
        except BaseException:
            await self.disconnect()
            raise

        return session

    async def disconnect(self, cancel_keepalive: bool = True):
        """Disconnect from the MCP server and clean up resources.

        Idempotent and safe to call from any task or thread: only one caller
        performs the teardown; concurrent callers (possibly on another event
        loop) return immediately once the session is marked gone.

        The transport is closed on the session owner task (via a shutdown
        signal), so the AnyIO task group inside the transport's async context is
        exited on the same task that entered it.
        """
        with self._cleanup_lock:
            if self._disconnecting:
                self.session = None
                return
            self._disconnecting = True
            self._cancel_keepalive_on_close = cancel_keepalive

        try:
            task = self._session_task
            if task is not None and not task.done():
                # Retire this task as owner before signalling, so an owner task on
                # another loop won't clear state a newer session has taken over.
                self._session_task = None
                if self._shutdown_event is not None:
                    self._shutdown_event.set()

                try:
                    await asyncio.wait_for(task, timeout=15)
                except asyncio.TimeoutError:
                    task.cancel()
                except RuntimeError:
                    # Session task lives on a different loop; it is torn down there.
                    pass

            elif task is None:
                await self._close_session(cancel_keepalive)
                await self.exit_stack.aclose()
        except (asyncio.CancelledError, RuntimeError, GeneratorExit):
            # Expected during shutdown - anyio cancel scopes don't play
            # well with asyncio teardown. Resources are still cleaned up.
            pass
        except Exception as e:
            logging.error(f"Error during cleanup of server {self.name}: {e}")
        finally:
            self.session = None
            self._connection_loop = None
            self._session_ready = None
            self._shutdown_event = None
            self._disconnecting = False

    async def reconnect(self):
        """Disconnect and reconnect, establishing a fresh session.

        Used when the server has invalidated the current session (e.g., after
        a server restart), as indicated by an HTTP 404 response per the MCP
        protocol specification.

        Returns:
            ClientSession: The new active session
        """
        if self.io:
            self.io.tool_warning(f"MCP session expired for {self.name}, reconnecting...")
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
        from cecli.http import httpx

        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
            return True

        # Some transports wrap the status in the exception message
        exc_str = str(exc).lower()
        if "404" in exc_str and ("session" in exc_str or "not found" in exc_str):
            return True

        return False

    async def _open_session(self):
        """Open the MCP transport and initialize the session.

        All context managers are entered into ``self.exit_stack`` and the active
        session is stored on ``self.session``. This runs on the session owner
        task (see ``_run_session``). Subclasses override this for
        transport-specific setup.

        Returns:
            ClientSession: The initialized session
        """
        command = self.config["command"]

        env = os.environ.copy()
        if self.config.get("env"):
            env.update(self.config["env"])

        server_params = StdioServerParameters(
            command=command,
            args=self.config.get("args"),
            env=env,
        )

        os.makedirs(".cecli/logs/", exist_ok=True)
        with safe_open(".cecli/logs/mcp-errors.log", "w") as err_file:
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params, errlog=err_file)
            )
            read, write = stdio_transport
            session = await self.exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.session = session

        return session

    async def _close_session(self, cancel_keepalive: bool = True):
        """Tear down session-specific resources.

        Always runs on the session owner task, immediately before the transport
        context is closed. Subclasses override to clean up extra state.
        """
        return None

    async def _run_session(self):
        """Own the transport context for the lifetime of the session.

        Opens the transport and session, then blocks until a shutdown is
        requested, then closes the transport. Both the open and the close happen
        in this single task so the AnyIO task group inside the transport context
        (for example ``stdio_client``) is entered and exited on the same task.

        Even when opening fails partway, any contexts already pushed onto
        ``self.exit_stack`` are still closed here, so nothing leaks.
        """
        # This session owns its own transport stack so an older owner task that
        # is still winding down can never close a newer session's contexts.
        exit_stack = AsyncExitStack()
        self.exit_stack = exit_stack

        try:
            try:
                session = await self._open_session()
            except BaseException as exc:
                if not self._session_ready.done():
                    if isinstance(exc, asyncio.CancelledError):
                        # Deliver cancellation as a future cancellation, not as an
                        # exception value, so a connect() caller that never awaits
                        # the future won't trigger a "Future exception was never
                        # retrieved" warning.
                        self._session_ready.cancel()
                    else:
                        logging.error(f"Error initializing server {self.name}: {exc}")
                        self._session_ready.set_exception(exc)

                return

            if not self._session_ready.done():
                self._session_ready.set_result(session)

            await self._shutdown_event.wait()
        except BaseException:
            pass
        finally:
            try:
                await self._close_session(self._cancel_keepalive_on_close)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logging.error(f"Error during cleanup of server {self.name}: {e}")

            try:
                await exit_stack.aclose()
            except (asyncio.CancelledError, RuntimeError, GeneratorExit):
                pass
            except Exception as e:
                logging.error(f"Error during cleanup of server {self.name}: {e}")

            # Only the current owner may clear shared state; if a newer session
            # has taken over, leave its session/loop fields alone.
            if self._session_task is asyncio.current_task():
                self.session = None
                self._connection_loop = None


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
            callback_handler=_get_oauth_callback_handler(get_auth_code),
        )

        return oauth_provider

    def _create_transport(self, url, http_client):
        """
        Create the transport for this server type.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement _create_transport")

    async def _open_session(self):
        url = self.config.get("url")
        headers = self.config.get("headers", {})

        oauth_provider = None
        if not headers:
            oauth_provider = await self._create_oauth_provider()

        http_client_cls = _get_http_client_module().AsyncClient
        http_client = await self.exit_stack.enter_async_context(
            http_client_cls(
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

        read, write = _unpack_transport(transport)

        session = await self.exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.session = session

        await self.start_keepalive()

        if oauth_provider is not None and oauth_provider.context.oauth_metadata:
            token_endpoint = oauth_provider._get_token_endpoint()
            server_info = get_mcp_oauth_token(self.name)
            if "client_info" not in server_info:
                server_info["client_info"] = {}

            server_info["client_info"]["token_endpoint"] = token_endpoint

            save_mcp_oauth_token(self.name, server_info)

        return session

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
                        raise _get_http_client_module().HTTPStatusError(
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

    async def _close_session(self, cancel_keepalive: bool = True):
        if cancel_keepalive and self._keepalive_task:
            self._keepalive_task.cancel()

            try:
                await asyncio.wait_for(self._keepalive_task, timeout=15)
            except asyncio.CancelledError:
                pass

            logger.info(f"Keepalive task stopped for {self.name}")

        if hasattr(self, "_oauth_shutdown"):
            self._oauth_shutdown()

        self._http_client = None


class HttpStreamingServer(HttpBasedMcpServer):
    """HTTP streaming MCP server using mcp.client.streamable_http_client."""

    def _create_transport(self, url, http_client):
        """Create the HTTP streaming transport."""
        return streamable_http_client(url, http_client=http_client)


class SseServer(McpServer):
    """SSE (Server-Sent Events) MCP server using mcp.client.sse_client."""

    async def _open_session(self):
        url = self.config.get("url")
        headers = self.config.get("headers", {})

        sse_transport = await self.exit_stack.enter_async_context(sse_client(url, headers=headers))
        read, write = sse_transport
        session = await self.exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.session = session

        return session


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


def _get_mcp_major_version() -> int:
    """Return the installed mcp SDK major version (1, 2, ...).

    Falls back to 1 if the version cannot be determined.
    """
    try:
        from importlib.metadata import version

        return int(version("mcp").split(".")[0])
    except Exception:
        return 1


def _get_http_client_module():
    """Return the HTTP client module used by the installed mcp SDK.

    mcp SDK 2.x migrated from httpx to httpx2; earlier versions use httpx.

    Note: ``cecli.http.httpx`` aliases ``httpx2`` when mcp SDK 2.x is
    installed, so import the real module here instead of relying on the
    module-level ``httpx`` name (which may be the httpx2 alias).
    """
    if _get_mcp_major_version() >= 2:
        import httpx2

        return httpx2

    import httpx

    return httpx


def _get_oauth_callback_handler(get_auth_code):
    """Return an OAuth callback handler compatible with the installed mcp SDK.

    mcp SDK 1.x expects a callback returning an (auth_code, state) tuple;
    SDK 2.x expects an AuthorizationCodeResult carrying the same fields.
    """
    if _get_mcp_major_version() >= 2:
        from mcp.shared.auth import AuthorizationCodeResult

        async def sdk2_callback_handler() -> AuthorizationCodeResult:
            code, state = await get_auth_code()
            return AuthorizationCodeResult(code=code, state=state)

        return sdk2_callback_handler

    return get_auth_code


def _unpack_transport(transport):
    """Return (read, write) streams from an HTTP transport.

    mcp SDK 1.x yields a 3-tuple (read, write, session_id_getter); SDK 2.x
    yields a 2-tuple (read, write).
    """
    if _get_mcp_major_version() >= 2:
        read, write = transport
    else:
        read, write, _ = transport

    return read, write
