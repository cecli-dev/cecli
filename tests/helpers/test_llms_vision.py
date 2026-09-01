"""Vision / image-input mapping tests: OpenAI-style content parts -> domain wire.

Covers the translation of multimodal user messages (``[{"type": "text", ...},
{"type": "image_url", ...}]``) onto each family's wire payload:

- chat: content lists pass through verbatim (OpenAI-style ``image_url`` parts)
- gemini: base64 data URLs -> ``inlineData {mimeType, data}``; http(s) URLs ->
  ``fileData {fileUri}``
- anthropic: base64 data URLs -> ``{"type": "image", "source": {base64}}``
  blocks; http(s) URLs fall back to JSON text (Anthropic only accepts base64)
- responses: ``image_url`` parts -> ``{"type": "input_image", "image_url"}``
  items

Unknown / malformed parts are JSON-serialized into a text part (never dropped).
No network: only the offline payload builders are exercised.
"""

from cecli.helpers.llms.config import resolve_model_config
from cecli.helpers.llms.domains.chat import chat_payload
from cecli.helpers.llms.domains.gemini import gemini_payload
from cecli.helpers.llms.domains.messages import anthropic_payload
from cecli.helpers.llms.domains.responses import responses_payload
from cecli.helpers.llms.utils import split_data_url

DATA_URL = "data:image/png;base64,iVBORw0KGgo="
HTTP_URL = "https://example.com/pic.png"

#: OpenAI-style multimodal user message (the shape cecli stores in history).
MULTIMODAL = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "what is in this image?"},
            {"type": "image_url", "image_url": {"url": DATA_URL}},
            {"type": "image_url", "image_url": {"url": HTTP_URL}},
        ],
    },
]


def _gemini_parts():
    resolved = resolve_model_config("gemini/gemini-3-flash-preview")
    payload = gemini_payload(resolved, MULTIMODAL, None, {})
    return payload["contents"][0]["parts"]


def _anthropic_blocks():
    resolved = resolve_model_config("claude-sonnet-5")
    payload = anthropic_payload(resolved, MULTIMODAL, None, False, {})
    return payload["messages"][0]["content"]


def _responses_content():
    resolved = resolve_model_config("openai/gpt-5.6-luna")
    payload = responses_payload(resolved, MULTIMODAL, None, False, {})
    return payload["input"][0]["content"]


def _chat_content():
    resolved = resolve_model_config("deepseek/deepseek-v4-flash")
    payload = chat_payload(resolved, MULTIMODAL, None, False, {})
    return payload["messages"][0]["content"]


# ---------------------------------------------------------------------------
# split_data_url unit checks
# ---------------------------------------------------------------------------


def test_split_data_url_parses_base64_data_url():
    assert split_data_url(DATA_URL) == ("image/png", "iVBORw0KGgo=")


def test_split_data_url_rejects_non_base64_and_http():
    assert split_data_url("data:text/plain,hello") is None
    assert split_data_url(HTTP_URL) is None
    assert split_data_url(None) is None


# ---------------------------------------------------------------------------
# gemini: inlineData / fileData parts
# ---------------------------------------------------------------------------


def test_gemini_data_url_becomes_inline_data():
    parts = _gemini_parts()
    assert parts[0] == {"text": "what is in this image?"}
    assert parts[1] == {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo="}}


def test_gemini_http_url_becomes_file_data():
    parts = _gemini_parts()
    assert parts[2] == {"fileData": {"fileUri": HTTP_URL}}


def test_gemini_unknown_part_falls_back_to_text():
    resolved = resolve_model_config("gemini/gemini-3-flash-preview")
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hi"},
                {"type": "audio_url", "audio_url": {"url": "https://example.com/a.mp3"}},
                "not-a-dict",
            ],
        }
    ]
    payload = gemini_payload(resolved, msgs, None, {})
    parts = payload["contents"][0]["parts"]
    assert parts[0] == {"text": "hi"}
    assert parts[1]["text"].startswith("{")
    assert parts[2] == {"text": '"not-a-dict"'}


# ---------------------------------------------------------------------------
# anthropic: base64 image blocks (http falls back to text)
# ---------------------------------------------------------------------------


def test_anthropic_data_url_becomes_image_block():
    blocks = _anthropic_blocks()
    assert blocks[0] == {"type": "text", "text": "what is in this image?"}
    assert blocks[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="},
    }


def test_anthropic_http_url_falls_back_to_text():
    blocks = _anthropic_blocks()
    assert blocks[2]["type"] == "text"
    assert HTTP_URL in blocks[2]["text"]


# ---------------------------------------------------------------------------
# responses: input_image items
# ---------------------------------------------------------------------------


def test_responses_image_url_becomes_input_image():
    content = _responses_content()
    assert content[0] == {"type": "input_text", "text": "what is in this image?"}
    assert content[1] == {"type": "input_image", "image_url": DATA_URL}
    assert content[2] == {"type": "input_image", "image_url": HTTP_URL}


# ---------------------------------------------------------------------------
# chat: pass-through unchanged
# ---------------------------------------------------------------------------


def test_chat_multimodal_passes_through_verbatim():
    content = _chat_content()
    assert content == MULTIMODAL[0]["content"]


# ---------------------------------------------------------------------------
# malformed image_url never drops the part
# ---------------------------------------------------------------------------


def test_malformed_image_url_falls_back_to_text():
    resolved = resolve_model_config("openai/gpt-5.6-luna")
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": "not-a-dict"},
                {"type": "image_url"},
            ],
        }
    ]
    payload = responses_payload(resolved, msgs, None, False, {})
    content = payload["input"][0]["content"]
    assert len(content) == 2
    assert all(item["type"] == "input_text" for item in content)
