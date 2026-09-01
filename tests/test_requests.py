from cecli.helpers.requests import (
    _process_thought_signature,
    add_continue_for_no_prefill,
    add_reasoning_content,
    concatenate_user_messages,
    model_request_parser,
    prevent_consecutive_assistant_messages,
    remove_empty_tool_calls,
    thought_signature,
)
from cecli.sendchat import ensure_alternating_roles


class _MockModel:
    """Minimal model stub for testing request transformation functions."""

    def __init__(self, name="test-model", supports_assistant_prefill=True):
        self.name = name
        self.info = {"supports_assistant_prefill": supports_assistant_prefill}


# ---------------------------------------------------------------------------
# add_reasoning_content
# ---------------------------------------------------------------------------


class TestAddReasoningContent:
    def test_empty_messages(self):
        assert add_reasoning_content([]) == []

    def test_no_assistant_messages(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = add_reasoning_content(msgs)
        assert result == msgs

    def test_assistant_already_has_reasoning_content(self):
        msgs = [{"role": "assistant", "content": "hello", "reasoning_content": "thinking"}]
        result = add_reasoning_content(msgs)
        assert result == msgs

    def test_assistant_missing_reasoning_content(self):
        msgs = [{"role": "assistant", "content": "hello"}]
        result = add_reasoning_content(msgs)
        assert result == [{"role": "assistant", "content": "hello", "reasoning_content": ""}]

    def test_removes_reasoning_content_from_provider_specific_fields(self):
        msgs = [
            {
                "role": "assistant",
                "content": "hello",
                "provider_specific_fields": {"reasoning_content": "some internal thought"},
            }
        ]
        result = add_reasoning_content(msgs)
        # reasoning_content should be removed from provider_specific_fields
        assert "reasoning_content" not in result[0]["provider_specific_fields"]

    def test_mixed_messages(self):
        msgs = [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "follow-up"},
            {"role": "assistant", "content": "reply"},
        ]
        result = add_reasoning_content(msgs)
        assert len(result) == 5
        # assistant messages should have reasoning_content added
        assert result[2]["reasoning_content"] == ""
        assert result[4]["reasoning_content"] == ""
        # user/system messages should be unchanged
        assert "reasoning_content" not in result[0]
        assert "reasoning_content" not in result[1]
        assert "reasoning_content" not in result[3]

    def test_provider_specific_fields_is_none(self):
        msgs = [{"role": "assistant", "content": "hi", "provider_specific_fields": None}]
        result = add_reasoning_content(msgs)
        # Should not crash when provider_specific_fields is None
        assert result[0]["reasoning_content"] == ""


# ---------------------------------------------------------------------------
# remove_empty_tool_calls
# ---------------------------------------------------------------------------


class TestRemoveEmptyToolCalls:
    def test_empty_list(self):
        assert remove_empty_tool_calls([]) == []

    def test_no_tool_calls(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert remove_empty_tool_calls(msgs) == msgs

    def test_non_empty_tool_calls_preserved(self):
        msgs = [
            {
                "role": "assistant",
                "content": "let me check",
                "tool_calls": [{"id": "call_1", "function": {"name": "get_weather"}}],
            }
        ]
        assert remove_empty_tool_calls(msgs) == msgs

    def test_empty_tool_calls_removed(self):
        msgs = [{"role": "assistant", "content": "", "tool_calls": []}]
        assert remove_empty_tool_calls(msgs) == []

    def test_mixed_tool_calls(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "", "tool_calls": []},  # should be removed
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "c1"}]},  # kept
            {"role": "assistant", "content": "", "tool_calls": []},  # should be removed
        ]
        result = remove_empty_tool_calls(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["tool_calls"] == [{"id": "c1"}]


# ---------------------------------------------------------------------------
# _process_thought_signature
# ---------------------------------------------------------------------------


class TestProcessThoughtSignature:
    def test_adds_provider_specific_fields_if_missing(self):
        container = {}
        _process_thought_signature(container)
        assert container["provider_specific_fields"] == {
            "thought_signature": "skip_thought_signature_validator"
        }

    def test_provider_specific_fields_is_none(self):
        container = {"provider_specific_fields": None}
        _process_thought_signature(container)
        assert container["provider_specific_fields"] == {
            "thought_signature": "skip_thought_signature_validator"
        }

    def test_existing_thought_signature_preserved(self):
        container = {"provider_specific_fields": {"thought_signature": "my_sig"}}
        _process_thought_signature(container)
        assert container["provider_specific_fields"]["thought_signature"] == "my_sig"

    def test_thought_signatures_list_takes_first(self):
        container = {"provider_specific_fields": {"thought_signatures": ["sig_A", "sig_B"]}}
        _process_thought_signature(container)
        assert container["provider_specific_fields"]["thought_signature"] == "sig_A"
        assert "thought_signatures" not in container["provider_specific_fields"]

    def test_thought_signatures_str(self):
        container = {"provider_specific_fields": {"thought_signatures": "sig_str"}}
        _process_thought_signature(container)
        assert container["provider_specific_fields"]["thought_signature"] == "sig_str"
        assert "thought_signatures" not in container["provider_specific_fields"]

    def test_empty_thought_signatures_list(self):
        container = {"provider_specific_fields": {"thought_signatures": []}}
        _process_thought_signature(container)
        assert (
            container["provider_specific_fields"]["thought_signature"]
            == "skip_thought_signature_validator"
        )

    def test_no_thought_signature_sets_skip(self):
        container = {"provider_specific_fields": {}}
        _process_thought_signature(container)
        assert (
            container["provider_specific_fields"]["thought_signature"]
            == "skip_thought_signature_validator"
        )


# ---------------------------------------------------------------------------
# thought_signature
# ---------------------------------------------------------------------------


class TestThoughtSignature:
    def test_non_vertex_gemini_model_no_changes(self):
        model = _MockModel(name="gpt-4")
        msgs = [{"role": "assistant", "content": "hello"}]
        result = thought_signature(model, msgs)
        assert result == msgs

    def test_vertex_ai_model_adds_thought_signature_to_assistant(self):
        model = _MockModel(name="vertex_ai/claude-sonnet")
        msgs = [{"role": "assistant", "content": "hello"}]
        result = thought_signature(model, msgs)
        assert "provider_specific_fields" in result[0]
        assert (
            result[0]["provider_specific_fields"]["thought_signature"]
            == "skip_thought_signature_validator"
        )

    def test_gemini_model_adds_thought_signature(self):
        model = _MockModel(name="gemini/gemini-2.5-flash")
        msgs = [{"role": "assistant", "content": "hello"}]
        result = thought_signature(model, msgs)
        assert "provider_specific_fields" in result[0]

    def test_thought_signature_added_to_tool_calls(self):
        model = _MockModel(name="vertex_ai/test")
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1"}, {}],
            }
        ]
        result = thought_signature(model, msgs)
        # Both the message and tool_calls should be processed
        assert "provider_specific_fields" in result[0]
        assert "provider_specific_fields" in result[0]["tool_calls"][0]

    def test_thought_signature_added_to_function_call(self):
        model = _MockModel(name="vertex_ai/test")
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "function_call": {"name": "get_temp"},
            }
        ]
        result = thought_signature(model, msgs)
        assert "provider_specific_fields" in result[0]
        assert "provider_specific_fields" in result[0]["function_call"]

    def test_user_messages_skipped(self):
        model = _MockModel(name="vertex_ai/test")
        msgs = [{"role": "user", "content": "hello"}]
        result = thought_signature(model, msgs)
        assert "provider_specific_fields" not in result[0]

    def test_mixed_messages_only_assistant_processed(self):
        model = _MockModel(name="gemini/test")
        msgs = [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
        result = thought_signature(model, msgs)
        assert "provider_specific_fields" not in result[0]
        assert "provider_specific_fields" not in result[1]
        assert "provider_specific_fields" in result[2]
        assert "provider_specific_fields" not in result[3]
        assert "provider_specific_fields" in result[4]


# ---------------------------------------------------------------------------
# concatenate_user_messages
# ---------------------------------------------------------------------------


class TestConcatenateUserMessages:
    def test_empty_list(self):
        assert concatenate_user_messages([]) == []

    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "hello"}]
        assert concatenate_user_messages(msgs) == msgs

    def test_no_empty_assistant_responses(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        assert concatenate_user_messages(msgs) == msgs

    def test_two_user_messages_separated_by_empty_assistant(self):
        msgs = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "(empty response)"},
            {"role": "user", "content": "second question"},
        ]
        result = concatenate_user_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "first question" in result[0]["content"]
        assert "second question" in result[0]["content"]
        assert "---" in result[0]["content"]

    def test_three_user_messages_separated_by_empty_assistants(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "(empty response)"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "(empty response)"},
            {"role": "user", "content": "q3"},
        ]
        result = concatenate_user_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "q1" in result[0]["content"]
        assert "q2" in result[0]["content"]
        assert "q3" in result[0]["content"]

    def test_mixed_preserves_non_empty_assistant_messages(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "(empty response)"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "real response"},
            {"role": "user", "content": "q3"},
        ]
        result = concatenate_user_messages(msgs)
        # q1 and q2 should be concatenated, real response preserved, q3 preserved
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert "q1" in result[0]["content"]
        assert "q2" in result[0]["content"]
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "real response"
        assert result[2]["role"] == "user"
        assert result[2]["content"] == "q3"

    def test_user_content_as_list(self):
        """User messages with list content pass through without concatenation."""
        msgs = [
            {"role": "user", "content": [{"text": "part1"}]},
            {"role": "assistant", "content": "(empty response)"},
            {"role": "user", "content": [{"text": "part2"}]},
        ]
        result = concatenate_user_messages(msgs)
        # List content user messages pass through; empty assistant is consumed
        assert len(result) == 2

    def test_non_string_content(self):
        msgs = [
            {"role": "user", "content": 42},
            {"role": "assistant", "content": "(empty response)"},
            {"role": "user", "content": True},
        ]
        result = concatenate_user_messages(msgs)
        assert len(result) == 1
        assert "42" in result[0]["content"]
        assert "True" in result[0]["content"]

    def test_empty_user_content_string(self):
        msgs = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "(empty response)"},
            {"role": "user", "content": "real content"},
        ]
        result = concatenate_user_messages(msgs)
        assert len(result) == 1
        assert "real content" in result[0]["content"]


# ---------------------------------------------------------------------------
# add_continue_for_no_prefill
# ---------------------------------------------------------------------------


class TestAddContinueForNoPrefill:
    def test_model_supports_prefill(self):
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        msgs = [{"role": "assistant", "content": "hello"}]
        result = add_continue_for_no_prefill(model, msgs, None)
        assert len(result) == 1
        assert result == msgs

    def test_no_prefill_last_is_user_no_change(self):
        model = _MockModel(name="some-model", supports_assistant_prefill=False)
        msgs = [{"role": "user", "content": "hello"}]
        result = add_continue_for_no_prefill(model, msgs, None)
        assert len(result) == 1
        assert result == msgs

    def test_no_prefill_last_is_assistant_adds_continue(self):
        model = _MockModel(name="some-model", supports_assistant_prefill=False)
        msgs = [{"role": "assistant", "content": "hello"}]
        result = add_continue_for_no_prefill(model, msgs, None)
        assert len(result) == 2
        assert result[0] == msgs[0]
        assert result[1] == {"role": "user", "content": "Continue"}

    def test_no_prefill_empty_messages_adds_continue(self):
        model = _MockModel(name="some-model", supports_assistant_prefill=False)
        msgs = []
        result = add_continue_for_no_prefill(model, msgs, None)
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "Continue"}

    def test_tools_with_assistant_prefix_removes_prefix_and_adds_continue(self):
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        msgs = [{"role": "assistant", "content": "", "prefix": True}]
        result = add_continue_for_no_prefill(model, msgs, [{"type": "function"}])
        assert len(result) == 2
        assert "prefix" not in result[0]
        assert result[1] == {"role": "user", "content": "Continue"}

    def test_tools_no_assistant_no_change(self):
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        msgs = [{"role": "user", "content": "hi"}]
        result = add_continue_for_no_prefill(model, msgs, [{"type": "function"}])
        assert result == msgs

    def test_tools_assistant_no_prefix_no_change(self):
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        msgs = [{"role": "assistant", "content": "ok"}]
        result = add_continue_for_no_prefill(model, msgs, [{"type": "function"}])
        assert result == msgs

    def test_both_no_prefill_and_tools_prefix_conditions(self):
        model = _MockModel(name="some-model", supports_assistant_prefill=False)
        msgs = [{"role": "assistant", "content": "", "prefix": True}]
        result = add_continue_for_no_prefill(model, msgs, [{"type": "function"}])
        # Both conditions trigger append_message = True, should still only add one Continue
        assert len(result) == 2
        assert "prefix" not in result[0]
        assert result[1] == {"role": "user", "content": "Continue"}


# ---------------------------------------------------------------------------
# prevent_consecutive_assistant_messages
# ---------------------------------------------------------------------------


class TestPreventConsecutiveAssistantMessages:
    def test_empty_list(self):
        assert prevent_consecutive_assistant_messages([]) == []

    def test_no_consecutive_assistants(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        assert prevent_consecutive_assistant_messages(msgs) == msgs

    def test_two_consecutive_assistants(self):
        msgs = [
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "a2"},
        ]
        result = prevent_consecutive_assistant_messages(msgs)
        assert len(result) == 3
        assert result[0] == msgs[0]
        assert result[1] == {"role": "user", "content": "(empty request)"}
        assert result[2] == msgs[1]

    def test_three_consecutive_assistants(self):
        msgs = [
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "a2"},
            {"role": "assistant", "content": "a3"},
        ]
        result = prevent_consecutive_assistant_messages(msgs)
        assert len(result) == 5
        assert result[0] == msgs[0]
        assert result[1] == {"role": "user", "content": "(empty request)"}
        assert result[2] == msgs[1]
        assert result[3] == {"role": "user", "content": "(empty request)"}
        assert result[4] == msgs[2]

    def test_consecutive_user_messages_not_affected(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a1"},
        ]
        result = prevent_consecutive_assistant_messages(msgs)
        # Only assistant consecutive messages get the empty request inserted
        assert result == msgs

    def test_mixed_consecutive_assistants(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a3"},
            {"role": "assistant", "content": "a4"},
        ]
        result = prevent_consecutive_assistant_messages(msgs)
        assert len(result) == 8
        assert result[0] == msgs[0]
        assert result[1] == msgs[1]
        assert result[2] == {"role": "user", "content": "(empty request)"}
        assert result[3] == msgs[2]
        assert result[4] == msgs[3]
        assert result[5] == msgs[4]
        assert result[6] == {"role": "user", "content": "(empty request)"}
        assert result[7] == msgs[5]


# ---------------------------------------------------------------------------
# model_request_parser (integration)
# ---------------------------------------------------------------------------


class TestModelRequestParser:
    def test_basic_workflow(self):
        """End-to-end test with a typical message sequence."""
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        msgs = [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "how are you?"},
            {"role": "assistant", "content": "I'm good"},
        ]
        result = model_request_parser(model, msgs, None)
        # For a standard model with no edge cases, the output should be similar
        # but with reasoning_content added to assistant messages
        # Let me trace the flow:
        # - thought_signature: no change (not vertex/gemini)
        # - remove_empty_tool_calls: no change
        # - concatenate_user_messages: no change (no empty assistant responses)
        # - ensure_alternating_roles: should alternate properly, no changes needed
        # - add_reasoning_content: adds reasoning_content to assistants
        # - add_continue_for_no_prefill: no change (supports prefill, no tools)
        # - prevent_consecutive_assistant_messages: no change
        assert len(result) == 5
        # Check reasoning_content was added
        assert result[2]["reasoning_content"] == ""
        assert result[4]["reasoning_content"] == ""

    def test_with_tool_calls(self):
        """End-to-end test with tool calls."""
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        msgs = [
            {"role": "user", "content": "what's the weather?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "get_weather", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "72°F"},
            {"role": "assistant", "content": "It's 72°F"},
        ]
        result = model_request_parser(model, msgs, None)
        # Should pass through OK, adding reasoning_content
        assert len(result) >= 4
        # The assistant message with tool_calls should have reasoning_content
        tool_call_msg = [m for m in result if m.get("tool_calls")]
        assert len(tool_call_msg) == 1
        assert tool_call_msg[0]["reasoning_content"] == ""

    def test_with_empty_tool_calls_removed(self):
        """Empty tool_calls messages should be filtered out."""
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "", "tool_calls": []},  # should be removed
            {"role": "assistant", "content": "hi"},
        ]
        result = model_request_parser(model, msgs, None)
        assert len(result) == 2  # user + assistant (empty removed, then alternating ok)
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"

    def test_with_consecutive_assistants(self):
        """Consecutive assistant messages should get empty requests inserted."""
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "a2"},
        ]
        result = model_request_parser(model, msgs, None)
        # prevent_consecutive_assistant_messages adds (empty request) between a1 and a2
        assert len(result) == 4
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"
        assert result[2]["content"] == "(empty request)"
        assert result[3]["role"] == "assistant"

    def test_with_vertex_ai_model(self):
        """Vertex AI models should get thought signatures."""
        model = _MockModel(name="vertex_ai/claude-sonnet", supports_assistant_prefill=True)
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = model_request_parser(model, msgs, None)
        assert len(result) == 2
        # Assistant message should have thought signature
        assert "provider_specific_fields" in result[1]
        assert (
            result[1]["provider_specific_fields"]["thought_signature"]
            == "skip_thought_signature_validator"
        )

    def test_with_no_prefill_model(self):
        """Models without assistant prefill should get Continue added."""
        model = _MockModel(name="some-model", supports_assistant_prefill=False)
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = model_request_parser(model, msgs, None)
        # Last message is assistant, so Continue should be added
        assert len(result) == 3
        assert result[2] == {"role": "user", "content": "Continue"}

    def test_with_user_messages_to_concat(self):
        """User messages separated by empty assistant should be concatenated."""
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "(empty response)"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "merged reply"},
        ]
        result = model_request_parser(model, msgs, None)
        # First two user messages should be concatenated into one
        assert len(result) == 2  # concat_user + assistant (merged)
        assert result[0]["role"] == "user"
        assert "first" in result[0]["content"]
        assert "second" in result[0]["content"]
        assert "---" in result[0]["content"]

    def test_empty_messages(self):
        """Empty input should return empty."""
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        result = model_request_parser(model, [], None)
        assert result == []

    def test_does_not_mutate_stored_provider_specific_fields(self):
        """The parser must not mutate the stored messages' nested provider_specific_fields."""
        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        reasoning_items = [
            {"id": "item-1", "type": "reasoning", "encrypted_content": "abc", "summary": []}
        ]
        stored = {
            "role": "assistant",
            "content": "Let me check that.",
            "reasoning_content": "thinking...",
            "provider_specific_fields": {
                "reasoning_items": reasoning_items,
                "reasoning_content": "thinking...",
            },
        }

        result = model_request_parser(model, [stored], None)

        # The returned request promotes reasoning_items to the top level...
        assert result[0]["reasoning_items"] == reasoning_items
        assert "reasoning_items" not in result[0]["provider_specific_fields"]

        # ...while the stored message keeps its provider_specific_fields intact.
        assert stored["provider_specific_fields"] == {
            "reasoning_items": reasoning_items,
            "reasoning_content": "thinking...",
        }
        assert "reasoning_items" not in stored

    def test_preserves_base_message_provider_specific_fields(self):
        """Stored BaseMessage psf survives a send (to_dict shares psf with the store)."""
        from cecli.helpers.conversation.base_message import BaseMessage

        model = _MockModel(name="gpt-4", supports_assistant_prefill=True)
        reasoning_items = [
            {"id": "item-1", "type": "reasoning", "encrypted_content": "abc", "summary": []}
        ]
        message = BaseMessage(
            message_dict={
                "role": "assistant",
                "content": "Let me check that.",
                "reasoning_content": "thinking...",
                "provider_specific_fields": {"reasoning_items": reasoning_items},
            },
            tag="cur",
        )

        result = model_request_parser(model, [message.to_dict()], None)

        assert result[0]["reasoning_items"] == reasoning_items
        assert (
            message.message_dict["provider_specific_fields"]["reasoning_items"] == reasoning_items
        )
        assert "reasoning_items" not in message.message_dict

    def test_preserves_tool_call_provider_specific_fields(self):
        """Gemini thought-signature processing must not mutate stored tool_calls."""
        model = _MockModel(name="gemini/gemini-2.0-flash", supports_assistant_prefill=True)
        reasoning_items = [
            {"id": "item-1", "type": "reasoning", "encrypted_content": "abc", "summary": []}
        ]
        stored_call = {
            "id": "call-1",
            "type": "function",
            "function": {"name": "Local--Grep", "arguments": "{}"},
            "provider_specific_fields": {"reasoning_items": reasoning_items},
        }
        stored = [
            {"role": "assistant", "content": None, "tool_calls": [stored_call]},
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
        ]

        result = model_request_parser(model, stored, None)

        # Thought signatures are added to the copied tool call only...
        call_psf = result[0]["tool_calls"][0]["provider_specific_fields"]
        assert call_psf["thought_signature"] == "skip_thought_signature_validator"

        # ...while the stored tool call keeps its original psf.
        assert stored[0]["tool_calls"][0]["provider_specific_fields"] == {
            "reasoning_items": reasoning_items
        }
        assert "thought_signature" not in stored[0]["tool_calls"][0]["provider_specific_fields"]


# ---------------------------------------------------------------------------
# ensure_alternating_roles (from sendchat)
# ---------------------------------------------------------------------------


class TestEnsureAlternatingRoles:
    def test_empty_list(self):
        assert ensure_alternating_roles([]) == []

    def test_single_user(self):
        msgs = [{"role": "user", "content": "hello"}]
        assert ensure_alternating_roles(msgs) == msgs

    def test_already_alternating(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        assert ensure_alternating_roles(msgs) == msgs

    def test_consecutive_user_inserts_empty_request(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "user", "content": "q2"},
        ]
        result = ensure_alternating_roles(msgs)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[1]["content"] == "(empty response)"
        assert result[2]["role"] == "user"

    def test_consecutive_assistant_inserts_empty_request(self):
        msgs = [
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "a2"},
        ]
        result = ensure_alternating_roles(msgs)
        assert len(result) == 3
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "user"
        assert result[1]["content"] == "(empty request)"
        assert result[2]["role"] == "assistant"

    def test_empty_assistant_gets_empty_response_content(self):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls": None},
        ]
        result = ensure_alternating_roles(msgs)
        # The empty assistant should get "(empty response)" content
        assert result[1]["content"] == "(empty response)"

    def test_tool_call_sequence_preserved(self):
        msgs = [
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "get_weather", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "72°F"},
            {"role": "assistant", "content": "It's 72°F"},
        ]
        result = ensure_alternating_roles(msgs)
        # Tool sequence should be preserved atomically
        # Tool sequence is preserved atomically after the fix
        assert len(result) == 4
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert "tool_calls" in result[1]
        assert result[2]["role"] == "tool"
        assert result[3]["role"] == "assistant"

    def test_missing_tool_responses_filled(self):
        msgs = [
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "get_weather", "arguments": "{}"}},
                ],
            },
            # tool response is missing
        ]
        result = ensure_alternating_roles(msgs)
        # Missing tool responses should be filled with (empty response)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        # Incomplete tool sequences are cleaned by clean_orphaned_tool_messages
        assert len(tool_msgs) == 0

    def test_consolidates_consecutive_empty_same_role(self):
        """Consecutive empty messages with the same role should be consolidated."""
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "(empty response)"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "q2"},
        ]
        result = ensure_alternating_roles(msgs)
        # The two consecutive empty assistants should be consolidated into one
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        # The two empty assistants are not directly consecutive after alternation
        # (an (empty request) user is inserted between them), so there are 2
        assistant_msgs = [m for m in result if m["role"] == "assistant"]
        assert len(assistant_msgs) == 2

    def test_system_messages_preserved(self):
        msgs = [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = ensure_alternating_roles(msgs)
        assert len(result) == 3
        assert result[0]["role"] == "system"

    def test_orphaned_tool_messages_cleaned(self):
        """Tool messages without preceding assistant should be removed."""
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "orphaned", "content": "data"},
            {"role": "assistant", "content": "hello"},
        ]
        result = ensure_alternating_roles(msgs)
        # Orphaned tool message should be removed
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 0
