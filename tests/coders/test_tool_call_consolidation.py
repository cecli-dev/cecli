"""Regression tests for streaming chunk consolidation bugs.

These cover three issues found when comparing raw stream chunks against the
constructed conversation history:

1. Parallel tool calls were dropped (only the first call was saved).
2. Provider reasoning items (``provider_specific_fields.reasoning_items``)
   streamed across multiple chunks were lost (only the last item survived).
3. Tool-call deltas that start at a non-zero index were mishandled.
"""

from cecli.coders.base_coder import Coder
from cecli.llm import litellm


def mk_chunk(delta_kwargs, finish_reason=None, usage=None, cid="cmpl-1", created=1000):
    delta = litellm.Delta(**delta_kwargs)
    choices = [litellm.StreamChoice(finish_reason=finish_reason, index=0, delta=delta)]
    return litellm.StreamChunk(
        id=cid,
        created=created,
        model="gpt-test",
        choices=choices,
        usage=usage,
    )


def tc(index, id=None, name=None, arguments=None):
    return litellm.ChatCompletionMessageToolCall(
        id=id,
        function=litellm.Function(arguments=arguments or "", name=name),
        type="function",
        index=index,
    )


def make_coder(chunks, stream=True):
    coder = Coder.__new__(Coder)
    coder.stream = stream
    coder.partial_response_chunks = chunks
    coder.partial_response_tool_calls = []
    coder.partial_response_function_call = dict()
    coder.partial_response_consolidated = None
    coder.partial_response_reasoning_content = ""
    coder.partial_response_content = ""
    coder.tool_reflection = False
    return coder


def test_parallel_tool_calls_are_all_preserved():
    """Bug 1: parallel tool calls streamed in one turn must all survive."""
    chunks = [
        mk_chunk(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tc(0, "call_ls", "Local--ls", "")],
            }
        ),
        mk_chunk(
            {"role": None, "content": None, "tool_calls": [tc(1, "call_grep", "Local--Grep", "")]}
        ),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, None, None, '{"pa')]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(1, None, None, '{"sea')]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, None, None, 'th":"."}')]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(1, None, None, 'rches":[]}')]}),
        mk_chunk({}, finish_reason="tool_calls"),
    ]
    coder = make_coder(chunks)
    response, func_err, content_err = coder.consolidate_chunks()

    assert func_err is None
    names = [t.function.name for t in coder.partial_response_tool_calls]
    assert names == ["Local--ls", "Local--Grep"], f"dropped tool calls: {names}"

    msg_tool_calls = response.choices[0].message.tool_calls
    assert [t.function.name for t in msg_tool_calls] == ["Local--ls", "Local--Grep"]
    assert msg_tool_calls[0].function.arguments == '{"path":"."}'
    assert msg_tool_calls[1].function.arguments == '{"searches":[]}'


def test_non_zero_starting_tool_call_index():
    """Bug 3: tool-call deltas may start at index 1 (not 0) and must still be kept."""
    chunks = [
        mk_chunk(
            {"role": "assistant", "content": None, "tool_calls": [tc(1, "call_a", "Local--A", "")]}
        ),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(1, None, None, '{"a":1}')]}),
        mk_chunk({}, finish_reason="tool_calls"),
    ]
    coder = make_coder(chunks)
    response, func_err, content_err = coder.consolidate_chunks()

    assert func_err is None
    assert [t.function.name for t in coder.partial_response_tool_calls] == ["Local--A"]
    assert coder.partial_response_tool_calls[0].function.arguments == '{"a":1}'


def test_reasoning_items_preserved_across_chunks():
    """Bug 2: reasoning_items streamed across chunks must all be kept, in order."""
    chunks = [
        mk_chunk(
            {
                "role": "assistant",
                "content": None,
                "provider_specific_fields": {
                    "reasoning_items": [
                        {"id": "item-1", "type": "reasoning", "encrypted_content": "AAA"}
                    ]
                },
            },
        ),
        mk_chunk(
            {
                "role": None,
                "content": None,
                "provider_specific_fields": {
                    "reasoning_items": [
                        {"id": "item-2", "type": "reasoning", "encrypted_content": "BBB"}
                    ]
                },
            },
        ),
        mk_chunk(
            {"role": None, "content": None, "tool_calls": [tc(0, "call_x", "Local--X", "{}")]}
        ),
        mk_chunk({}, finish_reason="tool_calls"),
    ]
    coder = make_coder(chunks)
    response, func_err, content_err = coder.consolidate_chunks()

    assert func_err is None
    psf = response.choices[0].message.provider_specific_fields
    items = psf.get("reasoning_items", []) if psf else []
    ids = [i["id"] for i in items]
    assert ids == ["item-1", "item-2"], f"reasoning items dropped: {ids}"

    # The dumped message (what add_assistant_reply_to_cur_messages stores)
    # must carry the full provider_specific_fields.
    dumped = response.model_dump()
    dumped_psf = dumped["choices"][0]["message"]["provider_specific_fields"]
    assert [i["id"] for i in dumped_psf["reasoning_items"]] == ["item-1", "item-2"]


def test_reasoning_items_combined_with_tool_calls():
    """Reasoning items + parallel tool calls in the same turn all survive."""
    chunks = [
        mk_chunk(
            {
                "role": "assistant",
                "content": None,
                "provider_specific_fields": {
                    "reasoning_items": [
                        {"id": "item-1", "type": "reasoning", "encrypted_content": "AAA"}
                    ]
                },
            },
        ),
        mk_chunk(
            {
                "role": None,
                "content": None,
                "provider_specific_fields": {
                    "reasoning_items": [
                        {"id": "item-2", "type": "reasoning", "encrypted_content": "BBB"}
                    ]
                },
            },
        ),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, "call_a", "Local--A", "")]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(1, "call_b", "Local--B", "")]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, None, None, '{"a":1}')]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(1, None, None, '{"b":2}')]}),
        mk_chunk({}, finish_reason="tool_calls"),
    ]
    coder = make_coder(chunks)
    response, func_err, content_err = coder.consolidate_chunks()

    assert func_err is None
    assert [t.function.name for t in coder.partial_response_tool_calls] == ["Local--A", "Local--B"]
    psf = response.choices[0].message.provider_specific_fields
    assert [i["id"] for i in psf["reasoning_items"]] == ["item-1", "item-2"]


def test_build_tool_calls_from_chunks_handles_missing_index():
    """Delta tool calls without an index fall back to append order."""
    coder = make_coder([])
    coder.partial_response_chunks = [
        mk_chunk(
            {"role": "assistant", "content": None, "tool_calls": [tc(0, "call_a", "Local--A", "")]}
        ),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, None, None, '{"a":1}')]}),
        mk_chunk({}, finish_reason="tool_calls"),
    ]
    built = coder._build_tool_calls_from_chunks()
    assert [t.function.name for t in built] == ["Local--A"]
    assert built[0].function.arguments == '{"a":1}'


def test_parallel_tool_calls_same_index_distinct_ids():
    """Bug 4 (deepseek): parallel calls reuse index0; only the ids differ.

    Without id-based keying both calls collapse onto one bucket: the second id
    overwrites the first and the argument fragments concatenate into invalid
    JSON (``{"tasks":...}{"path":...}``), silently dropping one call.
    """
    chunks = [
        mk_chunk(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tc(0, "call_00", "local--UpdateTodoList", "")],
            }
        ),
        mk_chunk(
            {
                "role": None,
                "content": None,
                "tool_calls": [tc(0, None, None, '{"tasks": [{"task": "Explore')],
            }
        ),
        mk_chunk(
            {
                "role": None,
                "content": None,
                "tool_calls": [tc(0, None, None, ' the code", "done": false}')],
            }
        ),
        mk_chunk(
            {"role": None, "content": None, "tool_calls": [tc(0, "call_01", "local--ls", "")]}
        ),
        mk_chunk(
            {"role": None, "content": None, "tool_calls": [tc(0, None, None, '{"path": "."}')]}
        ),
        mk_chunk({}, finish_reason="tool_calls"),
    ]
    coder = make_coder(chunks)
    response, func_err, content_err = coder.consolidate_chunks()

    assert func_err is None
    calls = coder.partial_response_tool_calls
    assert [t.id for t in calls] == ["call_00", "call_01"]
    assert [t.function.name for t in calls] == ["local--UpdateTodoList", "local--ls"]
    assert calls[0].function.arguments == '{"tasks": [{"task": "Explore the code", "done": false}'
    assert calls[1].function.arguments == '{"path": "."}'

    msg_tool_calls = response.choices[0].message.tool_calls
    assert [t.id for t in msg_tool_calls] == ["call_00", "call_01"]


def test_stream_chunk_builder_keeps_same_index_distinct_ids():
    """The facade stream_chunk_builder keeps parallel calls that share index0."""
    chunks = [
        mk_chunk(
            {"role": "assistant", "content": None, "tool_calls": [tc(0, "call_a", "f_alpha", "")]}
        ),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, None, None, '{"a"')]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, None, None, ":1}")]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, "call_b", "f_beta", "")]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, None, None, '{"b"')]}),
        mk_chunk({"role": None, "content": None, "tool_calls": [tc(0, None, None, ":2}")]}),
        mk_chunk({}, finish_reason="tool_calls"),
    ]
    resp = litellm.stream_chunk_builder(chunks)
    calls = resp.choices[0].message.tool_calls

    assert [t.id for t in calls] == ["call_a", "call_b"]
    assert [t.function.name for t in calls] == ["f_alpha", "f_beta"]
    assert calls[0].function.arguments == '{"a":1}'
    assert calls[1].function.arguments == '{"b":2}'


def _domain_pipeline(parse_fn, events, reset_fn=None):
    """Run domain SSE events through parse -> shim -> both accumulators."""
    from cecli.helpers.llms.litellm_compat import _chunk_shim

    if reset_fn:
        reset_fn()

    shims = []
    for evt in events:
        chunk = parse_fn(evt)
        if chunk is not None:
            shims.append(_chunk_shim(chunk, "test-model"))

    resp = litellm.stream_chunk_builder(shims)
    coder = make_coder(shims)
    return resp.choices[0].message.tool_calls, coder._build_tool_calls_from_chunks()


def test_parallel_tool_calls_across_domains():
    """responses / anthropic / gemini / chat all keep parallel tool calls.

    Each domain streams parallel calls differently (item_id-keyed deltas,
    per-block indices, complete parts with per-call indices, reused index0 with
    distinct ids); every path must survive both accumulators.
    """
    from cecli.helpers.llms.domains.chat import parse_chat_chunk
    from cecli.helpers.llms.domains.gemini import _stream_state as gem_state
    from cecli.helpers.llms.domains.gemini import parse_gemini_chunk
    from cecli.helpers.llms.domains.messages import parse_anthropic_chunk
    from cecli.helpers.llms.domains.responses import (
        _reset_stream_state,
        parse_responses_chunk,
    )

    cases = [
        (
            "responses",
            parse_responses_chunk,
            _reset_stream_state,
            [
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "id": "fc_1",
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "f_alpha",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.output_item.added",
                    "output_index": 1,
                    "item": {
                        "id": "fc_2",
                        "type": "function_call",
                        "call_id": "call_2",
                        "name": "f_beta",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "output_index": 0,
                    "delta": '{"a"',
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_2",
                    "output_index": 1,
                    "delta": '{"b"',
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "output_index": 0,
                    "delta": ":1}",
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_2",
                    "output_index": 1,
                    "delta": ":2}",
                },
                {"type": "response.completed", "response": {"status": "completed", "usage": {}}},
            ],
            ["call_1", "call_2"],
            ["f_alpha", "f_beta"],
            ['{"a":1}', '{"b":2}'],
        ),
        (
            "anthropic",
            parse_anthropic_chunk,
            None,
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "f_alpha",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_2",
                        "name": "f_beta",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"a"'},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": '{"b"'},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": ":1}"},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": ":2}"},
                },
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {}},
            ],
            ["toolu_1", "toolu_2"],
            ["f_alpha", "f_beta"],
            ['{"a":1}', '{"b":2}'],
        ),
        (
            "gemini",
            parse_gemini_chunk,
            lambda: gem_state.__setitem__("tool_indices", {}),
            [
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "f_alpha",
                                            "args": {"a": 1},
                                            "id": "call_1",
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "f_beta",
                                            "args": {"b": 2},
                                            "id": "call_2",
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
                {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]},
            ],
            ["call_1", "call_2"],
            ["f_alpha", "f_beta"],
            ['{"a": 1}', '{"b": 2}'],
        ),
        (
            "chat/deepseek (index0 reused)",
            parse_chat_chunk,
            None,
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_00",
                                        "type": "function",
                                        "function": {"name": "todo", "arguments": ""},
                                    }
                                ],
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": '{"tasks":[{"task":"A"'}}
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "}]}"}}]}}
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_01",
                                        "type": "function",
                                        "function": {"name": "ls", "arguments": ""},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": '{"path":"."}'}}
                                ]
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ],
            ["call_00", "call_01"],
            ["todo", "ls"],
            ['{"tasks":[{"task":"A"}]}', '{"path":"."}'],
        ),
    ]

    for label, parse_fn, reset_fn, events, ids, names, args in cases:
        facade, built = _domain_pipeline(parse_fn, events, reset_fn)
        for calls in (facade, built):
            assert [c.id for c in calls] == ids, f"{label}: ids {[c.id for c in calls]}"
            assert [c.function.name for c in calls] == names, f"{label}: names mismatch"
            assert [c.function.arguments for c in calls] == args, f"{label}: args mismatch"
