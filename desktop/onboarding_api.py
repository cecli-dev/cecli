"""GUI onboarding service: provider discovery, key persistence and Copilot auth.

The desktop bridge reuses the TUI onboarding helpers so keys land in
``~/.cecli/.env`` and the chosen default model in ``~/.cecli/conf.yml`` exactly
as the Textual wizard does. GitHub Copilot needs no API key; its availability
comes from the OAuth token files managed by
``cecli.helpers.llms.providers.github_copilot``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from cecli.helpers.onboarding import _persist_api_keys, _persist_default_model
from cecli.helpers.onboarding.providers import (
    get_models_for_provider,
    iter_providers,
    provider_has_key,
    provider_needs_key,
)

CHAT_MODES = ("chat", "responses")
COPILOT_SLUG = "github_copilot"
DEVICE_POLL_FLOOR = 5.0


class OnboardingError(Exception):
    """An onboarding failure carrying the HTTP status it should become."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class OnboardingService:
    """Provider status, persisted configuration and the Copilot device flow."""

    def __init__(self, manager: Any, store: Any) -> None:
        self.manager = manager
        self.store = store
        self._login: dict[str, Any] = {
            "state": "idle",
            "verification_uri": None,
            "user_code": None,
            "expires_at": None,
            "error": None,
            "started_at": None,
        }
        self._login_task: asyncio.Task[Any] | None = None

    def status(self) -> dict[str, Any]:
        """Whether a usable default model/provider is already configured."""
        env = _env_values()
        model = self.store.model()
        provider_slug = _provider_slug(model)
        entry = self._provider(provider_slug) if provider_slug else None
        configured = bool(model)
        if configured and entry is not None and provider_needs_key(entry):
            configured = _provider_configured(entry, env)
        return {
            "ok": True,
            "configured": configured,
            "requires_onboarding": not configured,
            "model": model,
            "provider": provider_slug,
            "project_config": str(self.store.project_path),
            "global_config": str(self.store.global_path),
        }

    def providers(self, slug: str | None = None) -> dict[str, Any]:
        """List selectable providers, optionally with one provider's models."""
        env = _env_values()
        entries = []
        for provider in iter_providers():
            entries.append(
                {
                    "slug": provider["slug"],
                    "display_name": provider.get("display_name", provider["slug"]),
                    "api_key_env": list(provider.get("api_key_env") or []),
                    "requires_key": provider_needs_key(provider),
                    "configured": _provider_configured(provider, env),
                }
            )

        payload: dict[str, Any] = {"ok": True, "providers": entries, **self.status()}
        if slug:
            entry = next((item for item in entries if item["slug"] == slug), None)
            if entry is None:
                raise OnboardingError(404, f"Unknown provider: {slug}")
            payload["provider"] = entry
            payload["models"] = self.models(slug)
        return payload

    def models(self, slug: str) -> list[str]:
        """Selectable chat models for one provider, from cache or live discovery."""
        modes = CHAT_MODES if slug == COPILOT_SLUG else None
        return get_models_for_provider(slug, modes=modes)

    async def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist API keys and the default model, then reload live sessions."""
        provider_slug = str(payload.get("provider") or "").strip()
        model = str(payload.get("model") or "").strip()
        api_keys = payload.get("api_keys") or {}

        if not model:
            raise OnboardingError(400, "A model is required")
        if not isinstance(api_keys, dict):
            raise OnboardingError(400, "api_keys must be an object")

        entry = self._provider(provider_slug) if provider_slug else None
        if provider_slug and entry is None:
            raise OnboardingError(404, f"Unknown provider: {provider_slug}")

        env = _env_values()
        keys = {
            str(name): str(value)
            for name, value in api_keys.items()
            if isinstance(name, str) and isinstance(value, str) and value.strip()
        }
        if (
            entry is not None
            and provider_needs_key(entry)
            and not _provider_configured(entry, env, extra=keys)
        ):
            missing = [
                name
                for name in entry.get("api_key_env") or []
                if not (keys.get(name) or os.environ.get(name) or env.get(name))
            ]
            detail = (
                f"Missing API key(s): {', '.join(missing)}" if missing else "An API key is required"
            )
            raise OnboardingError(400, detail)

        try:
            _persist_api_keys(keys)
            _persist_default_model(model)
        except Exception as err:
            raise OnboardingError(500, f"Failed to persist onboarding settings: {err}") from err

        os.environ.update(keys)
        await self._restart_sessions()
        return {
            "ok": True,
            "configured": True,
            "provider": provider_slug or None,
            "model": model,
        }

    def copilot(self) -> dict[str, Any]:
        """Copilot availability, token metadata and its model list."""
        auth = _copilot_authenticator()
        info = _read_json(Path(auth.api_key_file))
        access_token = Path(auth.access_token_file).is_file()
        api_key = bool(info.get("token"))
        expires_at = info.get("expires_at")
        configured = bool(access_token or api_key)
        return {
            "ok": True,
            "provider": COPILOT_SLUG,
            "configured": configured,
            "requires_key": False,
            "has_access_token": access_token,
            "has_api_key": api_key,
            "expires_at": expires_at if isinstance(expires_at, (int, float)) else None,
            "token_dir": auth.token_dir,
            "models": self.models(COPILOT_SLUG),
            "login": dict(self._login),
        }

    async def copilot_login(self) -> dict[str, Any]:
        """Start (or report) the GitHub device flow; poll in the background."""
        status = self.copilot()
        if status["configured"]:
            return {**status, "state": "configured"}
        if self._login_task is not None and not self._login_task.done():
            return {**status, **self._login_snapshot()}

        try:
            device = await asyncio.to_thread(_request_device_code)
        except Exception as err:
            raise OnboardingError(502, f"GitHub login failed: {err}") from err

        interval = max(float(device.get("interval") or 5), DEVICE_POLL_FLOOR)
        expires_in = float(device.get("expires_in") or 900)
        self._login = {
            "state": "pending",
            "verification_uri": device.get("verification_uri"),
            "user_code": device.get("user_code"),
            "expires_at": time.time() + expires_in,
            "error": None,
            "started_at": time.time(),
        }
        self._login_task = asyncio.create_task(
            self._poll_copilot_login(str(device.get("device_code")), interval, expires_in)
        )
        return {**status, **self._login_snapshot()}

    async def _poll_copilot_login(
        self, device_code: str, interval: float, expires_in: float
    ) -> None:
        """Poll GitHub until the user authorizes, then cache the API key."""
        deadline = time.time() + expires_in
        while time.time() < deadline:
            await asyncio.sleep(interval)
            try:
                result = await asyncio.to_thread(_poll_access_token, device_code)
            except Exception as err:
                self._login.update({"state": "error", "error": str(err)})
                return

            token = result.get("access_token")
            if token:
                try:
                    await asyncio.to_thread(_store_access_token, str(token))
                    key = await asyncio.to_thread(_refresh_copilot_key)
                except Exception as err:
                    self._login.update({"state": "error", "error": str(err)})
                    return
                if not key:
                    self._login.update(
                        {
                            "state": "error",
                            "error": "GitHub authorized but no Copilot key was issued",
                        }
                    )
                    return
                self._login.update({"state": "configured", "error": None})
                await self._restart_sessions()
                return

            error = result.get("error")
            if error == "slow_down":
                interval += DEVICE_POLL_FLOOR
            elif error not in ("authorization_pending", None):
                self._login.update({"state": "error", "error": str(error)})
                return

        self._login.update({"state": "expired", "error": "The GitHub device code expired"})

    def _login_snapshot(self) -> dict[str, Any]:
        return {
            "state": self._login.get("state"),
            **{
                key: self._login.get(key)
                for key in ("verification_uri", "user_code", "expires_at", "error")
            },
        }

    def _provider(self, slug: str) -> dict[str, Any] | None:
        return next((item for item in iter_providers() if item["slug"] == slug), None)

    async def _restart_sessions(self) -> None:
        """Reload children so they pick up the new model/key environment."""
        for bridge in list(self.manager.sessions.values()):
            try:
                await bridge.restart()
            except Exception:
                continue


def _env_values() -> dict[str, str]:
    """Values from cecli's dotenv files, without mutating the environment."""
    from dotenv import dotenv_values

    values: dict[str, str] = {}
    for path in (Path.home() / ".cecli" / ".env", Path.home() / ".cecli" / "oauth-keys.env"):
        try:
            values.update({key: value for key, value in dotenv_values(path).items() if value})
        except Exception:
            continue
    return values


def _provider_configured(
    entry: dict[str, Any], env: dict[str, str], extra: dict[str, str] | None = None
) -> bool:
    """True when a provider's key is set in the process, dotenv or this request."""
    if entry["slug"] == COPILOT_SLUG:
        return provider_has_key(entry)
    extra = extra or {}
    names = entry.get("api_key_env") or []
    return any(os.environ.get(name) or env.get(name) or extra.get(name) for name in names)


def _provider_slug(model: str | None) -> str | None:
    if not model or "/" not in model:
        return None
    return model.split("/", 1)[0]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _copilot_authenticator() -> Any:
    from cecli.helpers.llms.providers.github_copilot import CopilotAuthenticator

    return CopilotAuthenticator()


def _request_device_code() -> dict[str, Any]:
    """Ask GitHub for a device code, mirroring the provider's device flow."""
    from cecli.helpers.llms.providers.github_copilot import (
        COPILOT_CLIENT_ID,
        COPILOT_DEVICE_CODE_URL,
        COPILOT_TIMEOUT,
    )
    from cecli.http import httpx

    response = httpx.post(
        COPILOT_DEVICE_CODE_URL,
        headers={"accept": "application/json"},
        json={"client_id": COPILOT_CLIENT_ID, "scope": "read:user"},
        timeout=COPILOT_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _poll_access_token(device_code: str) -> dict[str, Any]:
    """One device-flow token poll; returns GitHub's JSON body."""
    from cecli.helpers.llms.providers.github_copilot import (
        COPILOT_ACCESS_TOKEN_URL,
        COPILOT_CLIENT_ID,
        COPILOT_TIMEOUT,
    )
    from cecli.http import httpx

    response = httpx.post(
        COPILOT_ACCESS_TOKEN_URL,
        headers={"accept": "application/json"},
        json={
            "client_id": COPILOT_CLIENT_ID,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        timeout=COPILOT_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _store_access_token(token: str) -> None:
    """Write the GitHub access token where the Copilot provider expects it."""
    auth = _copilot_authenticator()
    Path(auth.token_dir).mkdir(parents=True, exist_ok=True)
    Path(auth.access_token_file).write_text(token, encoding="utf-8")


def _refresh_copilot_key() -> str | None:
    """Exchange the stored access token for a cached Copilot API key."""
    from cecli.helpers.llms.providers.github_copilot import copilot_api_key

    return copilot_api_key()
