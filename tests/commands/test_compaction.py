from unittest.mock import AsyncMock, MagicMock

import pytest

# It's better to patch the Coder class where it's used if possible,
# but for this test, we will instantiate it and mock its methods.
from cecli.coders.base_coder import Coder
from cecli.io import InputOutput


@pytest.fixture
def mock_io():
    """Fixture for a mocked InputOutput object."""
    mock = MagicMock(spec=InputOutput)
    # Coder.__init__ reads instance-only attributes (e.g. self.io.pretty) that
    # are not covered by spec=InputOutput, so set them explicitly here.
    mock.pretty = False
    return mock


@pytest.fixture
def mock_model():
    """Fixture for a mocked model object."""
    model = MagicMock()
    model.info = {"max_input_tokens": 10000}
    # Mock the name attribute that is used in Coder.create
    model.name = "mock_model"
    model.edit_format = "whole"
    return model


@pytest.mark.asyncio
async def test_generate_skips_compaction_for_clear_command(mock_io, mock_model):
    """
    Verify that compact_context_if_needed is NOT called for the /clear command.
    """
    # Arrange
    coder = await Coder.create(main_model=mock_model, io=mock_io, edit_format="whole")
    coder.enable_context_compaction = True
    coder.compact_context_if_needed = AsyncMock()
    coder.run_one = AsyncMock()
    user_message = "/clear"

    # Act
    await coder.generate(user_message, preproc=True)

    # Assert
    coder.compact_context_if_needed.assert_not_called()
    coder.run_one.assert_called_once_with(user_message, True)


@pytest.mark.asyncio
async def test_generate_skips_compaction_for_exit_command(mock_io, mock_model):
    """
    Verify that compact_context_if_needed is NOT called for the /exit command.
    """
    # Arrange
    coder = await Coder.create(main_model=mock_model, io=mock_io, edit_format="whole")
    coder.enable_context_compaction = True
    coder.compact_context_if_needed = AsyncMock()
    coder.run_one = AsyncMock()
    user_message = "/exit"

    # Act
    await coder.generate(user_message, preproc=True)

    # Assert
    coder.compact_context_if_needed.assert_not_called()
    coder.run_one.assert_called_once_with(user_message, True)


@pytest.mark.asyncio
async def test_generate_skips_compaction_for_quit_command(mock_io, mock_model):
    """
    Verify that compact_context_if_needed is NOT called for the /quit command.
    """
    # Arrange
    coder = await Coder.create(main_model=mock_model, io=mock_io, edit_format="whole")
    coder.enable_context_compaction = True
    coder.compact_context_if_needed = AsyncMock()
    coder.run_one = AsyncMock()
    user_message = "/quit"

    # Act
    await coder.generate(user_message, preproc=True)

    # Assert
    coder.compact_context_if_needed.assert_not_called()
    coder.run_one.assert_called_once_with(user_message, True)


@pytest.mark.asyncio
async def test_generate_runs_compaction_for_regular_message(mock_io, mock_model):
    """
    Verify that compact_context_if_needed IS called for a regular message.
    """
    # Arrange
    coder = await Coder.create(main_model=mock_model, io=mock_io, edit_format="whole")
    coder.enable_context_compaction = True
    coder.compact_context_if_needed = AsyncMock()
    coder.run_one = AsyncMock()
    user_message = "This is a regular message"

    # Act
    await coder.generate(user_message, preproc=True)

    # Assert
    coder.compact_context_if_needed.assert_called_once()
    coder.run_one.assert_called_once_with(user_message, True)
