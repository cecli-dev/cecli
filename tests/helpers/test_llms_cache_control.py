"""Cache-control tests for the anthropic messages domain.

``anthropic_payload`` must request automatic caching via the top-level
``cache_control`` field for messages-API models (the model config flags them
``cache_control`` True + ``caches_by_default`` False), while chat-family
models keep their own caching semantics and receive no such field.

No network: only the offline payload builder and helpers are exercised.
"""

from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.domains.messages import (
    _anthropic_usage,
    anthropic_payload,
)

SYS = "You are cecli, an agentic coding assistant. " * 30

MULTI_TURN = [
    {"role": "system", "content": SYS},
    {"role": "user", "content": "first question"},
    {"role": "assistant", "content": "first answer"},
    {"role": "user", "content": "second question"},
    {
        "role": "assistant",
        "content": "I'll check",
        "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
        ],
    },
    {"role": "tool", "tool_call_id": "t1", "content": "result of tool"},
    {"role": "assistant", "content": "second answer"},
    {"role": "user", "content": "current question"},
]


def _content_blocks(payload):
    """All content blocks in the payload (system + messages), flattened."""
    blocks = []

    system = payload.get("system")

    if isinstance(system, list):
        blocks.extend(system)

    for msg in payload.get("messages") or []:
        content = msg.get("content")

        if isinstance(content, list):
            blocks.extend(content)

    return blocks


def test_messages_api_requests_top_level_cache_control():
    resolved = resolve_model_config("github_copilot/claude-sonnet-5")
    payload = anthropic_payload(resolved, MULTI_TURN, None, False, {})

    assert resolved["family"] == "messages"
    assert payload["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in block for block in _content_blocks(payload))


def test_single_turn_requests_top_level_cache_control():
    resolved = resolve_model_config("claude-sonnet-5")
    payload = anthropic_payload(resolved, [{"role": "user", "content": "hi"}], None, False, {})

    assert payload["cache_control"] == {"type": "ephemeral"}


def test_chat_family_claude_keeps_own_caching_semantics():
    resolved = resolve_model_config("openrouter/claude-sonnet-5")
    payload = anthropic_payload(
        resolved,
        [{"role": "system", "content": SYS}, {"role": "user", "content": "hi"}],
        None,
        False,
        {},
    )

    # Chat-family claude keeps its own caching semantics: no top-level field.
    assert resolved["family"] == "chat"
    assert "cache_control" not in payload


def test_anthropic_usage_normalizes_full_input():
    """Prompt tokens include cached input so hit-rate and cost math stay sane.

    Anthropic's ``input_tokens`` excludes cached input; the cache read and write
    tokens arrive in separate fields. ``base_coder.calculate_and_show_tokens_and_cost``
    expects ``prompt_tokens`` to be the total input (cache_creation + cache_read
    + input), otherwise the cache hit-rate blows up (e.g. a 9249-token cache read
    against a 2-token ``input_tokens`` shows a ~462450% hit rate).
    """
    usage = _anthropic_usage(
        {
            "input_tokens": 2,
            "output_tokens": 20,
            "cache_read_input_tokens": 9249,
            "cache_creation_input_tokens": 77,
            "output_tokens_details": {"thinking_tokens": 0},
        }
    )

    assert usage.prompt_tokens == 2 + 9249 + 77
    assert usage.completion_tokens == 20
    assert usage.total_tokens == 2 + 9249 + 77
    assert usage.cache_read_input_tokens == 9249
    assert usage.cache_creation_input_tokens == 77
    assert usage.completion_tokens_details == {"reasoning_tokens": 0}


def test_anthropic_usage_without_cache_keys_keeps_openai_shape():
    """A usage block with no cache fields still normalizes to plain counts."""
    usage = _anthropic_usage({"input_tokens": 10, "output_tokens": 5})

    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 10
    assert usage.cache_read_input_tokens is None
    assert usage.cache_creation_input_tokens is None
