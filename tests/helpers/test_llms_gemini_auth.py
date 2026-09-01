from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.helpers.llms.domains.gemini import gemini_complete
from cecli.helpers.llms.providers.gemini import GeminiProvider


def test_gemini_provider_build_headers():
    provider = GeminiProvider()
    headers = provider.build_headers(
        resolved={"provider": "gemini"},
        key="my-secret-gemini-key",
        family="gemini",
        headers={"Custom-Header": "value"},
    )

    assert headers["x-goog-api-key"] == "my-secret-gemini-key"
    assert headers["Content-Type"] == "application/json"
    assert headers["Custom-Header"] == "value"
    assert "Authorization" not in headers


def test_gemini_provider_build_headers_no_key():
    provider = GeminiProvider()
    headers = provider.build_headers(
        resolved={"provider": "gemini"},
        key=None,
        family="gemini",
        headers={},
    )

    assert "x-goog-api-key" not in headers
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_gemini_complete_sends_x_goog_api_key_header():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "responseId": "resp-123",
        "candidates": [
            {
                "content": {"parts": [{"text": "Hello world"}]},
                "finishReason": "STOP",
            }
        ],
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    mock_make_client = MagicMock()
    mock_make_client.return_value.__aenter__.return_value = mock_client

    with patch("cecli.helpers.llms.domains.gemini.make_client", mock_make_client):
        resolved = {
            "api_base": "https://generativelanguage.googleapis.com",
            "route": "gemini-2.0-flash",
            "model": "gemini/gemini-2.0-flash",
        }
        messages = [{"role": "user", "content": "Hi"}]
        headers = {"x-goog-api-key": "my-secret-gemini-key"}

        resp = await gemini_complete(
            resolved=resolved,
            messages=messages,
            tools=None,
            key="my-secret-gemini-key",
            headers=headers,
            kwargs={},
        )

        assert resp.choices[0].message.content == "Hello world"
        mock_client.post.assert_called_once()
        _, kwargs = mock_client.post.call_args
        assert kwargs["headers"]["x-goog-api-key"] == "my-secret-gemini-key"
        assert "Authorization" not in kwargs["headers"]
        assert kwargs["params"] == {}
