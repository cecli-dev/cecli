import os
from pathlib import Path
from typing import Any, Dict

from cecli.helpers.monorepo.project import Project


class WorkspaceManager:
    def __init__(self, workspace_name: str, config: Dict[str, Any]):
        self.name = workspace_name
        self.config = config
        self.path = Path(os.path.expanduser(f"~/.cecli/workspaces/{workspace_name}"))

    def exists(self) -> bool:
        """Check if workspace directory exists"""
        return self.path.exists()

    def initialize(self) -> None:
        """Create workspace structure and clone repositories"""
        self.path.mkdir(parents=True, exist_ok=True)

        projects_config = self.config.get("projects", [])
        for proj_cfg in projects_config:
            project = Project(self.path, proj_cfg)
            project.initialize()

        # Copy ignore files to workspace root
        for proj_cfg in projects_config:
            ignore_file = proj_cfg.get("ignore")
            if ignore_file:
                ignore_path = Path(ignore_file).expanduser()
                if ignore_path.exists():
                    import shutil

                    dest_path = self.path / f"{proj_cfg['name']}.ignore"
                    shutil.copy2(ignore_path, dest_path)

        # Write metadata
        import json

        metadata_path = self.path / ".cecli-workspace.json"
        with open(metadata_path, "w") as f:
            json.dump(self.config, f, indent=2)

    def get_working_directory(self) -> Path:
        """Return workspace root path for cd"""
        return self.path
