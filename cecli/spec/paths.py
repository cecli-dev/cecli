"""On-disk paths for BrightVision workspace metadata (under the Cecli project tree)."""

from __future__ import annotations

import threading
from pathlib import Path

# Shared with Cecli agent state (``.cecli/agents/``, ``sessions/``, ``logs/``, …).
WORKSPACE_META_DIR = ".cecli"

# BrightVision-only subtrees (Cecli does not write these).
TODOS_FILE = "todos.json"
SPECS_DIR = "specs"
ATTACHMENTS_DIR = "attachments"

_meta_dir_lock_guard = threading.Lock()
_meta_dir_locks: dict[str, threading.Lock] = {}


def _meta_dir_lock(root: Path) -> threading.Lock:
    key = str(root)
    with _meta_dir_lock_guard:
        lock = _meta_dir_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _meta_dir_locks[key] = lock
        return lock


def workspace_meta_dir(workspace: str | Path) -> Path:
    """
    Resolve ``<workspace>/.cecli``.

    Cecli uses ``.cecli/agents/…``, ``sessions/``, ``logs/``, etc.
    BrightVision adds ``todos.json``, ``specs/``, ``attachments/`` alongside them.
    """
    root = Path(workspace).resolve()
    target = root / WORKSPACE_META_DIR
    with _meta_dir_lock(root):
        target.mkdir(parents=True, exist_ok=True)
    return target


def todos_json_path(workspace: str | Path) -> Path:
    return workspace_meta_dir(workspace) / TODOS_FILE


def specs_root(workspace: str | Path) -> Path:
    return workspace_meta_dir(workspace) / SPECS_DIR


def attachments_dir(workspace: str | Path) -> Path:
    return workspace_meta_dir(workspace) / ATTACHMENTS_DIR


def attachments_prefix() -> str:
    return f"{WORKSPACE_META_DIR}/{ATTACHMENTS_DIR}/"
