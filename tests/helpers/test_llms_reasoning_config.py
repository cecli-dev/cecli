"""Reasoning-config path tests: Model settings -> shim -> domain wire payload.

Covers the per-provider mapping of ``reasoning_effort`` (low/medium/high) and the
thinking budget (``set_thinking_tokens``) onto each domain's wire payload:

- chat: flat ``reasoning_effort`` / ``thinking`` keys
- gemini: ``generationConfig.thinkingConfig`` (``thinkingLevel`` or
  ``thinkingBudget``), with an explicit budget winning over the config-default
  effort
- anthropic: ``output_config.effort`` (Claude 5+) or the ``thinking`` block
  (pre-5)
- responses: nested ``reasoning.effort`` (generic keys stripped)

Plus the shim's forwarding of the model-config formatters' top-level kwargs
(``LazyLiteLLM.acompletion``) into the ``extra_body`` channel the builders
consume. No network: the package dispatch is monkeypatched.
"""

import asyncio

import cecli.helpers.llms as llms_pkg
from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.domains.chat import chat_payload
from cecli.helpers.llms.domains.gemini import gemini_payload
from cecli.helpers.llms.domains.messages import anthropic_payload
from cecli.helpers.llms.domains.responses import responses_payload
from cecli.helpers.llms.litellm_compat import litellm
from cecli.helpers.llms.types import Choice, CompletionResponse, Message

MSGS = [{"role": "user", "content": "hi"}]


def _build(family, resolved, extra_body):
    """Call the family payload builder with ``extra_body`` overrides."""
    kwargs = {"extra_body": dict(extra_body or {})}
    if family == "chat":
        return chat_payload(resolved, MSGS, None, False, kwargs)
    if family == "gemini":
        return gemini_payload(resolved, MSGS, None, kwargs)
    if family == "anthropic":
        return anthropic_payload(resolved, MSGS, None, False, kwargs)
    return responses_payload(resolved, MSGS, None, False, kwargs)


def _wire(payload):
    """Extract the reasoning-related wire fields from a built payload."""
    out = {}
    gen = payload.get("generationConfig") or {}
    if gen.get("thinkingConfig"):
        out["thinkingConfig"] = gen["thinkingConfig"]
    for key in ("reasoning_effort", "thinking", "reasoning", "output_config"):
        if key in payload:
            out[key] = payload[key]
    return out


def _patch_dispatch(monkeypatch, captured):
    """Monkeypatch the package dispatch, capturing the kwargs it receives."""

    async def fake_dispatch(**kwargs):
        captured.clear()
        captured.update(kwargs)
        return CompletionResponse(
            id="x",
            model=kwargs.get("model"),
            choices=[Choice(index=0, message=Message(role="assistant", content="hi"))],
        )

    monkeypatch.setattr(llms_pkg, "acompletion", fake_dispatch)


# ---------------------------------------------------------------------------
# Builder-level wire mapping
# ---------------------------------------------------------------------------


def test_chat_flat_reasoning_effort():
    resolved = resolve_model_config("deepseek/deepseek-v4-flash")
    payload = _build("chat", resolved, {"reasoning_effort": "high"})
    assert payload["reasoning_effort"] == "high"


def test_chat_flat_thinking_budget():
    resolved = resolve_model_config("deepseek/deepseek-v4-flash")
    thinking = {"type": "enabled", "budget_tokens": 4096}
    payload = _build("chat", resolved, {"thinking": thinking})
    assert payload["thinking"] == thinking


def test_gemini_effort_maps_to_thinking_level():
    resolved = resolve_model_config("gemini/gemini-3-flash-preview")
    for effort, level in (("low", "low"), ("medium", "medium"), ("high", "high")):
        payload = _build("gemini", resolved, {"reasoning_effort": effort})
        assert payload["generationConfig"]["thinkingConfig"] == {
            "thinkingLevel": level,
            "includeThoughts": True,
        }


def test_gemini_thinking_budget():
    resolved = resolve_model_config("gemini/gemini-3-flash-preview")
    payload = _build("gemini", resolved, {"thinking": {"type": "enabled", "budget_tokens": 4096}})
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 4096}


def test_gemini_thinking_budget_wins_over_config_effort():
    """Regression: an explicit set_thinking_tokens budget beats the config-default
    reasoning_effort that rides in the same channel."""
    resolved = resolve_model_config("gemini/gemini-3-flash-preview")
    payload = _build(
        "gemini",
        resolved,
        {
            "reasoning_effort": "medium",
            "thinking": {"type": "enabled", "budget_tokens": 4096},
        },
    )
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 4096}


def test_gemini_generic_reasoning_keys_not_leaked():
    resolved = resolve_model_config("gemini/gemini-3-flash-preview")
    payload = _build(
        "gemini",
        resolved,
        {
            "reasoning_effort": "high",
            "thinking": {"type": "enabled", "budget_tokens": 4096},
            "other": 1,
        },
    )
    assert "reasoning_effort" not in payload
    assert "thinking" not in payload
    assert payload["other"] == 1


def test_anthropic_5_effort_to_output_config():
    resolved = resolve_model_config("claude-sonnet-5")
    payload = _build("anthropic", resolved, {"reasoning_effort": "high"})
    assert payload["output_config"] == {"effort": "high"}


def test_anthropic_5_thinking_block_dropped():
    """Claude 5+ cannot use thinking.type.enabled; the block must not be sent."""
    resolved = resolve_model_config("claude-sonnet-5")
    payload = _build(
        "anthropic", resolved, {"thinking": {"type": "enabled", "budget_tokens": 4096}}
    )
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload


def test_anthropic_pre5_thinking_budget():
    resolved = resolve_model_config("anthropic/claude-haiku-4-5-20251001")
    payload = _build(
        "anthropic", resolved, {"thinking": {"type": "enabled", "budget_tokens": 4096}}
    )
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 4096}


def test_anthropic_pre5_effort_ignored():
    """Haiku 4.x has no effort support; the thinking block stays at the default."""
    resolved = resolve_model_config("anthropic/claude-haiku-4-5-20251001")
    payload = _build("anthropic", resolved, {"reasoning_effort": "high"})
    assert "output_config" not in payload
    assert "reasoning_effort" not in payload
    assert payload["thinking"]["type"] == "enabled"


def test_responses_effort_override():
    resolved = resolve_model_config("meta/muse-spark-1.2-contributor")
    payload = _build("responses", resolved, {"reasoning": {"effort": "low"}})
    assert payload["reasoning"]["effort"] == "low"


def test_responses_generic_reasoning_keys_stripped():
    resolved = resolve_model_config("meta/muse-spark-1.2-contributor")
    payload = _build(
        "responses",
        resolved,
        {
            "reasoning_effort": "low",
            "thinking": {"type": "enabled", "budget_tokens": 4096},
        },
    )
    assert "reasoning_effort" not in payload
    assert "thinking" not in payload


# ---------------------------------------------------------------------------
# Shim forwarding of top-level reasoning kwargs
# ---------------------------------------------------------------------------


def test_shim_forwards_top_level_reasoning_kwargs(monkeypatch):
    """Top-level reasoning_effort/thinking kwargs reach the dispatch extra_body."""
    captured = {}
    _patch_dispatch(monkeypatch, captured)

    asyncio.run(
        litellm.acompletion(
            model="deepseek/deepseek-v4-flash",
            messages=MSGS,
            stream=False,
            reasoning_effort="high",
            thinking={"type": "enabled", "budget_tokens": 4096},
        )
    )

    extra_body = captured.get("extra_body") or {}
    assert extra_body["reasoning_effort"] == "high"
    assert extra_body["thinking"] == {"type": "enabled", "budget_tokens": 4096}


# ---------------------------------------------------------------------------
# Full path: Model.set_* -> shim -> builder -> wire
# ---------------------------------------------------------------------------


def test_model_settings_reach_wire(monkeypatch):
    """The program settings path carries low/medium/high + budget to each wire."""
    from cecli.models import Model

    captured = {}
    _patch_dispatch(monkeypatch, captured)

    cases = [
        # (model, family, setter, value, expected wire reasoning fields)
        (
            "deepseek/deepseek-v4-flash",
            "chat",
            "set_reasoning_effort",
            "high",
            {"reasoning_effort": "high"},
        ),
        (
            "gemini/gemini-3-flash-preview",
            "gemini",
            "set_reasoning_effort",
            "high",
            {"thinkingConfig": {"thinkingLevel": "high", "includeThoughts": True}},
        ),
        (
            "gemini/gemini-3-flash-preview",
            "gemini",
            "set_thinking_tokens",
            "4k",
            {"thinkingConfig": {"thinkingBudget": 4096}},
        ),
        (
            "claude-sonnet-5",
            "anthropic",
            "set_reasoning_effort",
            "low",
            {"output_config": {"effort": "low"}},
        ),
        (
            "anthropic/claude-haiku-4-5-20251001",
            "anthropic",
            "set_thinking_tokens",
            "4k",
            {"thinking": {"type": "enabled", "budget_tokens": 4096}},
        ),
        (
            "meta/muse-spark-1.2-contributor",
            "responses",
            "set_reasoning_effort",
            "low",
            {"reasoning": {"effort": "low"}},
        ),
    ]

    for label, family, setter, value, expected in cases:
        captured.clear()
        model = Model(label)
        getattr(model, setter)(value)
        kwargs = {
            "model": model.name,
            "stream": False,
            "messages": MSGS,
            **dict(model.extra_params or {}),
        }
        asyncio.run(litellm.acompletion(**kwargs))
        extra_body = captured.get("extra_body") or {}
        payload = _build(family, resolve_model_config(label), extra_body)
        wire = _wire(payload)
        assert wire == expected, f"{label} {setter}({value!r}): got {wire}, expected {expected}"
