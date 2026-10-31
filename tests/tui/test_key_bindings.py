"""Tests for TUI key binding normalization and registration."""

import pytest
from textual.binding import BindingsMap

from cecli.tui.app import TUI


@pytest.fixture
def tui_instance(monkeypatch):
    """Create a TUI instance without running Textual's App init."""
    monkeypatch.setattr("cecli.tui.app.TUI.__init__", lambda *args, **kwargs: None)
    tui = TUI(coder_worker=None, output_queue=None, input_queue=None, args=None)
    tui._bindings = BindingsMap()
    tui.tui_config = {"key_bindings": {}}
    return tui


def test_encode_keys_canonicalizes_modifier_order(tui_instance):
    assert tui_instance._encode_keys("ctrl+alt+right") == "alt+ctrl+right"
    assert tui_instance._encode_keys("shift+ctrl+alt+right") == "alt+ctrl+shift+right"
    assert tui_instance._encode_keys("alt+ctrl+right") == "alt+ctrl+right"


def test_encode_keys_preserves_unknown_modifiers(tui_instance):
    assert tui_instance._encode_keys("hyper+right") == "hyper+right"


def test_is_key_for_accepts_any_modifier_order(tui_instance):
    tui_instance.tui_config["key_bindings"]["next_agent"] = tui_instance._encode_keys(
        "ctrl+alt+right"
    )
    assert tui_instance.is_key_for("next_agent", "alt+ctrl+right")
    assert tui_instance.is_key_for("next_agent", "ctrl+alt+right")
    assert not tui_instance.is_key_for("next_agent", "ctrl+alt+left")


def test_bind_key_registers_priority_binding(tui_instance):
    tui_instance.tui_config["key_bindings"]["next_agent"] = tui_instance._encode_keys(
        "ctrl+alt+right"
    )
    tui_instance._bind_key(
        "next_agent", "switch_next_agent", description="Next Agent", priority=True
    )
    bindings = tui_instance._bindings.key_to_bindings["alt+ctrl+right"]
    assert bindings
    assert all(binding.priority for binding in bindings)


def test_bind_key_can_register_non_priority_binding(tui_instance):
    tui_instance.tui_config["key_bindings"]["submit"] = tui_instance._encode_keys("enter")
    tui_instance._bind_key("submit", "noop", description="Submit", priority=False)
    bindings = tui_instance._bindings.key_to_bindings["enter"]
    assert bindings
    assert not any(binding.priority for binding in bindings)
