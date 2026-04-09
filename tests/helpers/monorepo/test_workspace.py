import json
from unittest.mock import patch

import pytest

from cecli.helpers.monorepo.workspace import WorkspaceManager


@pytest.fixture
def temp_workspace_root(tmp_path):
    workspace_root = tmp_path / ".cecli" / "workspaces"
    workspace_root.mkdir(parents=True)

    def mock_expand(path):
        if path.startswith("~/.cecli/workspaces"):
            return str(workspace_root / path.replace("~/.cecli/workspaces", "").lstrip("/"))
        return path

    with patch("os.path.expanduser", side_effect=mock_expand):
        yield workspace_root


def test_workspace_manager_exists(temp_workspace_root):
    config = {"name": "test-ws", "projects": []}
    wm = WorkspaceManager("test-ws", config)
    assert not wm.exists()

    wm.path.mkdir(parents=True)
    assert wm.exists()


@patch("cecli.helpers.monorepo.project.Project.initialize")
def test_workspace_manager_initialize(mock_proj_init, temp_workspace_root):
    config = {
        "name": "test-ws",
        "projects": [{"name": "p1", "repo": "url1"}, {"name": "p2", "repo": "url2"}],
    }
    wm = WorkspaceManager("test-ws", config)
    wm.initialize()

    assert wm.exists()
    assert (wm.path / ".cecli-workspace.json").exists()
    assert mock_proj_init.call_count == 2

    with open(wm.path / ".cecli-workspace.json", "r") as f:
        saved_config = json.load(f)
        assert saved_config["name"] == "test-ws"


def test_workspace_manager_get_working_directory(temp_workspace_root):
    wm = WorkspaceManager("test-ws", {})
    assert wm.get_working_directory() == temp_workspace_root / "test-ws"
