"""Tests for the --spinner / --no-spinner CLI option."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_io():
    io = MagicMock()
    io.last_spinner_text = ""
    return io


@pytest.fixture
def mock_model():
    model = MagicMock()
    model.name = "test-model"
    model.system_prompt_prefix = None
    model.send_completion = MagicMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="test commit"))])
    )
    model.token_count = MagicMock(return_value=10)
    model.info = {"max_input_tokens": 100000}
    model.simple_send_with_retries = MagicMock(return_value=("test commit", None))

    async def _async_simple_send(*args, **kwargs):
        return ("test commit", None)

    model.simple_send_with_retries = _async_simple_send
    return model


class TestSpinnerArgParsing:
    """Tests that argparse correctly handles --spinner / --no-spinner."""

    def test_spinner_default_is_true(self):
        """The default value for --spinner should be True."""
        from cecli.args import get_parser

        parser = get_parser(default_config_files=[], git_root=None)
        args = parser.parse_args([])
        assert args.spinner is True

    def test_spinner_flag_sets_true(self):
        """Passing --spinner explicitly sets spinner to True."""
        from cecli.args import get_parser

        parser = get_parser(default_config_files=[], git_root=None)
        args = parser.parse_args(["--spinner"])
        assert args.spinner is True

    def test_no_spinner_flag_sets_false(self):
        """Passing --no-spinner sets spinner to False."""
        from cecli.args import get_parser

        parser = get_parser(default_config_files=[], git_root=None)
        args = parser.parse_args(["--no-spinner"])
        assert args.spinner is False


class TestIOSpinnerGating:
    """Tests that InputOutput.start_spinner respects show_spinner=False."""

    def test_io_show_spinner_false_disables_fallback_spinner(self):
        """When show_spinner=False, fallback_spinner_enabled is False."""
        from cecli.io import InputOutput

        io = InputOutput(pretty=False, show_spinner=False)
        assert io.fallback_spinner_enabled is False

    def test_io_show_spinner_true_by_default(self):
        """By default, fallback_spinner_enabled is True."""
        from cecli.io import InputOutput

        io = InputOutput(pretty=False)
        assert io.fallback_spinner_enabled is True

    def test_io_start_spinner_noop_when_disabled(self):
        """start_spinner should not create a fallback spinner when show_spinner=False."""
        from cecli.io import InputOutput

        io = InputOutput(pretty=False, show_spinner=False)
        io.start_spinner("Awaiting Confirmation...")
        assert io.fallback_spinner is None
        assert io.spinner_running is False
