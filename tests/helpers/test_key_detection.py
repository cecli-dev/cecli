"""Tests for api-key detection and BaseMessage redaction.

No real secrets are used: the values below are synthetic and the environment
is patched so the scan is deterministic.
"""

import pytest

from cecli.helpers import key_detection
from cecli.helpers.conversation.base_message import BaseMessage

FAKE_KEY = "sk-ant-api03-SynThEtIcVaLuE0123456789aBcDeF"
FAKE_TOKEN = "SynThEtIcToKeN-0123456789-aBcDeF"


@pytest.fixture(autouse=True)
def clean_registry():
    """Isolate the process-wide registry between tests."""
    key_detection.reset_api_keys()
    yield
    key_detection.reset_api_keys()


def test_detects_key_like_tokens_in_env_values():
    environ = {"SOME_PROVIDER": FAKE_KEY}

    assert FAKE_KEY in key_detection.detect_api_keys(environ=environ)


def test_detects_value_of_env_var_named_with_key():
    # Contains ':' so the token regex can't span it, but the name says secret.
    environ = {"CUSTOM_API_KEY": f"Bearer {FAKE_TOKEN}"}

    assert f"Bearer {FAKE_TOKEN}" in key_detection.detect_api_keys(environ=environ)


def test_detects_values_of_env_vars_named_with_token_or_password():
    environ = {"GH_TOKEN": FAKE_TOKEN, "DB_PASSWORD": f"pa:ss{FAKE_KEY}"}

    assert FAKE_TOKEN in key_detection.detect_api_keys(environ=environ)
    # Passwords carry punctuation the token regex cannot span, so the name has
    # to carry the decision.
    assert f"pa:ss{FAKE_KEY}" in key_detection.detect_api_keys(environ=environ)


def test_detects_credential_words_that_are_not_separate_name_words():
    environ = {"MYTOKEN": FAKE_TOKEN, "SERVICE_PASSWD": FAKE_TOKEN}

    assert key_detection.detect_api_keys(environ=environ) == [FAKE_TOKEN]


def test_ignores_names_where_credential_word_is_not_a_suffix():
    environ = {
        "TOKENIZER": f"Bearer {FAKE_TOKEN}",
        "KEYBOARD_LAYOUT": f"Bearer {FAKE_TOKEN}",
        "SSH_KEY_PATH": "/home/some/repo/lower_case-4/file.txt",
    }

    assert key_detection.detect_api_keys(environ=environ) == [FAKE_TOKEN]


def test_ignores_path_shaped_identifiers():
    environ = {
        "PWD": "/home/some/repo/my_project_worktree_checkout-4",
        "PYTHONPATH": "/home/some/project_with_a_really_long_name-4/lib",
        "SOME_PROVIDER": "parent_with_a_very_long_name-4/lower_case-4/file.txt",
        "SOME_OTHER": "parent_with_a_very_long_name-4/lower_case_checkout",
        "CLIENT_SECRET": "/home/some/project_with_a_really_long_name-4/secret.txt",
    }

    assert key_detection.detect_api_keys(environ=environ) == []


def test_contains_credential_word_requires_a_key_like_value():
    environ = {
        "API_KEY_V2": FAKE_KEY,
        "KEY_DESCRIPTION_V2": "ordinary human readable words",
        "KEY_LOW_DIVERSITY_V2": "abc123 abc123 abc123 abc123",
        "KEY_LOCATION_V2": "parent_with_a_very_long_name-4/file.txt",
    }

    assert key_detection.detect_api_keys(environ=environ) == [FAKE_KEY]


def test_detects_keys_embedded_in_path_shaped_values():
    environ = {"SOME_PROVIDER": f"/usr/bin/foo {FAKE_KEY}"}

    assert key_detection.detect_api_keys(environ=environ) == [FAKE_KEY]


def test_ambiguous_suffix_names_require_key_like_values():
    environ = {
        "MONKEY": "ordinary-value",
        "TURKEY": "ordinary-value",
        "sortKey": "ordinary-value",
        "lookupKey": "ordinary-value",
        "HOTKEYS": "ordinary-value",
        "MYTOKEN2": "ordinary-value",
    }
    merged = {"hotkeys": {"copy": "ordinary-value"}}

    assert key_detection.detect_api_keys(environ=environ) == []
    assert key_detection.detect_api_keys(merged, environ={}) == []


def test_entropy_gate_rejects_whitespace_and_prose():
    environ = {"sortKey": "rotate this api key every90 days"}

    assert key_detection.detect_api_keys(environ=environ) == []


def test_path_detection_handles_urls_windows_and_relative_paths():
    looks_like_path = key_detection._looks_like_path

    assert not looks_like_path("https://example.com/a/b")
    assert looks_like_path(r"C:\Users\some\project_with_a_long_name-4")
    assert looks_like_path(r"\\server\share\project_with_a_long_name-4")
    assert looks_like_path("parent_with_a_long_name-4/lower_case_checkout/index.txt")
    assert not looks_like_path("parent_with_a_long_name-4/lower_case_checkout")
    assert key_detection._looks_path_ish("parent_with_a_long_name-4/lower_case_checkout")
    assert not looks_like_path("AbCd/EfGh12/IjKl34/MnOp56")
    assert not looks_like_path(r"abc\def")
    assert not looks_like_path(FAKE_KEY)


def test_entropy_thresholds_cover_secret_words():
    assert set(key_detection.SECRET_NAME_SUFFIXES) <= set(
        key_detection.CREDENTIAL_ENTROPY_THRESHOLDS
    )


def test_keeps_slash_containing_secrets():
    slash_key = "AbCd/EfGh12/IjKl34/MnOp56/QrSt78"
    environ = {"API_KEY": slash_key, "CLIENT_SECRET": slash_key}
    merged = {"api_key": "abcd1234/efgh5678/ijkl9012mnop3456qrst"}

    assert key_detection.detect_api_keys(environ=environ) == [slash_key]
    assert key_detection.detect_api_keys(merged, environ={}) == [
        "abcd1234/efgh5678/ijkl9012mnop3456qrst"
    ]


def test_ambiguous_suffix_names_still_detect_key_like_values():
    environ = {"authToken": FAKE_TOKEN, "sortKey": FAKE_KEY, "MYTOKEN2": FAKE_TOKEN}

    assert key_detection.detect_api_keys(environ=environ) == sorted({FAKE_KEY, FAKE_TOKEN})


def test_credential_words_take_precedence_over_benign_words():
    environ = {"KEY_ID": FAKE_KEY, "TOKEN_NAME": FAKE_TOKEN}

    assert key_detection.detect_api_keys(environ=environ) == sorted({FAKE_KEY, FAKE_TOKEN})


def test_version_suffixed_unambiguous_names_are_trusted():
    environ = {
        "SECRET_KEY_1": "p@ss:w0rd!",
        "API_KEY_1": "pa:ssw0rd",
        "DB_PASSWORD_2": "hunter2hunter2",
    }

    assert set(key_detection.detect_api_keys(environ=environ)) == set(environ.values())


def test_ignores_short_values_of_key_named_env_vars():
    environ = {"SOME_FLAG_KEY": "true"}

    assert key_detection.detect_api_keys(environ=environ) == []


def test_ignores_identifier_like_names():
    environ = {
        "MODEL_NAME": "claude-3-5-sonnet-20241022",
        "PATHS": "/home/some/really/long/directory/name",
        "WT_SESSION": "1752eba7-c67d-4378-9e25-2531f2c095ac",
    }

    assert key_detection.detect_api_keys(environ=environ) == []


def test_skips_unexpanded_env_reference_and_registers_resolved_value():
    merged = {"agent-config": {"api_key": "${MY_KEY}"}}
    environ = {"MY_KEY": FAKE_KEY}

    found = key_detection.detect_api_keys(merged, environ=environ)

    assert found == [FAKE_KEY]


def test_detects_nested_config_secrets():
    merged = {"model-providers": {"chutes": {"api_key": FAKE_KEY}}, "list": [{"token": FAKE_TOKEN}]}

    assert key_detection.detect_api_keys(merged, environ={}) == sorted({FAKE_KEY, FAKE_TOKEN})


def test_registration_is_additive_and_longest_first():
    key_detection.register_api_keys([FAKE_KEY[:20]])
    key_detection.register_api_keys([FAKE_KEY])

    assert key_detection.get_api_keys() == [FAKE_KEY, FAKE_KEY[:20]]


def test_base_message_redacts_content_and_tool_calls():
    key_detection.register_api_keys([FAKE_KEY, FAKE_TOKEN])
    message = BaseMessage(
        message_dict={
            "role": "user",
            "content": f"use {FAKE_KEY} now",
            "tool_calls": [{"id": "1", "function": {"name": "B", "arguments": {"k": FAKE_TOKEN}}}],
        },
        tag="cur",
    )

    as_dict = message.to_dict()

    assert as_dict["content"] == "use <redacted> now"
    assert as_dict["tool_calls"][0]["function"]["arguments"] == {"k": "<redacted>"}
    # The choke point is the assignment, so nothing secret is stored at all.
    assert FAKE_KEY not in message.message_dict["content"]
    assert FAKE_TOKEN not in str(message.message_dict["tool_calls"])


def test_base_message_repr_is_redacted():
    key_detection.register_api_keys([FAKE_KEY])
    message = BaseMessage(message_dict={"role": "user", "content": f"{FAKE_KEY}"}, tag="cur")

    assert FAKE_KEY not in repr(message)


def test_content_is_redacted_when_the_dict_is_replaced():
    # Covers the ConversationManager force-update path, which assigns a new
    # message_dict onto an existing message.
    key_detection.register_api_keys([FAKE_KEY])
    message = BaseMessage(message_dict={"role": "user", "content": "clean"}, tag="cur")

    message.message_dict = {"role": "user", "content": f"key is {FAKE_KEY}"}

    assert FAKE_KEY not in message.message_dict["content"]
    assert message.message_dict["content"] == "key is <redacted>"


def test_ids_are_generated_from_redacted_content():
    key_detection.register_api_keys([FAKE_KEY])
    first = BaseMessage(message_dict={"role": "user", "content": f"a {FAKE_KEY}"}, tag="cur")
    second = BaseMessage(message_dict={"role": "user", "content": "a <redacted>"}, tag="cur")

    assert first.message_id == second.message_id


def test_stored_dict_is_the_same_object_when_nothing_is_redacted():
    key_detection.register_api_keys([FAKE_KEY])
    raw = {"role": "user", "content": "no secrets here"}

    assert BaseMessage(message_dict=raw, tag="cur").message_dict is raw


def test_redaction_is_noop_without_registered_keys():
    message = BaseMessage(message_dict={"role": "user", "content": f"{FAKE_KEY}"}, tag="cur")

    assert message.to_dict()["content"] == FAKE_KEY


def test_conversation_manager_write_paths_redact():
    """Both add_message() routes go through the BaseMessage choke point."""
    import uuid

    from cecli.helpers.conversation.manager import ConversationManager
    from cecli.helpers.conversation.tags import MessageTag

    class StubCoder:
        def __init__(self):
            self.uuid = str(uuid.uuid4())

    coder = StubCoder()
    manager = ConversationManager.get_instance(coder)

    key_detection.register_api_keys([FAKE_KEY])
    manager.add_message({"role": "user", "content": f"first {FAKE_KEY}"}, MessageTag.DONE)
    manager.add_message(
        {"role": "user", "content": f"second {FAKE_KEY}"},
        MessageTag.DONE,
        force=True,
        hash_key=("same",),
    )
    manager.add_message(
        {"role": "user", "content": f"updated {FAKE_KEY}"},
        MessageTag.DONE,
        force=True,
        hash_key=("same",),
    )

    stored = [msg.message_dict["content"] for msg in manager.get_messages()]

    assert FAKE_KEY not in "".join(stored)
    assert "updated <redacted>" in stored
    assert manager.get_messages_dict(MessageTag.DONE)[0]["content"].count("<redacted>") == 1
