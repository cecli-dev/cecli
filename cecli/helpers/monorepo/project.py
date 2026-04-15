import subprocess
from pathlib import Path
from typing import Any, Dict

from cecli.helpers.monorepo.worktree import WorktreeManager


class Project:
    def __init__(self, workspace_path: Path, config: Dict[str, Any]):
        self.workspace_path = workspace_path
        self.config = config
        self.name = config["name"]
        self.repo_url = config["repo"]
        self.ignore_file = config.get("ignore")
        self.base_path = workspace_path / self.name
        self.main_path = self.base_path / "main"

    def initialize(self) -> None:
        """Clone the repository and setup worktrees."""
        if not self.main_path.exists():
            self.main_path.mkdir(parents=True, exist_ok=True)

            target_branch = self.config.get("branch")
            use_current = self.config.get("use_current_branch", True)

            clone_cmd = ["git", "clone", "--depth", "1"]
            if target_branch and not use_current:
                clone_cmd += ["--branch", target_branch]

            clone_cmd += [self.repo_url, str(self.main_path)]

            subprocess.run(clone_cmd, check=True)

        # Ensure correct branch is checked out
        target_branch = self.config.get("branch")
        use_current = self.config.get("use_current_branch", True)

        if target_branch and not use_current:
            try:
                # Check current branch
                current_branch = subprocess.check_output(
                    ["git", "-C", str(self.main_path), "rev-parse", "--abbrev-ref", "HEAD"],
                    encoding="utf-8",
                ).strip()

                if current_branch != target_branch:
                    # Try to checkout directly
                    res = subprocess.run(
                        ["git", "-C", str(self.main_path), "checkout", target_branch],
                        check=False,
                        capture_output=True,
                    )

                    if res.returncode != 0:
                        # If checkout fails, check if it exists on origin
                        subprocess.run(
                            ["git", "-C", str(self.main_path), "fetch", "origin", target_branch],
                            check=False,
                        )

                        # Try checking out the remote branch
                        res = subprocess.run(
                            [
                                "git",
                                "-C",
                                str(self.main_path),
                                "checkout",
                                "-b",
                                target_branch,
                                f"origin/{target_branch}",
                            ],
                            check=False,
                            capture_output=True,
                        )

                        if res.returncode != 0:
                            # If it still fails, it doesn't exist on origin, so create it locally
                            subprocess.run(
                                ["git", "-C", str(self.main_path), "checkout", "-b", target_branch],
                                check=True,
                            )
            except Exception:
                # Fallback for unexpected errors
                pass
        # Handle worktrees
        worktrees_config = self.config.get("worktrees", [])
        if worktrees_config:
            wt_manager = WorktreeManager(self.main_path)
            for wt_cfg in worktrees_config:
                wt_manager.create(wt_cfg["name"], wt_cfg["branch"])
