"""Lifecycle management for isolated agent git worktrees.

A worktree is created from a local repository or a cached bare clone of a
remote.  Each worktree gets its own generated branch and lives under
``~/.cecli/worktrees`` (see :mod:`cecli.helpers.worktrees.paths`).  Records are
tracked in an atomically-written JSON registry so they can be recreated or
released later, even from a different process.

Releasing a worktree deliberately commits any uncommitted work first
("commit-on-release"), then removes the worktree.  Only branches with no
commits ahead of their base -- or branches fully merged into their base -- are
deleted; otherwise the branch is kept so the work is not lost.  Ignored files
are intentionally discarded by ``git worktree remove --force``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from cecli.helpers.worktrees import paths
from cecli.helpers.worktrees.git import (
    WorktreeError,
    ahead_count,
    branch_exists,
    branch_merged,
    current_branch,
    default_branch,
    git_root,
    is_git_repo,
    rev_parse,
    run_git,
    status_porcelain,
)

__all__ = [
    "WorktreeError",
    "WorktreeManager",
    "WorktreeRecord",
    "WorktreeReleaseResult",
]

_SCHEME_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_SCP_URL = re.compile(r"^[^/@\s]+@[^:\s]+:.+")


@dataclass(frozen=True)
class WorktreeRecord:
    """A managed worktree and the metadata needed to recreate or release it."""

    source: str
    repo: str
    path: str
    branch: str
    base_ref: str
    base_sha: str
    agent: str
    uuid: str
    pid: int
    host: str
    created_at: str

    def to_dict(self) -> dict:
        """Return a JSON-serializable representation of the record."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WorktreeRecord":
        """Build a record from a mapping, ignoring unknown keys."""
        known = {field.name for field in fields(cls)}
        values = {name: data[name] for name in known if name in data}

        return cls(**values)


@dataclass(frozen=True)
class WorktreeReleaseResult:
    """Outcome of releasing a single worktree."""

    uuid: str
    branch: str
    committed: bool = False
    removed: bool = False
    branch_kept: bool = False
    branch_deleted: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable representation of the result."""
        return asdict(self)


class WorktreeManager:
    """Create, recreate, release, and sweep agent worktrees."""

    BASE: Path = paths.managed_root()
    REGISTRY_FILENAME = "registry.json"
    MAX_UNTRACKED_FILE_BYTES = 10 * 1024 * 1024
    MAX_UNTRACKED_TOTAL_BYTES = 100 * 1024 * 1024
    MAX_NAME_ATTEMPTS = 8
    _THREAD_LOCK = threading.RLock()

    @classmethod
    def create(
        cls,
        *,
        agent_name: str,
        uuid: str,
        source: str | Path,
        base_ref: str | None = None,
        base_root: str | Path | None = None,
        reuse_existing: bool = True,
    ) -> WorktreeRecord:
        """Create a new worktree for *agent_name* and return its record.

        *source* may be a local repository path or a remote URL.  Remotes are
        cloned into a shared bare cache and fetched on reuse.  The default base
        branch is resolved from ``origin/HEAD``, ``main``, ``master``, or the
        current ``HEAD`` in that order.

        By default an already-recorded checkout for the same agent and
        repository is adopted (its owner is refreshed) instead of creating a
        duplicate; workflows never run the same pair concurrently.  Pass
        ``reuse_existing=False`` only when deliberately creating a second
        independent checkout for the same agent.
        """
        base = cls._base()
        repo = cls._prepare_source(source, base_root=base_root)

        # Reuse and creation are serialized per repository so concurrent runs of
        # the same workflow cannot each create their own checkout.
        with cls._repo_lock(base, repo):
            if reuse_existing:
                existing = cls._find_reusable(repo, agent_name)

                if existing is not None:
                    return cls._adopt(existing)

            base_ref_name, base_sha = cls._resolve_base(repo, base_ref)
            branch = paths.branch_name(agent_name, uuid)
            path = paths.worktree_path(base, repo, agent_name, uuid)
            path.parent.mkdir(parents=True, exist_ok=True)
            branch, path = cls._add_worktree(repo, branch, path, base_ref_name, base_sha)

            record = WorktreeRecord(
                source=str(source),
                repo=str(Path(repo).resolve()),
                path=str(path.resolve()),
                branch=branch,
                base_ref=base_ref_name,
                base_sha=base_sha,
                agent=str(agent_name),
                uuid=str(uuid),
                pid=os.getpid(),
                host=socket.gethostname(),
                created_at=_now(),
            )
            cls._save_record(record)

        return record

    @classmethod
    def recreate(
        cls,
        record: WorktreeRecord | dict,
        *,
        agent_name: str | None = None,
        uuid: str | None = None,
        path: str | Path | None = None,
    ) -> WorktreeRecord:
        """Reattach or rebuild the worktree described by *record*.

        An existing recorded path is reused when it is still a valid worktree.
        Otherwise the existing branch is attached, the recorded base SHA is
        checked out onto a new branch, or the base is resolved again as a last
        resort.  ``agent_name``, ``uuid``, and ``path`` may be overridden.
        """
        original = cls._coerce_record(record)
        base = cls._base()
        repo = Path(original.repo)
        new_agent = str(agent_name) if agent_name is not None else original.agent
        new_uuid = str(uuid) if uuid is not None else original.uuid
        recorded_path = Path(original.path)
        base_ref = original.base_ref
        base_sha = original.base_sha

        if path is None and recorded_path.exists() and cls._is_worktree(recorded_path, repo):
            target_path = recorded_path
            branch = current_branch(target_path) or original.branch
        else:
            branch = original.branch or paths.branch_name(new_agent, new_uuid)

            if path is not None:
                target_path = Path(path).expanduser().resolve()
            elif new_agent == original.agent and new_uuid == original.uuid:
                target_path = recorded_path
            else:
                target_path = paths.worktree_path(base, repo, new_agent, new_uuid)

            target_path.parent.mkdir(parents=True, exist_ok=True)

            with cls._repo_lock(base, repo):
                reusable = cls._find_reusable(repo, new_agent) if path is None else None

                if reusable is not None:
                    adopted = cls._adopt(reusable)

                    if original.uuid != adopted.uuid:
                        cls._discard_record(original.uuid)

                    return adopted

                if branch_exists(branch, repo):
                    try:
                        run_git("worktree", "add", str(target_path), branch, cwd=repo)
                    except WorktreeError:
                        # The saved branch may still be checked out elsewhere.
                        # Preserve its tip under the new generated name instead.
                        tip = rev_parse(branch, cwd=repo, check=False)
                        branch = paths.branch_name(new_agent, new_uuid)

                        if tip:
                            run_git(
                                "worktree", "add", "-b", branch, str(target_path), tip, cwd=repo
                            )
                        else:
                            raise
                elif base_sha and rev_parse(base_sha, cwd=repo, check=False):
                    run_git("worktree", "add", "-b", branch, str(target_path), base_sha, cwd=repo)
                else:
                    fallback_ref = base_ref if rev_parse(base_ref, cwd=repo, check=False) else None
                    base_ref, base_sha = cls._resolve_base(repo, fallback_ref)
                    branch, target_path = cls._add_worktree(
                        repo, branch, target_path, base_ref, base_sha
                    )

        record = WorktreeRecord(
            source=original.source,
            repo=str(repo.resolve()),
            path=str(target_path.resolve()),
            branch=branch,
            base_ref=base_ref,
            base_sha=base_sha,
            agent=new_agent,
            uuid=new_uuid,
            pid=os.getpid(),
            host=socket.gethostname(),
            created_at=original.created_at,
        )
        cls._replace_record(original.uuid, record)

        return record

    @classmethod
    def release(
        cls,
        record_or_uuid: WorktreeRecord | dict | str,
        *,
        force: bool = False,
    ) -> WorktreeReleaseResult:
        """Commit dirty work, remove the worktree, and clean up its branch.

        Uncommitted changes are committed with the cecli identity before the
        worktree is removed.  Oversized untracked files abort the release and
        leave everything in place.  *force* bypasses that size guard.  A branch
        is deleted only when it has no commits ahead of its base or is fully
        merged; otherwise it is kept.
        """
        record = cls._coerce_record(record_or_uuid)
        repo = Path(record.repo)
        path = Path(record.path)

        if not path.exists():
            run_git("worktree", "prune", cwd=repo, check=False)
            ahead = ahead_count(record.base_sha, record.branch, cwd=repo)
            branch_deleted = cls._drop_empty_branch(repo, record, ahead)
            cls._discard_record(record.uuid)

            return _release_result(
                record,
                removed=False,
                branch_kept=not branch_deleted,
                branch_deleted=branch_deleted,
                reason="worktree path missing",
            )

        if not cls._is_worktree(path, repo):
            cls._discard_record(record.uuid)

            return _release_result(
                record,
                branch_kept=True,
                reason="path is not a managed worktree",
            )

        try:
            status = status_porcelain(path)
        except WorktreeError as exc:
            return _release_result(record, branch_kept=True, reason=f"status failed: {exc}")

        committed = False

        if status.strip():
            if not force and cls._untracked_too_large(path, status):
                return _release_result(
                    record,
                    branch_kept=True,
                    reason="untracked files too large",
                )

            try:
                cls._commit_dirty(record, path, status)
            except WorktreeError as exc:
                return _release_result(record, branch_kept=True, reason=f"commit failed: {exc}")

            committed = True

        active_branch = current_branch(path)
        if active_branch is None and (
            status.strip() or ahead_count(record.base_sha, "HEAD", cwd=repo) > 0
        ):
            run_git("branch", "-f", f"{record.branch}-detached", "HEAD", cwd=path, check=False)

        ahead = ahead_count(record.base_sha, record.branch, cwd=repo)

        with cls._repo_lock(cls._base(), repo):
            try:
                run_git("worktree", "remove", "--force", str(path), cwd=repo)
            except WorktreeError as exc:
                return _release_result(
                    record,
                    committed=committed,
                    branch_kept=True,
                    reason=f"worktree remove failed: {exc}",
                )

            run_git("worktree", "prune", cwd=repo, check=False)
            branch_deleted = cls._drop_empty_branch(
                repo, record, ahead, allow_delete=active_branch == record.branch
            )

        branch_kept = not branch_deleted
        cls._discard_record(record.uuid)

        return _release_result(
            record,
            committed=committed,
            removed=True,
            branch_kept=branch_kept,
            branch_deleted=branch_deleted,
            reason="" if branch_deleted else "branch kept (unmerged commits)",
        )

    @classmethod
    def release_all(cls, *, pid: int | None = None) -> list[WorktreeReleaseResult]:
        """Release every recorded worktree belonging to *pid* (default: us)."""
        target = os.getpid() if pid is None else int(pid)
        host = socket.gethostname()
        results = []

        for record in cls._records():
            if record.pid != target or record.host != host:
                continue

            results.append(cls._release_safely(record))

        return results

    @classmethod
    def sweep_stale(cls) -> list[WorktreeReleaseResult]:
        """Release worktrees from this host whose owning process is gone."""
        host = socket.gethostname()
        results = []

        for record in cls._records():
            if record.host != host or _pid_alive(record.pid):
                continue

            results.append(cls._release_safely(record))

        return results

    @classmethod
    def get(cls, uuid: str) -> WorktreeRecord | None:
        """Return the registry record for *uuid*, or ``None`` if unknown."""
        data = cls._read_registry().get(str(uuid))

        if not data:
            return None

        try:
            return WorktreeRecord.from_dict(data)
        except (TypeError, KeyError):
            return None

    @classmethod
    def resolve_source(
        cls,
        source: str | Path,
        *,
        base_root: str | Path | None = None,
    ) -> str:
        """Resolve *source* to an absolute repository path or a remote URL.

        Existing paths are normalized to their git top-level; relative paths
        are resolved against *base_root* (or the current directory).  Strings
        that do not exist but look like URLs are returned unchanged.  A missing
        non-remote path raises :class:`WorktreeError`.
        """
        raw = str(source)
        candidate = Path(raw).expanduser()

        if candidate.is_absolute():
            if candidate.exists():
                return _normalize_local(candidate)
        elif base_root is not None:
            candidate = Path(base_root).expanduser() / candidate

            if candidate.exists():
                return _normalize_local(candidate)
        elif candidate.exists():
            return _normalize_local(candidate)

        if _looks_remote(raw):
            return raw

        raise WorktreeError(f"source path does not exist: {raw}")

    @classmethod
    def _base(cls) -> Path:
        override = os.environ.get("CECLI_WORKTREES_DIR")

        if override:
            return Path(override).expanduser().resolve()

        return Path(cls.BASE).expanduser().resolve()

    @classmethod
    def _prepare_source(
        cls,
        source: str | Path,
        *,
        base_root: str | Path | None = None,
    ) -> str:
        resolved = cls.resolve_source(source, base_root=base_root)

        if _looks_remote(resolved):
            return cls._cache_remote(cls._base(), resolved)

        return resolved

    @classmethod
    def _cache_remote(cls, base: Path, source: str) -> str:
        digest = paths.short_digest(source, 8)
        slug = paths.source_slug(source)
        cache = paths.sources_dir(base) / f"{slug}-{digest}"
        cache.parent.mkdir(parents=True, exist_ok=True)
        lock = paths.lock_path(base, f"source-{digest}")

        with _file_lock(lock):
            if cache.exists() and is_git_repo(cache):
                run_git(
                    "fetch",
                    "--prune",
                    "origin",
                    "+refs/heads/*:refs/heads/*",
                    cwd=cache,
                    check=False,
                )
            else:
                if cache.exists():
                    shutil.rmtree(cache, ignore_errors=True)

                run_git("clone", "--bare", source, str(cache))

        return str(cache.resolve())

    @classmethod
    def _resolve_base(cls, repo: str | Path, base_ref: str | None) -> tuple[str, str]:
        if base_ref is not None:
            ref = str(base_ref)
            sha = rev_parse(ref, cwd=repo, check=False)

            if not sha:
                raise WorktreeError(f"unknown base ref {ref!r} in {repo}")

            return ref, sha

        name = default_branch(cwd=repo)

        if name is None:
            name = "HEAD"

        sha = rev_parse(name, cwd=repo, check=False)

        if not sha:
            raise WorktreeError(f"repository has no resolvable base commit: {repo}")

        return name, sha

    @classmethod
    def _add_worktree(
        cls,
        repo: str | Path,
        branch: str,
        path: Path,
        base_ref: str,
        base_sha: str,
    ) -> tuple[str, Path]:
        start = base_ref if rev_parse(base_ref, cwd=repo, check=False) else base_sha

        if path.exists():
            existing = cls._existing_branch(repo, path, branch)

            if existing is not None:
                return existing, path

            raise WorktreeError(f"worktree path already exists: {path}")

        last_error: WorktreeError | None = None

        for attempt in range(cls.MAX_NAME_ATTEMPTS):
            candidate_branch = branch if attempt == 0 else f"{branch}-{attempt + 1}"

            try:
                if branch_exists(candidate_branch, repo):
                    run_git("worktree", "add", str(path), candidate_branch, cwd=repo)
                else:
                    run_git(
                        "worktree",
                        "add",
                        "-b",
                        candidate_branch,
                        str(path),
                        start,
                        cwd=repo,
                    )
            except WorktreeError as exc:
                last_error = exc

                if path.exists():
                    existing = cls._existing_branch(repo, path, candidate_branch)

                    if existing is not None:
                        return existing, path

                    break

                continue

            return candidate_branch, path

        raise WorktreeError(
            f"could not create worktree for branch {branch!r} in {repo}: {last_error}"
        )

    @classmethod
    def _commit_dirty(cls, record: WorktreeRecord, path: Path, status: str) -> None:
        subject = f"Unfinished Dirty Worktree from agent {record.uuid}"
        summary = status.rstrip()
        body = "\n".join(
            [
                f"agent: {record.agent}",
                f"worktree: {record.path}",
                f"base ref: {record.base_ref}",
                f"base sha: {record.base_sha}",
                "",
                "status:",
                summary[:4000],
            ]
        )
        run_git("add", "-A", cwd=path)
        run_git(
            "-c",
            "user.name=cecli",
            "-c",
            "user.email=cecli@localhost",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "-m",
            subject,
            "-m",
            body,
            cwd=path,
        )

    @classmethod
    def _untracked_too_large(cls, path: Path, status: str) -> bool:
        total = 0

        for line in status.splitlines():
            if not line.startswith("?? "):
                continue

            relative = line[3:].strip().strip('"')
            candidate = path / relative

            try:
                size = candidate.stat().st_size
            except OSError:
                continue

            if size > cls.MAX_UNTRACKED_FILE_BYTES:
                return True

            total += size

            if total > cls.MAX_UNTRACKED_TOTAL_BYTES:
                return True

        return False

    @classmethod
    def _drop_empty_branch(
        cls, repo: Path, record: WorktreeRecord, ahead: int, *, allow_delete: bool = True
    ) -> bool:
        """Delete a managed branch when it has no unique commits."""
        if not branch_exists(record.branch, repo):
            return True

        if not allow_delete:
            return False

        if not record.branch.startswith(f"{paths.BRANCH_PREFIX}/"):
            return False

        if not record.base_sha or not rev_parse(record.base_sha, cwd=repo, check=False):
            return False

        if ahead == 0 or cls._branch_merged(repo, record):
            delete = run_git("branch", "-D", record.branch, cwd=repo, check=False)
            return delete.returncode == 0

        return False

    @classmethod
    def _branch_merged(cls, repo: Path, record: WorktreeRecord) -> bool:
        if record.base_ref and branch_merged(record.branch, record.base_ref, cwd=repo):
            return True

        if record.base_sha and branch_merged(record.branch, record.base_sha, cwd=repo):
            return True

        return False

    @classmethod
    def _is_worktree(cls, path: Path, repo: Path) -> bool:
        if not path.is_dir():
            return False

        root = git_root(path)

        if root is None:
            return False

        try:
            if Path(root).resolve() != path.resolve():
                return False
        except OSError:
            return False

        path_common = _git_common_dir(path)
        repo_common = _git_common_dir(repo)

        return bool(path_common and repo_common and path_common == repo_common)

    @classmethod
    def _release_safely(cls, record: WorktreeRecord) -> WorktreeReleaseResult:
        try:
            return cls.release(record)
        except Exception as exc:
            return _release_result(record, branch_kept=True, reason=str(exc))

    @classmethod
    def _coerce_record(cls, value: WorktreeRecord | dict | str) -> WorktreeRecord:
        if isinstance(value, WorktreeRecord):
            return value

        if isinstance(value, dict):
            return WorktreeRecord.from_dict(value)

        record = cls.get(str(value))

        if record is None:
            raise WorktreeError(f"unknown worktree uuid: {value}")

        return record

    @classmethod
    def _save_record(cls, record: WorktreeRecord) -> None:
        with cls._registry_lock():
            data = cls._read_registry()
            data[record.uuid] = record.to_dict()
            cls._write_registry(data)

    @classmethod
    def _replace_record(cls, old_uuid: str, record: WorktreeRecord) -> None:
        with cls._registry_lock():
            data = cls._read_registry()

            if old_uuid != record.uuid:
                data.pop(old_uuid, None)

            data[record.uuid] = record.to_dict()
            cls._write_registry(data)

    @classmethod
    def _discard_record(cls, uuid: str) -> None:
        with cls._registry_lock():
            data = cls._read_registry()

            if data.pop(str(uuid), None) is not None:
                cls._write_registry(data)

    @classmethod
    def _records(cls) -> list[WorktreeRecord]:
        records = []

        for value in cls._read_registry().values():
            try:
                records.append(WorktreeRecord.from_dict(value))
            except (TypeError, KeyError):
                continue

        return records

    @classmethod
    def _read_registry(cls) -> dict[str, dict]:
        path = paths.registry_path(cls._base())

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(data, dict):
            return {}

        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    @classmethod
    def _write_registry(cls, data: dict[str, dict]) -> None:
        path = paths.registry_path(cls._base())
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".registry-", suffix=".tmp", dir=str(path.parent))

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass

            raise

    @classmethod
    @contextmanager
    def _registry_lock(cls) -> Iterator[None]:
        with cls._THREAD_LOCK:
            with _file_lock(paths.lock_path(cls._base(), "registry")):
                yield

    @classmethod
    @contextmanager
    def _repo_lock(cls, base: Path, repo: str | Path) -> Iterator[None]:
        digest = paths.short_digest(str(Path(repo).resolve()), 12)

        with _file_lock(paths.lock_path(base, f"repo-{digest}")):
            yield

    @classmethod
    def _find_reusable(cls, repo: str | Path, agent_name: str) -> WorktreeRecord | None:
        """Return a recorded checkout for *agent_name* in *repo*, if usable."""
        resolved_repo = str(Path(repo).resolve())

        for record in sorted(cls._records(), key=lambda item: item.created_at, reverse=True):
            if record.agent != agent_name:
                continue

            if str(Path(record.repo).resolve()) != resolved_repo:
                continue

            if cls._is_worktree(Path(record.path), Path(repo)):
                return record

        return None

    @classmethod
    def _adopt(cls, record: WorktreeRecord) -> WorktreeRecord:
        """Refresh *record* ownership and persist it."""
        adopted = WorktreeRecord(
            source=record.source,
            repo=record.repo,
            path=record.path,
            branch=record.branch,
            base_ref=record.base_ref,
            base_sha=record.base_sha,
            agent=record.agent,
            uuid=record.uuid,
            pid=os.getpid(),
            host=socket.gethostname(),
            created_at=record.created_at,
        )
        cls._save_record(adopted)

        return adopted

    @classmethod
    def _existing_branch(cls, repo: str | Path, path: Path, fallback: str) -> str | None:
        """Return the branch checked out at an existing managed worktree."""
        if not cls._is_worktree(path, Path(repo)):
            return None

        return current_branch(path) or fallback


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+", encoding="utf-8")
    fcntl = None
    msvcrt = None

    try:
        try:
            import fcntl as _fcntl
        except ImportError:
            _fcntl = None

        fcntl = _fcntl

        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        else:
            try:
                import msvcrt as _msvcrt
            except ImportError:
                _msvcrt = None

            msvcrt = _msvcrt

            if msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        elif msvcrt is not None:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

        handle.close()


def _normalize_local(path: Path) -> str:
    root = git_root(path)

    if root is None:
        raise WorktreeError(f"not a git repository: {path}")

    return root


def _looks_remote(value: str) -> bool:
    text = str(value)

    return bool(_SCHEME_URL.match(text) or _SCP_URL.match(text))


def _git_common_dir(path: str | Path) -> str | None:
    """Return a canonical git common directory for *path*, or ``None``."""
    result = run_git("rev-parse", "--git-common-dir", cwd=path, check=False)

    if result.returncode != 0:
        return None

    value = result.stdout.strip()

    if not value:
        return None

    common = Path(value)

    if not common.is_absolute():
        common = Path(path).expanduser() / common

    try:
        return str(common.resolve())
    except OSError:
        return None


def _release_result(
    record: WorktreeRecord,
    *,
    committed: bool = False,
    removed: bool = False,
    branch_kept: bool = False,
    branch_deleted: bool = False,
    reason: str = "",
) -> WorktreeReleaseResult:
    return WorktreeReleaseResult(
        uuid=record.uuid,
        branch=record.branch,
        committed=committed,
        removed=removed,
        branch_kept=branch_kept,
        branch_deleted=branch_deleted,
        reason=reason,
    )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False

    try:
        import psutil

        return bool(psutil.pid_exists(int(pid)))
    except ImportError:
        pass

    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))

        if handle:
            kernel32.CloseHandle(handle)
            return True

        return kernel32.GetLastError() == 5

    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return False

    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
