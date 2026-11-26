"""Gemini thought-signature handling for stateless (full-history) requests.

Covers the Gemini 3/4 function-call validation rules:

- signatures are required on the first ``functionCall`` of each step, so a
  replayed tool call needs its native ``thoughtSignature``;
- history transferred from another provider (or a parallel call after the
  first) has none, and the documented dummy signature must be used instead of
  rewriting the call as text;
- response-level signatures live on a part, never on the ``Content``;
- streaming responses may carry the signature on an empty final text part.
"""

from types import SimpleNamespace

from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.domains.gemini import (
    DUMMY_THOUGHT_SIGNATURE,
    _build_call_meta,
    _model_content,
    _requires_thought_signatures,
    _tool_content,
    gemini_payload,
    gemini_thinking_config,
    normalize_gemini_response,
    parse_gemini_chunk,
)
from cecli.helpers.requests import model_request_parser

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

FOREIGN_HISTORY = [
    {"role": "user", "content": "What's the weather in Paris?"},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call_abc", "name": "get_weather", "content": "Sunny"},
]

REAL_SIGNATURE = "native-encrypted-signature"


def _resolved(route: str):
    return resolve_model_config(f"gemini/{route}")


def _payload(route: str, messages):
    return gemini_payload(_resolved(route), messages, TOOLS, {"max_tokens": 16})


def _function_calls(payload):
    return [
        part
        for content in payload["contents"]
        for part in content.get("parts") or []
        if "functionCall" in part
    ]


def _function_responses(payload):
    return [
        part
        for content in payload["contents"]
        for part in content.get("parts") or []
        if "functionResponse" in part
    ]


# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------


def test_requires_thought_signatures_for_gemini_3_and_4():
    for route in (
        "gemini-3-pro-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash",
        "gemini-3.8-flash",
        "gemini-4-hydrogen",
        "gemini-4-carbon",
    ):
        assert _requires_thought_signatures({"route": route}), route


def test_requires_thought_signatures_is_false_for_older_models():
    for route in ("gemini-2.5-pro", "gemini-2.5-flash-lite", "gemini-2.0-flash", ""):
        assert not _requires_thought_signatures({"route": route}), route


# ---------------------------------------------------------------------------
# Replay: foreign history and native signatures
# ---------------------------------------------------------------------------


def test_foreign_tool_call_gets_dummy_signature_instead_of_text():
    resolved = _resolved("gemini-4-hydrogen")
    messages = model_request_parser(
        SimpleNamespace(name="gemini/gemini-4-hydrogen", info={"supports_assistant_prefill": True}),
        [dict(m) for m in FOREIGN_HISTORY],
        TOOLS,
    )
    payload = gemini_payload(resolved, messages, TOOLS, {"max_tokens": 16})

    calls = _function_calls(payload)
    assert len(calls) == 1
    assert calls[0]["thoughtSignature"] == DUMMY_THOUGHT_SIGNATURE
    assert len(_function_responses(payload)) == 1
    assert not any("thoughtSignature" in content for content in payload["contents"])


def test_native_function_call_signature_is_replayed_verbatim():
    messages = [
        {"role": "user", "content": "Weather?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                }
            ],
            "provider_specific_fields": {"function_call_signatures": {"call_1": REAL_SIGNATURE}},
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "get_weather", "content": "Sunny"},
    ]

    payload = _payload("gemini-4-hydrogen", messages)
    calls = _function_calls(payload)

    assert calls[0]["thoughtSignature"] == REAL_SIGNATURE
    assert len(_function_responses(payload)) == 1


def test_per_tool_call_provider_signature_is_used():
    messages = [
        {"role": "user", "content": "Weather?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                    "provider_specific_fields": {"thought_signature": REAL_SIGNATURE},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "get_weather", "content": "Sunny"},
    ]

    assert _build_call_meta(messages)["call_1"]["signature"] == REAL_SIGNATURE
    assert (
        _function_calls(_payload("gemini-4-hydrogen", messages))[0]["thoughtSignature"]
        == REAL_SIGNATURE
    )


def test_parallel_calls_keep_first_signature_and_dummy_the_rest():
    messages = [
        {"role": "user", "content": "Weather in Paris and London?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "London"}'},
                },
            ],
            "provider_specific_fields": {"function_call_signatures": {"call_1": REAL_SIGNATURE}},
        },
        {"role": "tool", "tool_call_id": "call_1", "name": "get_weather", "content": "Sunny"},
        {"role": "tool", "tool_call_id": "call_2", "name": "get_weather", "content": "Rain"},
    ]

    calls = _function_calls(_payload("gemini-4-hydrogen", messages))

    assert calls[0]["thoughtSignature"] == REAL_SIGNATURE
    assert calls[1]["thoughtSignature"] == DUMMY_THOUGHT_SIGNATURE


def test_text_response_signature_is_replayed_on_the_part_not_the_content():
    msg = {
        "role": "assistant",
        "content": "Occam's razor favors the simpler explanation.",
        "provider_specific_fields": {"response_signature": REAL_SIGNATURE},
    }

    content = _model_content(msg)
    assert "thoughtSignature" not in content
    assert content["parts"][-1]["thoughtSignature"] == REAL_SIGNATURE


def test_dummy_message_signature_is_not_emitted():
    msg = {
        "role": "assistant",
        "content": "hi",
        "provider_specific_fields": {"thought_signature": DUMMY_THOUGHT_SIGNATURE},
    }

    assert "thoughtSignature" not in _model_content(msg)["parts"][-1]


def test_thought_parts_replay_with_their_signature():
    msg = {
        "role": "assistant",
        "content": "Answer",
        "provider_specific_fields": {
            "thought_parts": [{"text": "thinking", "thought": True, "signature": REAL_SIGNATURE}]
        },
    }

    parts = _model_content(msg)["parts"]
    assert parts[0] == {"text": "thinking", "thought": True, "thoughtSignature": REAL_SIGNATURE}


def test_tool_response_stays_structured_without_a_signature():
    content = _tool_content(
        {"role": "tool", "tool_call_id": "call_1", "content": "Sunny"},
        {"call_1": {"name": "get_weather"}},
        require_signatures=True,
    )

    assert content["parts"][0]["functionResponse"]["name"] == "get_weather"
    assert "thoughtSignature" not in content["parts"][0]


# ---------------------------------------------------------------------------
# Response normalization
# ---------------------------------------------------------------------------


def test_normalize_captures_function_call_signature():
    data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "functionCall": {"name": "get_weather", "args": {}, "id": "call_1"},
                            "thoughtSignature": REAL_SIGNATURE,
                        }
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }

    response = normalize_gemini_response(data, "gemini/gemini-4-hydrogen")

    assert response.provider_specific_fields["function_call_signatures"] == {
        "call_1": REAL_SIGNATURE
    }
    assert response.choices[0].finish_reason == "tool_calls"


def test_normalize_captures_text_part_and_thought_part_signatures():
    data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "thinking", "thought": True, "thoughtSignature": "thought-sig"},
                        {"text": "answer", "thoughtSignature": REAL_SIGNATURE},
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }

    provider_fields = normalize_gemini_response(
        data, "gemini/gemini-4-hydrogen"
    ).provider_specific_fields

    assert provider_fields["response_signature"] == REAL_SIGNATURE
    assert provider_fields["thought_signature"] == REAL_SIGNATURE
    assert provider_fields["thought_parts"][0]["signature"] == "thought-sig"


def test_normalize_captures_candidate_level_signature():
    data = {
        "candidates": [
            {
                "content": {"parts": [{"text": "answer"}]},
                "thoughtSignature": REAL_SIGNATURE,
                "finishReason": "STOP",
            }
        ]
    }

    provider_fields = normalize_gemini_response(
        data, "gemini/gemini-4-hydrogen"
    ).provider_specific_fields

    assert provider_fields["response_signature"] == REAL_SIGNATURE


# ---------------------------------------------------------------------------
# Streaming chunks
# ---------------------------------------------------------------------------


def test_chunk_captures_signature_from_empty_text_part():
    chunk = parse_gemini_chunk(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "", "thoughtSignature": REAL_SIGNATURE}]},
                    "finishReason": "STOP",
                }
            ]
        }
    )

    assert chunk is not None
    assert chunk.text == ""
    assert chunk.provider_specific_fields["response_signature"] == REAL_SIGNATURE


def test_signature_only_chunk_is_not_dropped():
    chunk = parse_gemini_chunk(
        {"candidates": [{"content": {"parts": [{"text": "", "thoughtSignature": REAL_SIGNATURE}]}}]}
    )

    assert chunk is not None
    assert chunk.provider_specific_fields["response_signature"] == REAL_SIGNATURE


def test_chunk_captures_function_call_signature():
    chunk = parse_gemini_chunk(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {"name": "get_weather", "args": {}, "id": "call_1"},
                                "thoughtSignature": REAL_SIGNATURE,
                            }
                        ]
                    }
                }
            ]
        }
    )

    assert chunk.provider_specific_fields["function_call_signatures"] == {"call_1": REAL_SIGNATURE}


# ---------------------------------------------------------------------------
# Thinking levels
# ---------------------------------------------------------------------------


def test_gemini_4_thinking_levels_include_medium_and_xhigh():
    resolved = _resolved("gemini-4-hydrogen")

    assert gemini_thinking_config(resolved, "medium") == {
        "thinkingLevel": "medium",
        "includeThoughts": True,
    }
    assert gemini_thinking_config(resolved, "xhigh") == {
        "thinkingLevel": "xhigh",
        "includeThoughts": True,
    }
    assert gemini_thinking_config(resolved, "minimal")["thinkingLevel"] == "low"


def test_gemini_3_flash_keeps_minimal_level():
    resolved = _resolved("gemini-3.5-flash")

    assert gemini_thinking_config(resolved, "minimal")["thinkingLevel"] == "minimal"


def test_gemini_4_carbon_downgrades_unsupported_xhigh():
    resolved = _resolved("gemini-4-carbon")

    assert gemini_thinking_config(resolved, "xhigh")["thinkingLevel"] == "high"


def test_gemini_3_8_flash_downgrades_unsupported_minimal():
    resolved = _resolved("gemini-3.8-flash")

    assert gemini_thinking_config(resolved, "minimal")["thinkingLevel"] == "low"
