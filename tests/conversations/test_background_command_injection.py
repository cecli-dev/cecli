"""Tests for the independently debounced background command output injection."""

import uuid

from cecli.helpers.conversation import ConversationService


class MockCoder:
    def __init__(self):
        self.uuid = str(uuid.uuid4())
        self.use_enhanced_context = True
        self.turn_count = 0
        self.output_calls = 0
        self.output = "roster"

    def get_background_command_output(self):
        self.output_calls += 1
        return self.output


def _make_chunks(coder):
    manager = ConversationService.get_manager(coder)
    manager.reset()
    chunks = ConversationService.get_chunks(coder)
    chunks.message_tracker = {}
    return chunks, manager


def test_background_command_output_debounced_to_every_five_turns():
    coder = MockCoder()
    chunks, manager = _make_chunks(coder)

    for turn in range(7):
        coder.turn_count = turn
        chunks.add_background_command_output(frequency=5)

    # Injected once up front, then not again until turn 5
    assert coder.output_calls == 2
    assert [message["content"] for message in manager.get_messages_dict()] == ["roster"]


def test_background_command_output_replaces_same_hash_key():
    coder = MockCoder()
    chunks, manager = _make_chunks(coder)

    coder.turn_count = 0
    chunks.add_background_command_output(frequency=5)

    coder.output = "roster v2"
    coder.turn_count = 5
    chunks.add_background_command_output(frequency=5)

    assert [message["content"] for message in manager.get_messages_dict()] == ["roster v2"]


def test_background_command_output_skipped_without_enhanced_context():
    coder = MockCoder()
    coder.use_enhanced_context = False
    chunks, manager = _make_chunks(coder)

    coder.turn_count = 0
    chunks.add_background_command_output(frequency=5)

    assert coder.output_calls == 0
    assert manager.get_messages_dict() == []


def test_empty_background_command_output_does_not_consume_window():
    coder = MockCoder()
    coder.output = ""
    chunks, manager = _make_chunks(coder)

    coder.turn_count = 0
    chunks.add_background_command_output(frequency=5)
    coder.turn_count = 1
    chunks.add_background_command_output(frequency=5)

    # Empty output never injects and never marks the tracker, so polling continues
    assert coder.output_calls == 2
    assert manager.get_messages_dict() == []

    coder.output = "roster"
    coder.turn_count = 2
    chunks.add_background_command_output(frequency=5)

    assert coder.output_calls == 3
    assert [message["content"] for message in manager.get_messages_dict()] == ["roster"]


class SignalCoder(MockCoder):
    def __init__(self):
        super().__init__()
        self.state = {}

    def get_background_command_state(self):
        return self.state


def test_finish_transition_bypasses_debounce():
    coder = SignalCoder()
    chunks, manager = _make_chunks(coder)

    coder.state = {"bg_1_0001": {"running": True, "pages": 0}}
    coder.turn_count = 0
    chunks.add_background_command_output(frequency=5)
    assert coder.output_calls == 1

    # Still running, nothing changed, and not due -> skip
    coder.turn_count = 1
    chunks.add_background_command_output(frequency=5)
    assert coder.output_calls == 1

    # Finished -> inject immediately despite the frequency window
    coder.state = {"bg_1_0001": {"running": False, "pages": 0}}
    coder.turn_count = 2
    chunks.add_background_command_output(frequency=5)
    assert coder.output_calls == 2


def test_new_page_flush_bypasses_debounce():
    coder = SignalCoder()
    chunks, _ = _make_chunks(coder)

    coder.state = {"bg_1_0001": {"running": True, "pages": 0}}
    coder.turn_count = 0
    chunks.add_background_command_output(frequency=5)
    assert coder.output_calls == 1

    coder.state = {"bg_1_0001": {"running": True, "pages": 1}}
    coder.turn_count = 1
    chunks.add_background_command_output(frequency=5)
    assert coder.output_calls == 2


def test_new_command_appearance_bypasses_debounce():
    coder = SignalCoder()
    chunks, _ = _make_chunks(coder)

    coder.state = {"bg_1_0001": {"running": True, "pages": 0}}
    coder.turn_count = 0
    chunks.add_background_command_output(frequency=5)
    assert coder.output_calls == 1

    coder.state = {
        "bg_1_0001": {"running": True, "pages": 0},
        "bg_2_0002": {"running": True, "pages": 0},
    }
    coder.turn_count = 1
    chunks.add_background_command_output(frequency=5)
    assert coder.output_calls == 2


def test_running_command_without_change_respects_frequency():
    coder = SignalCoder()
    chunks, _ = _make_chunks(coder)

    coder.state = {"bg_1_0001": {"running": True, "pages": 0}}
    coder.turn_count = 0
    chunks.add_background_command_output(frequency=5)
    assert coder.output_calls == 1

    for turn in (1, 2, 3, 4):
        coder.turn_count = turn
        chunks.add_background_command_output(frequency=5)

    assert coder.output_calls == 1

    coder.turn_count = 5
    chunks.add_background_command_output(frequency=5)
    assert coder.output_calls == 2
