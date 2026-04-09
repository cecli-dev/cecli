import subprocess
from pathlib import Path


class WorktreeManager:
    def __init__(self, main_repo_path: Path):
        self.main_repo_path = main_repo_path
        self.worktrees_dir = main_repo_path.parent / "worktrees"

    def create(self, name: str, branch: str) -> None:
        """Create a git worktree."""
        wt_path = self.worktrees_dir / name
        if wt_path.exists():
            return

        self.worktrees_dir.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            ["git", "-C", str(self.main_repo_path), "worktree", "add", str(wt_path), branch],
            check=True,
        )
