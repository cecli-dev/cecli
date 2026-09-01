"""Compatibility tests for mcp SDK 1.x / 2.x dual support.

These tests exercise the version-sensitive code paths in cecli.mcp.server
that changed to support mcp SDK 2.x (httpx2 migration, AuthorizationCodeResult
callback contract, 2-tuple HTTP transports, and OAuth provider skipping when
static headers are configured).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.mcp.server import (
    HttpStreamingServer,
    _get_http_client_module,
    _get_mcp_major_version,
    _get_oauth_callback_handler,
    _unpack_transport,
)
from tests.mcp.conftest import _mock_transport_streams


def test_mcp_major_version_is_positive_int():
    """The mcp SDK major version is detected as a positive integer."""
    version = _get_mcp_major_version()

    assert isinstance(version, int)
    assert version >= 1


def test_http_client_module_matches_installed_sdk():
    """The HTTP client module matches the installed mcp SDK version."""
    http_module = _get_http_client_module()

    if _get_mcp_major_version() >= 2:
        import httpx2

        assert http_module is httpx2
    else:
        import httpx

        assert http_module is httpx


def test_http_client_module_httpx_for_mcp1(monkeypatch):
    """Forcing mcp major version 1 selects httpx."""
    monkeypatch.setattr("cecli.mcp.server._get_mcp_major_version", lambda: 1)
    import httpx

    assert _get_http_client_module() is httpx


def test_http_client_module_httpx2_for_mcp2(monkeypatch):
    """Forcing mcp major version 2 selects httpx2."""
    monkeypatch.setattr("cecli.mcp.server._get_mcp_major_version", lambda: 2)
    pytest.importorskip("httpx2")
    import httpx2

    assert _get_http_client_module() is httpx2


def test_unpack_transport_mcp1_three_tuple(monkeypatch):
    """mcp 1.x HTTP transports yield (read, write, session_id_getter)."""
    monkeypatch.setattr("cecli.mcp.server._get_mcp_major_version", lambda: 1)

    read, write = _unpack_transport(("r", "w", "session-getter"))

    assert (read, write) == ("r", "w")


def test_unpack_transport_mcp2_two_tuple(monkeypatch):
    """mcp 2.x HTTP transports yield (read, write)."""
    monkeypatch.setattr("cecli.mcp.server._get_mcp_major_version", lambda: 2)

    read, write = _unpack_transport(("r", "w"))

    assert (read, write) == ("r", "w")


@pytest.mark.asyncio
async def test_oauth_callback_handler_mcp1_passthrough(monkeypatch):
    """mcp 1.x uses the raw callback returning an (auth_code, state) tuple."""
    monkeypatch.setattr("cecli.mcp.server._get_mcp_major_version", lambda: 1)

    async def get_auth_code():
        return ("code123", "state456")

    handler = _get_oauth_callback_handler(get_auth_code)

    assert handler is get_auth_code
    assert await handler() == ("code123", "state456")


@pytest.mark.asyncio
async def test_oauth_callback_handler_mcp2_wraps_result(monkeypatch):
    """mcp 2.x wraps the callback into an AuthorizationCodeResult."""
    try:
        from mcp.shared.auth import AuthorizationCodeResult
    except ImportError:
        pytest.skip("AuthorizationCodeResult requires mcp SDK 2.x")

    monkeypatch.setattr("cecli.mcp.server._get_mcp_major_version", lambda: 2)

    async def get_auth_code():
        return ("code123", "state456")

    handler = _get_oauth_callback_handler(get_auth_code)
    result = await handler()

    assert isinstance(result, AuthorizationCodeResult)
    assert result.code == "code123"
    assert result.state == "state456"


def test_oauth_provider_is_selected_http_client_auth():
    """OAuthClientProvider must be an Auth subclass of the selected module.

    This is the regression behind issue #633: on mcp SDK 2.x the provider
    became an httpx2.Auth, so it is only accepted by httpx2.AsyncClient.
    """
    from mcp.client.auth import OAuthClientProvider

    http_module = _get_http_client_module()

    assert issubclass(OAuthClientProvider, http_module.Auth)


@pytest.mark.asyncio
async def test_async_client_accepts_oauth_provider_auth():
    """An AsyncClient from the selected module accepts OAuthClientProvider."""
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    provider = OAuthClientProvider(
        server_url="http://localhost:8000",
        client_metadata=OAuthClientMetadata(
            client_name="Cecli",
            redirect_uris=["http://localhost:9999/callback"],
            grant_types=["authorization_code", "refresh_token"],
        ),
        storage=MagicMock(),
        redirect_handler=AsyncMock(),
        callback_handler=AsyncMock(),
    )

    http_module = _get_http_client_module()
    client = http_module.AsyncClient(auth=provider)

    await client.aclose()


@pytest.mark.asyncio
async def test_connect_skips_oauth_provider_when_headers_set():
    """Static headers mean no OAuth provider is created or used."""
    server = HttpStreamingServer(
        {
            "name": "test-server",
            "url": "http://localhost:8000",
            "type": "streamable_http",
            "headers": {"Authorization": "Bearer token"},
        },
        io=MagicMock(),
    )
    server._create_oauth_provider = AsyncMock()

    with (
        patch("cecli.mcp.server.ClientSession") as MockSession,
        patch("cecli.mcp.server.streamable_http_client") as mock_transport,
        patch("cecli.mcp.server._get_http_client_module") as mock_get_module,
    ):
        mock_http_client = AsyncMock()
        mock_module = MagicMock()
        mock_module.AsyncClient = MagicMock(return_value=mock_http_client)
        mock_get_module.return_value = mock_module

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        MockSession.return_value = mock_session

        mock_transport.return_value = AsyncMock()
        mock_transport.return_value.__aenter__ = AsyncMock(return_value=_mock_transport_streams())

        await server.connect()

    server._create_oauth_provider.assert_not_awaited()
    mock_module.AsyncClient.assert_called_once()
    call_kwargs = mock_module.AsyncClient.call_args.kwargs
    assert call_kwargs["auth"] is None
    assert call_kwargs["headers"] == {"Authorization": "Bearer token"}

    await server.disconnect()


@pytest.mark.asyncio
async def test_connect_creates_oauth_provider_when_no_headers():
    """Without static headers, an OAuth provider is created."""
    server = HttpStreamingServer(
        {
            "name": "test-server",
            "url": "http://localhost:8000",
            "type": "streamable_http",
            "headers": {},
        },
        io=MagicMock(),
    )
    server._create_oauth_provider = AsyncMock(return_value=None)

    with (
        patch("cecli.mcp.server.ClientSession") as MockSession,
        patch("cecli.mcp.server.streamable_http_client") as mock_transport,
        patch("cecli.mcp.server._get_http_client_module") as mock_get_module,
    ):
        mock_http_client = AsyncMock()
        mock_module = MagicMock()
        mock_module.AsyncClient = MagicMock(return_value=mock_http_client)
        mock_get_module.return_value = mock_module

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        MockSession.return_value = mock_session

        mock_transport.return_value = AsyncMock()
        mock_transport.return_value.__aenter__ = AsyncMock(return_value=_mock_transport_streams())

        await server.connect()

    server._create_oauth_provider.assert_awaited_once()
    assert mock_module.AsyncClient.call_args.kwargs["auth"] is None

    await server.disconnect()
