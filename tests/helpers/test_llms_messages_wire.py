"""Wire-format tests for the anthropic messages domain.

``anthropic_payload`` must produce a spec-compliant /v1/messages request body:

- roles alternate (no consecutive user messages), with all ``tool_result``
  blocks for a parallel tool call grouped into one user message and any
  following text placed after them (tool-use spec ordering), and
- consecutive user text turns are concatenated into a single ``text`` block
  joined with ``"\n---\n"`` separators (the conversation manager injects
  file-context text as its own user messages, so it rides along inline).

No network: only the offline payload builder is exercised.
"""

from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.domains.messages import anthropic_payload

SYS = "You are cecli, an agentic coding assistant. " * 30

FILE_CONTEXT = (
    "ID-Prefixed Context For:\ncecli/tools/__init__.py\n\n"
    '{"file_path": "/home/cecli/cecli/tools/__init__.py", "results": [...]}'
)

FILE_CONTENT = (
    "Original File Contents For:\ncecli/tools/utils/base_tool.py\n\n"
    "from abc import ABC, abstractmethod\n...\n\n"
    "Modifications will be communicated as diff messages.\n\n"
)

# Mirrors the conversation manager's sequence around a parallel tool call:
# several tool results followed by injected file-context text, all as
# consecutive user turns in the internal (OpenAI-style) message list.
TRACE_LIKE = [
    {"role": "system", "content": SYS},
    {"role": "user", "content": "<context environment_info>Hello\n</context>"},
    {"role": "assistant", "content": "Hello!"},
    {"role": "user", "content": "Can you explain cecli/tools to me"},
    {
        "role": "assistant",
        "provider_specific_fields": {
            "anthropic": [
                {"type": "thinking", "thinking": "", "signature": "sig1"},
                {"type": "tool_use", "id": "t1", "name": "Local--ls", "input": {}},
                {"type": "tool_use", "id": "t2", "name": "Local--ls", "input": {}},
                {"type": "tool_use", "id": "t3", "name": "Local--ls", "input": {}},
            ]
        },
    },
    {"role": "tool", "tool_call_id": "t1", "content": '{"result": [1]}'},
    {"role": "tool", "tool_call_id": "t2", "content": '{"result": [2]}'},
    {"role": "tool", "tool_call_id": "t3", "content": '{"result": [3]}'},
    {"role": "user", "content": FILE_CONTEXT},
    {"role": "user", "content": FILE_CONTENT},
]


def _wire_roles(payload):
    return [m["role"] for m in payload["messages"]]


def _block_types(msg):
    return [b.get("type") for b in msg["content"]]


def _assert_alternating(roles):
    assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))


def test_copilot_coalesces_turns_and_keeps_file_text_inline():
    resolved = resolve_model_config("github_copilot/claude-sonnet-5")
    payload = anthropic_payload(resolved, TRACE_LIKE, None, False, {})

    _assert_alternating(_wire_roles(payload))

    # No input_artifacts: file-context text rides inline in the history.
    assert "input_artifacts" not in payload

    # The three parallel tool results are grouped into one user message with
    # the trailing file-context text after them, joined with "\n---\n".
    tool_msg = next(
        m for m in payload["messages"] if any(b.get("type") == "tool_result" for b in m["content"])
    )
    assert [b["tool_use_id"] for b in tool_msg["content"][:3]] == ["t1", "t2", "t3"]
    assert _block_types(tool_msg) == ["tool_result"] * 3 + ["text"]
    assert tool_msg["content"][3]["text"] == FILE_CONTEXT + "\n---\n" + FILE_CONTENT


def test_direct_anthropic_coalesces_turns_and_keeps_file_text_inline():
    resolved = resolve_model_config("claude-sonnet-5")
    payload = anthropic_payload(resolved, TRACE_LIKE, None, False, {})

    _assert_alternating(_wire_roles(payload))

    # No input_artifacts extension for either provider: file text stays inline.
    assert "input_artifacts" not in payload
    tool_msg = next(
        m for m in payload["messages"] if any(b.get("type") == "tool_result" for b in m["content"])
    )
    types = _block_types(tool_msg)
    assert types[:3] == ["tool_result"] * 3
    assert types[3:] == ["text"]
    assert tool_msg["content"][3]["text"] == FILE_CONTEXT + "\n---\n" + FILE_CONTENT


def test_new_user_question_after_tool_results_merges_text_after_results():
    messages = [
        {
            "role": "assistant",
            "provider_specific_fields": {
                "anthropic": [{"type": "tool_use", "id": "t1", "name": "Local--ls", "input": {}}]
            },
        },
        {"role": "tool", "tool_call_id": "t1", "content": "ok"},
        {"role": "user", "content": "what next?"},
    ]
    resolved = resolve_model_config("github_copilot/claude-sonnet-5")
    payload = anthropic_payload(resolved, messages, None, False, {})

    user_msg = payload["messages"][-1]
    assert _block_types(user_msg) == ["tool_result", "text"]
    assert user_msg["content"][0]["tool_use_id"] == "t1"
    assert user_msg["content"][1]["text"] == "what next?"


def test_consecutive_text_users_merge_into_one():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ]
    resolved = resolve_model_config("github_copilot/claude-sonnet-5")
    payload = anthropic_payload(resolved, messages, None, False, {})

    assert _wire_roles(payload) == ["user"]
    assert _block_types(payload["messages"][0]) == ["text"]
    assert payload["messages"][0]["content"][0]["text"] == "first\n---\nsecond"


def test_file_context_text_merges_with_previous_user_message():
    messages = [
        {"role": "user", "content": "<context>Hello\n</context>"},
        {"role": "user", "content": FILE_CONTEXT},
    ]
    resolved = resolve_model_config("github_copilot/claude-sonnet-5")
    payload = anthropic_payload(resolved, messages, None, False, {})

    assert "input_artifacts" not in payload
    assert _wire_roles(payload) == ["user"]
    assert payload["messages"][0]["content"][0]["text"] == (
        "<context>Hello\n</context>\n---\n" + FILE_CONTEXT
    )
