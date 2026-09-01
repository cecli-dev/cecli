"""Workspace manager supporting clone and local layouts.

- **clone** — projects with a ``repo:`` URL are cloned under
  ``~/.cecli/workspaces/{name}/{project}/main``; the working directory is the
  workspace root.
- **local** — projects point at existing on-disk git roots via ``path:``; the
  working directory is the primary project's git root.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from .config import workspace_layout
from .paths import primary_project, project_path


class WorkspaceManager:
    def __init__(
        self,
        workspace_name: str,
        config: Dict[str, Any],
        root: Optional[Path | str] = None,
    ):
        self.name = workspace_name
        self.config = config
        self.layout = workspace_layout(config)

        if self.layout == "clone":
            self.path = Path(os.path.expanduser(f"~/.cecli/workspaces/{workspace_name}"))
        elif root is not None:
            self.path = Path(root).resolve()
        else:
            primary = primary_project(config)
            self.path = (
                Path(str(primary["path"])).expanduser().resolve()
                if primary and primary.get("path")
                else Path.cwd().resolve()
            )
        self.root = self.path

    def exists(self) -> bool:
        """Check whether the workspace root directory exists."""
        return self.path.exists()

    def initialize(self) -> None:
        """Create the workspace root, clone ``repo:`` projects, and write metadata."""
        self.path.mkdir(parents=True, exist_ok=True)

        if self.layout == "clone":
            for proj in self.config.get("projects") or []:
                if proj.get("repo"):
                    self._clone_project(self.path, proj)

        from .paths import write_workspace_metadata

        write_workspace_metadata(self.path, self.config)

    def get_working_directory(self) -> Path:
        """Return the workspace root (clone) or the primary project's git root (local)."""
        if self.layout == "clone":
            return self.path
        primary = primary_project(self.config)
        if primary:
            root = project_path(self.path, primary, layout="local")
            if root:
                return root
        return self.path

    def _clone_project(self, workspace_root: Path, project: Dict[str, Any]) -> None:
        """Clone a ``repo:`` project under ``{workspace_root}/{name}/main``."""
        name = project.get("name")
        repo_url = project.get("repo")
        if not name or not repo_url:
            return

        main_path = workspace_root / name / "main"
        if main_path.exists():
            return
        main_path.mkdir(parents=True, exist_ok=True)

        target_branch = project.get("branch")
        use_current = project.get("use_current_branch", True)

        clone_cmd = ["git", "clone", "--depth", "1"]
        if target_branch and not use_current:
            clone_cmd += ["--branch", target_branch]
        clone_cmd += [repo_url, str(main_path)]

        subprocess.run(clone_cmd, check=True)

        ignore_file = project.get("ignore")
        if ignore_file:
            ignore_path = Path(ignore_file).expanduser()
            if ignore_path.exists():
                shutil.copy2(ignore_path, workspace_root / f"{name}.ignore")
