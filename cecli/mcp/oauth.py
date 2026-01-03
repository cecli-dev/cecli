import asyncio
import http.server
import json
import os
import socketserver
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


def create_oauth_callback_server(
    port, path="/callback"
) -> Tuple[Callable[[], Awaitable[Tuple[str, str]]], Callable[[], None]]:
    """
    Create a local HTTP server to handle OAuth callback.

    Returns:
        Tuple of (async callback handler function, shutdown function)
    """
    auth_code = None
    state = None
    server_error = None
    callback_received = threading.Event()
    server = None

    class OAuthCallbackHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code, state, server_error
            parsed_path = urlparse(self.path)

            if parsed_path.path == path:
                query_params = parse_qs(parsed_path.query)
                if "code" in query_params:
                    auth_code = query_params["code"][0]
                    if "state" in query_params:
                        state = query_params["state"][0]

                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body><h1>Success!</h1>"
                        b"<p>Authentication successful. You can close this browser tab.</p>"
                        b"</body></html>"
                    )
                    callback_received.set()
                elif "error" in query_params:
                    error = query_params["error"][0]
                    error_desc = query_params.get("error_description", [""])[0]
                    server_error = f"OAuth error: {error} - {error_desc}"

                    self.send_response(400)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        "<html><body><h1>Authentication Failed</h1>"
                        f"<p>{error}: {error_desc}</p></body></html>".encode()
                    )
                    callback_received.set()
                else:
                    self.send_response(400)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<html><body><h1>Invalid Request</h1></body></html>")
            else:
                self.send_response(404)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Not Found</h1></body></html>")

        def log_message(self, format, *args):
            pass

    # Start server in a separate thread
    def start_server():
        nonlocal server
        try:
            server = socketserver.TCPServer(("localhost", port), OAuthCallbackHandler)
            server.serve_forever()
        except Exception as e:
            server_error = f"Server error: {e}"  # noqa
            callback_received.set()

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Shutdown function
    def shutdown():
        nonlocal server
        if server:
            server.shutdown()
            server = None

    async def get_auth_code() -> Tuple[str, str]:
        # Wait for callback to be received
        MINUTES = 5
        timeout = MINUTES * 60

        start_time = time.time()
        while not callback_received.is_set():
            if time.time() - start_time > timeout:
                shutdown()
                raise Exception(f"OAuth callback timed out after {MINUTES} minutes")

            # Small sleep to avoid busy waiting
            await asyncio.sleep(0.1)

        if server_error:
            shutdown()
            raise Exception(server_error)

        if not auth_code:
            shutdown()
            raise Exception("No authorization code received")

        return auth_code, state

    return get_auth_code, shutdown


def get_token_file_path():
    """Get the path to the MCP OAuth tokens file."""
    config_dir = Path.home() / ".cecli"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "mcp-oauth-tokens.json"


def load_mcp_oauth_tokens():
    """Load stored OAuth tokens from file."""
    token_file = get_token_file_path()
    if not token_file.exists():
        return {}

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            # File might be empty
            return json.load(f) or {}
    except Exception:
        return {}


def save_mcp_oauth_token(server_name, token_data):
    """Save OAuth token for an MCP server."""
    tokens = load_mcp_oauth_tokens()
    tokens[server_name] = token_data

    token_file = get_token_file_path()
    try:
        with open(token_file, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2)
        # Set restrictive permissions (owner read/write only)
        os.chmod(token_file, 0o600)
    except Exception as e:
        raise Exception(f"Failed to save OAuth token: {e}")


def save_mcp_oauth_tokens(tokens_dict):
    """Save all OAuth tokens to file."""
    token_file = get_token_file_path()
    try:
        with open(token_file, "w", encoding="utf-8") as f:
            json.dump(tokens_dict, f, indent=2)
        # Set restrictive permissions (owner read/write only)
        os.chmod(token_file, 0o600)
    except Exception as e:
        raise Exception(f"Failed to save OAuth tokens: {e}")


def get_mcp_oauth_token(server_name):
    """Retrieve stored OAuth token for an MCP server."""
    tokens = load_mcp_oauth_tokens()
    return tokens.get(server_name, {})


class FileBasedTokenStorage(TokenStorage):
    """File-based token storage for MCP OAuth using the SDK's TokenStorage interface."""

    def __init__(self, server_name: str):
        self.server_name = server_name

    async def get_tokens(self) -> Optional[OAuthToken]:
        """Get stored tokens for this server."""
        all_tokens = load_mcp_oauth_tokens()
        server_data = all_tokens.get(self.server_name, {})

        if "tokens" not in server_data:
            return None

        return OAuthToken.model_validate(server_data["tokens"])

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Store tokens for this server."""
        all_tokens = load_mcp_oauth_tokens()

        if self.server_name not in all_tokens:
            all_tokens[self.server_name] = {}

        tokens_dict = tokens.model_dump()
        all_tokens[self.server_name]["tokens"] = tokens_dict
        save_mcp_oauth_tokens(all_tokens)

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        """Get stored client information."""
        all_tokens = load_mcp_oauth_tokens()
        server_data = all_tokens.get(self.server_name, {})

        if "client_info" not in server_data:
            return None

        return OAuthClientInformationFull.model_validate(server_data["client_info"])

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Store client information."""
        all_tokens = load_mcp_oauth_tokens()

        if self.server_name not in all_tokens:
            all_tokens[self.server_name] = {}

        all_tokens[self.server_name]["client_info"] = json.loads(client_info.model_dump_json())
        save_mcp_oauth_tokens(all_tokens)
