"""Shared fixtures for sub-agent unit tests."""

import uuid
from unittest.mock import MagicMock

import pytest


class MockCoder:
    """A lightweight coder mock with the minimum attributes sub-agent code needs."""

    def __init__(self, uid=None, parent_uid=""):
        self.uuid = str(uid or uuid.uuid4())
        self.parent_uuid = parent_uid
        self.io = MagicMock()
        self.tui = None
        self.agent_finished = False
        self.max_sub_agents = 3
        self.main_model = MagicMock()
        self.main_model.edit_format = None
        self.main_model.system_prompt_prefix = ""
        self.gpt_prompts = MagicMock()
        self.gpt_prompts.main_system = "You are a helpful assistant."
        self.gpt_prompts.system_reminder = ""
        self.files_edited_by_tools = set()
        self.edit_format = "agent"

    def fmt_system_prompt(self, prompt):
        return prompt

    def choose_fence(self):
        pass

    def wrap_user_input(self, text):
        return text


@pytest.fixture
def mock_coder():
    """Basic mock coder with a fresh UUID."""
    return MockCoder()


@pytest.fixture
def parent_coder():
    """A mock parent coder (used as the primary agent)."""
    return MockCoder(uid="parent-uuid-001")


@pytest.fixture
def sub_coder(parent_coder):
    """A mock sub-agent coder with a parent_uuid set."""
    return MockCoder(uid="sub-uuid-001", parent_uid=parent_coder.uuid)


@pytest.fixture
def temp_dir(tmp_path):
    """A temporary directory for config file tests."""
    return tmp_path
