"""Tests for the /search-memory command."""

from unittest.mock import MagicMock, patch

import pytest

from cecli.commands.search_memory import SearchMemoryCommand


@pytest.fixture
def mock_coder():
    return MagicMock()


@pytest.fixture
def mock_io():
    return MagicMock()


@pytest.fixture
def sample_results():
    return [
        {
            "id_fact": 1,
            "fact": "alpha beta gamma",
            "date": "2026-01-01",
            "tags": ["memory"],
        },
        {
            "id_fact": 2,
            "fact": "delta epsilon",
            "date": "2026-01-02",
            "tags": [],
        },
    ]


class TestSearchMemoryCommand:
    @pytest.mark.asyncio
    async def test_execute_no_words_shows_usage(self, mock_coder, mock_io):
        """No search terms prints usage."""
        result = await SearchMemoryCommand.execute(mock_io, mock_coder, "   ")

        mock_io.tool_error.assert_any_call("Usage: /search-memory <word> [<word> ...]")
        assert result == "Successfully executed search-memory."

    @pytest.mark.asyncio
    async def test_execute_returns_matching_facts(self, mock_coder, mock_io, sample_results):
        """Matching facts are printed with id, category and text."""
        with patch(
            "cecli.helpers.memory.utils.search_facts", return_value=sample_results
        ) as mock_search:
            result = await SearchMemoryCommand.execute(mock_io, mock_coder, "alpha beta")

        mock_search.assert_called_once_with(mock_coder, words=["alpha", "beta"])
        mock_io.tool_output.assert_any_call("Found 2 fact(s) matching: alpha beta")
        mock_io.tool_output.assert_any_call("[1] (memory)\nalpha beta gamma\n")
        mock_io.tool_output.assert_any_call("[2] ((uncategorized))\ndelta epsilon\n")
        assert result == "Successfully executed search-memory."

    @pytest.mark.asyncio
    async def test_execute_no_matches(self, mock_coder, mock_io):
        """No matches prints a 'no facts found' message."""
        with patch("cecli.helpers.memory.utils.search_facts", return_value=[]):
            result = await SearchMemoryCommand.execute(mock_io, mock_coder, "zzz")

        mock_io.tool_output.assert_any_call("No facts found matching: zzz")
        assert result == "Successfully executed search-memory."

    @pytest.mark.asyncio
    async def test_execute_search_failure(self, mock_coder, mock_io):
        """A failing search reports the error."""
        with patch("cecli.helpers.memory.utils.search_facts", side_effect=Exception("boom")):
            result = await SearchMemoryCommand.execute(mock_io, mock_coder, "alpha")

        mock_io.tool_error.assert_any_call("Error in search-memory: boom")
        assert result == "Error: boom"

    def test_get_completions(self, mock_coder, mock_io):
        """No completions are offered for search-memory."""
        assert SearchMemoryCommand.get_completions(mock_io, mock_coder, "al") == []

    def test_get_help(self):
        """Help text documents usage."""
        help_text = SearchMemoryCommand.get_help()

        assert "/search-memory" in help_text
        assert "preferences" in help_text
