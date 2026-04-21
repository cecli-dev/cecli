"""Tests for the --spinner / --no-spinner CLI option."""

from unittest.mock import MagicMock, patch

import pytest

from cecli.repo import GitRepo


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
    model.send_completion = MagicMock(return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="test commit"))]))
    return model


class TestSpinnerOption:
    """Tests that show_spinner controls whether the spinner is started."""

    def test_spinner_enabled_by_default(self, mock_io, mock_model):
        """GitRepo defaults to show_spinner=True."""
        repo = GitRepo(mock_io, models=[mock_model], fnames=[])
        assert repo.show_spinner is True

    def test_spinner_disabled_when_false(self, mock_io, mock_model):
        """GitRepo respects show_spinner=False."""
        repo = GitRepo(mock_io, models=[mock_model], fnames=[], show_spinner=False)
        assert repo.show_spinner is False

    def test_spinner_started_during_commit_message(self, mock_io, mock_model):
        """When show_spinner=True, start_spinner is called during get_commit_message."""
        repo = GitRepo(mock_io, models=[mock_model], fnames=[], show_spinner=True)
        repo.get_commit_message("some diff", "some context")
        mock_io.start_spinner.assert_called()

    def test_spinner_not_started_when_disabled(self, mock_io, mock_model):
        """When show_spinner=False, start_spinner is never called during get_commit_message."""
        repo = GitRepo(mock_io, models=[mock_model], fnames=[], show_spinner=False)
        repo.get_commit_message("some diff", "some context")
        mock_io.start_spinner.assert_not_called()


class TestSpinnerArgParsing:
    """Tests that argparse correctly handles --spinner / --no-spinner."""

    def test_spinner_default_is_true(self):
        """The default value for --spinner should be True."""
        from cecli.args import get_parser

        parser = get_parser()
        args = parser.parse_args([])
        assert args.spinner is True

    def test_spinner_flag_sets_true(self):
        """Passing --spinner explicitly sets spinner to True."""
        from cecli.args import get_parser

        parser = get_parser()
        args = parser.parse_args(["--spinner"])
        assert args.spinner is True

    def test_no_spinner_flag_sets_false(self):
        """Passing --no-spinner sets spinner to False."""
        from cecli.args import get_parser

        parser = get_parser()
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
