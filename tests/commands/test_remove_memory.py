"""Tests for the /remove-memory command."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cecli.commands.remove_memory import RemoveMemoryCommand


@pytest.fixture
def mock_coder():
    return MagicMock()


@pytest.fixture
def mock_io():
    return MagicMock()


class TestRemoveMemoryCommand:
    @pytest.mark.asyncio
    async def test_execute_parses_ids_with_any_separators(self, mock_coder, mock_io):
        """Continuous numbers are parsed into fact ids regardless of separators."""
        with patch("cecli.helpers.memory.utils.remove_facts", return_value=3) as mock_remove:
            result = await RemoveMemoryCommand.execute(mock_io, mock_coder, "1,2,3 7 10,30")

        mock_remove.assert_called_once_with(mock_coder, id_facts=[1, 2, 3, 7, 10, 30])
        mock_io.tool_output.assert_any_call("Removed 3 fact(s): 1, 2, 3, 7, 10, 30")
        assert result == "Successfully executed remove-memory."

    @pytest.mark.asyncio
    async def test_execute_single_id(self, mock_coder, mock_io):
        """A single id is handled."""
        with patch("cecli.helpers.memory.utils.remove_facts", return_value=1) as mock_remove:
            result = await RemoveMemoryCommand.execute(mock_io, mock_coder, "42")

        mock_remove.assert_called_once_with(mock_coder, id_facts=[42])
        assert result == "Successfully executed remove-memory."

    @pytest.mark.asyncio
    async def test_execute_no_ids_shows_usage(self, mock_coder, mock_io):
        """No numeric ids prints usage."""
        result = await RemoveMemoryCommand.execute(mock_io, mock_coder, "abc, def!")

        mock_io.tool_error.assert_any_call("Usage: /remove-memory <id> [<id> ...]")
        assert result == "Successfully executed remove-memory."

    @pytest.mark.asyncio
    async def test_execute_remove_failure(self, mock_coder, mock_io):
        """A failing removal reports the error."""
        with patch("cecli.helpers.memory.utils.remove_facts", side_effect=Exception("boom")):
            result = await RemoveMemoryCommand.execute(mock_io, mock_coder, "1,2")

        mock_io.tool_error.assert_any_call("Error in remove-memory: boom")
        assert result == "Error: boom"

    def test_get_completions(self, mock_coder, mock_io):
        """No completions are offered for remove-memory."""
        assert RemoveMemoryCommand.get_completions(mock_io, mock_coder, "1") == []

    def test_get_help(self):
        """Help text documents usage."""
        help_text = RemoveMemoryCommand.get_help()

        assert "/remove-memory" in help_text
        assert "1,2,3 7 10,30" in help_text


class TestRemoveMemoryCommandIntegration:
    """End-to-end checks against a real temporary SQLite memory database."""

    @pytest.fixture(autouse=True)
    def _fresh_db_state(self, tmp_path):
        """Point the memory DB at a temp root and reset cached connection state."""
        import cecli.helpers.memory.db as memory_db

        memory_db._INIT_COMPLETED = False
        memory_db._local.conn = None

        self.root = tmp_path

        yield

        memory_db._local.conn = None

    @pytest.mark.asyncio
    async def test_execute_removes_facts_from_db(self):
        """Facts added to a real DB are deleted by the command."""
        from cecli.helpers.memory.db import _get_connection
        from cecli.helpers.memory.utils import add_fact

        coder = SimpleNamespace(root=self.root)
        io = MagicMock()

        id_1 = add_fact(coder, fact="keep me", tags=["a"])
        id_2 = add_fact(coder, fact="delete me", tags=["b"])
        id_3 = add_fact(coder, fact="also delete", tags=["c"])

        result = await RemoveMemoryCommand.execute(io, coder, f"{id_1},{id_3} {id_2}")

        conn = _get_connection(root=self.root)
        remaining = conn.execute("SELECT COUNT(*) AS n FROM Facts").fetchone()["n"]
        remaining_tags = conn.execute("SELECT COUNT(*) AS n FROM FactTags").fetchone()["n"]

        assert remaining == 0
        assert remaining_tags == 0
        assert result == "Successfully executed remove-memory."
