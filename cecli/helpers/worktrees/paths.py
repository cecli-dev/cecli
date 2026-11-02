"""Filesystem layout and naming helpers for managed git worktrees.

Managed layout::

    <BASE>/
        registry.json
        .locks/
        _sources/<source-slug>-<sha8>/       # bare caches for remote sources
        <repo-slug>/<agent-slug>-<uuid>/     # one directory per worktree

``BASE`` defaults to ``~/.cecli/worktrees`` and can be overridden with the
``CECLI_WORKTREES_DIR`` environment variable.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

DEFAULT_BASE = "~/.cecli/worktrees"
BRANCH_PREFIX = "cecli"
AGENT_SLUG_MAX = 40
REPO_SLUG_MAX = 48
LOCK_NAME_MAX = 80

_SLUG_SEPARATORS = re.compile(r"[:\\/\s]+")
_SLUG_INVALID = re.compile(r"[^A-Za-z0-9._-]+")
_SLUG_DASHES = re.compile(r"-{2,}")


def managed_root() -> Path:
    """Return the managed worktree root, honoring ``CECLI_WORKTREES_DIR``."""
    override = os.environ.get("CECLI_WORKTREES_DIR")
    raw = override if override else DEFAULT_BASE
    return Path(raw).expanduser().resolve()


def registry_path(base: str | Path | None = None) -> Path:
    """Return the path of the JSON registry for managed worktrees."""
    return _base_path(base) / "registry.json"


def lock_dir(base: str | Path | None = None) -> Path:
    """Return the directory holding inter-process lock files."""
    return _base_path(base) / ".locks"


def lock_path(base: str | Path | None, name: str) -> Path:
    """Return a lock file path for *name* under the managed lock directory."""
    slug = slugify(name, max_length=LOCK_NAME_MAX, fallback="lock")
    return lock_dir(base) / f"{slug}.lock"


def sources_dir(base: str | Path | None = None) -> Path:
    """Return the directory holding bare caches for remote sources."""
    return _base_path(base) / "_sources"


def slugify(value: str, *, max_length: int | None = None, fallback: str = "item") -> str:
    """Turn *value* into a filesystem- and branch-safe slug.

    Colons, whitespace, and path separators become dashes; other characters
    outside ``[A-Za-z0-9._-]`` become dashes as well. Leading and trailing
    punctuation is stripped, and the result is truncated to *max_length*.
    """
    text = str(value).strip()
    text = _SLUG_SEPARATORS.sub("-", text)
    text = _SLUG_INVALID.sub("-", text)
    text = _SLUG_DASHES.sub("-", text).strip("-._")

    if max_length is not None and len(text) > max_length:
        text = text[:max_length].rstrip("-._")

    return text or fallback


def short_digest(value: str, length: int = 8) -> str:
    """Return a stable short SHA-1 digest of *value*."""
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:length]


def repo_slug(repo: str | Path) -> str:
    """Return the directory slug used for the repository at *repo*."""
    name = Path(str(repo)).name.removesuffix(".git")
    fallback = f"repo-{short_digest(str(repo))}"

    return slugify(name, max_length=REPO_SLUG_MAX, fallback=fallback)


def source_slug(source: str) -> str:
    """Return a human-readable slug for a remote source URL."""
    text = str(source).rstrip("/")
    text = text.removesuffix(".git")
    name = re.split(r"[/:]", text)[-1]
    fallback = f"source-{short_digest(str(source))}"

    return slugify(name, max_length=REPO_SLUG_MAX, fallback=fallback)


def agent_slug(agent_name: str) -> str:
    """Return the slug used for *agent_name* in branches and paths."""
    return slugify(agent_name, max_length=AGENT_SLUG_MAX, fallback="agent")


def branch_name(agent_name: str, uuid: str) -> str:
    """Return the generated branch name for an agent worktree."""
    return f"{BRANCH_PREFIX}/{worktree_dir_name(agent_name, uuid)}"


def worktree_dir_name(agent_name: str, uuid: str) -> str:
    """Return the generated directory name for an agent worktree."""
    return f"{agent_slug(agent_name)}-{_uuid_slug(uuid)}"


def worktree_path(base: str | Path | None, repo: str | Path, agent_name: str, uuid: str) -> Path:
    """Return the full managed path for an agent worktree."""
    return _base_path(base) / repo_slug(repo) / worktree_dir_name(agent_name, uuid)


def _uuid_slug(uuid: str) -> str:
    text = slugify(uuid, max_length=40, fallback="")
    return text or short_digest(uuid, 8)


def _base_path(base: str | Path | None) -> Path:
    if base is None:
        return managed_root()

    return Path(base).expanduser().resolve()
