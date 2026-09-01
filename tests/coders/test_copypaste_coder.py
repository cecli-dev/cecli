import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from cecli.coders.copypaste_coder import get_copy_paste_coder_class
from cecli.coders.editblock_coder import EditBlockCoder

# Dynamically create a CopyPasteCoder class for testing purposes.
# We use the 'diff' edit format so it inherits EditBlockCoder behavior.
_TestModel = type("TestModel", (), {"edit_format": None, "name": "test"})
CopyPasteCoder = get_copy_paste_coder_class("diff", _TestModel())


def test_dynamic_class_inherits_from_target_coder():
    """The dynamic CopyPasteCoder class inherits from the target coder class."""
    # Already created at module level: CopyPasteCoder = get_copy_paste_coder_class("diff", _TestModel())
    assert issubclass(
        CopyPasteCoder, EditBlockCoder
    ), "CopyPasteCoder should inherit from EditBlockCoder for 'diff' format"
    # The fixed CopyPasteCoder marker should also be in the MRO
    from cecli.coders.copypaste_coder import CopyPasteCoder as FixedCopyPasteCoder

    assert (
        FixedCopyPasteCoder in CopyPasteCoder.__mro__
    ), "Fixed CopyPasteCoder should be in the MRO for isinstance checks"
    # gpt_prompts should resolve correctly via the inherited property
    assert CopyPasteCoder.prompt_format is not None
    assert CopyPasteCoder.prompt_format == EditBlockCoder.prompt_format


@pytest.mark.asyncio
async def test_send_uses_copy_paste_flow(monkeypatch):
    coder = CopyPasteCoder.__new__(CopyPasteCoder)

    io = MagicMock()
    coder.io = io
    coder.stream = False
    coder.partial_response_content = ""
    coder.partial_response_tool_calls = []
    coder.partial_response_function_call = None
    coder.chat_completion_call_hashes = []
    coder.interrupt_event = MagicMock()

    coder.show_send_output = AsyncMock(
        side_effect=lambda c: coder.partial_response_chunks.append(c)
    )
    coder.calculate_and_show_tokens_and_cost = MagicMock()

    def fake_preprocess_response():
        coder.partial_response_content = "final-response"

    coder.preprocess_response = fake_preprocess_response

    class ModelStub:
        copy_paste_mode = True
        copy_paste_transport = "clipboard"
        name = "cp:gpt-4o"

        @staticmethod
        def token_count(text):
            return len(text)

    coder.main_model = ModelStub()

    hash_obj = MagicMock()
    hash_obj.hexdigest.return_value = "hash"
    completion = MagicMock()

    with patch.object(
        CopyPasteCoder, "copy_paste_completion", return_value=(hash_obj, completion)
    ) as mock_completion:
        messages = [{"role": "user", "content": "Hello"}]
        chunks = [chunk async for chunk in coder.send(messages)]

    assert chunks == []
    mock_completion.assert_called_once_with(messages, coder.main_model)
    coder.show_send_output.assert_called_once_with(completion)
    coder.calculate_and_show_tokens_and_cost.assert_called_once_with(messages, completion)
    assert coder.chat_completion_call_hashes == ["hash"]
    coder.io.ai_output.assert_called_once_with("final-response")


def test_copy_paste_completion_interacts_with_clipboard(monkeypatch):
    coder = CopyPasteCoder.__new__(CopyPasteCoder)

    io = MagicMock()
    coder.io = io

    import cecli.helpers.copypaste as copypaste

    copy_mock = MagicMock()
    read_mock = MagicMock(return_value="initial value")
    wait_mock = MagicMock(return_value="assistant reply")

    monkeypatch.setattr(copypaste, "copy_to_clipboard", copy_mock)
    monkeypatch.setattr(copypaste, "read_clipboard", read_mock)
    monkeypatch.setattr(copypaste, "wait_for_clipboard_change", wait_mock)

    class DummyMessage:
        def __init__(self, **kwargs):
            self.data = kwargs

    class DummyChoices:
        def __init__(self, **kwargs):
            self.data = kwargs

    class DummyModelResponse:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class DummyUsage(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    monkeypatch.setattr("cecli.coders.copypaste_coder.litellm.Message", DummyMessage)
    monkeypatch.setattr("cecli.coders.copypaste_coder.litellm.Choices", DummyChoices)
    monkeypatch.setattr("cecli.coders.copypaste_coder.litellm.ModelResponse", DummyModelResponse)
    monkeypatch.setattr("cecli.coders.copypaste_coder.litellm.Usage", DummyUsage)

    class ModelStub:
        name = "cp:gpt-4o"
        copy_paste_mode = True
        copy_paste_transport = "clipboard"

        @staticmethod
        def token_count(text):
            return len(text)

    model = ModelStub()

    messages = [
        {"role": "system", "content": "keep calm"},
        {"role": "user", "content": [{"text": "Hello"}, {"text": "!"}]},
        {"role": "assistant", "content": [{"text": "Prior"}, {"text": " reply"}]},
    ]

    hash_obj, completion = coder.copy_paste_completion(messages, model)

    expected_prompt = "SYSTEM:\nkeep calm\n\nUSER:\nHello!\n\nASSISTANT:\nPrior reply"
    copy_mock.assert_called_once_with(expected_prompt)
    read_mock.assert_called_once()
    wait_mock.assert_called_once_with(initial="initial value")

    io.tool_output.assert_has_calls(
        [
            call("Request copied to clipboard."),
            call("Paste it into your LLM interface, then copy the reply back."),
            call("Waiting for clipboard updates (Ctrl+C to cancel)..."),
        ]
    )

    expected_hash = hashlib.sha1(
        json.dumps(
            {"model": model.name, "messages": messages, "stream": False}, sort_keys=True
        ).encode()
    ).hexdigest()
    assert hash_obj.hexdigest() == expected_hash

    usage = completion.kwargs["usage"]
    assert usage["prompt_tokens"] == len(expected_prompt)
    assert usage["completion_tokens"] == len("assistant reply")
    assert usage["total_tokens"] == len(expected_prompt) + len("assistant reply")

    choices = completion.kwargs["choices"]
    assert len(choices) == 1
    choice_payload = choices[0].data
    assert choice_payload["message"].data["content"] == "assistant reply"
