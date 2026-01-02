import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from cecli.coders.copypaste_coder import CopyPasteCoder
from cecli.coders.editblock_coder import EditBlockCoder


def test_init_prompts_uses_selected_edit_format():
    coder = CopyPasteCoder.__new__(CopyPasteCoder)
    coder.args = SimpleNamespace(edit_format="diff")
    coder.main_model = SimpleNamespace(edit_format=None)
    coder.edit_format = None
    coder.gpt_prompts = None

    coder._init_prompts_from_selected_edit_format()

    assert coder.gpt_prompts is not None
    assert hasattr(coder.gpt_prompts, "main_system")
    assert coder.edit_format == EditBlockCoder.edit_format


def test_init_prompts_preserves_existing_when_no_match(monkeypatch):
    coder = CopyPasteCoder.__new__(CopyPasteCoder)
    coder.args = SimpleNamespace(edit_format="custom-format")
    coder.main_model = SimpleNamespace(edit_format=None)
    coder.edit_format = "original-format"
    coder.gpt_prompts = "original-prompts"

    import cecli.coders as coders

    monkeypatch.setattr(coders, "__all__", [], raising=False)

    coder._init_prompts_from_selected_edit_format()

    assert coder.gpt_prompts == "original-prompts"
    assert coder.edit_format == "original-format"


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
    coder.show_send_output = MagicMock()
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

    monkeypatch.setattr("cecli.coders.copypaste_coder.litellm.Message", DummyMessage)
    monkeypatch.setattr("cecli.coders.copypaste_coder.litellm.Choices", DummyChoices)
    monkeypatch.setattr("cecli.coders.copypaste_coder.litellm.ModelResponse", DummyModelResponse)

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
