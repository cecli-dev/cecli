"""Tests for the cheap git-branch helper and cwd/gitBranch state exposure."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cecli.helpers.server.acp.agent.agent import _git_branch_for  # noqa: E402


def load_server_module():
    """Import desktop/server.py by path without invoking its CLI."""
    spec = importlib.util.spec_from_file_location("desktop_server", ROOT / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GitBranchHelperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_repo(self, name: str = "repo", head: str = "ref: refs/heads/main\n") -> Path:
        repo = self.root / name
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "HEAD").write_text(head, encoding="utf-8")
        return repo

    def test_branch_ref(self) -> None:
        repo = self.make_repo()
        self.assertEqual(_git_branch_for(repo), "main")

    def test_walks_up_from_subdirectory(self) -> None:
        repo = self.make_repo()
        nested = repo / "src" / "pkg"
        nested.mkdir(parents=True)
        self.assertEqual(_git_branch_for(nested), "main")

    def test_detached_head_returns_short_sha(self) -> None:
        repo = self.make_repo(head="0123456789abcdef0123456789abcdef01234567\n")
        self.assertEqual(_git_branch_for(repo), "0123456")

    def test_worktree_gitdir_file(self) -> None:
        repo = self.make_repo(head="ref: refs/heads/worktree-branch\n")
        worktree = self.root / "worktree"
        worktree.mkdir()
        (worktree / ".git").write_text(f"gitdir: {repo / '.git'}\n", encoding="utf-8")
        self.assertEqual(_git_branch_for(worktree), "worktree-branch")

    def test_relative_worktree_gitdir_file(self) -> None:
        self.make_repo(head="ref: refs/heads/relative-branch\n")
        worktree = self.root / "worktree"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: ../repo/.git\n", encoding="utf-8")
        self.assertEqual(_git_branch_for(worktree), "relative-branch")

    def test_non_repo_is_empty(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual(_git_branch_for(plain), "")
        self.assertEqual(_git_branch_for(None), "")
        self.assertEqual(_git_branch_for(""), "")

    def test_unreadable_head_is_empty(self) -> None:
        repo = self.make_repo()
        (repo / ".git" / "HEAD").unlink()
        self.assertEqual(_git_branch_for(repo), "")


class BridgeLocationStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = load_server_module()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.bridge = self.server.AcpBridge(
            cecli="cecli",
            extra_args=[],
            workspace=self.temp_dir.name,
            primary=True,
        )

    def tearDown(self) -> None:
        self.server = None
        self.bridge = None
        self.temp_dir.cleanup()

    def test_snapshot_defaults_to_empty_strings(self) -> None:
        snapshot = self.bridge.snapshot()
        self.assertEqual(snapshot["cwd"], "")
        self.assertEqual(snapshot["gitBranch"], "")

    def test_apply_details_caches_cwd_and_branch(self) -> None:
        self.bridge._apply_details({"ready": True, "cwd": "/home/u/proj", "gitBranch": "main"})
        snapshot = self.bridge.snapshot()
        self.assertEqual(snapshot["cwd"], "/home/u/proj")
        self.assertEqual(snapshot["gitBranch"], "main")

    def test_apply_details_ignores_non_strings(self) -> None:
        self.bridge._apply_details({"ready": True, "cwd": None, "gitBranch": 7})
        snapshot = self.bridge.snapshot()
        self.assertEqual(snapshot["cwd"], "")
        self.assertEqual(snapshot["gitBranch"], "")

    def test_subagent_entries_keep_location_keys(self) -> None:
        self.bridge._apply_details(
            {
                "ready": True,
                "cwd": "/home/u/proj",
                "gitBranch": "main",
                "subagents": [{"sessionId": "child-1", "cwd": "/home/u/wt", "gitBranch": "feat"}],
            }
        )
        child = self.bridge.snapshot()["subagents"][0]
        self.assertEqual(child["cwd"], "/home/u/wt")
        self.assertEqual(child["gitBranch"], "feat")


if __name__ == "__main__":
    unittest.main()
