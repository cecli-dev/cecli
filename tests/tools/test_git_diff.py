from pathlib import Path
from types import SimpleNamespace

import git

from cecli.io import InputOutput
from cecli.repo import GitRepo
from cecli.tools import git_diff
from cecli.utils import GitTemporaryDirectory


def test_gitdiff_head_argument_includes_working_tree_changes():
    with GitTemporaryDirectory():
        repo = git.Repo()
        fname = Path("example.txt")
        fname.write_text("original\n")
        repo.git.add(str(fname))
        repo.config_writer().set_value("commit", "gpgsign", "false").release()
        repo.git.commit("-m", "initial")

        fname.write_text("updated\n")

        io = InputOutput()
        git_repo = GitRepo(io, None, ".")
        coder = SimpleNamespace(repo=git_repo, io=io)

        result = git_diff.Tool.execute(coder, branch="HEAD")

        assert "updated" in result
