"""Endpoint configuration for System One decision calls.

An endpoint is described with the same keys cecli uses for custom model
providers (``api_base`` / ``api_key_env`` / ``extra_headers``), so
``--system-one`` and the ``system-one`` config-file key read like a slimmed
down ``model-providers`` entry::

    system-one:
      api_base: "http://127.0.0.1:8000"
      api_key_env: ["LITELLM_API_KEY"]
      model_name: "von-latest"
      extra_headers:
        x-trace-id: "cecli"

With no configuration the defaults are local and vendor neutral: only
``SYSTEM_ONE_*`` environment variables are probed, so pointing the helper at a
hosted service or naming a different API-key variable is always an explicit
configuration choice rather than an implicit fallback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Default endpoint: a locally served ``/v1/systemone`` server.
DEFAULT_API_BASE = "http://127.0.0.1:8000"

#: Path appended to ``api_base`` to reach the evaluation endpoint.
ENDPOINT_PATH = "/v1/systemone"

#: Default model name sent in every request body.
DEFAULT_MODEL_NAME = "von-latest"

#: Environment variable probed for the endpoint base URL.
BASE_URL_ENV_VARS = ("SYSTEM_ONE_API_BASE",)

#: Environment variables probed for the API key, in priority order.
API_KEY_ENV_VARS = ("SYSTEM_ONE_API_KEY",)

#: Environment variable probed for the model name.
MODEL_ENV_VARS = ("SYSTEM_ONE_MODEL",)

#: Request timeout in seconds.
DEFAULT_TIMEOUT = 30.0

#: Accepted spellings for each config key (hyphen/underscore/camel variants).
_KEY_ALIASES: Dict[str, tuple[str, ...]] = {
    "api_base": ("api_base", "api-base", "base_url", "base-url"),
    "api_key_env": ("api_key_env", "api-key-env", "api_key_envs", "apiKeyEnv"),
    "model_name": ("model_name", "model-name", "model", "model_id", "model-id"),
    "extra_headers": ("extra_headers", "extra-headers", "headers", "default_headers"),
    "timeout": ("timeout", "request_timeout", "request-timeout"),
    "max_retries": ("max_retries", "max-retries", "retries"),
}


def _pick(raw: Dict[str, Any], canonical: str) -> Any:
    """Return the first alias present in *raw* for a canonical key."""
    for alias in _KEY_ALIASES.get(canonical, (canonical,)):
        if alias in raw:
            return raw[alias]

    return None


def _first_env(names) -> Optional[str]:
    """Return the first non-empty environment value among *names*."""
    if isinstance(names, str):
        names = [names]

    for name in names or ():
        value = os.environ.get(name)

        if value:
            return value

    return None


@dataclass
class SystemOneConfig:
    """Resolved configuration for one System One endpoint."""

    api_base: str = DEFAULT_API_BASE
    api_key_env: List[str] = field(default_factory=lambda: list(API_KEY_ENV_VARS))
    model_name: str = DEFAULT_MODEL_NAME
    extra_headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = 2

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "SystemOneConfig":
        """Build a config from a user supplied dict, filling gaps from env."""
        defaults = cls.from_env()
        raw = raw if isinstance(raw, dict) else {}

        api_base = _pick(raw, "api_base") or defaults.api_base

        key_env = _pick(raw, "api_key_env")

        if isinstance(key_env, str):
            key_env = [key_env]

        if not key_env:
            key_env = defaults.api_key_env

        model_name = _pick(raw, "model_name") or defaults.model_name

        extra_headers = _pick(raw, "extra_headers")

        if not isinstance(extra_headers, dict):
            extra_headers = {}

        timeout = _pick(raw, "timeout")
        timeout = defaults.timeout if timeout is None else float(timeout)

        max_retries = _pick(raw, "max_retries")
        max_retries = defaults.max_retries if max_retries is None else int(max_retries)

        return cls(
            api_base=str(api_base).rstrip("/"),
            api_key_env=[str(name) for name in key_env],
            model_name=str(model_name),
            extra_headers={str(k): str(v) for k, v in extra_headers.items()},
            timeout=timeout,
            max_retries=max_retries,
        )

    @classmethod
    def from_env(cls) -> "SystemOneConfig":
        """Build a config from ``SYSTEM_ONE_*`` variables and module defaults."""
        api_base = _first_env(BASE_URL_ENV_VARS)
        model_name = _first_env(MODEL_ENV_VARS)

        return cls(
            api_base=(api_base or DEFAULT_API_BASE).rstrip("/"),
            model_name=model_name or DEFAULT_MODEL_NAME,
        )

    @property
    def endpoint_url(self) -> str:
        """Full URL of the evaluation endpoint.

        ``api_base`` may be given with or without the ``/v1`` prefix; the
        trailing path segment is never duplicated.
        """
        base = self.api_base.rstrip("/")

        if base.endswith(ENDPOINT_PATH):
            return base

        if base.endswith("/v1"):
            return f"{base}/systemone"

        return f"{base}{ENDPOINT_PATH}"

    def resolve_api_key(self) -> Optional[str]:
        """Return the API key from the configured environment variables."""
        return _first_env(self.api_key_env)

    def build_headers(self) -> Dict[str, str]:
        """Return request headers (content type and auth, then user extras)."""
        headers = {"Content-Type": "application/json"}

        api_key = self.resolve_api_key()

        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        headers.update(self.extra_headers)

        return headers


#: Config installed via ``--system-one`` / config file / :func:`configure`.
_active_config: Optional[SystemOneConfig] = None


def configure(raw: Any) -> Optional[SystemOneConfig]:
    """Install *raw* as the active endpoint config.

    Accepts a dict (from ``--system-one`` or a config file) or an existing
    :class:`SystemOneConfig`. Returns ``None`` when *raw* carries nothing
    usable so callers can tell a no-op apart from a real configuration.
    """
    global _active_config

    if isinstance(raw, SystemOneConfig):
        _active_config = raw
    elif isinstance(raw, dict):
        if not raw:
            return None

        _active_config = SystemOneConfig.from_dict(raw)
    else:
        return None

    return _active_config


def reset() -> None:
    """Drop the active config so lookups fall back to the environment."""
    global _active_config

    _active_config = None


def is_configured() -> bool:
    """Return whether an endpoint config was explicitly installed."""
    return _active_config is not None


def get_config() -> SystemOneConfig:
    """Return the active config, falling back to environment defaults."""
    return _active_config if _active_config is not None else SystemOneConfig.from_env()
