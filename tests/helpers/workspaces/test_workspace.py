import os
import tempfile
from pathlib import Path

from cecli.helpers.workspaces.workspace import WorkspaceManager
from cecli.utils import make_repo


def _make_git_repo(base: Path, name: str) -> Path:
    root = base / name
    os.makedirs(root, exist_ok=True)
    make_repo(root)
    return root.resolve()


def test_get_working_directory_returns_primary_project():
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

        manager = WorkspaceManager("ws", config, root=base)
        assert manager.path == base.resolve()
        assert manager.get_working_directory() == app


def test_default_root_falls_back_to_primary_project():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        app = _make_git_repo(base, "app")
        config = {"name": "ws", "projects": [{"name": "app", "path": str(app), "primary": True}]}

        manager = WorkspaceManager("ws", config)
        assert manager.path == app


def test_exists_and_initialize_local():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        manager = WorkspaceManager("ws", {"name": "ws", "projects": []}, root=base)
        manager.initialize()
        assert manager.exists()
        assert (base / ".cecli" / ".workspace-meta.json").is_file()


def test_clone_workspace_uses_cecli_workspaces_dir():
    config = {"name": "my-ws", "projects": [{"name": "app", "repo": "https://x/r.git"}]}
    manager = WorkspaceManager("my-ws", config)
    assert manager.layout == "clone"
    assert manager.path == Path(os.path.expanduser("~/.cecli/workspaces/my-ws"))
    assert manager.get_working_directory() == manager.path
