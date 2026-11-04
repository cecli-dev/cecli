"""Tests for worktree path layout and naming helpers."""

from __future__ import annotations

import re

import pytest

from cecli.helpers.worktrees import paths


@pytest.fixture(autouse=True)
def isolated_base(tmp_path, monkeypatch):
    base = tmp_path / "worktrees"
    monkeypatch.setenv("CECLI_WORKTREES_DIR", str(base))
    return base


def test_managed_root_honors_env(isolated_base):
    assert paths.managed_root() == isolated_base.resolve()


def test_registry_and_lock_paths(isolated_base):
    assert paths.registry_path() == isolated_base.resolve() / "registry.json"
    assert paths.lock_dir() == isolated_base.resolve() / ".locks"
    assert paths.lock_path(None, "My Lock") == isolated_base.resolve() / ".locks" / "My-Lock.lock"


def test_slugify_sanitizes_colons_whitespace_and_slashes():
    assert paths.slugify("wf:nightly tidy") == "wf-nightly-tidy"
    assert paths.slugify("a/b\\c:d") == "a-b-c-d"
    assert paths.slugify("  ???  ") == "item"
    assert paths.slugify("x" * 80, max_length=10) == "x" * 10


def test_agent_slug_truncates():
    slug = paths.agent_slug("wf:" + "a" * 100)
    assert len(slug) == paths.AGENT_SLUG_MAX
    assert not slug.endswith("-")


def test_branch_and_dir_names():
    assert paths.branch_name("wf:nightly-tidy", "456abcde") == "cecli/wf-nightly-tidy-456abcde"
    assert paths.worktree_dir_name("wf:nightly-tidy", "456abcde") == "wf-nightly-tidy-456abcde"


def test_branch_name_has_no_slash_after_prefix():
    branch = paths.branch_name("wf:a/b", "u/u")
    assert branch.startswith("cecli/")
    assert "/" not in branch[len("cecli/") :]


def test_worktree_path_layout(tmp_path):
    repo = tmp_path / "my-repo"
    path = paths.worktree_path(None, repo, "wf:nightly-tidy", "456abcde")
    assert path.parent.name == "my-repo"
    assert path.name == "wf-nightly-tidy-456abcde"
    assert path.is_relative_to(paths.managed_root())


def test_repo_and_source_slugs():
    assert paths.repo_slug("/tmp/My Repo.git") == "My-Repo"
    assert paths.source_slug("https://example.com/org/Cool-Repo.git") == "Cool-Repo"
    assert paths.source_slug("git@github.com:org/Cool-Repo.git") == "Cool-Repo"


def test_short_digest_is_stable():
    assert paths.short_digest("value") == paths.short_digest("value")
    assert len(paths.short_digest("value", 12)) == 12
    assert re.fullmatch(r"[0-9a-f]+", paths.short_digest("value"))
