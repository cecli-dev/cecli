"""Tests for @-mention completion in the TUI."""

from cecli.tui.app import TUI


def test_mention_completion_replaces_at_sign():
    """Accepting a mention completion removes the @ rather than leaving it behind."""
    result = TUI._get_completed_text(None, "hello @fo", "foo.py")  # codespell:ignore fo

    assert result == "hello foo.py "


def test_quoted_mention_completion_stays_quoted():
    """Quoted mentions keep their quoting when completed."""
    assert TUI._get_completed_text(None, 'hello @"my fi', "my file.py") == ('hello @"my file.py" ')
