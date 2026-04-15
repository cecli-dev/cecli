import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import git

from cecli.helpers.monorepo.workspace import WorkspaceManager
from cecli.io import InputOutput
from cecli.repo import GitRepo


class TestIgnoreLogic(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp()).resolve()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup a dummy source ignore file
        self.src_ignore = self.test_dir / "my_proj.ignore_src"
        self.src_ignore.write_text("ignored_file.txt\n*.log\n")

        self.workspace_name = "test_ws"
        # Use a local path for testing instead of ~/.cecli
        self.workspace_root = (self.test_dir / "workspaces").resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.ws_path = self.workspace_root / self.workspace_name

        self.config = {
            "name": self.workspace_name,
            "projects": [
                {
                    "name": "my_proj",
                    "repo": "https://github.com/example/repo",
                    "ignore": str(self.src_ignore),
                }
            ],
        }

    def tearDown(self):
        os.chdir(self.old_cwd)
        if hasattr(self, "test_dir") and self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_ignore_file_copying(self):
        # Test that WorkspaceManager.initialize copies the ignore file
        wm = WorkspaceManager(self.workspace_name, self.config)
        # Use our test ws_path
        wm.path = self.ws_path

        with patch("cecli.helpers.monorepo.project.Project.initialize"):
            wm.initialize()

        dest_ignore = self.ws_path / "my_proj.ignore"
        self.assertTrue(dest_ignore.exists(), "Ignore file should be copied to workspace root")
        self.assertEqual(dest_ignore.read_text(), self.src_ignore.read_text())

    def test_repo_ignore_loading(self):
        # Test that GitRepo loads the copied ignore file
        wm = WorkspaceManager(self.workspace_name, self.config)
        wm.path = self.ws_path

        with patch("cecli.helpers.monorepo.project.Project.initialize"):
            wm.initialize()

        io = InputOutput()
        # Create a dummy file in the workspace to trigger detection
        dummy_file = self.ws_path / "my_proj" / "main" / "some_file.txt"
        dummy_file.parent.mkdir(parents=True, exist_ok=True)
        dummy_file.touch()

        # Mock git.Repo to avoid FileNotFoundError in GitRepo.__init__
        mock_repo = MagicMock(spec=git.Repo)
        mock_repo.working_dir = str(self.ws_path)
        mock_repo.__enter__.return_value = mock_repo

        # Patch _detect_workspace_path to return our test workspace path
        with patch("git.Repo", return_value=mock_repo):
            with patch("cecli.repo.GitRepo._detect_workspace_path", return_value=self.ws_path):
                with patch("cecli.repo.GitRepo.init_repo"):
                    with patch(
                        "cecli.helpers.monorepo.config.load_workspace_config",
                        return_value=self.config,
                    ):
                        repo = GitRepo(io, fnames=[str(dummy_file)], git_dname=None)

                        self.assertTrue(repo.is_workspace)
                        self.assertEqual(Path(repo.workspace_path), self.ws_path)

                        # Verify ignore spec is loaded
                        repo._refresh_workspace_ignores()
                        self.assertIn("my_proj", repo.workspace_ignore_specs)

                        spec = repo.workspace_ignore_specs["my_proj"]
                        self.assertTrue(spec.match_file("ignored_file.txt"))
                        self.assertTrue(spec.match_file("test.log"))
                        self.assertFalse(spec.match_file("keep.txt"))


if __name__ == "__main__":
    unittest.main()
