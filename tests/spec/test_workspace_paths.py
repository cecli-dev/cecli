"""Workspace metadata paths under ``.cecli/``."""

from __future__ import annotations

from pathlib import Path

from cecli.spec.paths import (
    WORKSPACE_META_DIR,
    attachments_dir,
    todos_json_path,
    workspace_meta_dir,
)
from cecli.spec.todos import WorkspaceTodos


def test_workspace_meta_dir_creates_cecli(tmp_path: Path):
    meta = workspace_meta_dir(tmp_path)
    assert meta.name == WORKSPACE_META_DIR == ".cecli"
    assert meta.is_dir()


def test_existing_cecli_agents_preserved(tmp_path: Path):
    cecli = tmp_path / ".cecli"
    (cecli / "agents").mkdir(parents=True)
    meta = workspace_meta_dir(tmp_path)
    assert (cecli / "agents").is_dir()
    assert meta == cecli


def test_workspace_todos_uses_cecli(tmp_path: Path):
    api = WorkspaceTodos(tmp_path)
    assert str(api.path).endswith(".cecli/todos.json")
    assert str(api.specs_root).endswith(".cecli/specs")


def test_attachments_dir_under_cecli(tmp_path: Path):
    path = attachments_dir(tmp_path)
    assert path == tmp_path / ".cecli" / "attachments"


def test_concurrent_meta_dir_creation(tmp_path: Path):
    """Parallel calls must not raise."""
    workspace_meta_dir(tmp_path)
    workspace_meta_dir(tmp_path)
    assert todos_json_path(tmp_path).parent.is_dir()
