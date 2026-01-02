from pathlib import Path
from types import SimpleNamespace

import git

from cecli.io import InputOutput
from cecli.repo import GitRepo
from cecli.tools import git_branch
from cecli.utils import GitTemporaryDirectory


def _make_repo():
    repo = git.Repo()
    repo.config_writer().set_value("commit", "gpgsign", "false").release()
    return repo


def test_gitbranch_show_current_returns_branch_name():
    with GitTemporaryDirectory():
        repo = _make_repo()
        Path("file.txt").write_text("content\n")
        repo.git.add("file.txt")
        repo.git.commit("-m", "init")
        repo.git.checkout("-b", "feature")

        io = InputOutput()
        git_repo = GitRepo(io, None, ".")
        coder = SimpleNamespace(repo=git_repo, io=io)

        result = git_branch.Tool.execute(coder, show_current=True)

        assert result.strip() == "feature"


def test_gitbranch_show_current_handles_detached_head():
    with GitTemporaryDirectory():
        repo = _make_repo()
        Path("file.txt").write_text("content\n")
        repo.git.add("file.txt")
        repo.git.commit("-m", "init")

        commit_sha = repo.head.commit.hexsha
        repo.git.checkout(commit_sha)

        io = InputOutput()
        git_repo = GitRepo(io, None, ".")
        coder = SimpleNamespace(repo=git_repo, io=io)

        result = git_branch.Tool.execute(coder, show_current=True)

        assert result.strip() == "HEAD (detached)"
