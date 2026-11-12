"""Null ``content`` normalization at the llms pipeline wire boundary.

Some OpenAI-compatible APIs reject ``content: null``; the pipeline must send an
empty string instead for every request body (stream and non-stream) without
mutating the caller's stored messages.
"""

import asyncio

import cecli.helpers.llms.pipeline as pipeline
from cecli.helpers.llms.types import (
    Choice,
    CompletionChunk,
    CompletionResponse,
    Message,
)

MODEL = "deepseek/deepseek-v4-flash"


def _fake_response(model):
    return CompletionResponse(
        id="x",
        model=model,
        choices=[Choice(index=0, message=Message(role="assistant", content="hi"))],
    )


def test_pipeline_replaces_null_content(monkeypatch):
    captured = {}

    async def fake_chat_complete(resolved, messages, tools, key, headers, kwargs):
        captured["messages"] = messages
        return _fake_response(resolved["model"])

    monkeypatch.setattr(pipeline, "chat_complete", fake_chat_complete)

    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": None},
    ]

    asyncio.run(pipeline.acompletion(model=MODEL, messages=messages))

    assert captured["messages"][1]["content"] == ""
    assert captured["messages"][2]["content"] == ""
    # The caller's stored messages are not touched.
    assert messages[1]["content"] is None
    assert messages[2]["content"] is None


def test_pipeline_replaces_null_reasoning_content(monkeypatch):
    captured = {}

    async def fake_chat_complete(resolved, messages, tools, key, headers, kwargs):
        captured["messages"] = messages
        return _fake_response(resolved["model"])

    monkeypatch.setattr(pipeline, "chat_complete", fake_chat_complete)

    messages = [
        {"role": "assistant", "content": "hi", "reasoning_content": None},
        {"role": "assistant", "content": "yo"},
        {"role": "user", "content": "q", "reasoning_content": None},
    ]

    asyncio.run(pipeline.acompletion(model=MODEL, messages=messages))

    assert captured["messages"][0]["reasoning_content"] == ""
    # Absent keys stay absent.
    assert "reasoning_content" not in captured["messages"][1]
    assert captured["messages"][2]["reasoning_content"] is None
    # The caller's stored messages are not touched.
    assert messages[0]["reasoning_content"] is None


def test_pipeline_leaves_non_null_content_alone(monkeypatch):
    captured = {}

    async def fake_chat_complete(resolved, messages, tools, key, headers, kwargs):
        captured["messages"] = messages
        return _fake_response(resolved["model"])

    monkeypatch.setattr(pipeline, "chat_complete", fake_chat_complete)

    parts = [{"type": "text", "text": "hi"}]
    messages = [
        {"role": "user", "content": parts},
        {"role": "assistant", "content": ""},
    ]

    asyncio.run(pipeline.acompletion(model=MODEL, messages=messages))

    assert captured["messages"][0]["content"] is parts
    assert captured["messages"][1]["content"] == ""


def test_pipeline_replaces_null_content_for_streaming(monkeypatch):
    captured = {}

    async def fake_chat_stream(resolved, messages, tools, key, headers, kwargs):
        captured["messages"] = messages
        yield CompletionChunk(text="hi", finish_reason="stop")

    monkeypatch.setattr(pipeline, "chat_stream", fake_chat_stream)

    async def consume():
        gen = await pipeline.acompletion(
            model=MODEL,
            messages=[{"role": "assistant", "content": None}],
            stream=True,
        )

        return [chunk async for chunk in gen]

    chunks = asyncio.run(consume())

    assert captured["messages"][0]["content"] == ""
    assert chunks[0].text == "hi"
