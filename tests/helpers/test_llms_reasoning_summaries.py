"""Reasoning/thinking summary tracking and replay-stripping for the llms package.

When a model is configured to expose summaries (``display: "summarized"`` on the
messages API, ``reasoning.summary`` on the responses API), the response captures
the readable summary. We track that in ``provider_specific_fields`` and then
actively strip the summary text when re-injecting (replaying) the conversation
into the next request, keeping only the continuity artifacts (thinking
``signature`` / reasoning ``encrypted_content``). This keeps the cached prompt
prefix stable across turns instead of churning it with per-turn reasoning text.
"""

from __future__ import annotations

from cecli.helpers.llms.domains.messages import (
    anthropic_message,
    normalize_anthropic_response,
)
from cecli.helpers.llms.domains.responses import (
    normalize_responses_response,
    to_responses_input,
)


# --- Anthropic (messages) ---
def test_anthropic_summary_flags_and_strips_on_replay():
    data = {
        "model": "claude-sonnet-5",
        "content": [
            {"type": "thinking", "thinking": "Here is the summary.", "signature": "sig1"},
            {"type": "text", "text": "Answer"},
        ],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    msg = normalize_anthropic_response(data, "claude-sonnet-5").choices[0].message

    assert msg.provider_specific_fields["use_thinking_summaries"] is True

    replayed = anthropic_message(
        {
            "role": "assistant",
            "content": msg.content,
            "provider_specific_fields": msg.provider_specific_fields,
        }
    )
    thinking = [b for b in replayed["content"] if b["type"] == "thinking"][0]
    assert thinking["thinking"] == ""  # summary text stripped
    assert thinking["signature"] == "sig1"  # continuity artifact preserved


def test_anthropic_omitted_no_flag_and_replays_as_is():
    data = {
        "model": "claude-sonnet-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig0"},
            {"type": "text", "text": "Answer"},
        ],
        "stop_reason": "end_turn",
        "usage": {},
    }
    msg = normalize_anthropic_response(data, "claude-sonnet-5").choices[0].message

    assert msg.provider_specific_fields.get("use_thinking_summaries", False) is False

    replayed = anthropic_message(
        {
            "role": "assistant",
            "content": msg.content,
            "provider_specific_fields": msg.provider_specific_fields,
        }
    )
    thinking = [b for b in replayed["content"] if b["type"] == "thinking"][0]
    assert thinking["thinking"] == ""
    assert thinking["signature"] == "sig0"


def test_anthropic_legacy_no_flag_preserves_summary():
    # A message stashed before the flag existed keeps its summary text on replay.
    psf = {"anthropic": [{"type": "thinking", "thinking": "OLD TEXT", "signature": "sig2"}]}
    replayed = anthropic_message(
        {"role": "assistant", "content": "x", "provider_specific_fields": psf}
    )
    thinking = [b for b in replayed["content"] if b["type"] == "thinking"][0]
    assert thinking["thinking"] == "OLD TEXT"


# --- Responses ---
def test_responses_summary_flags_and_strips_on_replay():
    data = {
        "id": "r1",
        "model": "gpt-5.1",
        "status": "completed",
        "output": [
            {
                "type": "reasoning",
                "id": "rsn1",
                "summary": [{"type": "summary_text", "text": "Step-by-step."}],
                "encrypted_content": "cipher",
            },
            {"type": "message", "content": [{"type": "output_text", "text": "Answer"}]},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    msg = normalize_responses_response(data, "gpt-5.1").choices[0].message

    assert msg.provider_specific_fields["use_reasoning_summaries"] is True

    items = to_responses_input(
        [
            {"role": "user", "content": "next"},
            {
                "role": "assistant",
                "content": msg.content,
                "provider_specific_fields": msg.provider_specific_fields,
            },
        ],
        "gpt-5.1",
    )
    reasoning = [i for i in items if i.get("type") == "reasoning"][0]
    assert reasoning["summary"] == []  # summary stripped
    assert reasoning["encrypted_content"] == "cipher"  # continuity preserved
    assert reasoning["id"] == "rsn1"


def test_responses_legacy_no_flag_preserves_summary():
    psf = {
        "reasoning_items": [
            {
                "type": "reasoning",
                "id": "i",
                "encrypted_content": "c",
                "summary": [{"type": "summary_text", "text": "LEGACY"}],
            }
        ],
        "reasoning_items_origin": "gpt-5.1",
    }
    items = to_responses_input(
        [{"role": "assistant", "content": "x", "provider_specific_fields": psf}], "gpt-5.1"
    )
    reasoning = [i for i in items if i.get("type") == "reasoning"][0]
    assert reasoning["summary"] == [{"type": "summary_text", "text": "LEGACY"}]
