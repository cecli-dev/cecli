"""Browser-harness CDP integration helpers.

browser-harness drives a running Chrome/Chromium over the Chrome DevTools
Protocol. It reads the endpoint from ``BU_CDP_URL``, so cecli detects or
launches a CDP-enabled browser and exports that variable before running a
browser-harness command. Browser settings can override the endpoint, launch
command, port, profile directory, and headless mode.
"""

import http.client
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

BROWSER_HARNESS_COMMAND = "browser-harness"
CDP_URL_ENV = "BU_CDP_URL"
DEFAULT_CDP_PORT = 9222
DEFAULT_CDP_PORTS = (9222, 9223, 9224, 9225)
DEFAULT_LAUNCH_TIMEOUT = 10.0
LAUNCH_COOLDOWN_SECONDS = 30.0

_BROWSER_HARNESS_PATTERN = re.compile(
    r"(?:^|[;&|()]\s*)"
    r"(?:(?:sudo|doas|exec|env|nohup|time|nice|uvx)\s+|timeout\s+\d+\s+"
    r"|[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
    r"browser[-_]harness\b",
    re.MULTILINE,
)

_last_launch_attempt = 0.0


def is_browser_harness_available():
    """Return True when the browser-harness CLI is installed."""
    return shutil.which(BROWSER_HARNESS_COMMAND) is not None


def is_browser_harness_command(command):
    """Return True when a shell command invokes the browser-harness CLI."""
    if not command:
        return False

    return _BROWSER_HARNESS_PATTERN.search(command) is not None


def parse_browser_config(value):
    """Parse a browser config mapping from a dict, JSON/YAML string, or file path."""
    import json

    import yaml

    if not value:
        return {}

    if isinstance(value, dict):
        return dict(value)

    if not isinstance(value, str):
        return {}

    stripped = value.strip()
    if not stripped:
        return {}

    for parser in (json.loads, yaml.safe_load):
        try:
            parsed = parser(stripped)
        except (json.JSONDecodeError, yaml.YAMLError, TypeError, ValueError):
            continue

        if isinstance(parsed, dict):
            return parsed

    try:
        path = Path(stripped).expanduser()
    except (OSError, RuntimeError, ValueError):
        return {}
    if path.is_file():
        try:
            parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                return parsed
        except (OSError, yaml.YAMLError):
            pass

    return {}


def get_browser_config(browser_config=None):
    """Return normalized browser settings from config and the environment."""
    config = parse_browser_config(browser_config)

    return {
        "cdp_url": config.get("cdp_url"),
        "env_cdp_url": os.environ.get(CDP_URL_ENV),
        "port": _as_int(config.get("port"), DEFAULT_CDP_PORT),
        "user_data_dir": config.get("user_data_dir") or default_user_data_dir(),
        "launch_command": config.get("launch_command"),
        "launch": _as_bool(config.get("launch"), True),
        "headless": _as_bool(config.get("headless"), False),
        "launch_timeout": _as_float(config.get("launch_timeout"), DEFAULT_LAUNCH_TIMEOUT),
        "harness_timeout": _as_float(config.get("harness_timeout"), 30.0),
    }


def default_user_data_dir():
    """Return the persistent Chrome profile directory used for cecli launches."""
    configured = os.environ.get("CECLI_BROWSER_PROFILE_DIR")
    if configured:
        return configured

    try:
        home = Path.home()
    except RuntimeError:
        # ``Path.home()`` raises when HOME/USERPROFILE are unset (for example in
        # a stripped-down environment). Fall back to a temporary location so the
        # browser helpers stay usable instead of aborting.
        home = Path(tempfile.gettempdir())

    return str(home / ".cecli" / "browser-profile")


def cdp_available(cdp_url, timeout=1.0):
    """Return True when a Chrome DevTools endpoint answers at cdp_url."""
    if not cdp_url:
        return False

    parsed = urllib.parse.urlparse(cdp_url)
    if not parsed.hostname:
        return False

    connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)
    path = parsed.path.rstrip("/") + "/json/version"
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return 200 <= response.status < 300
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def ensure_cdp_url(browser_config=None, launch=None, headless=None):
    """Resolve a CDP endpoint, optionally launching a browser when none exists."""
    config = get_browser_config(browser_config)

    if config["cdp_url"]:
        return config["cdp_url"]

    env_cdp_url = config["env_cdp_url"]
    if env_cdp_url and cdp_available(env_cdp_url):
        return env_cdp_url

    existing = find_existing_cdp_url(config)
    if existing:
        return existing

    if launch is None:
        launch = config["launch"]

    launched = launch_cdp_browser(config, headless=headless) if launch else None
    if launched:
        return launched

    return env_cdp_url


def find_active_cdp_url(browser_config=None, include_default_ports=False):
    """Return a live CDP endpoint without launching a browser."""
    config = get_browser_config(browser_config)

    if config["cdp_url"]:
        return config["cdp_url"]

    env_cdp_url = config["env_cdp_url"]
    if env_cdp_url and cdp_available(env_cdp_url, timeout=0.25):
        return env_cdp_url

    ports = [config["port"]]
    active_port = _read_active_port(config["user_data_dir"])
    if active_port:
        ports.append(active_port)
    if include_default_ports:
        ports.extend(DEFAULT_CDP_PORTS)

    for port in dict.fromkeys(ports):
        cdp_url = build_cdp_url(port=port)
        if cdp_available(cdp_url, timeout=0.25):
            return cdp_url

    return None


def export_active_cdp_url(browser_config=None, include_default_ports=False):
    """Export BU_CDP_URL when a live browser already exists."""
    cdp_url = find_active_cdp_url(browser_config, include_default_ports=include_default_ports)
    if cdp_url:
        os.environ[CDP_URL_ENV] = cdp_url

    return cdp_url


def find_existing_cdp_url(config=None):
    """Probe the configured port and common Chrome debugging ports."""
    config = config or get_browser_config()
    ports = [config["port"]]

    active_port = _read_active_port(config["user_data_dir"])
    if active_port:
        ports.append(active_port)

    ports.extend(DEFAULT_CDP_PORTS)

    seen = set()
    for port in ports:
        if port in seen:
            continue

        seen.add(port)
        cdp_url = build_cdp_url(port=port)
        if cdp_available(cdp_url, timeout=0.4):
            return cdp_url

    return None


def launch_cdp_browser(config=None, headless=None):
    """Launch a CDP-enabled browser and wait for its DevTools endpoint."""
    global _last_launch_attempt

    config = config or get_browser_config()
    now = time.monotonic()
    if now - _last_launch_attempt < LAUNCH_COOLDOWN_SECONDS:
        return None

    command, use_shell = build_launch_command(config, headless=headless)
    if not command:
        return None

    _last_launch_attempt = now

    try:
        Path(config["user_data_dir"]).mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            command,
            shell=use_shell,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return None

    cdp_url = build_cdp_url(port=config["port"])
    deadline = time.monotonic() + config["launch_timeout"]
    while time.monotonic() < deadline:
        if cdp_available(cdp_url, timeout=0.5):
            return cdp_url

        time.sleep(0.2)

    return None


def build_launch_command(config=None, headless=None):
    """Return ``(command, use_shell)`` for launching a CDP-enabled browser."""
    config = config or get_browser_config()
    use_headless = config["headless"] if headless is None else headless

    if config["launch_command"]:
        try:
            command = config["launch_command"].format(
                port=config["port"],
                user_data_dir=config["user_data_dir"],
                profile_dir=config["user_data_dir"],
                headless="--headless=new" if use_headless else "",
                url="about:blank",
            )
        except (KeyError, IndexError, ValueError):
            command = config["launch_command"]

        return command, True

    executable = find_browser_executable()
    if not executable:
        return None, False

    command = [
        executable,
        f"--remote-debugging-port={config['port']}",
        f"--user-data-dir={config['user_data_dir']}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if use_headless:
        command.append("--headless=new")

    command.append("about:blank")

    return command, False


def find_browser_executable():
    """Return a known Chrome/Chromium/Edge executable path when available."""
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
        "microsoft-edge",
        "microsoft-edge-stable",
        "brave-browser",
        "vivaldi",
    ]

    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path

    absolute_candidates = _absolute_browser_candidates()
    for candidate in absolute_candidates:
        if os.path.isfile(candidate):
            return candidate

    return None


def browser_harness_env(browser_config=None, headless=None):
    """Return an environment with BU_CDP_URL set when a CDP browser is available."""
    env = os.environ.copy()
    cdp_url = ensure_cdp_url(browser_config, headless=headless)
    if cdp_url:
        env[CDP_URL_ENV] = cdp_url

    return env


def configure_browser_environment(browser_config=None, command=None, headless=None):
    """Set BU_CDP_URL in os.environ for browser-harness shell commands.

    When ``command`` is provided, browser-harness invocations trigger detection
    or launch. Other commands still export an endpoint when a live browser
    already exists, without opening a new one. Passing ``None`` always resolves
    an endpoint, which is useful for the scraper.
    """
    if command is not None and not is_browser_harness_command(command):
        return export_active_cdp_url(browser_config) or os.environ.get(CDP_URL_ENV)

    cdp_url = ensure_cdp_url(browser_config, headless=headless)
    if cdp_url:
        os.environ[CDP_URL_ENV] = cdp_url

    return cdp_url


def build_cdp_url(host="127.0.0.1", port=DEFAULT_CDP_PORT):
    """Build the HTTP DevTools endpoint URL for a host and port."""
    return f"http://{host}:{port}"


def _read_active_port(user_data_dir):
    """Read the port Chrome writes to DevToolsActivePort in a profile dir."""
    try:
        content = (Path(user_data_dir) / "DevToolsActivePort").read_text(encoding="utf-8")
        return int(content.splitlines()[0].strip())
    except (OSError, ValueError, IndexError):
        return None


def _absolute_browser_candidates():
    """Return platform-specific browser paths for common install locations."""
    system = platform.system()

    if system == "Darwin":
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]

    if system == "Windows":
        roots = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        relative = [
            ("Google", "Chrome", "Application", "chrome.exe"),
            ("Chromium", "Application", "chrome.exe"),
            ("Microsoft", "Edge", "Application", "msedge.exe"),
            ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        ]

        return [str(Path(root).joinpath(*parts)) for root in roots if root for parts in relative]

    return [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        "/usr/bin/microsoft-edge",
        "/usr/bin/brave-browser",
    ]


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default):
    if value is None:
        return default

    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off")

    return bool(value)
