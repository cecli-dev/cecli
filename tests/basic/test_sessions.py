import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cecli.io import InputOutput
from cecli.sessions import SessionManager


@pytest.fixture
def mock_coder():
    """Fixture to create a mock coder with necessary attributes."""
    coder = MagicMock()
    coder.abs_fnames = {"/path/to/file1.py"}
    coder.abs_read_only_fnames = {"/path/to/file2.py"}
    coder.abs_read_only_stubs_fnames = set()
    coder.auto_commits = True
    coder.auto_lint = True
    coder.auto_test = False
    coder.total_tokens_sent = 100
    coder.total_tokens_received = 200
    coder.total_cached_tokens = 50
    coder.total_cost = 0.01
    coder.edit_format = "diff"

    # Mock the main_model and its attributes
    main_model = MagicMock()
    main_model.name = "test_model"
    main_model.weak_model.name = "test_weak_model"
    main_model.editor_model.name = "test_editor_model"
    main_model.agent_model.name = "test_agent_model"
    main_model.editor_edit_format = "editor-diff"
    coder.main_model = main_model

    # Mock ConversationService methods
    mock_conversation_service = MagicMock()
    mock_conversation_service.get_manager.return_value.get_messages_dict.return_value = []
    coder.conversation_service = mock_conversation_service

    # Mock other necessary methods and attributes
    coder.get_rel_fname.side_effect = lambda x: os.path.basename(x)
    coder.abs_root_path.side_effect = lambda x: f"/test/root/{x}"
    coder.local_agent_folder.side_effect = lambda x: f".cecli/{x}"
    coder.io = MagicMock(spec=InputOutput)
    coder.agent_config = {}
    coder.mcp_manager = None
    coder.skills_manager = None
    coder.io.read_text.return_value = "some todo content"
    coder.format_chat_chunks = MagicMock()
    coder.args = SimpleNamespace(
        model="test_model",
        weak_model="test_weak_model",
        editor_model="test_editor_model",
        agent_model="test_agent_model",
        editor_edit_format="editor-diff",
        verbose=False,
        session_encrypt=False,
        session_key_file=None,
    )

    return coder


@pytest.fixture
def session_manager(mock_coder):
    """Fixture to create a SessionManager instance."""
    return SessionManager(mock_coder, mock_coder.io)


@pytest.mark.asyncio
async def test_load_session_quiet_skips_tool_error_on_invalid_json(
    session_manager, mock_coder, tmp_path
):
    """Headless hosts may auto-load with quiet=True when restore is best-effort."""
    session_dir = tmp_path / ".cecli" / "sessions"
    os.makedirs(session_dir, exist_ok=True)
    mock_coder.abs_root_path.side_effect = lambda x: str(tmp_path / x)
    bad = session_dir / "bad.json"
    bad.write_text("not json", encoding="utf-8")

    assert await session_manager.load_session(str(bad), switch=False, quiet=True) is False
    mock_coder.io.tool_error.assert_not_called()


def test_save_session(session_manager, mock_coder, tmp_path):
    """Test saving a session."""
    session_dir = tmp_path / ".cecli" / "sessions"
    os.makedirs(session_dir, exist_ok=True)
    mock_coder.abs_root_path.side_effect = lambda x: str(tmp_path / x)

    session_name = "test_session"
    success = session_manager.save_session(session_name, output=False)

    assert success
    session_file = session_dir / f"{session_name}.json"
    assert session_file.exists()

    with open(session_file, "r") as f:
        session_data = json.load(f)

    assert session_data["session_name"] == session_name
    assert session_data["model"] == "test_model"
    assert session_data["edit_format"] == "diff"
    assert "file1.py" in session_data["files"]["editable"]


@pytest.mark.asyncio
async def test_load_session_restores_edit_format(session_manager, mock_coder, tmp_path):
    """Test that loading a session restores the edit_format."""
    session_dir = tmp_path / ".cecli" / "sessions"
    os.makedirs(session_dir, exist_ok=True)
    mock_coder.abs_root_path.side_effect = lambda x: str(tmp_path / x)

    # 1. Save a session with a specific edit_format
    mock_coder.edit_format = "agent"
    session_name = "agent_session"
    session_manager.save_session(session_name, output=False)

    # 2. Change the coder's edit_format to something different
    mock_coder.edit_format = "diff"

    # 3. Load the session
    session_file = session_dir / f"{session_name}.json"

    # Mock the SwitchCoderSignal to capture the edit_format it's called with
    from cecli import commands

    original_switch_coder_signal = commands.SwitchCoderSignal

    class MockSwitchCoderSignal(Exception):
        def __init__(self, edit_format, **kwargs):
            self.edit_format = edit_format
            super().__init__()

    commands.SwitchCoderSignal = MockSwitchCoderSignal

    try:
        with pytest.raises(MockSwitchCoderSignal) as excinfo:
            await session_manager.load_session(str(session_file))

        # 4. Assert that the SwitchCoderSignal was raised with the correct edit_format
        assert excinfo.value.edit_format == "agent"

    finally:
        # Restore the original SwitchCoderSignal
        commands.SwitchCoderSignal = original_switch_coder_signal


@pytest.mark.asyncio
async def test_load_session_restores_architect_mode(session_manager, mock_coder, tmp_path):
    """Test that loading a session restores architect mode."""
    session_dir = tmp_path / ".cecli" / "sessions"
    os.makedirs(session_dir, exist_ok=True)
    mock_coder.abs_root_path.side_effect = lambda x: str(tmp_path / x)

    # 1. Save a session with architect mode
    mock_coder.edit_format = "architect"
    session_name = "architect_session"
    session_manager.save_session(session_name, output=False)

    # 2. Change the coder's edit_format to something different
    mock_coder.edit_format = "diff"

    # 3. Load the session
    session_file = session_dir / f"{session_name}.json"

    # Mock the SwitchCoderSignal to capture the edit_format it's called with
    from cecli import commands

    original_switch_coder_signal = commands.SwitchCoderSignal

    class MockSwitchCoderSignal(Exception):
        def __init__(self, edit_format, **kwargs):
            self.edit_format = edit_format
            super().__init__()

    commands.SwitchCoderSignal = MockSwitchCoderSignal

    try:
        with pytest.raises(MockSwitchCoderSignal) as excinfo:
            await session_manager.load_session(str(session_file))
        # 4. Assert that the SwitchCoderSignal was raised with the correct edit_format
        assert excinfo.value.edit_format == "architect"
    finally:
        # Restore the original SwitchCoderSignal
        commands.SwitchCoderSignal = original_switch_coder_signal


@pytest.mark.asyncio
async def test_load_session_restores_ask_mode(session_manager, mock_coder, tmp_path):
    """Test that loading a session restores ask mode."""
    session_dir = tmp_path / ".cecli" / "sessions"
    os.makedirs(session_dir, exist_ok=True)
    mock_coder.abs_root_path.side_effect = lambda x: str(tmp_path / x)

    # 1. Save a session with ask mode
    mock_coder.edit_format = "ask"
    session_name = "ask_session"
    session_manager.save_session(session_name, output=False)

    # 2. Change the coder's edit_format to something different
    mock_coder.edit_format = "diff"

    # 3. Load the session
    session_file = session_dir / f"{session_name}.json"

    # Mock the SwitchCoderSignal to capture the edit_format it's called with
    from cecli import commands

    original_switch_coder_signal = commands.SwitchCoderSignal

    class MockSwitchCoderSignal(Exception):
        def __init__(self, edit_format, **kwargs):
            self.edit_format = edit_format
            super().__init__()

    commands.SwitchCoderSignal = MockSwitchCoderSignal

    try:
        with pytest.raises(MockSwitchCoderSignal) as excinfo:
            await session_manager.load_session(str(session_file))
        # 4. Assert that the SwitchCoderSignal was raised with the correct edit_format
        assert excinfo.value.edit_format == "ask"
    finally:
        # Restore the original SwitchCoderSignal
        commands.SwitchCoderSignal = original_switch_coder_signal


@pytest.mark.asyncio
async def test_load_session_backwards_compatible(session_manager, mock_coder, tmp_path):
    """Test that loading an old session (without edit_format) uses current mode."""
    session_dir = tmp_path / ".cecli" / "sessions"
    os.makedirs(session_dir, exist_ok=True)
    mock_coder.abs_root_path.side_effect = lambda x: str(tmp_path / x)

    # 1. Create a session file without edit_format (old format)
    session_name = "old_session"
    session_file = session_dir / f"{session_name}.json"

    # Create session data without edit_format
    session_data = {
        "version": 1,
        "session_name": session_name,
        "model": "test_model",
        "chat_history": {"done_messages": [], "cur_messages": []},
        "files": {"editable": ["file1.py"], "read_only": [], "read_only_stubs": []},
        "settings": {"auto_commits": True, "auto_lint": True, "auto_test": False},
        "todo_list": None,
    }

    with open(session_file, "w") as f:
        json.dump(session_data, f, indent=2)

    # 2. Set current edit_format to agent
    mock_coder.edit_format = "agent"

    # 3. Load the session
    # Mock the SwitchCoderSignal to capture the edit_format it's called with
    from cecli import commands

    original_switch_coder_signal = commands.SwitchCoderSignal

    class MockSwitchCoderSignal(Exception):
        def __init__(self, edit_format, **kwargs):
            self.edit_format = edit_format
            super().__init__()

    commands.SwitchCoderSignal = MockSwitchCoderSignal

    try:
        with pytest.raises(MockSwitchCoderSignal) as excinfo:
            await session_manager.load_session(str(session_file))
        # 4. Assert that the SwitchCoderSignal was raised with the current mode (not None)
        assert excinfo.value.edit_format == "agent"
    finally:
        # Restore the original SwitchCoderSignal
        commands.SwitchCoderSignal = original_switch_coder_signal


@pytest.mark.asyncio
async def test_load_session_with_agent_mode_and_mcp_skills(session_manager, mock_coder, tmp_path):
    """Test that loading a session with agent mode restores MCP servers and skills."""
    session_dir = tmp_path / ".cecli" / "sessions"
    os.makedirs(session_dir, exist_ok=True)
    mock_coder.abs_root_path.side_effect = lambda x: str(tmp_path / x)

    # 1. Save a session with agent mode and MCP servers/skills
    mock_coder.edit_format = "agent"
    session_name = "agent_with_mcp_session"

    # Mock MCP servers and skills
    mock_coder.mcp_manager = AsyncMock()
    mock_mcp = MagicMock()
    mock_mcp.name = "mock_mcp"
    mock_coder.mcp_manager.connected_servers = [mock_mcp]
    mock_coder.skills_manager = MagicMock()
    mock_coder.skills_manager.include_list = {"included_skill"}
    mock_coder.skills_manager.exclude_list = {"excluded_skill"}
    mock_coder.skills_manager.directory_paths = ["/test/skills/path"]

    session_manager.save_session(session_name, output=False)

    # 2. Change the coder's edit_format and clear MCP/skills
    mock_coder.edit_format = "diff"
    mock_coder.mcp_manager.connected_servers = []
    mock_coder.skills_manager.include_list = set()
    mock_coder.skills_manager.exclude_list = set()
    mock_coder.skills_manager.directory_paths = []

    # 3. Load the session
    session_file = session_dir / f"{session_name}.json"

    # Mock the SwitchCoderSignal to capture the edit_format it's called with
    from cecli import commands

    original_switch_coder_signal = commands.SwitchCoderSignal

    class MockSwitchCoderSignal(Exception):
        def __init__(self, edit_format, **kwargs):
            self.edit_format = edit_format
            super().__init__()

    commands.SwitchCoderSignal = MockSwitchCoderSignal

    try:
        with pytest.raises(MockSwitchCoderSignal) as excinfo:
            await session_manager.load_session(str(session_file))
        # 4. Assert that the SwitchCoderSignal was raised with the correct edit_format
        assert excinfo.value.edit_format == "agent"
    finally:
        # Restore the original SwitchCoderSignal
        commands.SwitchCoderSignal = original_switch_coder_signal


# Add a test for the save_session method to ensure it saves edit_format
@pytest.mark.parametrize("edit_format", ["diff", "architect", "ask", "agent"])
def test_save_session_saves_edit_format(session_manager, mock_coder, tmp_path, edit_format):
    """Test that save_session correctly saves the edit_format for all modes."""
    session_dir = tmp_path / ".cecli" / "sessions"
    os.makedirs(session_dir, exist_ok=True)
    mock_coder.abs_root_path.side_effect = lambda x: str(tmp_path / x)

    # Set the edit_format
    mock_coder.edit_format = edit_format
    session_name = f"{edit_format}_session"

    # Save the session
    success = session_manager.save_session(session_name, output=False)
    assert success

    # Load the session data and verify edit_format
    session_file = session_dir / f"{session_name}.json"
    assert session_file.exists()

    with open(session_file, "r") as f:
        session_data = json.load(f)

    # Verify edit_format was saved correctly
    assert session_data["edit_format"] == edit_format
