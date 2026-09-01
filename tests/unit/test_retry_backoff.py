import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from cecli.llm import litellm
from cecli.models import Model


def test_extract_retry_delay_valid():
    model = Model("gemini/gemini-2.5-flash")

    payload = {
        "error": {
            "code": 429,
            "message": "Quota exceeded for metric ... Please retry in 15.2s.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "://googleapis.com",
                    "violations": [
                        {
                            "subject": "client_id:your_api_key_or_project",
                            "description": "Rate limit exceeded.",
                        }
                    ],
                },
                {"@type": "://googleapis.com", "retryDelay": "15.2s"},
            ],
        }
    }

    # Exception with response object
    err = Exception("Rate limit error")
    err.status_code = 429
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    err.response = mock_resp

    delay = model._extract_retry_delay(err)
    assert delay == 15.2


def test_extract_retry_delay_json_in_message():
    model = Model("gemini/gemini-2.5-flash")

    payload = {
        "error": {
            "code": 429,
            "message": "Quota exceeded",
            "details": [{"retryDelay": "8.5s"}],
        }
    }

    err = Exception(f"APIError: 429 {json.dumps(payload)}")
    delay = model._extract_retry_delay(err)
    assert delay == 8.5


def test_extract_retry_delay_non_429():
    model = Model("gemini/gemini-2.5-flash")

    payload = {
        "error": {
            "code": 500,
            "message": "Internal error",
            "details": [{"retryDelay": "15.2s"}],
        }
    }

    err = Exception("Internal Error")
    err.status_code = 500
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    err.response = mock_resp

    delay = model._extract_retry_delay(err)
    assert delay is None


def test_extract_retry_delay_missing_details():
    model = Model("gemini/gemini-2.5-flash")

    payload = {
        "error": {
            "code": 429,
            "message": "Quota exceeded",
        }
    }

    err = Exception("Quota exceeded")
    err.status_code = 429
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    err.response = mock_resp

    delay = model._extract_retry_delay(err)
    assert delay is None


def test_extract_retry_delay_headers_fallback():
    model = Model("gemini/gemini-2.5-flash")

    # Standard retry-after header (seconds)
    err1 = Exception("Rate limit")
    err1.status_code = 429
    mock_resp1 = MagicMock()
    mock_resp1.json.return_value = {}
    mock_resp1.headers = {"retry-after": "6.5"}
    err1.response = mock_resp1
    assert model._extract_retry_delay(err1) == 6.5

    # Standard retry-after-ms header (milliseconds)
    err2 = Exception("Rate limit")
    err2.status_code = 429
    mock_resp2 = MagicMock()
    mock_resp2.json.return_value = {}
    mock_resp2.headers = {"retry-after-ms": "2500"}
    err2.response = mock_resp2
    assert model._extract_retry_delay(err2) == 2.5


def test_extract_retry_delay_direct_err_headers():
    model = Model("openai/gpt-4o")

    # Direct headers dict on err
    err = Exception("Rate limit")
    err.status_code = 429
    err.headers = {"retry-after": "3.5"}
    assert model._extract_retry_delay(err) == 3.5

    err_ms = Exception("Rate limit")
    err_ms.status_code = 429
    err_ms.headers = {"retry-after-ms": "4500"}
    assert model._extract_retry_delay(err_ms) == 4.5


def test_extract_retry_delay_malformed_headers():
    model = Model("openai/gpt-4o")

    # HTTP-date header value (non-numeric string)
    err = Exception("Rate limit")
    err.status_code = 429
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    mock_resp.headers = {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}
    err.response = mock_resp
    assert model._extract_retry_delay(err) is None

    # Garbage string header value
    mock_resp.headers = {"retry-after": "invalid"}
    assert model._extract_retry_delay(err) is None


def test_extract_retry_delay_bytes_payload():
    model = Model("gemini/gemini-2.5-flash")

    payload_bytes = json.dumps(
        {
            "error": {
                "code": 429,
                "message": "Resource exhausted",
                "details": [{"retryDelay": "4.0s"}],
            }
        }
    ).encode("utf-8")

    err = Exception("Rate limit")
    err.status_code = 429
    mock_resp = MagicMock()
    mock_resp.json.side_effect = Exception("Not parsed")
    mock_resp.text = payload_bytes
    err.response = mock_resp

    assert model._extract_retry_delay(err) == 4.0


def test_retry_fallback_to_unilateral_backoff_when_no_retry_delay():
    async def run_test():
        model = Model("gemini/gemini-2.5-flash")
        model.caches_by_default = False

        rate_limit_err = litellm.RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(
                json=lambda: {"error": {"code": 429, "message": "Rate limit exceeded"}}
            ),
            model="gemini/gemini-2.5-flash",
            llm_provider="gemini",
        )

        call_count = 0
        slept_delays = []

        async def mock_acompletion(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise rate_limit_err
            return MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])

        async def mock_sleep(delay):
            slept_delays.append(delay)

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=mock_acompletion),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        # Initial retry_delay is 0.125, multiplied by retry_backoff_factor (1.5) = 0.1875
        assert len(slept_delays) == 1
        assert pytest.approx(slept_delays[0]) == 0.125 * 1.5

    asyncio.run(run_test())


def test_send_completion_retry_after_header_integration():
    async def run_test():
        model = Model("openai/gpt-4o")
        model.caches_by_default = False

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.headers = {"retry-after": "2.5"}

        rate_limit_err = litellm.RateLimitError(
            message="Rate limit exceeded",
            response=mock_resp,
            model="openai/gpt-4o",
            llm_provider="openai",
        )
        rate_limit_err.status_code = 429

        call_count = 0
        slept_delays = []

        async def mock_acompletion(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise rate_limit_err
            return MagicMock(choices=[MagicMock(message=MagicMock(content="success"))])

        async def mock_sleep(delay):
            slept_delays.append(delay)

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=mock_acompletion),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            _hash, resp = await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        assert len(slept_delays) == 1
        assert slept_delays[0] == 2.5
        assert resp.choices[0].message.content == "success"

    asyncio.run(run_test())


def test_send_completion_retry_after_ms_header_integration():
    async def run_test():
        model = Model("anthropic/claude-3-5-sonnet")
        model.caches_by_default = False

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.headers = {"retry-after-ms": "1500"}

        rate_limit_err = litellm.RateLimitError(
            message="Rate limit exceeded",
            response=mock_resp,
            model="anthropic/claude-3-5-sonnet",
            llm_provider="anthropic",
        )
        rate_limit_err.status_code = 429

        call_count = 0
        slept_delays = []

        async def mock_acompletion(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise rate_limit_err
            return MagicMock(choices=[MagicMock(message=MagicMock(content="success"))])

        async def mock_sleep(delay):
            slept_delays.append(delay)

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=mock_acompletion),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            _hash, resp = await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        assert len(slept_delays) == 1
        assert slept_delays[0] == 1.5
        assert resp.choices[0].message.content == "success"

    asyncio.run(run_test())


def test_send_completion_gemini_payload_retry_delay_integration():
    async def run_test():
        model = Model("gemini/gemini-2.5-flash")
        model.caches_by_default = False

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": {
                "code": 429,
                "message": "Resource exhausted",
                "details": [{"retryDelay": "3.5s"}],
            }
        }

        rate_limit_err = litellm.RateLimitError(
            message="Resource exhausted",
            response=mock_resp,
            model="gemini/gemini-2.5-flash",
            llm_provider="gemini",
        )
        rate_limit_err.status_code = 429

        call_count = 0
        slept_delays = []

        async def mock_acompletion(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise rate_limit_err
            return MagicMock(choices=[MagicMock(message=MagicMock(content="success"))])

        async def mock_sleep(delay):
            slept_delays.append(delay)

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=mock_acompletion),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            _hash, resp = await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        assert len(slept_delays) == 1
        assert slept_delays[0] == 3.5
        assert resp.choices[0].message.content == "success"

    asyncio.run(run_test())


def test_send_completion_exceeds_retry_timeout():
    async def run_test():
        model = Model("openai/gpt-4o")
        model.caches_by_default = False
        model.retry_timeout = 10

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.headers = {"retry-after": "100"}

        rate_limit_err = litellm.RateLimitError(
            message="Rate limit exceeded",
            response=mock_resp,
            model="openai/gpt-4o",
            llm_provider="openai",
        )
        rate_limit_err.status_code = 429

        slept_delays = []

        async def mock_acompletion(*args, **kwargs):
            raise rate_limit_err

        async def mock_sleep(delay):
            slept_delays.append(delay)

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=mock_acompletion),
            patch("asyncio.sleep", side_effect=mock_sleep),
        ):
            _hash, resp = await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        # Should not sleep and should return model error response immediately
        assert len(slept_delays) == 0
        assert "Model API Response Error" in resp.choices[0].message.content

    asyncio.run(run_test())


def test_simple_send_with_retries_retry_after_integration():
    async def run_test():
        model = Model("openai/gpt-4o")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.headers = {"retry-after": "1.5"}

        rate_limit_err = litellm.RateLimitError(
            message="Rate limit exceeded",
            response=mock_resp,
            model="openai/gpt-4o",
            llm_provider="openai",
        )
        rate_limit_err.status_code = 429

        call_count = 0
        slept_delays = []

        async def mock_send_completion(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise rate_limit_err
            return (
                "hash",
                MagicMock(choices=[MagicMock(message=MagicMock(content="generated commit"))]),
            )

        def mock_sleep(delay):
            slept_delays.append(delay)

        with (
            patch.object(model, "send_completion", side_effect=mock_send_completion),
            patch("time.sleep", side_effect=mock_sleep),
        ):
            result = await model.simple_send_with_retries(
                messages=[{"role": "user", "content": "generate commit"}]
            )

        assert len(slept_delays) == 1
        assert slept_delays[0] == 1.5
        assert result == "generated commit"

    asyncio.run(run_test())


def test_simple_send_with_retries_gemini_payload_integration():
    async def run_test():
        model = Model("gemini/gemini-2.5-flash")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": {
                "code": 429,
                "message": "Resource exhausted",
                "details": [{"retryDelay": "2.0s"}],
            }
        }

        rate_limit_err = litellm.RateLimitError(
            message="Resource exhausted",
            response=mock_resp,
            model="gemini/gemini-2.5-flash",
            llm_provider="gemini",
        )
        rate_limit_err.status_code = 429

        call_count = 0
        slept_delays = []

        async def mock_send_completion(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise rate_limit_err
            return (
                "hash",
                MagicMock(choices=[MagicMock(message=MagicMock(content="summary output"))]),
            )

        def mock_sleep(delay):
            slept_delays.append(delay)

        with (
            patch.object(model, "send_completion", side_effect=mock_send_completion),
            patch("time.sleep", side_effect=mock_sleep),
        ):
            result = await model.simple_send_with_retries(
                messages=[{"role": "user", "content": "summarize"}]
            )

        assert len(slept_delays) == 1
        assert slept_delays[0] == 2.0
        assert result == "summary output"

    asyncio.run(run_test())


def test_simple_send_with_retries_exceeds_retry_timeout():
    async def run_test():
        model = Model("openai/gpt-4o")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.headers = {"retry-after": "100"}

        rate_limit_err = litellm.RateLimitError(
            message="Rate limit exceeded",
            response=mock_resp,
            model="openai/gpt-4o",
            llm_provider="openai",
        )
        rate_limit_err.status_code = 429

        slept_delays = []

        async def mock_send_completion(*args, **kwargs):
            raise rate_limit_err

        def mock_sleep(delay):
            slept_delays.append(delay)

        with (
            patch.object(model, "send_completion", side_effect=mock_send_completion),
            patch("time.sleep", side_effect=mock_sleep),
        ):
            result = await model.simple_send_with_retries(
                messages=[{"role": "user", "content": "test"}]
            )

        assert len(slept_delays) == 0
        assert result is None

    asyncio.run(run_test())
