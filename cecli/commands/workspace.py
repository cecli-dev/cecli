import subprocess

from cecli.commands.utils.base_command import BaseCommand


class WorkspaceCommand(BaseCommand):
    NORM_NAME = "workspace"
    DESCRIPTION = "Print information about the current workspace"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the workspace command."""
        if not coder or not coder.repo:
            io.tool_output("No repository or workspace active.")
            return

        workspace_path = getattr(coder.repo, "workspace_path", None)
        if not workspace_path:
            io.tool_output("Not currently working within a cecli workspace.")
            return

        import json

        metadata_path = workspace_path / ".cecli-workspace.json"
        config = {}
        if metadata_path.exists():
            try:
                with open(metadata_path, "r") as f:
                    config = json.load(f)
            except Exception:
                pass

        ws_name = config.get("name", workspace_path.name)
        is_active = config.get("active", False)

        io.print(f"Current Workspace: {ws_name}{' (Active)' if is_active else ''}")
        io.print(f"Root Directory:    {workspace_path}")
        io.print("-" * 40)
        io.print("Projects:")

        projects = config.get("projects", [])
        for proj in projects:
            proj_name = proj.get("name")
            if not proj_name:
                continue

            proj_root = workspace_path / proj_name / "main"
            branch_info = "Unknown"
            if proj_root.exists():
                try:
                    branch_info = subprocess.check_output(
                        ["git", "-C", str(proj_root), "rev-parse", "--abbrev-ref", "HEAD"],
                        stderr=subprocess.DEVNULL,
                        encoding="utf-8",
                    ).strip()
                except Exception:
                    branch_info = "Error retrieving branch"

            repo_url = proj.get("repo", "N/A")
            io.print(f"  - {proj_name}:")
            io.print(f"    Branch: {branch_info}")
            io.print(f"    Remote: {repo_url}")
            io.print(f"    Path:   {proj_root}")
            io.print("")

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the workspace command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /workspace  # Show details of the active monorepo workspace\n"
        return help_text
