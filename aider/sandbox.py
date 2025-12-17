"""
Subprocess sandboxing for aider.

Protects against accidental damage from AI-generated shell commands
by restricting filesystem access, network, and secrets.
"""

import os
import sys
from typing import Optional

# Try to import bubbleproc - it's optional
try:
    import bubbleproc
    SANDBOX_AVAILABLE = True
except ImportError:
    SANDBOX_AVAILABLE = False

_enabled = False


def get_env_passthrough() -> list[str]:
    """Environment variables to pass through to sandboxed processes."""
    return [
        # API Keys (all providers aider supports)
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "AZURE_API_KEY",
        "AZURE_API_BASE",
        "AZURE_API_VERSION",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "VERTEX_PROJECT",
        "VERTEX_LOCATION",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "COHERE_API_KEY",
        "MISTRAL_API_KEY",
        "OLLAMA_API_BASE",
        "OPENAI_API_BASE",
        "OPENAI_API_TYPE",
        "OPENAI_API_VERSION",
        "OPENAI_ORGANIZATION",
        
        # Git configuration
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_SSH_COMMAND",
        "GIT_ASKPASS",
        "GIT_TERMINAL_PROMPT",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_EXEC_PATH",
        
        # Terminal/Display
        "TERM",
        "COLORTERM",
        "CLICOLOR",
        "FORCE_COLOR",
        "NO_COLOR",
        "COLUMNS",
        "LINES",
        
        # Aider configuration
        "AIDER_MODEL",
        "AIDER_OPUS",
        "AIDER_SONNET",
        "AIDER_DARK_MODE",
        "AIDER_LIGHT_MODE",
        "AIDER_AUTO_COMMITS",
        "AIDER_DIRTY_COMMITS",
        "AIDER_GITIGNORE",
        "AIDER_LINT_CMD",
        "AIDER_TEST_CMD",
        "AIDER_AUTO_LINT",
        "AIDER_AUTO_TEST",
        "AIDER_VERBOSE",
        "AIDER_SHOW_DIFFS",
        
        # Python/System
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "CONDA_DEFAULT_ENV",
        "CONDA_PREFIX",
        
        # Editor
        "EDITOR",
        "VISUAL",
        
        # Proxy settings
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        
        # SSL
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    ]


def enable_sandbox(
    project_dir: str,
    io=None,
    network: bool = True,
    allow_gpg: bool = False,
    allow_ssh: bool = False,
    extra_rw: Optional[list[str]] = None,
    verbose: bool = False,
) -> bool:
    """
    Enable subprocess sandboxing.
    
    Args:
        project_dir: The project directory (git root) to allow writes to
        io: Aider IO object for output (optional)
        network: Allow network access (required for API calls)
        allow_gpg: Allow access to ~/.gnupg for signed commits
        allow_ssh: Allow access to ~/.ssh for git operations
        extra_rw: Additional read-write paths
        verbose: Show sandbox configuration
        
    Returns:
        True if sandbox was enabled, False otherwise
    """
    global _enabled
    
    if _enabled:
        return True
    
    if not SANDBOX_AVAILABLE:
        if io:
            io.tool_warning(
                "Sandboxing requested but 'bubbleproc' is not installed. "
                "Install with: pip install bubbleproc"
            )
        return False
    
    # Build list of read-write paths
    rw_paths = [project_dir]
    
    # Add /tmp for temp files
    rw_paths.append("/tmp")
    
    # Add virtualenv if active
    if venv := os.environ.get("VIRTUAL_ENV"):
        rw_paths.append(venv)
    
    # Add any extra paths
    if extra_rw:
        rw_paths.extend(extra_rw)
    
    # Build list of allowed secret paths
    allow_secrets = []
    if allow_gpg:
        allow_secrets.append(".gnupg")
    if allow_ssh:
        allow_secrets.append(".ssh")
    
    try:
        bubbleproc.patch_subprocess(
            rw=rw_paths,
            network=network,
            share_home=True,
            env_passthrough=get_env_passthrough(),
            allow_secrets=allow_secrets,
        )
        _enabled = True
        
        if verbose and io:
            io.tool_output("Sandbox enabled:")
            io.tool_output(f"   Project dir: {project_dir}")
            io.tool_output(f"   Network: {'enabled' if network else 'disabled'}")
            io.tool_output(f"   RW paths: {rw_paths}")
            if allow_secrets:
                io.tool_output(f"   Allowed secrets: {allow_secrets}")
        elif io:
            io.tool_output(f"Sandbox enabled for: {project_dir}")
            
        return True
        
    except Exception as e:
        if io:
            io.tool_error(f"Failed to enable sandbox: {e}")
        return False


def disable_sandbox():
    """Disable subprocess sandboxing."""
    global _enabled
    
    if not _enabled or not SANDBOX_AVAILABLE:
        return
    
    bubbleproc.unpatch_subprocess()
    _enabled = False


def is_enabled() -> bool:
    """Check if sandboxing is currently enabled."""
    return _enabled