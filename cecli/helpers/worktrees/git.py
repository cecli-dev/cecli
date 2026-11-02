"""Thin subprocess wrappers around the git CLI.

Every wrapper captures output, disables the pager and interactive credential
prompts, and reports fatal failures as :class:`WorktreeError` carrying git's
stderr.  Read-only probes accept ``check=False`` so callers can treat a
non-zero exit code as a falsy answer instead of an exception.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class WorktreeError(RuntimeError):
    """Raised when a worktree operation or git invocation cannot complete."""


def run_git(
    *args: str,
    cwd: str | Path | None = None,
    check: bool = True,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run ``git`` with *args* and capture its output.

    ``GIT_PAGER=cat`` keeps output machine-readable and
    ``GIT_TERMINAL_PROMPT=0`` prevents a hung process waiting on credentials.
    When *check* is true a non-zero exit code raises :class:`WorktreeError`
    with git's stderr attached.
    """
    command = ["git", *(_as_text(arg) for arg in args)]
    full_env = os.environ.copy()
    full_env["GIT_PAGER"] = "cat"
    full_env.setdefault("GIT_TERMINAL_PROMPT", "0")

    if env:
        full_env.update(env)

    try:
        result = subprocess.run(
            command,
            cwd=_as_text(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=full_env,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise WorktreeError("git executable not found") from exc
    except OSError as exc:
        raise WorktreeError(f"failed to run {' '.join(command)}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(f"git command timed out: {' '.join(command)}") from exc

    if check and result.returncode != 0:
        raise WorktreeError(_format_error(command, result))

    return result


def rev_parse(ref: str, cwd: str | Path | None = None, *, check: bool = True) -> str | None:
    """Resolve *ref* to a commit SHA, or return ``None`` when it is unknown."""
    result = run_git("rev-parse", "--verify", ref, cwd=cwd, check=False)

    if result.returncode != 0:
        if check:
            raise WorktreeError(_format_error(["git", "rev-parse", "--verify", ref], result))

        return None

    value = result.stdout.strip()

    return value or None


def git_root(path: str | Path) -> str | None:
    """Return the absolute top-level of the worktree containing *path*.

    A path pointing directly at a ``.git`` file (as used by linked worktrees)
    is resolved through its parent.  Bare repositories are returned as-is.
    """
    target = Path(path).expanduser()

    if target.is_file():
        if target.name != ".git":
            return None

        target = target.parent

    result = run_git("rev-parse", "--show-toplevel", cwd=target, check=False)

    if result.returncode == 0:
        value = result.stdout.strip()

        if value:
            return str(Path(value).resolve())

    if is_bare_repo(target):
        return str(target.resolve())

    return None


def is_git_repo(path: str | Path) -> bool:
    """Return whether *path* is inside a git repository (bare included)."""
    result = run_git("rev-parse", "--git-dir", cwd=path, check=False)

    return result.returncode == 0 and bool(result.stdout.strip())


def is_bare_repo(path: str | Path) -> bool:
    """Return whether *path* is a bare git repository."""
    result = run_git("rev-parse", "--is-bare-repository", cwd=path, check=False)

    return result.returncode == 0 and result.stdout.strip() == "true"


def default_branch(cwd: str | Path | None = None) -> str | None:
    """Best-effort default base branch, preferring ``origin/HEAD``.

    Falls back to local ``main``, then ``master``, then the currently checked
    out branch.  Returns ``None`` for an empty repository with no commits.
    """
    result = run_git(
        "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", cwd=cwd, check=False
    )

    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    for candidate in ("main", "master"):
        if rev_parse(candidate, cwd=cwd, check=False):
            return candidate

    return current_branch(cwd)


def current_branch(cwd: str | Path | None = None) -> str | None:
    """Return the short name of the checked out branch, if any."""
    result = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd, check=False)

    if result.returncode != 0:
        return None

    name = result.stdout.strip()

    return name if name and name != "HEAD" else None


def status_porcelain(cwd: str | Path) -> str:
    """Return V1 porcelain status, listing untracked files individually."""
    result = run_git("status", "--porcelain=v1", "--untracked-files=all", cwd=cwd, check=False)

    return result.stdout


def branch_exists(branch: str, cwd: str | Path | None = None) -> bool:
    """Return whether a local branch named *branch* exists."""
    name = branch.removeprefix("refs/heads/")
    result = run_git("show-ref", "--verify", "--quiet", f"refs/heads/{name}", cwd=cwd, check=False)

    return result.returncode == 0


def branch_merged(branch: str, base: str, cwd: str | Path | None = None) -> bool:
    """Return whether *branch* is an ancestor of (fully merged into) *base*."""
    if not branch or not base:
        return False

    result = run_git("merge-base", "--is-ancestor", branch, base, cwd=cwd, check=False)

    return result.returncode == 0


def ahead_count(base_sha: str, branch: str, cwd: str | Path | None = None) -> int:
    """Return the number of commits on *branch* not reachable from *base_sha*."""
    if not base_sha or not branch:
        return 0

    result = run_git("rev-list", "--count", f"{base_sha}..{branch}", cwd=cwd, check=False)

    if result.returncode != 0:
        return 0

    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _format_error(command: list[str], result: subprocess.CompletedProcess) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    prefix = f"git command failed (exit {result.returncode}): {' '.join(command)}"

    return f"{prefix}: {detail}" if detail else prefix


def _as_text(value: object) -> str:
    return str(value)
