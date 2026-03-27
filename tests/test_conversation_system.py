"""
Unit tests for the conversation system.
"""

import uuid

import pytest

from cecli.helpers.conversation import BaseMessage, ConversationService, MessageTag
from cecli.io import InputOutput


class MockCoder:
    """Simple mock coder class for conversation system tests."""

    def __init__(self, io=None):
        self.uuid = uuid.uuid4()
        self.abs_fnames = set()
        self.abs_read_only_fnames = set()
        self.edit_format = None
        self.context_management_enabled = False
        self.large_file_token_threshold = 1000
        self.io = io or InputOutput(yes=False)
        self.add_cache_headers = False
        self.hashlines = False
        self.add_cache_headers = False  # Default to False for tests

    @property
    def done_messages(self):
        """Get DONE messages from ConversationManager."""
        return ConversationService.get_manager(self).get_messages_dict(MessageTag.DONE)

    @property
    def cur_messages(self):
        """Get CUR messages from ConversationManager."""
        return ConversationService.get_manager(self).get_messages_dict(MessageTag.CUR)


class TestBaseMessage:
    """Test BaseMessage class."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset conversation manager before each test."""
        self.test_coder = MockCoder()
        ConversationService.get_manager(self.test_coder).reset()
        ConversationService.get_files(self.test_coder).reset()
        yield
        ConversationService.get_manager(self.test_coder).reset()
        ConversationService.get_files(self.test_coder).reset()

    def test_base_message_creation(self):
        """Test creating a BaseMessage instance."""
        message_dict = {"role": "user", "content": "Hello, world!"}
        message = BaseMessage(message_dict=message_dict, tag=MessageTag.CUR.value)

        assert message.message_dict == message_dict
        assert message.tag == MessageTag.CUR.value
        assert message.priority == 0  # Default priority
        assert message.message_id is not None
        assert message.mark_for_delete is None

    def test_base_message_validation(self):
        """Test message validation."""
        # Missing role should raise ValueError
        with pytest.raises(ValueError):
            BaseMessage(message_dict={"content": "Hello"}, tag=MessageTag.CUR.value)

        # Missing content and tool_calls should raise ValueError
        with pytest.raises(ValueError):
            BaseMessage(message_dict={"role": "user"}, tag=MessageTag.CUR.value)

        # Valid with tool_calls
        message_dict = {"role": "assistant", "tool_calls": [{"id": "1", "type": "function"}]}
        message = BaseMessage(message_dict=message_dict, tag=MessageTag.CUR.value)
        assert message.message_dict == message_dict

    def test_base_message_hash_generation(self):
        """Test hash generation for messages."""
        message_dict1 = {"role": "user", "content": "Hello"}
        message_dict2 = {"role": "user", "content": "Hello"}
        message_dict3 = {"role": "user", "content": "World"}

        message1 = BaseMessage(message_dict=message_dict1, tag=MessageTag.CUR.value)
        message2 = BaseMessage(message_dict=message_dict2, tag=MessageTag.CUR.value)
        message3 = BaseMessage(message_dict=message_dict3, tag=MessageTag.CUR.value)

        # Same content should have same hash
        assert message1.message_id == message2.message_id
        # Different content should have different hash
        assert message1.message_id != message3.message_id

    def test_base_message_expiration(self):
        """Test message expiration logic."""
        message_dict = {"role": "user", "content": "Hello"}

        # Message with no mark_for_delete should not expire
        message1 = BaseMessage(message_dict=message_dict, tag=MessageTag.CUR.value)
        assert not message1.is_expired()

        # Message with mark_for_delete = -1 should expire
        message2 = BaseMessage(
            message_dict=message_dict, tag=MessageTag.CUR.value, mark_for_delete=-1
        )
        assert message2.is_expired()

        # Message with mark_for_delete > 0 should not expire
        message3 = BaseMessage(
            message_dict=message_dict, tag=MessageTag.CUR.value, mark_for_delete=1
        )
        assert not message3.is_expired()


class TestConversationManager:
    """Test ConversationManager class."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset conversation manager before each test."""
        # Create a test coder with real InputOutput
        self.test_coder = MockCoder()
        self.manager = ConversationService.get_manager(self.test_coder)
        self.chunks = ConversationService.get_chunks(self.test_coder)
        self.manager.reset()

        # Initialize conversation system
        self.chunks.initialize_conversation_system()
        yield
        self.manager.reset()

    def test_add_message(self):
        """Test adding messages to conversation manager."""
        message_dict = {"role": "user", "content": "Hello"}

        # Add first message
        message1 = self.manager.add_message(
            message_dict=message_dict,
            tag=MessageTag.CUR,
        )
        assert len(self.manager.get_messages()) == 1
        assert self.manager.get_messages()[0].message_dict["content"] == "Hello"

        # Add same message (should be idempotent by default)
        message2 = self.manager.add_message(
            message_dict=message_dict,
            tag=MessageTag.CUR,
        )
        assert len(self.manager.get_messages()) == 1
        assert message1.message_id == message2.message_id

        # Add message with different tag
        self.manager.add_message(
            message_dict={"role": "assistant", "content": "Hi"},
            tag=MessageTag.EXAMPLES,
        )
        assert len(self.manager.get_messages()) == 2

    def test_add_message_with_force(self):
        """Test adding messages with force=True."""
        message_dict = {"role": "user", "content": "Hello"}
        message1 = self.manager.add_message(
            message_dict=message_dict,
            tag=MessageTag.CUR,
            hash_key=("test", "message"),
        )

        # Update message with force=True using same hash_key
        updated_dict = {"role": "user", "content": "Updated"}
        message2 = self.manager.add_message(
            message_dict=updated_dict,
            tag=MessageTag.CUR,
            hash_key=("test", "message"),
            force=True,
        )

        assert len(self.manager.get_messages()) == 1
        # When using hash_key + force, the existing message object is updated
        assert message1.message_id == message2.message_id
        assert self.manager.get_messages()[0].message_dict["content"] == "Updated"

        # Normal priority messages
        self.manager.add_message(
            message_dict={"role": "user", "content": "Low priority"},
            tag=MessageTag.CUR,  # priority 200
        )
        self.manager.add_message(
            message_dict={"role": "system", "content": "High priority"},
            tag=MessageTag.SYSTEM,  # priority 0
        )

        # Promoted message (should be between SYSTEM and CUR)
        self.manager.add_message(
            message_dict={"role": "assistant", "content": "Promoted"},
            tag=MessageTag.CUR,
            promotion=100,
            mark_for_demotion=1,  # Required for is_promoted()
        )

        messages = self.manager.get_messages()
        assert len(messages) == 4
        assert messages[0].tag == MessageTag.SYSTEM.value
        assert messages[1].message_dict["content"] == "Promoted"
        assert messages[2].message_dict["content"] == "Updated"
        assert messages[3].message_dict["content"] == "Low priority"

    def test_is_promoted_method(self):
        """Test that is_promoted() method works correctly."""
        # Not promoted (no mark_for_demotion)
        message1 = self.manager.add_message(
            message_dict={"role": "user", "content": "Not promoted"},
            tag=MessageTag.CUR,
            promotion=100,
        )
        assert not message1.is_promoted()

        # Promoted (has mark_for_demotion >= 0)
        message2 = self.manager.add_message(
            message_dict={"role": "user", "content": "Promoted"},
            tag=MessageTag.CUR,
            promotion=100,
            mark_for_demotion=0,
        )
        assert message2.is_promoted()

    def test_base_sort_with_promotion(self):
        """Test that base_sort correctly handles promoted and non-promoted messages."""
        m1 = BaseMessage({"role": "user", "content": "M1"}, tag=MessageTag.CUR.value, priority=200)
        m2 = BaseMessage(
            {"role": "system", "content": "M2"}, tag=MessageTag.SYSTEM.value, priority=0
        )
        m3 = BaseMessage(
            {"role": "assistant", "content": "M3"},
            tag=MessageTag.CUR.value,
            priority=200,
            promotion=100,
            mark_for_demotion=1,  # Required for is_promoted()
        )

        sorted_msgs = self.manager.base_sort([m1, m2, m3])
        assert sorted_msgs == [m2, m3, m1]


class TestConversationFiles:
    """Test ConversationFiles class."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset conversation files before each test."""
        # Create a test coder with real InputOutput
        self.test_coder = MockCoder()
        self.files = ConversationService.get_files(self.test_coder)
        self.chunks = ConversationService.get_chunks(self.test_coder)

        # Initialize conversation system
        self.chunks.initialize_conversation_system()

        yield
        self.files.reset()

    def test_add_and_get_file_content(self, mocker):
        """Test adding and getting file content."""
        import os
        import tempfile

        # Create a temporary file
        fd, temp_file = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "w") as f:
                f.write("Test content")

            # Patch the read_text method to return content only for the temp file
            def side_effect(fname, **kwargs):
                if fname == temp_file:
                    return "Test content"
                return None

            mocker.patch.object(self.test_coder.io, "read_text", side_effect=side_effect)
            # Add file to cache
            content = self.files.add_file(temp_file)
            assert content == "Test content"

            # Get file content from cache
            cached_content = self.files.get_file_content(temp_file)
            assert cached_content == "Test content"

            # Get content for non-existent file
            non_existent_content = self.files.get_file_content("/non/existent/file")
            assert non_existent_content == ""
        finally:
            # Clean up
            os.unlink(temp_file)

    def test_has_file_changed(self, mocker):
        """Test file change detection."""
        import os
        import tempfile
        import time

        # Create a temporary file
        fd, temp_file = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "w") as f:
                f.write("Original content")

            # Patch the read_text method on the coder's io
            def mock_read_text(filename, silent=False):
                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    return None

            mocker.patch.object(self.test_coder.io, "read_text", side_effect=mock_read_text)

            # Add file to cache
            self.files.add_file(temp_file)

            # File should not have changed yet
            assert not self.files.has_file_changed(temp_file)

            # Modify the file
            time.sleep(0.01)  # Ensure different mtime
            with open(temp_file, "w") as f:
                f.write("Modified content")

            # File should now be detected as changed
            assert self.files.has_file_changed(temp_file)
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
