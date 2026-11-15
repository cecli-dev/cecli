"""Tests for composer completion parsing."""

import pytest

from cecli.helpers.completion import find_at_mention
from cecli.helpers.server.acp.agent.agent import _complete


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", None),
        ("hello", None),
        ("@", (0, "", False)),
        ("hello @fo", (6, "fo", False)),  # codespell:ignore fo
        ("hello @foo bar", None),
        ('@"my fi', (0, "my fi", True)),
        ('@"my file"', None),
        ('hello @"my fi', (6, "my fi", True)),
        ("first @foo then @bar", (16, "bar", False)),
    ],
)
def test_find_at_mention(text, expected):
    """Mentions end at whitespace, or at the closing quote when quoted."""
    assert find_at_mention(text) == expected


class _FakeFs:
    trie = None

    def search(self, prefix, threshold=0.0):
        return []


class _FakeCoder:
    commands = None

    def __init__(self, root):
        self.root = str(root)
        self.fs = _FakeFs()


def test_complete_replaces_at_mention_from_at_sign(tmp_path):
    """The desktop completion start includes the @ so accepting removes it."""
    (tmp_path / "foo.py").write_text("pass\n", encoding="utf-8")
    coder = _FakeCoder(tmp_path)

    result = _complete(coder, "hello @fo")  # codespell:ignore fo

    assert result["start"] == 6
    assert "foo.py" in result["suggestions"]


def test_complete_stops_at_space_after_at_mention(tmp_path):
    """A space closes an unquoted mention and suppresses @ completions."""
    (tmp_path / "foo.py").write_text("pass\n", encoding="utf-8")
    coder = _FakeCoder(tmp_path)

    assert _complete(coder, "hello @foo ")["suggestions"] == []


def test_complete_stops_at_closing_quote(tmp_path):
    """A closing quote closes a quoted mention and suppresses completions."""
    (tmp_path / "foo.py").write_text("pass\n", encoding="utf-8")
    coder = _FakeCoder(tmp_path)

    assert _complete(coder, 'hello @"foo"')["suggestions"] == []
