import os
import tempfile
from pathlib import Path

from cecli.helpers.agents.service import AgentService
from cecli.helpers.workspaces.subagents import register_workspace_subagents
from cecli.utils import make_repo


def _make_git_repo(base: Path, name: str) -> Path:
    root = base / name
    os.makedirs(root, exist_ok=True)
    make_repo(root)
    return root.resolve()


def test_register_workspace_subagents_creates_ws_agents_local():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        app = _make_git_repo(base, "app")
        lib = _make_git_repo(base, "lib")

        config = {
            "name": "ws",
            "projects": [
                {"name": "app", "path": str(app), "primary": True},
                {"name": "lib", "path": str(lib)},
            ],
        }

        registered = register_workspace_subagents(config)
        assert "ws:app" in registered
        assert "ws:lib" in registered

        ws_app = AgentService.get_registry()["ws:app"]
        assert ws_app.name == "ws:app"
        assert ws_app.metadata["root"] == str(app)
        assert ws_app.metadata["agent-config"]["allow_nested_delegation"] is True

        ws_lib = AgentService.get_registry()["ws:lib"]
        assert ws_lib.metadata["root"] == str(lib)
        assert ws_lib.metadata["agent-config"]["allow_nested_delegation"] is True


def test_register_workspace_subagents_clone_root():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        clone_root = _make_git_repo(base, "app/main")

        config = {"name": "ws", "projects": [{"name": "app", "repo": "https://x/r.git"}]}
        registered = register_workspace_subagents(config, workspace_root=base)
        assert "ws:app" in registered

        ws_app = AgentService.get_registry()["ws:app"]
        assert ws_app.metadata["root"] == str(clone_root)
        assert ws_app.metadata["layout"] == "clone"
        assert ws_app.metadata["agent-config"]["allow_nested_delegation"] is True


def test_register_workspace_subagents_project_metadata_frontmatter():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        app = _make_git_repo(base, "app")

        config = {
            "name": "ws",
            "projects": [
                {
                    "name": "app",
                    "path": str(app),
                    "metadata": {
                        "model": "<weak_model>",
                        "auto_reap": False,
                        "name": "hijack",
                        "root": "/somewhere/else",
                        "description": "Custom ws agent",
                        "tools_includelist": ["readfile", "grep", "yield"],
                    },
                }
            ],
        }

        registered = register_workspace_subagents(config)
        assert "ws:app" in registered

        ws_app = AgentService.get_registry()["ws:app"]
        assert ws_app.name == "ws:app"
        assert ws_app.model == "<weak_model>"
        assert ws_app.auto_reap is False
        # ``root``, ``name`` and ``description`` are always derived from the
        # workspace/project definition and cannot be overridden by ``metadata``.
        assert ws_app.metadata["root"] == str(app)
        assert ws_app.metadata.get("name") != "hijack"
        assert ws_app.metadata["description"].startswith("Workspace sub-agent for project 'app'")
        assert ws_app.metadata["tools_includelist"] == ["readfile", "grep", "yield"]
        assert ws_app.metadata["agent-config"]["allow_nested_delegation"] is True


def test_register_workspace_subagents_skips_non_git_project():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        plain = base / "plain"
        os.makedirs(plain, exist_ok=True)
        config = {"name": "ws", "projects": [{"name": "plain", "path": str(plain)}]}
        registered = register_workspace_subagents(config)
        assert registered == []
