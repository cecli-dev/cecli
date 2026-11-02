"""End-to-end tests for worktree creation, recreation, and release."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from cecli.helpers.worktrees import (
    WorktreeError,
    WorktreeManager,
    WorktreeRecord,
    WorktreeReleaseResult,
)


@pytest.fixture(autouse=True)
def isolated_base(tmp_path, monkeypatch):
    base = tmp_path / "worktrees"
    monkeypatch.setenv("CECLI_WORKTREES_DIR", str(base))
    return base


def _git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "symbolic-ref", "HEAD", f"refs/heads/{branch}"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "initial")

    return path


def _create(repo: Path, uuid: str = "456abcde", agent: str = "wf:nightly-tidy", **kwargs):
    source = kwargs.pop("source", repo)

    return WorktreeManager.create(agent_name=agent, uuid=uuid, source=source, **kwargs)


def test_create_from_local_repo(tmp_path, isolated_base):
    repo = _init_repo(tmp_path / "repo")

    record = _create(repo)

    assert record.repo == str(repo.resolve())
    assert record.branch == "cecli/wf-nightly-tidy-456abcde"
    assert record.path == str((isolated_base / "repo" / "wf-nightly-tidy-456abcde").resolve())
    assert Path(record.path).is_dir()
    assert record.base_ref == "main"
    assert record.base_sha == _git(repo, "rev-parse", "main")
    assert record.agent == "wf:nightly-tidy"
    assert record.uuid == "456abcde"
    assert record.pid == os.getpid()
    assert record.created_at
    assert WorktreeManager.get(record.uuid) == record


def test_default_branch_master(tmp_path):
    repo = _init_repo(tmp_path / "repo", branch="master")

    record = _create(repo)

    assert record.base_ref == "master"


def test_explicit_base_ref(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "branch", "feature")
    feature_sha = _git(repo, "rev-parse", "feature")

    record = _create(repo, base_ref="feature")

    assert record.base_ref == "feature"
    assert record.base_sha == feature_sha


def test_unknown_base_ref_raises(tmp_path):
    repo = _init_repo(tmp_path / "repo")

    with pytest.raises(WorktreeError):
        _create(repo, base_ref="does-not-exist")


def test_branch_and_path_naming_are_sanitized(tmp_path):
    repo = _init_repo(tmp_path / "repo")

    record = _create(repo, agent="wf:nightly tidy", uuid="abc/def")

    assert record.branch == "cecli/wf-nightly-tidy-abc-def"
    assert "/" not in Path(record.path).name
    assert Path(record.path).name == "wf-nightly-tidy-abc-def"


def test_two_creates_produce_distinct_paths_and_branches(tmp_path):
    repo = _init_repo(tmp_path / "repo")

    first = _create(repo, uuid="aaaa1111")
    second = _create(repo, uuid="bbbb2222")

    assert first.path != second.path
    assert first.branch != second.branch
    assert Path(first.path).is_dir()
    assert Path(second.path).is_dir()


def test_clean_release_deletes_branch(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)

    result = WorktreeManager.release(record)

    assert isinstance(result, WorktreeReleaseResult)
    assert result.removed is True
    assert result.committed is False
    assert result.branch_deleted is True
    assert result.branch_kept is False
    assert not Path(record.path).exists()
    assert WorktreeManager.get(record.uuid) is None
    assert record.branch not in _git(repo, "branch", "--list")


def test_dirty_release_commits_and_keeps_branch(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    (Path(record.path) / "README.md").write_text("changed\n", encoding="utf-8")

    result = WorktreeManager.release(record)

    subject = f"Unfinished Dirty Worktree from agent {record.uuid}"
    body = _git(repo, "log", "-1", "--format=%b", record.branch)

    assert result.committed is True
    assert result.removed is True
    assert result.branch_kept is True
    assert result.branch_deleted is False
    assert not Path(record.path).exists()
    assert _git(repo, "log", "-1", "--format=%s", record.branch) == subject
    assert record.agent in body
    assert record.base_sha in body
    assert "README.md" in body
    assert WorktreeManager.get(record.uuid) is None


def test_release_commits_untracked_file(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    (Path(record.path) / "notes.txt").write_text("scratch\n", encoding="utf-8")

    result = WorktreeManager.release(record)

    assert result.committed is True
    assert result.branch_kept is True
    assert _git(repo, "show", f"{record.branch}:notes.txt") == "scratch"


def test_release_keeps_branch_with_agent_commits(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    (Path(record.path) / "agent.txt").write_text("work\n", encoding="utf-8")
    _git(Path(record.path), "add", "-A")
    _git(Path(record.path), "commit", "-m", "agent work")

    result = WorktreeManager.release(record)

    assert result.committed is False
    assert result.removed is True
    assert result.branch_kept is True
    assert result.branch_deleted is False
    assert not Path(record.path).exists()
    assert record.branch in _git(repo, "branch", "--list")


def test_release_with_missing_path(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    shutil.rmtree(record.path)

    result = WorktreeManager.release(record)

    assert result.removed is False
    assert result.branch_kept is False
    assert result.branch_deleted is True
    assert result.reason == "worktree path missing"
    assert WorktreeManager.get(record.uuid) is None
    assert record.branch not in _git(repo, "branch", "--list")


def test_release_oversized_untracked_guard(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    big = Path(record.path) / "big.bin"
    big.write_bytes(b"x" * (WorktreeManager.MAX_UNTRACKED_FILE_BYTES + 1))

    result = WorktreeManager.release(record)

    assert result.removed is False
    assert result.committed is False
    assert result.branch_kept is True
    assert "untracked files too large" in result.reason
    assert Path(record.path).is_dir()
    assert record.branch in _git(repo, "branch", "--list")
    assert WorktreeManager.get(record.uuid) == record


def test_release_oversized_guard_can_be_forced(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    (Path(record.path) / "big.bin").write_bytes(
        b"x" * (WorktreeManager.MAX_UNTRACKED_FILE_BYTES + 1)
    )

    result = WorktreeManager.release(record, force=True)

    assert result.removed is True
    assert result.committed is True
    assert not Path(record.path).exists()


def test_is_worktree_rejects_other_repo(tmp_path):
    repo_one = _init_repo(tmp_path / "repo-one")
    repo_two = _init_repo(tmp_path / "repo-two")
    record = _create(repo_one)

    assert WorktreeManager._is_worktree(Path(record.path), repo_one)
    assert not WorktreeManager._is_worktree(Path(record.path), repo_two)


def test_recreate_from_branch(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    _git(repo, "worktree", "remove", "--force", record.path)

    recreated = WorktreeManager.recreate(record)

    assert recreated.path == record.path
    assert recreated.branch == record.branch
    assert Path(recreated.path).is_dir()
    assert WorktreeManager.get(record.uuid) == recreated


def test_recreate_from_base_sha(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    _git(repo, "worktree", "remove", "--force", record.path)
    _git(repo, "branch", "-D", record.branch)

    recreated = WorktreeManager.recreate(record)

    assert recreated.path == record.path
    assert recreated.branch == record.branch
    assert Path(recreated.path).is_dir()
    assert _git(repo, "rev-parse", recreated.branch) == record.base_sha


def test_recreate_with_path_override(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    _git(repo, "worktree", "remove", "--force", record.path)
    new_path = tmp_path / "elsewhere" / "worktree"

    recreated = WorktreeManager.recreate(record, path=new_path)

    assert recreated.path == str(new_path.resolve())
    assert Path(recreated.path).is_dir()
    assert WorktreeManager.get(record.uuid) == recreated


def test_recreate_with_new_uuid_attaches_saved_branch(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    work = Path(record.path) / "work.txt"
    work.write_text("saved work\n", encoding="utf-8")
    _git(record.path, "add", "-A")
    _git(record.path, "commit", "-m", "saved work")
    _git(repo, "worktree", "remove", "--force", record.path)

    recreated = WorktreeManager.recreate(record, agent_name="wf:nightly-tidy", uuid="new99999")

    assert recreated.branch == record.branch
    assert recreated.uuid == "new99999"
    assert (Path(recreated.path) / "work.txt").read_text(encoding="utf-8") == "saved work\n"
    assert WorktreeManager.get(record.uuid) is None
    assert WorktreeManager.get("new99999") == recreated


def test_release_keeps_saved_branch_when_agent_switched_branches(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    path = Path(record.path)
    _git(path, "checkout", "-b", "agent-work")
    (path / "work.txt").write_text("switched branch work\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "agent work")

    result = WorktreeManager.release(record)

    assert result.removed is True
    assert result.branch_kept is True
    assert result.branch_deleted is False
    assert record.branch in _git(repo, "branch", "--list")
    assert "agent-work" in _git(repo, "branch", "--list")
    assert _git(repo, "show", "agent-work:work.txt") == "switched branch work"


def test_registry_round_trip(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)

    data = record.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert WorktreeRecord.from_dict(data) == record

    result = WorktreeManager.release(record)
    result_data = result.to_dict()
    assert WorktreeReleaseResult(**result_data) == result


def test_get_unknown_uuid_returns_none():
    assert WorktreeManager.get("missing") is None


def test_release_all_releases_matching_pid(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    first = _create(repo, uuid="aaaa1111")
    second = _create(repo, uuid="bbbb2222")

    results = WorktreeManager.release_all()

    assert {result.uuid for result in results} == {first.uuid, second.uuid}
    assert not Path(first.path).exists()
    assert not Path(second.path).exists()
    assert WorktreeManager.get(first.uuid) is None
    assert WorktreeManager.get(second.uuid) is None


def test_release_all_skips_other_pids(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    other = replace(record, pid=os.getpid() + 1)
    WorktreeManager._replace_record(record.uuid, other)

    results = WorktreeManager.release_all()

    assert results == []
    assert Path(record.path).is_dir()


def test_sweep_stale_releases_dead_pid(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    dead = replace(record, pid=process.pid)
    WorktreeManager._replace_record(record.uuid, dead)

    results = WorktreeManager.sweep_stale()

    assert len(results) == 1
    assert results[0].removed is True
    assert not Path(record.path).exists()
    assert WorktreeManager.get(record.uuid) is None


def test_sweep_stale_skips_alive_pid(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)

    assert WorktreeManager.sweep_stale() == []
    assert Path(record.path).is_dir()


def test_sweep_stale_skips_other_hosts(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    record = _create(repo)
    other_host = replace(record, host="some-other-host", pid=1)
    WorktreeManager._replace_record(record.uuid, other_host)

    assert WorktreeManager.sweep_stale() == []
    assert Path(record.path).is_dir()


def test_resolve_source_variants(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    nested = repo / "nested"
    nested.mkdir()

    assert WorktreeManager.resolve_source(nested) == str(repo.resolve())
    assert WorktreeManager.resolve_source("repo", base_root=tmp_path) == str(repo.resolve())
    assert WorktreeManager.resolve_source("file:///tmp/example.git") == "file:///tmp/example.git"
    assert (
        WorktreeManager.resolve_source("https://example.com/org/repo.git")
        == "https://example.com/org/repo.git"
    )

    with pytest.raises(WorktreeError):
        WorktreeManager.resolve_source(tmp_path / "missing")


def test_create_from_file_url_remote(tmp_path, isolated_base):
    repo = _init_repo(tmp_path / "repo")
    source = repo.as_uri()

    first = _create(repo, uuid="aaaa1111", source=source)
    second = _create(repo, uuid="bbbb2222", source=source)

    assert first.repo == second.repo
    assert Path(first.repo).is_dir()
    assert Path(first.repo).parent.name == "_sources"
    assert first.path != second.path
    assert first.base_ref == "main"
    assert Path(first.path).is_dir()
    assert Path(second.path).is_dir()
