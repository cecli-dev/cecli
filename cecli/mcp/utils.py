import base64
import hashlib
import json
import secrets
import socketserver
from pathlib import Path

from .server import McpServer


def find_available_port(start_port=8484, end_port=8584):
    """Find an available port in the given range."""
    for port in range(start_port, end_port + 1):
        try:
            # Check if the port is available by trying to bind to it
            with socketserver.TCPServer(("localhost", port), None):
                return port
        except OSError:
            # Port is likely already in use
            continue
    return None


def generate_pkce_codes():
    """Generate PKCE code verifier and challenge."""
    code_verifier = secrets.token_urlsafe(64)
    hasher = hashlib.sha256()
    hasher.update(code_verifier.encode("utf-8"))
    code_challenge = base64.urlsafe_b64encode(hasher.digest()).rstrip(b"=").decode("utf-8")
    return code_verifier, code_challenge


def _parse_mcp_servers_from_json_string(json_string, io, verbose=False, mcp_transport="stdio"):
    """Parse MCP servers from a JSON string."""
    from .server import HttpStreamingServer, McpServer, SseServer

    servers = []

    try:
        config = json.loads(json_string)
        if verbose:
            io.tool_output("Loading MCP servers from provided JSON")

        if "mcpServers" in config:
            for name, server_config in config["mcpServers"].items():
                if verbose:
                    io.tool_output(f"Loading MCP server: {name}")

                # Create a server config with name included
                server_config["name"] = name
                transport = server_config.get("transport", mcp_transport)
                if transport == "stdio":
                    servers.append(McpServer(server_config, io=io, verbose=verbose))
                elif transport == "http":
                    servers.append(HttpStreamingServer(server_config, io=io, verbose=verbose))
                elif transport == "sse":
                    servers.append(SseServer(server_config, io=io, verbose=verbose))

            if verbose:
                io.tool_output(f"Loaded {len(servers)} MCP servers")
            return servers
        else:
            io.tool_warning("No 'mcpServers' key found in MCP config")
    except json.JSONDecodeError:
        io.tool_error("Invalid JSON in MCP config")
    except Exception as e:
        io.tool_error(f"Error loading MCP config: {e}")

    return servers


def _resolve_mcp_config_path(file_path, io, verbose=False):
    """Resolve MCP config file path relative to closest cecli.conf.yml, git directory, or CWD."""
    if not file_path:
        return None

    # If the path is absolute or already exists, use it as-is
    path = Path(file_path)
    if path.is_absolute() or path.exists():
        return str(path.resolve())

    # Search for the closest cecli.conf.yml in parent directories
    current_dir = Path.cwd()
    conf_path = None

    for parent in [current_dir] + list(current_dir.parents):
        conf_file = parent / ".cecli.conf.yml"
        if conf_file.exists():
            conf_path = parent
            break

    # If cecli.conf.yml found, try relative to that directory
    if conf_path:
        resolved_path = conf_path / file_path
        if resolved_path.exists():
            if verbose:
                io.tool_output(f"Resolved MCP config relative to cecli.conf.yml: {resolved_path}")
            return str(resolved_path.resolve())

    # Try to find git root directory
    git_root = None
    try:
        import git

        repo = git.Repo(search_parent_directories=True)
        git_root = Path(repo.working_tree_dir)
    except (ImportError, git.InvalidGitRepositoryError, FileNotFoundError):
        pass

    # If git root found, try relative to that directory
    if git_root:
        resolved_path = git_root / file_path
        if resolved_path.exists():
            if verbose:
                io.tool_output(f"Resolved MCP config relative to git root: {resolved_path}")
            return str(resolved_path.resolve())

    # Finally, try relative to current working directory
    resolved_path = current_dir / file_path
    if resolved_path.exists():
        if verbose:
            io.tool_output(f"Resolved MCP config relative to CWD: {resolved_path}")
        return str(resolved_path.resolve())

    # If none found, return the original path (will trigger FileNotFoundError)
    return str(path.resolve())


def _parse_mcp_servers_from_file(file_path, io, verbose=False, mcp_transport="stdio"):
    """Parse MCP servers from a JSON file."""
    # Resolve the file path relative to closest cecli.conf.yml, git directory, or CWD
    resolved_file_path = _resolve_mcp_config_path(file_path, io, verbose)

    try:
        with open(resolved_file_path, "r") as f:
            json_string = f.read()

        if verbose:
            io.tool_output(f"Loading MCP servers from file: {file_path}")

        return _parse_mcp_servers_from_json_string(json_string, io, verbose, mcp_transport)

    except FileNotFoundError:
        io.tool_warning(f"MCP config file not found: {file_path}")
    except Exception as e:
        io.tool_error(f"Error reading MCP config file: {e}")

    return []


def load_mcp_servers(
    mcp_servers, mcp_servers_file, io, verbose=False, mcp_transport="stdio"
) -> list["McpServer"]:
    """Load MCP servers from a JSON string or file."""
    servers = []

    # First try to load from the JSON string (preferred)
    if mcp_servers:
        servers = _parse_mcp_servers_from_json_string(mcp_servers, io, verbose, mcp_transport)
        if servers:
            return servers

    # If JSON string failed or wasn't provided, try the file
    if mcp_servers_file:
        servers = _parse_mcp_servers_from_file(mcp_servers_file, io, verbose, mcp_transport)

    if not servers:
        # A default MCP server is actually now necessary for the overall agentic loop
        # and a dummy server does suffice for the job
        # because I am not smart enough to figure out why
        # on coder switch, the agent actually initializes the prompt area twice
        # once immediately after input for the old coder
        # and immediately again for the new target coder
        # which causes a race condition where we are awaiting a coroutine
        # that can no longer yield control (somehow?)
        # but somehow having to run through the MCP server checks
        # allows control to be yielded again somehow
        # and I cannot figure out just how that is happening
        # and maybe it is actually prompt_toolkit's fault
        # but this hack works swimmingly because ???
        # so sure! why not
        servers = [McpServer(json.loads('{"cecli_default": {}}'), io=io, verbose=verbose)]

    return servers
