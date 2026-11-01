"""Tests for retry-config fallback models and credential pools.

Covers the nested ``retries.fallbacks`` block: model-chain failover on
rate-limit/retryable errors, credential rotation within a provider key pool,
and the bench policy that skips recently-failed models on subsequent requests.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from cecli.llm import litellm
from cecli.models import Model, parse_retry_config


def _rate_limit(model_name):
    return litellm.RateLimitError(message="429 slow down", model=model_name, llm_provider="openai")


def _auth_error(model_name):
    return litellm.AuthenticationError(
        message="401 invalid", model=model_name, llm_provider="openai"
    )


def _ok_response():
    return MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])


class TestParseFallbacks:
    def test_nested_models_and_keys(self):
        cfg = parse_retry_config(
            {
                "fallbacks": {
                    "models": {"model": ["a", 7, "b"], "weak": ["w"]},
                    "keys": {"openai": ["K1", "K2"]},
                }
            }
        )
        assert cfg["fallbacks"]["models"] == {"model": ["a", "b"], "weak": ["w"]}
        assert cfg["fallbacks"]["keys"] == {"openai": ["K1", "K2"]}

    def test_list_shorthand_is_main_chain(self):
        cfg = parse_retry_config({"fallbacks": ["m1", "m2"]})
        assert cfg["fallbacks"]["models"] == {"model": ["m1", "m2"]}

    def test_min_switch_reset_seconds(self):
        cfg = parse_retry_config({"min-switch-reset-seconds": 120})
        assert cfg["min_switch_reset_seconds"] == 120.0

    def test_malformed_block_ignored(self):
        assert parse_retry_config({"fallbacks": 5})["fallbacks"] is None
        assert parse_retry_config({"fallbacks": {"models": "nope"}}) is not None

    def test_defaults_have_no_fallbacks(self):
        assert parse_retry_config(None)["fallbacks"] is None


@pytest.fixture
def fallback_model():
    os.environ.setdefault("OPENAI_API_KEY", "sk-primary")
    return Model(
        "gpt-4o",
        retries={
            "retry_timeout": 1.0,
            "retry_backoff_factor": 1.5,
            "fallbacks": {"models": {"model": ["gpt-4o-mini"]}},
        },
    )


class TestModelFallback:
    async def test_rate_limit_switches_to_fallback(self, fallback_model):
        model = fallback_model
        seen = []

        async def fake_acompletion(**kwargs):
            seen.append(kwargs["model"])
            if kwargs["model"] == "gpt-4o":
                raise _rate_limit("gpt-4o")
            return _ok_response()

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=fake_acompletion),
            patch("asyncio.sleep"),
            patch("builtins.print"),
        ):
            _hash, res = await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        assert seen[-1] == "gpt-4o-mini"
        assert res.choices[0].message.content == "ok"
        assert model.fallback_state["benched_until"].get("gpt-4o")

    async def test_no_fallback_configured_returns_error_sentinel(self, monkeypatch):
        model = Model("gpt-4o", retries={"retry_timeout": 0.2})

        async def fake_acompletion(**kwargs):
            raise _rate_limit("gpt-4o")

        monkeypatch.setattr(model, "retry_timeout", 0.2)
        with (
            patch("cecli.llm.litellm.acompletion", side_effect=fake_acompletion),
            patch("asyncio.sleep"),
            patch("builtins.print"),
        ):
            _hash, res = await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        assert "Error" in res.choices[0].message.content

    async def test_rate_limit_gets_one_retry_before_switching(self):
        model = Model(
            "gpt-4o",
            retries={
                "retry_timeout": 30,
                "retry_backoff_factor": 1.5,
                "fallbacks": {"models": {"model": ["gpt-4o-mini"]}},
            },
        )
        # Otherwise the opportunistic cache-warm sleep lands in slept[0] on
        # ~25% of runs and masks the retry delay under test.
        model.caches_by_default = False
        seen = []

        async def fake_acompletion(**kwargs):
            seen.append(kwargs["model"])
            if kwargs["model"] == "gpt-4o":
                err = litellm.RateLimitError(
                    message="429 reset in 15s", model="gpt-4o", llm_provider="openai"
                )
                err.response = MagicMock()
                err.response.headers = {"retry-after": "15"}
                raise err
            return _ok_response()

        slept = []

        async def mock_sleep(delay):
            slept.append(delay)

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=fake_acompletion),
            patch("asyncio.sleep", side_effect=mock_sleep),
            patch("builtins.print"),
        ):
            _hash, res = await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        # The long declared reset permits switching, but only after the primary
        # has had one retry, and that retry must not wait out the reset window.
        assert seen[:2] == ["gpt-4o", "gpt-4o"]
        assert seen[-1] == "gpt-4o-mini"
        assert slept[0] <= 1.0
        assert res.choices[0].message.content == "ok"

    async def test_benched_chain_skips_on_next_request(self, fallback_model):
        model = fallback_model
        calls = []

        async def fake_acompletion(**kwargs):
            calls.append(kwargs["model"])
            raise _rate_limit(kwargs["model"])

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=fake_acompletion),
            patch("asyncio.sleep"),
            patch("builtins.print"),
        ):
            await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )
            calls.clear()
            await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        # Second request must not hit the benched primary first.
        assert calls and calls[0] == "gpt-4o-mini"

    async def test_expired_bench_restores_primary(self, fallback_model):
        model = fallback_model
        calls = []

        async def fake_acompletion(**kwargs):
            calls.append(kwargs["model"])
            raise _rate_limit(kwargs["model"])

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=fake_acompletion),
            patch("asyncio.sleep"),
            patch("builtins.print"),
        ):
            await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )
            model.fallback_state["benched_until"] = {}
            calls.clear()
            await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        assert calls[0] == "gpt-4o"

    async def test_copy_paste_mode_does_not_fall_back(self):
        model = Model(
            "gpt-4o",
            retries={"retry_timeout": 0.2, "fallbacks": {"models": {"model": ["gpt-4o-mini"]}}},
        )
        model.enable_copy_paste_mode()
        seen = []

        async def fake_acompletion(**kwargs):
            seen.append(kwargs["model"])
            raise _rate_limit(kwargs["model"])

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=fake_acompletion),
            patch("asyncio.sleep"),
            patch("builtins.print"),
        ):
            await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        assert set(seen) == {"gpt-4o"}

    async def test_fallback_kwargs_drop_primary_provider_params(self):
        model = Model("gpt-4o", retries=None)
        candidate = Model("gpt-4o-mini", retries=None)
        kwargs = {
            "model": "gpt-4o",
            "base_url": "https://primary.example/v1",
            "custom_llm_provider": "openai",
            "messages": [],
        }

        model._apply_fallback_kwargs(kwargs, candidate, stream=False)

        assert kwargs["model"] == "gpt-4o-mini"
        assert "base_url" not in kwargs
        assert kwargs["messages"] == []


class TestKeyPoolRotation:
    async def test_rotation_before_model_fallback(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-one")
        monkeypatch.setenv("OPENAI_API_KEY_2", "sk-two")

        model = Model(
            "openai/gpt-4o",
            retries={
                "retry_timeout": 0.2,
                "retry_on_unauthorized": True,
                "fallbacks": {
                    "keys": {"openai": ["OPENAI_API_KEY", "OPENAI_API_KEY_2"]},
                    "models": {"model": ["gpt-4o-mini"]},
                },
            },
        )
        keys = []

        async def fake_acompletion(**kwargs):
            keys.append(kwargs.get("api_key"))
            if kwargs.get("api_key") != "sk-two":
                raise _auth_error("openai/gpt-4o")
            return _ok_response()

        with (
            patch("cecli.llm.litellm.acompletion", side_effect=fake_acompletion),
            patch("asyncio.sleep"),
            patch("builtins.print"),
        ):
            _hash, res = await model.send_completion(
                messages=[{"role": "user", "content": "hi"}], functions=None, stream=False
            )

        assert None in keys[:1]  # first attempt uses the provider default key
        assert "sk-two" in keys
        assert res.choices[0].message.content == "ok"
        assert model.fallback_state["active"] == 0  # never reached model fallback

    async def test_dedicated_auth_providers_skip_rotation(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "g-one")
        monkeypatch.setenv("GEMINI_API_KEY_2", "g-two")

        model = Model(
            "gemini/gemini-2.5-flash",
            retries={"fallbacks": {"keys": {"gemini": ["GEMINI_API_KEY", "GEMINI_API_KEY_2"]}}},
        )

        class ExInfo:
            name = "AuthenticationError"

        kwargs = {"model": "gemini/gemini-2.5-flash"}
        assert model._should_rotate_key(Exception("401"), ExInfo(), kwargs) is True
        # rotation is allowed for plain env-keyed providers
        assert kwargs["api_key"] == "g-two"
