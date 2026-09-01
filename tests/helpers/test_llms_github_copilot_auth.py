"""GitHub Copilot auth key flow tests (offline; no network).

Drives :mod:`cecli.helpers.llms.providers.github_copilot` through its full
auth lifecycle without touching the network or the real
``~/.config/litellm/github_copilot`` cache:

- cached ``api-key.json`` hit path (no HTTP at all)
- expired/missing key -> refresh from the GitHub token endpoint
- ``access-token`` cache + device-flow login (code print + poll)
- api base resolution from the cached session ``endpoints.api``
- ``copilot_headers()`` shape (messages-proxy vs conversation-panel)
- wiring through ``resolve_model_config`` / ``get_api_key`` and the
  ``GithubCopilotProvider`` adapter, down to the family adapter

``httpx.get`` / ``httpx.post`` are monkeypatched and
``GITHUB_COPILOT_TOKEN_DIR`` points at a tmp dir, so every path is hermetic.
"""

import asyncio
import json
import time

import pytest

import cecli.helpers.llms.pipeline as pipeline
from cecli.helpers.llms import config as llms_config
from cecli.helpers.llms.providers import github_copilot as copilot
from cecli.helpers.llms.providers.github_copilot import (
    COPILOT_ACCESS_TOKEN_URL,
    COPILOT_DEFAULT_API_BASE,
    COPILOT_DEVICE_CODE_URL,
    CopilotAuthenticator,
    GithubCopilotProvider,
    copilot_api_base,
    copilot_api_key,
    copilot_headers,
)

SAMPLE_KEY = {
    "token": "sk-cached",
    "expires_at": time.time() + 3600,
    "endpoints": {"api": "https://tenant.githubcopilot.com"},
}

FRESH_KEY = {
    "token": "sk-fresh",
    "expires_at": time.time() + 3600,
    "endpoints": {"api": "https://tenant.githubcopilot.com"},
}

DEVICE_INFO = {
    "verification_uri": "https://github.com/login/device",
    "user_code": "ABCD-1234",
    "device_code": "dev-1",
}

MSGS = [{"role": "user", "content": "hi"}]


class _FakeResponse:
    """Minimal httpx.Response stand-in (raise_for_status + json)."""

    def __init__(self, payload, *, ok=True):
        self._payload = payload
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


@pytest.fixture
def auth(tmp_path, monkeypatch):
    """Fresh authenticator rooted at a tmp dir; module singleton reset."""
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(copilot, "_AUTH", None)

    return CopilotAuthenticator()


def _seed_api_key(token_dir, payload=SAMPLE_KEY):
    (token_dir / "api-key.json").write_text(json.dumps(payload))


def _seed_expired_key(token_dir):
    _seed_api_key(token_dir, dict(SAMPLE_KEY, expires_at=time.time() - 100))


def _key_payload(*, token="sk-cached", expires_at=None, refreshed_at=None):
    """Build an api-key.json payload with optional rotation metadata."""

    payload = {
        "token": token,
        "expires_at": expires_at if expires_at is not None else time.time() + 3600,
        "endpoints": {"api": "https://tenant.githubcopilot.com"},
    }

    if refreshed_at is not None:
        payload["refreshed_at"] = refreshed_at

    return payload


def _seed_access_token(token_dir, token="tok-gh"):
    (token_dir / "access-token").write_text(token)


def _no_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("unexpected network call")

    monkeypatch.setattr(copilot.httpx, "get", fail)
    monkeypatch.setattr(copilot.httpx, "post", fail)


def _fake_refresh(monkeypatch, payload):
    monkeypatch.setattr(copilot.httpx, "get", lambda *a, **k: _FakeResponse(payload))


def _fake_device_flow(monkeypatch, poll_payloads):
    """Stub httpx.post for the device-code and token-poll endpoints."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)

        if url == COPILOT_DEVICE_CODE_URL:
            return _FakeResponse(DEVICE_INFO)

        if poll_payloads:
            return _FakeResponse(poll_payloads.pop(0))

        return _FakeResponse({})

    monkeypatch.setattr(copilot.httpx, "post", fake_post)
    monkeypatch.setattr(copilot.time, "sleep", lambda *a: None)

    return calls


# ---------------------------------------------------------------------------
# Cached api-key.json hit path (no network)
# ---------------------------------------------------------------------------


def test_get_api_key_returns_valid_cached_key(auth, tmp_path, monkeypatch):
    _seed_api_key(tmp_path)
    _no_network(monkeypatch)

    assert auth.get_api_key() == "sk-cached"


def test_copilot_api_key_module_function(auth, tmp_path):
    _seed_api_key(tmp_path)

    assert copilot_api_key() == "sk-cached"


def test_get_api_base_returns_session_endpoint(auth, tmp_path):
    _seed_api_key(tmp_path)

    assert auth.get_api_base() == "https://tenant.githubcopilot.com"


def test_get_api_base_none_when_no_cache(auth):
    assert auth.get_api_base() is None


def test_copilot_api_base_falls_back_to_default(auth):
    assert copilot_api_base() == COPILOT_DEFAULT_API_BASE


def test_get_access_token_from_cache(auth, tmp_path, monkeypatch):
    _seed_access_token(tmp_path)
    _no_network(monkeypatch)

    assert auth.get_access_token() == "tok-gh"


# ---------------------------------------------------------------------------
# Refresh path (expired/missing key -> GitHub token endpoint)
# ---------------------------------------------------------------------------


def test_get_api_key_refreshes_when_expired(auth, tmp_path, monkeypatch):
    _seed_expired_key(tmp_path)
    _seed_access_token(tmp_path)
    _fake_refresh(monkeypatch, FRESH_KEY)

    assert auth.get_api_key() == "sk-fresh"

    cached = json.loads((tmp_path / "api-key.json").read_text())
    assert cached["token"] == "sk-fresh"


def test_get_api_key_refreshes_when_cache_missing(auth, tmp_path, monkeypatch):
    _seed_access_token(tmp_path)
    _fake_refresh(monkeypatch, FRESH_KEY)

    assert auth.get_api_key() == "sk-fresh"


def test_get_api_key_none_on_refresh_http_error(auth, tmp_path, monkeypatch):
    _seed_expired_key(tmp_path)
    _seed_access_token(tmp_path)
    monkeypatch.setattr(copilot.httpx, "get", lambda *a, **k: _FakeResponse({}, ok=False))

    assert auth.get_api_key() is None


def test_get_api_key_none_when_response_missing_token(auth, tmp_path, monkeypatch):
    _seed_access_token(tmp_path)
    _fake_refresh(monkeypatch, {"foo": "bar"})

    assert auth.get_api_key() is None


def test_get_api_key_refreshes_when_within_leeway(auth, tmp_path, monkeypatch):
    _seed_api_key(tmp_path, _key_payload(expires_at=time.time() + 60))
    _seed_access_token(tmp_path)
    _fake_refresh(monkeypatch, FRESH_KEY)

    assert auth.get_api_key() == "sk-fresh"

    cached = json.loads((tmp_path / "api-key.json").read_text())
    assert cached["token"] == "sk-fresh"
    assert cached["refreshed_at"] > 0


def test_get_api_key_does_not_refresh_outside_leeway(auth, tmp_path, monkeypatch):
    _seed_api_key(tmp_path, _key_payload(expires_at=time.time() + 600))
    _no_network(monkeypatch)

    assert auth.get_api_key() == "sk-cached"


def test_get_api_key_rotates_long_lived_key_when_due(auth, tmp_path, monkeypatch):
    refreshed_at = time.time() - 4 * 3600
    _seed_api_key(
        tmp_path, _key_payload(expires_at=refreshed_at + 25 * 3600, refreshed_at=refreshed_at)
    )
    _seed_access_token(tmp_path)
    _fake_refresh(monkeypatch, FRESH_KEY)

    assert auth.get_api_key() == "sk-fresh"


def test_get_api_key_keeps_long_lived_key_before_interval(auth, tmp_path, monkeypatch):
    refreshed_at = time.time() - 1 * 3600
    _seed_api_key(
        tmp_path, _key_payload(expires_at=refreshed_at + 25 * 3600, refreshed_at=refreshed_at)
    )
    _no_network(monkeypatch)

    assert auth.get_api_key() == "sk-cached"


def test_get_api_key_short_lived_key_not_rotated_periodically(auth, tmp_path, monkeypatch):
    refreshed_at = time.time() - 10 * 3600
    _seed_api_key(
        tmp_path, _key_payload(expires_at=refreshed_at + 12 * 3600, refreshed_at=refreshed_at)
    )
    _no_network(monkeypatch)

    assert auth.get_api_key() == "sk-cached"


def test_get_api_key_refresh_failure_keeps_valid_cached_key(auth, tmp_path, monkeypatch):
    refreshed_at = time.time() - 4 * 3600
    _seed_api_key(
        tmp_path, _key_payload(expires_at=refreshed_at + 25 * 3600, refreshed_at=refreshed_at)
    )
    _seed_access_token(tmp_path)
    monkeypatch.setattr(copilot.httpx, "get", lambda *a, **k: _FakeResponse({}, ok=False))

    assert auth.get_api_key() == "sk-cached"


# ---------------------------------------------------------------------------
# Device flow (no access-token cached)
# ---------------------------------------------------------------------------


def test_device_flow_login_writes_access_token(auth, tmp_path, monkeypatch, capsys):
    _fake_device_flow(monkeypatch, [{"access_token": "tok-device"}])

    assert auth.get_access_token() == "tok-device"
    assert (tmp_path / "access-token").read_text() == "tok-device"

    out = capsys.readouterr().out
    assert DEVICE_INFO["verification_uri"] in out
    assert DEVICE_INFO["user_code"] in out


def test_device_flow_times_out_after_12_polls(auth, monkeypatch):
    calls = _fake_device_flow(monkeypatch, [{}] * 12)

    with pytest.raises(RuntimeError, match="Timed out"):
        auth.get_access_token()

    poll_count = sum(1 for url in calls if url == COPILOT_ACCESS_TOKEN_URL)
    assert poll_count == 12


# ---------------------------------------------------------------------------
# copilot_headers()
# ---------------------------------------------------------------------------


def test_copilot_headers_messages_proxy():
    headers = copilot_headers("sk-test", messages_proxy=True)

    assert headers["Authorization"] == "Bearer sk-test"
    assert headers["openai-intent"] == "messages-proxy"
    assert headers["x-interaction-type"] == "messages-proxy"
    assert headers["x-github-api-version"] == "2026-06-01"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["x-request-id"]


def test_copilot_headers_conversation_panel():
    headers = copilot_headers("sk-test")

    assert headers["openai-intent"] == "conversation-panel"
    assert headers["x-github-api-version"] == "2025-04-01"
    assert "anthropic-version" not in headers


# ---------------------------------------------------------------------------
# Wiring through config resolution / get_api_key / the provider adapter
# ---------------------------------------------------------------------------


def test_resolve_model_config_uses_session_endpoint(auth, tmp_path):
    _seed_api_key(tmp_path)

    resolved = llms_config.resolve_model_config("github_copilot/gpt-5")

    assert resolved["provider"] == "github_copilot"
    assert resolved["api_base"] == "https://tenant.githubcopilot.com"
    assert resolved["family"] == "responses"


def test_resolve_model_config_claude_family_messages(auth, tmp_path):
    _seed_api_key(tmp_path)

    # github_copilot/claude-sonnet-4.5 is the bundled copilot record; the
    # bare claude-sonnet-5 key resolves to the anthropic provider.
    resolved = llms_config.resolve_model_config("github_copilot/claude-sonnet-4.5")

    assert resolved["provider"] == "github_copilot"
    assert resolved["family"] == "messages"


def test_resolve_model_config_hyphenated_claude_maps_to_copilot(auth, tmp_path):
    """Hyphenated claude names without an exact copilot record must still
    route through the copilot provider instead of falling back to the bare
    anthropic record (e.g. ``github_copilot/claude-sonnet-4-5``)."""
    _seed_api_key(tmp_path)

    resolved = llms_config.resolve_model_config("github_copilot/claude-sonnet-4-5")

    assert resolved["provider"] == "github_copilot"
    assert resolved["family"] == "messages"
    assert resolved["api_key_env"] is None


def test_resolve_model_config_unlisted_copilot_model_maps_to_copilot(auth, tmp_path):
    """Any ``github_copilot/``-prefixed model routes through the copilot
    provider even when no copilot metadata record exists at all (e.g. a brand
    new gpt model, so it must not fall back to the bare openai record)."""
    _seed_api_key(tmp_path)

    resolved = llms_config.resolve_model_config("github_copilot/o3")

    assert resolved["provider"] == "github_copilot"
    assert resolved["family"] == "responses"
    assert resolved["api_key_env"] is None


def test_get_api_key_wiring_uses_cached_token(auth, tmp_path):
    _seed_api_key(tmp_path)
    resolved = llms_config.resolve_model_config("github_copilot/gpt-5")

    assert llms_config.get_api_key(resolved, None) == "sk-cached"


def test_get_api_key_wiring_explicit_key_wins(auth, tmp_path):
    _seed_api_key(tmp_path)
    resolved = llms_config.resolve_model_config("github_copilot/gpt-5")

    assert llms_config.get_api_key(resolved, "explicit-key") == "explicit-key"


def test_provider_adapter_resolves_from_session(auth, tmp_path):
    _seed_api_key(tmp_path)
    provider = GithubCopilotProvider()
    resolved = llms_config.resolve_model_config("github_copilot/gpt-5")

    assert provider.resolve_api_base(resolved) == "https://tenant.githubcopilot.com"
    assert provider.resolve_api_key(resolved, None) == "sk-cached"
    # Token-leak prevention: the copilot adapter ignores caller-supplied keys
    # and always serves the authenticated session key.
    assert provider.resolve_api_key(resolved, "explicit") == "sk-cached"


def test_provider_adapter_build_headers_messages_family():
    provider = GithubCopilotProvider()
    resolved = {"family": "messages"}

    headers = provider.build_headers(resolved, "sk-test", "messages", {})

    assert headers["Authorization"] == "Bearer sk-test"
    assert headers["openai-intent"] == "messages-proxy"
    assert headers["Content-Type"] == "application/json"


def test_provider_adapter_build_headers_conversation_family():
    provider = GithubCopilotProvider()
    resolved = {"family": "responses"}

    headers = provider.build_headers(resolved, "sk-test", "responses", {})

    assert headers["openai-intent"] == "conversation-panel"


def test_pipeline_uses_copilot_key_and_headers(auth, tmp_path, monkeypatch):
    """End to end: cached key flows from config -> adapter -> family adapter."""
    _seed_api_key(tmp_path)
    captured = {}

    async def fake_responses_complete(resolved, messages, tools, key, headers, kwargs):
        captured["key"] = key
        captured["headers"] = headers
        return None

    monkeypatch.setattr(pipeline, "responses_complete", fake_responses_complete)
    asyncio.run(pipeline.acompletion(model="github_copilot/gpt-5", messages=MSGS))

    assert captured["key"] == "sk-cached"
    assert captured["headers"]["Authorization"] == "Bearer sk-cached"
    assert captured["headers"]["openai-intent"] == "conversation-panel"
