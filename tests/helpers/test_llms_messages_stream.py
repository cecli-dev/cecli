"""Streaming stash fidelity for anthropic tool_use input.

Tool-call arguments arrive over SSE as ``input_json_delta`` partial_json
fragments. ``anthropic_stream`` must accumulate them into the stashed
``tool_use`` block so the next-turn replay (and prompt-cache prefix) keeps
the exact ``input`` the model sent instead of ``{}``.

No network: the family adapter's ``make_client`` is monkeypatched.
"""

import asyncio
import json

from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.domains import messages as messages_domain
from cecli.helpers.llms.domains.messages import anthropic_payload, anthropic_stream


def _sse(obj):
    return f"data: {json.dumps(obj)}"


class _FakeStreamClient:
    """Stand-in for ``make_client`` supporting the stream() context manager."""

    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def stream(self, *args, **kwargs):
        return self

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _run(gen):
    async def collect():
        return [c async for c in gen]

    return asyncio.new_event_loop().run_until_complete(collect())


def _stream_tool_use_chunks(monkeypatch, partials):
    lines = [
        _sse(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_01",
                    "name": "Local--ReadFile",
                    "input": {},
                },
            }
        ),
    ]
    lines += [
        _sse(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": p},
            }
        )
        for p in partials
    ]
    lines += [
        _sse({"type": "content_block_stop", "index": 0}),
        _sse(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        ),
    ]

    client = _FakeStreamClient(lines)
    monkeypatch.setattr(messages_domain, "make_client", lambda *a, **k: client)
    resolved = resolve_model_config("claude-sonnet-5")

    return _run(
        anthropic_stream(resolved, [{"role": "user", "content": "hi"}], None, "key", {}, {})
    )


def _stashed_tool_use(chunks):
    stash = next(
        c.provider_specific_fields.get("anthropic")
        for c in chunks
        if c.provider_specific_fields.get("anthropic")
    )

    return next(b for b in stash if b["type"] == "tool_use")


def test_streaming_stash_keeps_full_tool_use_input(monkeypatch):
    chunks = _stream_tool_use_chunks(monkeypatch, ['{"r', 'ead": [', '{"file_path": "a.py"}]}'])
    tool_use = _stashed_tool_use(chunks)

    assert tool_use["id"] == "toolu_01"
    assert tool_use["name"] == "Local--ReadFile"
    assert tool_use["input"] == {"read": [{"file_path": "a.py"}]}
    assert "_input_raw" not in tool_use


def test_streamed_input_round_trips_into_next_payload(monkeypatch):
    chunks = _stream_tool_use_chunks(monkeypatch, ['{"sear', 'ches": [', '".py"]}'])
    stash = next(
        c.provider_specific_fields.get("anthropic")
        for c in chunks
        if c.provider_specific_fields.get("anthropic")
    )

    messages = [
        {"role": "user", "content": "search"},
        {"role": "assistant", "provider_specific_fields": {"anthropic": stash}},
        {"role": "tool", "tool_call_id": "toolu_01", "content": "ok"},
    ]
    resolved = resolve_model_config("claude-sonnet-5")
    payload = anthropic_payload(resolved, messages, None, False, {})

    tool_use = next(
        b
        for m in payload["messages"]
        if m["role"] == "assistant"
        for b in m["content"]
        if b["type"] == "tool_use"
    )

    assert tool_use["input"] == {"searches": [".py"]}
