"""Tests for the opt-in Gemini Interactions API adapter (stateless mode).

All HTTP is mocked with ``httpx.MockTransport``; no live network is used.
"""

import asyncio
import json

from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.domains import interactions as interactions_mod
from cecli.helpers.llms.domains.interactions import (
    interactions_complete,
    interactions_input,
    interactions_payload,
    interactions_stream,
    normalize_interactions_response,
)
from cecli.http import httpx

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]


def _resolved(model="gemini/gemini-4-hydrogen"):
    return resolve_model_config(model)


def _mock_client(monkeypatch, handler):
    def make_client(timeout, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(interactions_mod, "make_client", make_client)


def _sse_body(events):
    lines = []

    for event_type, data in events:
        lines.append(f"event: {event_type}\n")
        lines.append(f"data: {json.dumps(data)}\n\n")

    return "".join(lines).encode()


# ---------------------------------------------------------------------------
# Routing: Gemini 4 uses Interactions; Gemini 3 and older use generateContent
# ---------------------------------------------------------------------------


def test_gemini_4_resolution_uses_interactions():
    resolved = _resolved("gemini/gemini-4-hydrogen")

    assert resolved["family"] == "interactions"
    assert resolved["provider"] == "gemini"
    assert resolved["route"] == "gemini-4-hydrogen"
    assert resolved["api_base"] == "https://generativelanguage.googleapis.com"


def test_gemini_4_variants_use_interactions():
    for model in (
        "gemini/gemini-4-carbon",
        "gemini/gemini-4-argon",
        "gemini/gemini-4-neon",
    ):
        assert _resolved(model)["family"] == "interactions", model


def test_gemini_3_resolution_stays_generate_content():
    assert _resolved("gemini/gemini-3.5-flash")["family"] == "gemini"


def test_gemini_25_resolution_stays_generate_content():
    assert _resolved("gemini/gemini-2.5-pro")["family"] == "gemini"


# ---------------------------------------------------------------------------
# Request body: stateless full history and verbatim thought signatures
# ---------------------------------------------------------------------------


def test_request_body_is_stateless_and_uses_full_history():
    messages = [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "weather in Paris?"},
        {
            "role": "assistant",
            "content": "",
            "provider_specific_fields": {
                "interactions_steps": [
                    {
                        "type": "thought",
                        "signature": "sig-verbatim",
                        "summary": [{"type": "text", "text": "Need the weather"}],
                    },
                    {
                        "type": "function_call",
                        "name": "get_weather",
                        "arguments": {"city": "Paris"},
                        "id": "call_1",
                    },
                ]
            },
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "get_weather", "content": "sunny"},
        {"role": "user", "content": "thanks"},
    ]
    payload = interactions_payload(_resolved(), messages, TOOLS, {})

    assert payload["model"] == "gemini-4-hydrogen"
    assert payload["store"] is False
    assert "previous_interaction_id" not in payload
    assert payload["system_instruction"] == "be terse"
    assert [step["type"] for step in payload["input"]] == [
        "user_input",
        "thought",
        "function_call",
        "function_result",
        "user_input",
    ]
    assert payload["input"][1]["signature"] == "sig-verbatim"
    assert payload["input"][1]["summary"] == [{"type": "text", "text": "Need the weather"}]
    assert payload["input"][2]["id"] == "call_1"
    assert payload["input"][3]["call_id"] == "call_1"
    assert payload["input"][3]["result"] == [{"type": "text", "text": "sunny"}]
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "get_weather",
            "description": "Get weather for a city",
            "parameters": TOOLS[0]["function"]["parameters"],
        }
    ]


def test_signature_round_trips_verbatim_from_response_to_next_request():
    data = {
        "id": "int_1",
        "model": "gemini-4-hydrogen",
        "status": "completed",
        "steps": [
            {
                "type": "thought",
                "signature": "sig-xyz",
                "summary": [{"type": "text", "text": "thinking"}],
            },
            {"type": "model_output", "content": [{"type": "text", "text": "hello"}]},
        ],
        "usage": {},
    }
    response = normalize_interactions_response(data, "gemini-4-hydrogen")
    assert response.choices[0].finish_reason == "stop"
    assert response.text == "hello"
    assert response.reasoning == "thinking"
    assert response.provider_specific_fields["thought_signatures"] == ["sig-xyz"]

    history = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": response.text,
            "provider_specific_fields": response.provider_specific_fields,
        },
        {"role": "user", "content": "again"},
    ]
    payload = interactions_payload(_resolved(), history, None, {})

    assert payload["input"][1] == data["steps"][0]
    assert payload["input"][1]["signature"] == "sig-xyz"


def test_builtin_tool_step_signatures_are_preserved_for_replay():
    steps = [
        {
            "type": "google_search_call",
            "id": "gs_1",
            "arguments": {"queries": ["weather paris"]},
            "signature": "search-sig-1",
        },
        {
            "type": "google_search_result",
            "call_id": "gs_1",
            "result": {"search_suggestions": "sunny"},
            "signature": "search-sig-2",
        },
        {"type": "model_output", "content": [{"type": "text", "text": "sunny"}]},
    ]
    response = normalize_interactions_response(
        {"id": "int_search", "status": "completed", "steps": steps, "usage": {}},
        "gemini-4-hydrogen",
    )
    history = [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "provider_specific_fields": response.provider_specific_fields},
    ]
    payload = interactions_payload(_resolved(), history, None, {})

    assert payload["input"][1:4] == steps
    assert payload["input"][1]["signature"] == "search-sig-1"
    assert payload["input"][2]["signature"] == "search-sig-2"


def test_thought_steps_resend_when_switching_models():
    steps = [
        {"type": "thought", "signature": "sig-other", "summary": []},
        {"type": "model_output", "content": [{"type": "text", "text": "ok"}]},
    ]
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "ok",
            "provider_specific_fields": {"interactions_steps": steps},
        },
    ]
    resolved = _resolved("gemini/gemini-3-flash-preview")
    payload = interactions_payload(resolved, messages, None, {})

    assert payload["input"][1]["signature"] == "sig-other"


# ---------------------------------------------------------------------------
# Function calls and results
# ---------------------------------------------------------------------------


def test_function_call_response_and_result_round_trip(monkeypatch):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "int_call",
                "model": "gemini-4-hydrogen",
                "status": "requires_action",
                "steps": [
                    {
                        "type": "thought",
                        "signature": "sig-call",
                        "summary": [{"type": "text", "text": "call the tool"}],
                    },
                    {
                        "type": "function_call",
                        "name": "get_weather",
                        "arguments": {"city": "Paris"},
                        "id": "call_42",
                    },
                ],
                "usage": {},
            },
        )

    _mock_client(monkeypatch, handler)
    response = asyncio.run(
        interactions_complete(
            _resolved(),
            [{"role": "user", "content": "weather?"}],
            TOOLS,
            "key",
            {},
            {},
        )
    )

    assert calls[0]["store"] is False
    assert calls[0]["input"] == [
        {"type": "user_input", "content": [{"type": "text", "text": "weather?"}]}
    ]
    assert response.choices[0].finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert (call.id, call.name, call.arguments) == ("call_42", "get_weather", {"city": "Paris"})

    history = [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "provider_specific_fields": response.provider_specific_fields},
        {
            "role": "tool",
            "tool_call_id": "call_42",
            "name": "get_weather",
            "content": "sunny",
        },
    ]
    payload = interactions_payload(_resolved(), history, TOOLS, {})
    kinds = [step["type"] for step in payload["input"]]

    assert kinds == ["user_input", "thought", "function_call", "function_result"]
    assert payload["input"][2]["id"] == "call_42"
    assert payload["input"][2]["arguments"] == {"city": "Paris"}
    assert payload["input"][3]["call_id"] == "call_42"


def test_parallel_function_calls_are_preserved():
    response = normalize_interactions_response(
        {
            "id": "int_parallel",
            "status": "requires_action",
            "steps": [
                {
                    "type": "function_call",
                    "name": "get_weather",
                    "arguments": {"city": "Paris"},
                    "id": "call_a",
                },
                {
                    "type": "function_call",
                    "name": "get_weather",
                    "arguments": {"city": "Rome"},
                    "id": "call_b",
                },
            ],
            "usage": {},
        },
        "gemini-4-hydrogen",
    )

    assert [call.id for call in response.tool_calls] == ["call_a", "call_b"]
    assert [call.arguments for call in response.tool_calls] == [
        {"city": "Paris"},
        {"city": "Rome"},
    ]
    assert response.choices[0].finish_reason == "tool_calls"
    assert len(response.provider_specific_fields["interactions_steps"]) == 2


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def test_streaming_tool_call_deltas_and_signatures(monkeypatch):
    events = [
        (
            "step.start",
            {
                "index": 0,
                "step": {
                    "type": "thought",
                    "summary": [{"type": "text", "text": "Thinking..."}],
                },
                "event_type": "step.start",
            },
        ),
        (
            "step.delta",
            {
                "index": 0,
                "delta": {"type": "thought_signature", "signature": "sig-stream"},
                "event_type": "step.delta",
            },
        ),
        ("step.stop", {"index": 0, "event_type": "step.stop"}),
        (
            "step.start",
            {
                "index": 1,
                "step": {
                    "type": "function_call",
                    "id": "call_s",
                    "name": "get_weather",
                    "arguments": {},
                },
                "event_type": "step.start",
            },
        ),
        (
            "step.delta",
            {
                "index": 1,
                "delta": {"type": "arguments_delta", "arguments": '{"city": "'},
                "event_type": "step.delta",
            },
        ),
        (
            "step.delta",
            {
                "index": 1,
                "delta": {"type": "arguments_delta", "arguments": 'Paris"}'},
                "event_type": "step.delta",
            },
        ),
        ("step.stop", {"index": 1, "event_type": "step.stop"}),
        (
            "interaction.completed",
            {
                "event_type": "interaction.completed",
                "interaction": {
                    "id": "int_stream",
                    "status": "requires_action",
                    "usage": {
                        "total_input_tokens": 10,
                        "total_output_tokens": 5,
                        "total_thought_tokens": 7,
                        "total_tokens": 22,
                    },
                },
            },
        ),
    ]
    body = _sse_body(events)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    _mock_client(monkeypatch, handler)

    async def collect():
        return [chunk async for chunk in interactions_stream(_resolved(), [], TOOLS, "key", {}, {})]

    chunks = asyncio.run(collect())

    assert seen[0]["stream"] is True
    assert seen[0]["store"] is False
    fragments = [message.arguments["_fragment"] for chunk in chunks for message in chunk.tool_calls]
    assert "".join(fragments) == '{"city": "Paris"}'
    assert any(chunk.finish_reason == "tool_calls" for chunk in chunks)
    assert chunks[-1].usage.prompt_tokens == 10
    assert chunks[-1].usage.completion_tokens == 12

    steps = []
    for chunk in chunks:
        steps.extend(chunk.provider_specific_fields.get("interactions_steps", []))

    assert steps[0]["type"] == "thought"
    assert steps[0]["signature"] == "sig-stream"
    assert steps[1] == {
        "type": "function_call",
        "id": "call_s",
        "name": "get_weather",
        "arguments": {"city": "Paris"},
    }


def test_streaming_model_output_text_and_usage(monkeypatch):
    events = [
        (
            "step.start",
            {
                "index": 0,
                "step": {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "Hel"}],  # codespell:ignore
                },
                "event_type": "step.start",
            },
        ),
        (
            "step.delta",
            {
                "index": 0,
                "delta": {"type": "text", "text": "lo"},
                "event_type": "step.delta",
            },
        ),
        ("step.stop", {"index": 0, "event_type": "step.stop"}),
        (
            "interaction.completed",
            {
                "event_type": "interaction.completed",
                "interaction": {
                    "id": "int_text",
                    "status": "completed",
                    "usage": {
                        "total_input_tokens": 3,
                        "total_output_tokens": 2,
                        "total_thought_tokens": 1,
                        "total_tokens": 6,
                        "total_cached_tokens": 2,
                        "total_tool_use_tokens": 0,
                    },
                },
            },
        ),
    ]
    body = _sse_body(events)
    _mock_client(monkeypatch, lambda request: httpx.Response(200, content=body))

    async def collect():
        return [chunk async for chunk in interactions_stream(_resolved(), [], None, "key", {}, {})]

    chunks = asyncio.run(collect())
    assert "".join(chunk.text for chunk in chunks) == "Hello"
    step_chunks = [
        chunk for chunk in chunks if chunk.provider_specific_fields.get("interactions_steps")
    ]
    assert step_chunks[0].provider_specific_fields["interactions_steps"][0]["content"] == [
        {"type": "text", "text": "Hello"}
    ]


# ---------------------------------------------------------------------------
# Usage / finish reason mapping
# ---------------------------------------------------------------------------


def test_usage_mapping_adds_thought_tokens():
    response = normalize_interactions_response(
        {
            "id": "int_usage",
            "status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": "ok"}]}],
            "usage": {
                "total_input_tokens": 10,
                "total_output_tokens": 5,
                "total_thought_tokens": 7,
                "total_tokens": 22,
                "total_cached_tokens": 2,
                "total_tool_use_tokens": 0,
            },
        },
        "gemini-4-hydrogen",
    )

    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 12
    assert response.usage.total_tokens == 22
    assert response.usage.prompt_cache_hit_tokens == 2
    assert response.usage.completion_tokens_details["reasoning_tokens"] == 7


def test_incomplete_status_maps_to_length():
    response = normalize_interactions_response(
        {"status": "incomplete", "steps": [], "usage": {}}, "gemini-4-hydrogen"
    )
    assert response.choices[0].finish_reason == "length"


def test_input_builder_does_not_emit_state_fields():
    steps = interactions_input([{"role": "user", "content": "hi"}])

    assert steps == [{"type": "user_input", "content": [{"type": "text", "text": "hi"}]}]
    assert all("previous_interaction_id" not in step for step in steps)


def test_is_gemini_4_identifier():
    from cecli.helpers.llms.identifiers import is_gemini_4

    assert is_gemini_4("gemini", "gemini-4-hydrogen", {})
    assert is_gemini_4(None, "gemini-4-carbon", {})
    assert not is_gemini_4("gemini", "gemini-3.5-flash", {})
    assert not is_gemini_4("gemini", "gemini-2.5-pro", {})
