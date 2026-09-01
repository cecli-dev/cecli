"""GitHub Copilot provider: OAuth device flow + disk-cached API key.

Mirrors litellm's ``Authenticator`` (llms/github_copilot/authenticator.py):
an access token (from device flow) is exchanged for a short-lived Copilot API
key via ``https://api.github.com/copilot_internal/v2/token``; the key is cached
to disk (api-key.json) and refreshed on expiry, within a leeway of it, and
periodically for long-lived keys (see the ``COPILOT_*`` refresh constants).
The tenant endpoint (``endpoints.api``) comes from the authenticated session,
never a caller-supplied base (token-leak prevention, matching litellm).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from cecli.http import httpx

from .base import ProviderAdapter

COPILOT_DEFAULT_API_BASE = "https://api.githubcopilot.com"
COPILOT_API_KEY_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_DEVICE_CODE_URL = "https://github.com/login/device/code"
COPILOT_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
COPILOT_TOKEN_DIR = os.path.expanduser("~/.config/litellm/github_copilot")
COPILOT_TIMEOUT = 120.0

#: Refresh the Copilot API key when it is within this many seconds of
#: expiring, so a key never dies mid-request.
COPILOT_REFRESH_LEEWAY = 300.0  # 5 minutes

#: Keys whose total lifetime exceeds this are rotated at most every
#: ``COPILOT_MAX_REFRESH_INTERVAL`` instead of waiting for natural expiry.
COPILOT_LONG_LIVED_THRESHOLD = 24 * 3600.0  # 1 day

#: Maximum age of a long-lived key before it is refreshed.
COPILOT_MAX_REFRESH_INTERVAL = 4 * 3600.0  # 4 hours


class CopilotAuthenticator:
    """GitHub Copilot OAuth: device flow + disk-cached API key with refresh."""

    def __init__(self) -> None:
        self.token_dir = os.getenv("GITHUB_COPILOT_TOKEN_DIR", COPILOT_TOKEN_DIR)
        self.access_token_file = os.path.join(self.token_dir, "access-token")
        self.api_key_file = os.path.join(self.token_dir, "api-key.json")

    def get_api_key(self) -> Optional[str]:
        """Return a valid Copilot API key, refreshing from disk if needed.

        The cached key is refreshed when it is expired, when it is within
        ``COPILOT_REFRESH_LEEWAY`` of expiring, or when a long-lived key
        (lifetime > ``COPILOT_LONG_LIVED_THRESHOLD``) has been held for more
        than ``COPILOT_MAX_REFRESH_INTERVAL``. A failed refresh keeps serving
        a cached key that is still unexpired instead of failing the request.
        """
        cached = None
        expired = False

        try:
            with open(self.api_key_file) as f:
                info = json.load(f)

            cached = info.get("token")

            if not self._should_refresh(info):
                return cached

            expired = info.get("expires_at", 0) <= time.time()
        except (IOError, json.JSONDecodeError):
            pass

        try:
            info = self._refresh_api_key()
            os.makedirs(self.token_dir, exist_ok=True)
            info["refreshed_at"] = time.time()

            with open(self.api_key_file, "w") as f:
                json.dump(info, f)

            return info.get("token")
        except Exception:
            if cached and not expired:
                return cached

            return None

    def get_api_base(self) -> Optional[str]:
        """Return the tenant-specific Copilot endpoint from the cached key."""
        try:
            with open(self.api_key_file) as f:
                info = json.load(f)

            return (info.get("endpoints") or {}).get("api")
        except (IOError, json.JSONDecodeError):
            return None

    def get_access_token(self) -> str:
        """Return the cached GitHub access token, or run device-flow login."""
        try:
            with open(self.access_token_file) as f:
                token = f.read().strip()

            if token:
                return token
        except IOError:
            pass

        return self._device_flow_login()

    def _refresh_api_key(self) -> Dict[str, Any]:
        access_token = self.get_access_token()
        headers = {
            "accept": "application/json",
            "editor-version": "vscode/1.85.1",
            "editor-plugin-version": "copilot/1.155.0",
            "user-agent": "GithubCopilot/1.155.0",
            "authorization": f"token {access_token}",
        }
        resp = httpx.get(COPILOT_API_KEY_URL, headers=headers, timeout=COPILOT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if "token" not in data:
            raise RuntimeError(f"API key response missing token: {data}")

        return data

    def _device_flow_login(self) -> str:
        """GitHub device flow: print verification URI + code, poll for token."""
        resp = httpx.post(
            COPILOT_DEVICE_CODE_URL,
            headers={"accept": "application/json"},
            json={"client_id": COPILOT_CLIENT_ID, "scope": "read:user"},
            timeout=COPILOT_TIMEOUT,
        )
        resp.raise_for_status()
        info = resp.json()

        print(  # noqa: T201
            f"Please visit {info['verification_uri']} and enter code {info['user_code']} to authenticate.",
            flush=True,
        )

        for _ in range(12):
            poll = httpx.post(
                COPILOT_ACCESS_TOKEN_URL,
                headers={"accept": "application/json"},
                json={
                    "client_id": COPILOT_CLIENT_ID,
                    "device_code": info["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=COPILOT_TIMEOUT,
            )
            poll.raise_for_status()
            data = poll.json()

            if "access_token" in data:
                os.makedirs(self.token_dir, exist_ok=True)

                with open(self.access_token_file, "w") as f:
                    f.write(data["access_token"])

                return data["access_token"]

            time.sleep(5)

        raise RuntimeError("Timed out waiting for user to authorize the device")

    def _should_refresh(self, info: Dict[str, Any]) -> bool:
        """True when the cached key should be replaced.

        Refreshes when the key is expired, within ``COPILOT_REFRESH_LEEWAY``
        of expiring, or when a long-lived key has been held for more than
        ``COPILOT_MAX_REFRESH_INTERVAL`` (periodic rotation). Rotation
        metadata (``refreshed_at``) is stamped when this version caches a
        key; legacy caches fall back to the natural-expiry rules.
        """
        now = time.time()
        expires_at = info.get("expires_at", 0)

        if expires_at <= now:
            return True

        if expires_at - now <= COPILOT_REFRESH_LEEWAY:
            return True

        refreshed_at = info.get("refreshed_at") or info.get("issued_at")

        if not refreshed_at:
            return False

        lifetime = expires_at - refreshed_at

        if (
            lifetime > COPILOT_LONG_LIVED_THRESHOLD
            and now - refreshed_at >= COPILOT_MAX_REFRESH_INTERVAL
        ):
            return True

        return False


#: Module-level singleton so config resolution and pipeline share one instance.
_AUTH: Optional[CopilotAuthenticator] = None


def _auth() -> CopilotAuthenticator:
    global _AUTH

    if _AUTH is None:
        _AUTH = CopilotAuthenticator()

    return _AUTH


def copilot_api_key() -> Optional[str]:
    """Return a valid Copilot API key (refreshing on demand)."""
    return _auth().get_api_key()


def copilot_api_base() -> str:
    """Return the tenant endpoint, falling back to the default base."""
    return _auth().get_api_base() or COPILOT_DEFAULT_API_BASE


def copilot_headers(api_key: str, *, messages_proxy: bool = False) -> Dict[str, str]:
    """Copilot request headers (Authorization Bearer + VSCode integration)."""
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
        "copilot-integration-id": "vscode-chat",
        "editor-version": "vscode/1.95.0",
        "editor-plugin-version": "copilot-chat/0.26.7",
        "user-agent": "GitHubCopilotChat/0.26.7",
        "x-request-id": str(uuid4()),
        "x-vscode-user-agent-library-version": "electron-fetch",
    }

    if messages_proxy:
        headers["openai-intent"] = "messages-proxy"
        headers["x-interaction-type"] = "messages-proxy"
        headers["x-github-api-version"] = "2026-06-01"
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["openai-intent"] = "conversation-panel"
        headers["x-github-api-version"] = "2025-04-01"

    return headers


class GithubCopilotProvider(ProviderAdapter):
    """Provider adapter for GitHub Copilot (auth + headers + routing)."""

    provider = "github_copilot"

    def resolve_api_base(self, resolved: Dict[str, Any]) -> str:
        return copilot_api_base()

    def resolve_api_key(self, resolved: Dict[str, Any], api_key: Optional[str]) -> Optional[str]:
        return copilot_api_key()

    def build_headers(
        self,
        resolved: Dict[str, Any],
        key: Optional[str],
        family: str,
        headers: Dict[str, str],
    ) -> Dict[str, str]:
        merged = dict(headers)

        if key:
            for k, v in copilot_headers(key, messages_proxy=(family == "messages")).items():
                merged.setdefault(k, v)

        merged.setdefault("Content-Type", "application/json")
        return merged


__all__ = [
    "CopilotAuthenticator",
    "copilot_api_key",
    "copilot_api_base",
    "copilot_headers",
    "GithubCopilotProvider",
]
