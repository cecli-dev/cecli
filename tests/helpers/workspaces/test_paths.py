import os
import subprocess
import tempfile
from pathlib import Path

from cecli.helpers.workspaces.paths import (
    project_path,
    resolve_workspace_file_path,
    union_tracked_files,
)
from cecli.utils import make_repo


def _make_git_repo(base: Path, name: str, files=None) -> Path:
    root = base / name
    os.makedirs(root, exist_ok=True)
    make_repo(root)
    if files:
        for rel in files:
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(rel, encoding="utf-8")
            subprocess.check_call(["git", "-C", str(root), "add", rel])
    return root.resolve()


def test_project_path_returns_git_root_local():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        root = _make_git_repo(base, "app")
        assert project_path(Path("."), {"name": "app", "path": str(root)}, layout="local") == root


def test_project_path_clone_returns_main_checkout():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        clone_root = _make_git_repo(base, "app/main")
        assert (
            project_path(base, {"name": "app", "repo": "https://x/r.git"}, layout="clone")
            == clone_root
        )


def test_project_path_none_for_non_git():
    with tempfile.TemporaryDirectory() as td:
        plain = Path(td) / "plain"
        os.makedirs(plain, exist_ok=True)
        assert project_path(Path("."), {"name": "p", "path": str(plain)}, layout="local") is None


def test_project_path_none_for_missing():
    assert project_path(Path("."), {"name": "p", "path": "/does/not/exist"}, layout="local") is None


def test_resolve_workspace_file_path_local():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        app = _make_git_repo(base, "app")
        config = {"name": "ws", "projects": [{"name": "app", "path": str(app)}]}
        resolved = resolve_workspace_file_path(base, "app/src/main.py", config, layout="local")
        assert resolved is not None
        git_root, abs_path, in_repo = resolved
        assert git_root == app
        assert abs_path == app / "src" / "main.py"
        assert in_repo == "src/main.py"


def test_resolve_workspace_file_path_clone():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        clone_root = _make_git_repo(base, "app/main")
        config = {"name": "ws", "projects": [{"name": "app", "repo": "https://x/r.git"}]}
        resolved = resolve_workspace_file_path(base, "app/main/src/main.py", config, layout="clone")
        assert resolved is not None
        git_root, abs_path, in_repo = resolved
        assert git_root == clone_root
        assert abs_path == clone_root / "src" / "main.py"
        assert in_repo == "src/main.py"


def test_resolve_workspace_file_path_primary_fallback():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        app = _make_git_repo(base, "app")
        config = {"name": "ws", "projects": [{"name": "app", "path": str(app), "primary": True}]}
        resolved = resolve_workspace_file_path(base, "some/file.txt", config, layout="local")
        assert resolved is not None
        git_root, abs_path, in_repo = resolved
        assert git_root == app
        assert in_repo == "some/file.txt"


def test_union_tracked_files_local():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        app = _make_git_repo(base, "app", files=["src/main.py", "README.md"])
        lib = _make_git_repo(base, "lib", files=["lib.py"])
        config = {
            "name": "ws",
            "projects": [{"name": "app", "path": str(app)}, {"name": "lib", "path": str(lib)}],
        }

        files = union_tracked_files(base, config, layout="local")
        assert "app/src/main.py" in files
        assert "app/README.md" in files
        assert "lib/lib.py" in files


def test_union_tracked_files_clone():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _make_git_repo(base, "app/main", files=["src/main.py"])
        config = {"name": "ws", "projects": [{"name": "app", "repo": "https://x/r.git"}]}

        files = union_tracked_files(base, config, layout="clone")
        assert "app/main/src/main.py" in files
