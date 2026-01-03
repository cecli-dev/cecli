import http.server
import os
import socketserver
import threading
import time
import webbrowser
from urllib.parse import parse_qs, urlparse

import requests

from cecli import urls
from cecli.io import InputOutput
from cecli.mcp import find_available_port, generate_pkce_codes


def check_openrouter_tier(api_key):
    """
    Checks if the user is on a free tier for OpenRouter.

    Args:
        api_key: The OpenRouter API key to check.

    Returns:
        A boolean indicating if the user is on a free tier (True) or paid tier (False).
        Returns True if the check fails.
    """
    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("is_free_tier", True)
    except Exception:
        return True


def try_to_select_default_model():
    """
    Attempts to select a default model based on available API keys.
    Checks OpenRouter tier status to select appropriate model.

    Returns:
        The name of the selected model, or None if no suitable default is found.
    """
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        is_free_tier = check_openrouter_tier(openrouter_key)
        if is_free_tier:
            return "openrouter/deepseek/deepseek-r1:free"
        else:
            return "openrouter/anthropic/claude-sonnet-4"
    model_key_pairs = [
        ("ANTHROPIC_API_KEY", "sonnet"),
        ("DEEPSEEK_API_KEY", "deepseek"),
        ("OPENAI_API_KEY", "gpt-4o"),
        ("GEMINI_API_KEY", "gemini/gemini-2.5-pro-exp-03-25"),
        ("VERTEXAI_PROJECT", "vertex_ai/gemini-2.5-pro-exp-03-25"),
    ]
    for env_key, model_name in model_key_pairs:
        api_key_value = os.environ.get(env_key)
        if api_key_value:
            return model_name
    return None


async def offer_openrouter_oauth(io):
    """
    Offers OpenRouter OAuth flow to the user if no API keys are found.

    Args:
        io: The InputOutput object for user interaction.

    Returns:
        True if authentication was successful, False otherwise.
    """
    io.tool_output("OpenRouter provides free and paid access to many LLMs.")
    if await io.confirm_ask(
        "Login to OpenRouter or create a free account?", default="y", acknowledge=True
    ):
        openrouter_key = start_openrouter_oauth_flow(io)
        if openrouter_key:
            os.environ["OPENROUTER_API_KEY"] = openrouter_key
            return True
        io.tool_error("OpenRouter authentication did not complete successfully.")
    return False


async def select_default_model(args, io):
    """
    Selects a default model based on available API keys if no model is specified.
    Offers OAuth flow for OpenRouter if no keys are found.

    Args:
        args: The command line arguments object.
        io: The InputOutput object for user interaction.

    Returns:
        The name of the selected model, or None if no suitable default is found.
    """
    if args.model:
        return args.model
    model = try_to_select_default_model()
    if model:
        io.tool_warning(f"Using {model} model with API key from environment.")
        return model
    no_model_msg = "No LLM model was specified and no API keys were provided."
    io.tool_warning(no_model_msg)
    await offer_openrouter_oauth(io)
    model = try_to_select_default_model()
    if model:
        return model
    await io.offer_url(urls.models_and_keys, "Open documentation URL for more info?")


# Function to exchange the authorization code for an API key
def exchange_code_for_key(code, code_verifier, io):
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/auth/keys",
            headers={"Content-Type": "application/json"},
            json={"code": code, "code_verifier": code_verifier, "code_challenge_method": "S256"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        api_key = data.get("key")
        if not api_key:
            io.tool_error("Error: 'key' not found in OpenRouter response.")
            io.tool_error(f"Response: {response.text}")
            return None
        return api_key
    except requests.exceptions.Timeout:
        io.tool_error("Error: Request to OpenRouter timed out during code exchange.")
        return None
    except requests.exceptions.HTTPError as e:
        io.tool_error(
            "Error exchanging code for OpenRouter key:"
            f" {e.response.status_code} {e.response.reason}"
        )
        io.tool_error(f"Response: {e.response.text}")
        return None
    except requests.exceptions.RequestException as e:
        io.tool_error(f"Error exchanging code for OpenRouter key: {e}")
        return None
    except Exception as e:
        io.tool_error(f"Unexpected error during code exchange: {e}")
        return None


def start_openrouter_oauth_flow(io):
    """Initiates the OpenRouter OAuth PKCE flow using a local server."""
    port = find_available_port()
    if not port:
        io.tool_error("Could not find an available port between 8484 and 8584.")
        io.tool_error("Please ensure a port in this range is free, or configure manually.")
        return None
    callback_url = f"http://localhost:{port}/callback/cecli"
    auth_code = None
    server_error = None
    server_started = threading.Event()
    shutdown_server = threading.Event()

    class OAuthCallbackHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code, server_error
            parsed_path = urlparse(self.path)
            if parsed_path.path == "/callback/cecli":
                query_params = parse_qs(parsed_path.query)
                if "code" in query_params:
                    auth_code = query_params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body><h1>Success!</h1><p>cecli has received the authentication"
                        b" code. You can close this browser tab.</p></body></html>"
                    )
                    shutdown_server.set()
                else:
                    self.send_response(302)
                    self.send_header("Location", urls.website)
                    self.end_headers()
            else:
                self.send_response(302)
                self.send_header("Location", urls.website)
                self.end_headers()
                self.wfile.write(b"Not Found")

        def log_message(self, format, *args):
            pass

    def run_server():
        nonlocal server_error
        try:
            with socketserver.TCPServer(("localhost", port), OAuthCallbackHandler) as httpd:
                io.tool_output(f"Temporary server listening on {callback_url}", log_only=True)
                server_started.set()
                while not shutdown_server.is_set():
                    httpd.handle_request()
                    time.sleep(0.1)
                io.tool_output("Shutting down temporary server.", log_only=True)
        except Exception as e:
            server_error = f"Failed to start or run temporary server: {e}"
            server_started.set()
            shutdown_server.set()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    if not server_started.wait(timeout=5):
        io.tool_error("Temporary authentication server failed to start in time.")
        shutdown_server.set()
        server_thread.join(timeout=1)
        return None
    if server_error:
        io.tool_error(server_error)
        shutdown_server.set()
        server_thread.join(timeout=1)
        return None
    code_verifier, code_challenge = generate_pkce_codes()
    auth_url_base = "https://openrouter.ai/auth"
    auth_params = {
        "callback_url": callback_url,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{auth_url_base}?{'&'.join(f'{k}={v}' for k, v in auth_params.items())}"
    io.tool_output("\nPlease open this URL in your browser to connect cecli with OpenRouter:")
    io.tool_output()
    print(auth_url)
    MINUTES = 5
    io.tool_output(f"\nWaiting up to {MINUTES} minutes for you to finish in the browser...")
    io.tool_output("Use Control-C to interrupt.")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    interrupted = False
    try:
        shutdown_server.wait(timeout=MINUTES * 60)
    except KeyboardInterrupt:
        io.tool_warning("\nOAuth flow interrupted.")
        interrupted = True
        shutdown_server.set()
    server_thread.join(timeout=1)
    if interrupted:
        return None
    if server_error:
        io.tool_error(f"Authentication failed: {server_error}")
        return None
    if not auth_code:
        io.tool_error("Authentication with OpenRouter failed.")
        return None
    io.tool_output("Completing authentication...")
    api_key = exchange_code_for_key(auth_code, code_verifier, io)
    if api_key:
        os.environ["OPENROUTER_API_KEY"] = api_key
        try:
            config_dir = os.path.expanduser("~/.cecli")
            os.makedirs(config_dir, exist_ok=True)
            key_file = os.path.join(config_dir, "oauth-keys.env")
            with open(key_file, "a", encoding="utf-8") as f:
                f.write(f'OPENROUTER_API_KEY="{api_key}"\n')
            io.tool_warning("cecli will load the OpenRouter key automatically in future sessions.")
            io.tool_output()
            return api_key
        except Exception as e:
            io.tool_error(f"Successfully obtained key, but failed to save it to file: {e}")
            io.tool_warning("Set OPENROUTER_API_KEY environment variable for this session only.")
            return api_key
    else:
        io.tool_error("Authentication with OpenRouter failed.")
        return None


def main():
    """Main function to test the OpenRouter OAuth flow."""
    print("Starting OpenRouter OAuth flow test...")
    io = InputOutput(
        pretty=True,
        yes=False,
        input_history_file=None,
        chat_history_file=None,
        tool_output_color="BLUE",
        tool_error_color="RED",
    )
    if "OPENROUTER_API_KEY" in os.environ:
        print("Warning: OPENROUTER_API_KEY is already set in environment.")
    api_key = start_openrouter_oauth_flow(io)
    if api_key:
        print("\nOAuth flow completed successfully!")
        print(f"Obtained API Key (first 5 chars): {api_key[:5]}...")
    else:
        print("\nOAuth flow failed or was cancelled.")
    print("\nOpenRouter OAuth flow test finished.")


if __name__ == "__main__":
    main()
