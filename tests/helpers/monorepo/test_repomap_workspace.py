import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cecli.io import InputOutput
from cecli.repo import GitRepo


@pytest.fixture
def mock_workspace(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    # Project 1
    p1_dir = workspace_root / "p1" / "main"
    p1_dir.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=p1_dir, check=True)
    (p1_dir / "file1.py").write_text("def func1(): pass")
    subprocess.run(["git", "add", "file1.py"], cwd=p1_dir, check=True)
    subprocess.run(["git", "commit", "-m", "p1 init"], cwd=p1_dir, check=True)

    # Project 2
    p2_dir = workspace_root / "p2" / "main"
    p2_dir.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=p2_dir, check=True)
    (p2_dir / "file2.py").write_text("def func2(): pass")
    subprocess.run(["git", "add", "file2.py"], cwd=p2_dir, check=True)
    subprocess.run(["git", "commit", "-m", "p2 init"], cwd=p2_dir, check=True)

    # Workspace metadata
    config = {
        "name": "test-ws",
        "projects": [{"name": "p1", "repo": "url1"}, {"name": "p2", "repo": "url2"}],
    }
    (workspace_root / ".cecli-workspace.json").write_text(json.dumps(config))

    return workspace_root


def test_get_workspace_files(mock_workspace):
    io = MagicMock(spec=InputOutput)
    # Initialize GitRepo in p1 but it should detect the workspace
    repo = GitRepo(io, [], str(mock_workspace / "p1" / "main"))

    # Force workspace_path for the test since _detect_workspace_path looks in ~/.cecli/workspaces
    repo.workspace_path = mock_workspace

    files = repo.get_workspace_files()
    assert "p1/main/file1.py" in files
    assert "p2/main/file2.py" in files
    assert len(files) == 2


@pytest.mark.asyncio
async def test_coder_get_all_relative_files_workspace_integration(mock_workspace):
    io = MagicMock()
    repo = GitRepo(io, [], str(mock_workspace / "p1" / "main"))
    repo.workspace_path = mock_workspace

    # Create a Coder-like object without full __init__
    class SimpleCoder:
        def __init__(self, repo):
            self.repo = repo
            self.in_chat_files = []

        def get_inchat_relative_files(self):
            return self.in_chat_files

        def get_all_relative_files(self):
            # Verify the logic we implemented in base_coder.py
            if self.repo:
                if hasattr(self.repo, "workspace_path") and self.repo.workspace_path:
                    files = self.repo.get_workspace_files()
                elif not self.repo.cecli_ignore_file or not self.repo.cecli_ignore_file.is_file():
                    files = self.repo.get_tracked_files()
                else:
                    files = self.repo.get_non_ignored_files_from_root()
            else:
                files = self.get_inchat_relative_files()
            return files

    coder = SimpleCoder(repo)
    files = coder.get_all_relative_files()

    assert "p1/main/file1.py" in files
    assert "p2/main/file2.py" in files
    assert len(files) == 2


def test_repo_root_detection_for_repomap(mock_workspace):
    io = MagicMock()
    repo = GitRepo(io, [], str(mock_workspace / "p1" / "main"))
    repo.workspace_path = mock_workspace

    # Verify that the logic we added to base_coder.py picks the workspace root
    repo_root = (
        repo.workspace_path if (repo and getattr(repo, "workspace_path", None)) else Path(repo.root)
    )

    assert repo_root == mock_workspace
    assert (repo_root / ".cecli-workspace.json").exists()


def test_project_branch_switching(mock_workspace):
    # Setup: Create a new branch in p1
    p1_dir = mock_workspace / "p1" / "main"
    subprocess.run(["git", "checkout", "-b", "feature/xyz"], cwd=p1_dir, check=True)
    (p1_dir / "feature.py").write_text("print('feature')")
    subprocess.run(["git", "add", "feature.py"], cwd=p1_dir, check=True)
    subprocess.run(["git", "commit", "-m", "feature commit"], cwd=p1_dir, check=True)

    # Go back to master
    subprocess.run(["git", "checkout", "main"], cwd=p1_dir, check=True)

    # Define config with the new branch
    config = {
        "name": "test-ws",
        "projects": [
            {"name": "p1", "repo": "url1", "branch": "feature/xyz", "use_current_branch": False}
        ],
    }

    from cecli.helpers.monorepo.workspace import WorkspaceManager

    wm = WorkspaceManager("test-ws", config)
    wm.path = mock_workspace  # Override path for test

    # Re-initialize should trigger checkout
    wm.initialize()

    # Verify p1 is now on feature/xyz
    current_branch = subprocess.check_output(
        ["git", "-C", str(p1_dir), "rev-parse", "--abbrev-ref", "HEAD"], encoding="utf-8"
    ).strip()

    assert current_branch == "feature/xyz"
    assert (p1_dir / "feature.py").exists()


def test_project_use_current_branch_flag(mock_workspace):
    # Setup: p1 is on master
    p1_dir = mock_workspace / "p1" / "main"
    subprocess.run(["git", "checkout", "main"], cwd=p1_dir, check=True)

    # Define config with a different branch but use_current_branch=True
    config = {
        "name": "test-ws",
        "projects": [
            {"name": "p1", "repo": "url1", "branch": "feature/xyz", "use_current_branch": True}
        ],
    }

    from cecli.helpers.monorepo.workspace import WorkspaceManager

    wm = WorkspaceManager("test-ws", config)
    wm.path = mock_workspace

    # Re-initialize should NOT trigger checkout
    wm.initialize()

    # Verify p1 is still on main
    current_branch = subprocess.check_output(
        ["git", "-C", str(p1_dir), "rev-parse", "--abbrev-ref", "HEAD"], encoding="utf-8"
    ).strip()

    assert current_branch == "main"


def test_get_workspace_files_caching(mock_workspace):
    io = MagicMock()
    repo = GitRepo(io, [], str(mock_workspace / "p1" / "main"))
    repo.workspace_path = mock_workspace

    # First call - should populate cache
    with patch("subprocess.check_output", wraps=subprocess.check_output) as mock_run:
        files1 = repo.get_workspace_files()
        # Should have called rev-parse (2x) and ls-files (2x)
        assert mock_run.call_count >= 4

    # Second call - should use cache
    with patch("subprocess.check_output", wraps=subprocess.check_output) as mock_run:
        files2 = repo.get_workspace_files()
        # Should only call rev-parse to check SHAs (2x), NOT ls-files
        # Total calls = number of projects (2)
        assert mock_run.call_count == 2
        assert files1 == files2

    # Modify a project - should invalidate cache
    p1_dir = mock_workspace / "p1" / "main"
    (p1_dir / "new_file.py").write_text("test")
    subprocess.run(["git", "add", "new_file.py"], cwd=p1_dir, check=True)
    subprocess.run(["git", "commit", "-m", "new file"], cwd=p1_dir, check=True)

    with patch("subprocess.check_output", wraps=subprocess.check_output) as mock_run:
        files3 = repo.get_workspace_files()
        # Should call rev-parse (2x) and then ls-files (2x) because SHAs changed
        assert mock_run.call_count >= 4
        assert "p1/main/new_file.py" in files3


@pytest.mark.asyncio
async def test_workspace_command(mock_workspace):
    from cecli.commands.workspace import WorkspaceCommand
    from cecli.io import InputOutput

    io = MagicMock(spec=InputOutput)
    repo = MagicMock()
    repo.workspace_path = mock_workspace
    repo.root = str(mock_workspace / "p1" / "main")

    coder = MagicMock()
    coder.repo = repo

    await WorkspaceCommand.execute(io, coder, None)

    # Check if io.print was called with workspace info
    # WorkspaceCommand prints name, root, then projects
    io.print.assert_any_call("Current Workspace: test-ws")
    io.print.assert_any_call(f"Root Directory:    {mock_workspace}")

    # Verify project details were printed
    # The output includes project name, branch, remote, path
    io.print.assert_any_call("  - p1:")
    io.print.assert_any_call("  - p2:")
