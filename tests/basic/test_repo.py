import os
import platform
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import git
import pytest

from cecli.dump import dump  # noqa: F401
from cecli.io import InputOutput
from cecli.models import Model
from cecli.repo import GitRepo
from cecli.utils import GitTemporaryDirectory


class TestRepo:
    @pytest.fixture(autouse=True)
    def setup(self, gpt35_model):
        self.GPT35 = gpt35_model

    def test_diffs_empty_repo(self):
        with GitTemporaryDirectory():
            repo = git.Repo()

            # Add a change to the index
            fname = Path("foo.txt")
            fname.write_text("index\n")
            repo.git.add(str(fname))

            # Make a change in the working dir
            fname.write_text("workingdir\n")

            git_repo = GitRepo(InputOutput(), None, ".")
            diffs = git_repo.get_diffs()
            assert "index" in diffs
            assert "workingdir" in diffs

    def test_diffs_nonempty_repo(self):
        with GitTemporaryDirectory():
            repo = git.Repo()
            fname = Path("foo.txt")
            fname.touch()
            repo.git.add(str(fname))

            fname2 = Path("bar.txt")
            fname2.touch()
            repo.git.add(str(fname2))

            repo.git.commit("-m", "initial")

            fname.write_text("index\n")
            repo.git.add(str(fname))

            fname2.write_text("workingdir\n")

            git_repo = GitRepo(InputOutput(), None, ".")
            diffs = git_repo.get_diffs()
            assert "index" in diffs
            assert "workingdir" in diffs

    def test_diffs_with_single_byte_encoding(self):
        with GitTemporaryDirectory():
            encoding = "cp1251"

            repo = git.Repo()

            fname = Path("foo.txt")
            fname.write_text("index\n", encoding=encoding)
            repo.git.add(str(fname))

            # Make a change with non-ASCII symbols in the working dir
            fname.write_text("АБВ\n", encoding=encoding)

            git_repo = GitRepo(InputOutput(encoding=encoding), None, ".")
            diffs = git_repo.get_diffs()

            # check that all diff output can be converted to utf-8 for sending to model
            diffs.encode("utf-8")

            assert "index" in diffs
            assert "АБВ" in diffs

    def test_diffs_detached_head(self):
        with GitTemporaryDirectory():
            repo = git.Repo()
            fname = Path("foo.txt")
            fname.touch()
            repo.git.add(str(fname))
            repo.git.commit("-m", "foo")

            fname2 = Path("bar.txt")
            fname2.touch()
            repo.git.add(str(fname2))
            repo.git.commit("-m", "bar")

            fname3 = Path("baz.txt")
            fname3.touch()
            repo.git.add(str(fname3))
            repo.git.commit("-m", "baz")

            repo.git.checkout("HEAD^")

            fname.write_text("index\n")
            repo.git.add(str(fname))

            fname2.write_text("workingdir\n")

            git_repo = GitRepo(InputOutput(), None, ".")
            diffs = git_repo.get_diffs()
            assert "index" in diffs
            assert "workingdir" in diffs

    def test_diffs_between_commits(self):
        with GitTemporaryDirectory():
            repo = git.Repo()
            fname = Path("foo.txt")

            fname.write_text("one\n")
            repo.git.add(str(fname))
            repo.git.commit("-m", "initial")

            fname.write_text("two\n")
            repo.git.add(str(fname))
            repo.git.commit("-m", "second")

            git_repo = GitRepo(InputOutput(), None, ".")
            diffs = git_repo.diff_commits(False, "HEAD~1", "HEAD")
            assert "two" in diffs

    @patch("cecli.models.Model.simple_send_with_retries", new_callable=AsyncMock)
    async def test_get_commit_message(self, mock_send):
        mock_send.side_effect = ["", "a good commit message"]

        model1 = Model("gpt-3.5-turbo")
        model2 = Model("gpt-4")
        dump(model1)
        dump(model2)
        repo = GitRepo(InputOutput(), None, None, models=[model1, model2])

        # Call the get_commit_message method with dummy diff and context
        result = await repo.get_commit_message("dummy diff", "dummy context")

        # Assert that the returned message is the expected one from the second model
        assert result == "a good commit message"

        # Check that simple_send_with_retries was called twice
        assert mock_send.call_count == 2

        # Check that both calls were made with the same messages
        first_call_messages = mock_send.call_args_list[0][0][0]  # Get messages from first call
        second_call_messages = mock_send.call_args_list[1][0][0]  # Get messages from second call
        assert first_call_messages == second_call_messages

    @patch("cecli.models.Model.simple_send_with_retries", new_callable=AsyncMock)
    async def test_get_commit_message_strip_quotes(self, mock_send):
        mock_send.return_value = '"a good commit message"'

        repo = GitRepo(InputOutput(), None, None, models=[self.GPT35])
        # Call the get_commit_message method with dummy diff and context
        result = await repo.get_commit_message("dummy diff", "dummy context")

        # Assert that the returned message is the expected one
        assert result == "a good commit message"

    @patch("cecli.models.Model.simple_send_with_retries", new_callable=AsyncMock)
    async def test_get_commit_message_no_strip_unmatched_quotes(self, mock_send):
        mock_send.return_value = 'a good "commit message"'

        repo = GitRepo(InputOutput(), None, None, models=[self.GPT35])
        # Call the get_commit_message method with dummy diff and context
        result = await repo.get_commit_message("dummy diff", "dummy context")

        # Assert that the returned message is the expected one
        assert result == 'a good "commit message"'

    @patch("cecli.models.Model.simple_send_with_retries", new_callable=AsyncMock)
    async def test_get_commit_message_with_custom_prompt(self, mock_send):
        mock_send.return_value = "Custom commit message"
        custom_prompt = "Generate a commit message in the style of Shakespeare"

        repo = GitRepo(InputOutput(), None, None, models=[self.GPT35], commit_prompt=custom_prompt)
        result = await repo.get_commit_message("dummy diff", "dummy context")

        assert result == "Custom commit message"
        mock_send.assert_called_once()
        args = mock_send.call_args[0]  # Get positional args
        assert args[0][0]["content"] == custom_prompt  # Check first message content

    @pytest.mark.skipif(
        platform.system() == "Windows", reason="Git env var behavior differs on Windows"
    )
    @patch("cecli.repo.GitRepo.get_commit_message")
    async def test_commit_with_custom_committer_name(self, mock_send):
        mock_send.return_value = '"a good commit message"'

        with GitTemporaryDirectory():
            # new repo
            raw_repo = git.Repo()
            raw_repo.config_writer().set_value("user", "name", "Test User").release()

            # add a file and commit it
            fname = Path("file.txt")
            fname.touch()
            raw_repo.git.add(str(fname))
            raw_repo.git.commit("-m", "initial commit")

            io = InputOutput()
            # Initialize GitRepo with default None values for attributes
            git_repo = GitRepo(io, None, None, attribute_author=None, attribute_committer=None)

            # commit a change with coder_edits=True (using default attributes)
            fname.write_text("new content")
            commit_result = await git_repo.commit(fnames=[str(fname)], coder_edits=True)
            assert commit_result is not None

            # check the committer name (defaults interpreted as True)
            commit = raw_repo.head.commit
            assert commit.author.name == "Test User (cecli)"
            assert commit.committer.name == "Test User (cecli)"

            # commit a change without coder_edits (using default attributes)
            fname.write_text("new content again!")
            commit_result = await git_repo.commit(fnames=[str(fname)], coder_edits=False)
            assert commit_result is not None

            # check the committer name (author not modified, committer still modified by default)
            commit = raw_repo.head.commit
            assert commit.author.name == "Test User"
            assert commit.committer.name == "Test User (cecli)"

            # Now test with explicit False
            git_repo_explicit_false = GitRepo(
                io, None, None, attribute_author=False, attribute_committer=False
            )
            fname.write_text("explicit false content")
            commit_result = await git_repo_explicit_false.commit(
                fnames=[str(fname)], coder_edits=True
            )
            assert commit_result is not None
            commit = raw_repo.head.commit
            assert commit.author.name == "Test User"  # Explicit False
            assert commit.committer.name == "Test User"  # Explicit False

            # check that the original committer name is restored
            original_committer_name = os.environ.get("GIT_COMMITTER_NAME")
            assert original_committer_name is None
            original_author_name = os.environ.get("GIT_AUTHOR_NAME")
            assert original_author_name is None

            # Test user commit with explicit no-committer attribution
            git_repo_user_no_committer = GitRepo(io, None, None, attribute_committer=False)
            fname.write_text("user no committer content")
            commit_result = await git_repo_user_no_committer.commit(
                fnames=[str(fname)], coder_edits=False
            )
            assert commit_result is not None
            commit = raw_repo.head.commit
            assert (
                commit.author.name == "Test User"
            ), "Author name should not be modified for user commits"
            assert (
                commit.committer.name == "Test User"
            ), "Committer name should not be modified when attribute_committer=False"

    @pytest.mark.skipif(
        platform.system() == "Windows", reason="Git env var behavior differs on Windows"
    )
    async def test_commit_with_co_authored_by(self):
        with GitTemporaryDirectory():
            # new repo
            raw_repo = git.Repo()
            raw_repo.config_writer().set_value("user", "name", "Test User").release()
            raw_repo.config_writer().set_value("user", "email", "test@example.com").release()

            # add a file and commit it
            fname = Path("file.txt")
            fname.touch()
            raw_repo.git.add(str(fname))
            raw_repo.git.commit("-m", "initial commit")

            # Mock coder args: Co-authored-by enabled, author/committer use default (None)
            mock_coder = MagicMock()
            mock_coder.args.attribute_co_authored_by = True
            mock_coder.args.attribute_author = None  # Default
            mock_coder.args.attribute_committer = None  # Default
            mock_coder.args.attribute_commit_message_author = False
            mock_coder.args.attribute_commit_message_committer = False
            # The code uses coder.main_model.name for the co-authored-by line
            mock_coder.main_model = MagicMock()
            mock_coder.main_model.name = "gpt-test"

            io = InputOutput()
            git_repo = GitRepo(io, None, None)

            # commit a change with coder_edits=True and co-authored-by flag
            fname.write_text("new content")
            commit_result = await git_repo.commit(
                fnames=[str(fname)], coder_edits=True, coder=mock_coder, message="cecli edit"
            )
            assert commit_result is not None

            # check the commit message and author/committer
            commit = raw_repo.head.commit
            assert "Co-authored-by: cecli (gpt-test)" in commit.message
            assert commit.message.splitlines()[0] == "cecli edit"
            # With default (None), co-authored-by takes precedence
            assert (
                commit.author.name == "Test User"
            ), "Author name should not be modified when co-authored-by takes precedence"
            assert (
                commit.committer.name == "Test User"
            ), "Committer name should not be modified when co-authored-by takes precedence"

    @pytest.mark.skipif(
        platform.system() == "Windows", reason="Git env var behavior differs on Windows"
    )
    async def test_commit_co_authored_by_with_explicit_name_modification(self):
        # Test scenario where Co-authored-by is true AND
        # author/committer modification are explicitly True
        with GitTemporaryDirectory():
            # Setup repo...
            # new repo
            raw_repo = git.Repo()
            raw_repo.config_writer().set_value("user", "name", "Test User").release()
            raw_repo.config_writer().set_value("user", "email", "test@example.com").release()

            # add a file and commit it
            fname = Path("file.txt")
            fname.touch()
            raw_repo.git.add(str(fname))
            raw_repo.git.commit("-m", "initial commit")

            # Mock coder args: Co-authored-by enabled,
            # author/committer modification explicitly enabled
            mock_coder = MagicMock()
            mock_coder.args.attribute_co_authored_by = True
            mock_coder.args.attribute_author = True  # Explicitly enable
            mock_coder.args.attribute_committer = True  # Explicitly enable
            mock_coder.args.attribute_commit_message_author = False
            mock_coder.args.attribute_commit_message_committer = False
            mock_coder.main_model = MagicMock()
            mock_coder.main_model.name = "gpt-test-combo"

            io = InputOutput()
            git_repo = GitRepo(io, None, None)

            # commit a change with coder_edits=True and combo flags
            fname.write_text("new content combo")
            commit_result = await git_repo.commit(
                fnames=[str(fname)], coder_edits=True, coder=mock_coder, message="cecli combo edit"
            )
            assert commit_result is not None

            # check the commit message and author/committer
            commit = raw_repo.head.commit
            assert "Co-authored-by: cecli (gpt-test-combo)" in commit.message
            assert commit.message.splitlines()[0] == "cecli combo edit"
            # When co-authored-by is true BUT author/committer are explicit True,
            # modification SHOULD happen
            assert (
                commit.author.name == "Test User (cecli)"
            ), "Author name should be modified when explicitly True, even with co-author"
            assert (
                commit.committer.name == "Test User (cecli)"
            ), "Committer name should be modified when explicitly True, even with co-author"

    @pytest.mark.skipif(
        platform.system() == "Windows", reason="Git env var behavior differs on Windows"
    )
    async def test_commit_ai_edits_no_coauthor_explicit_false(self):
        # Test AI edits (coder_edits=True) when co-authored-by is False,
        # but author or committer attribution is explicitly disabled.
        with GitTemporaryDirectory():
            # Setup repo
            raw_repo = git.Repo()
            raw_repo.config_writer().set_value("user", "name", "Test User").release()
            raw_repo.config_writer().set_value("user", "email", "test@example.com").release()
            fname = Path("file.txt")
            fname.touch()
            raw_repo.git.add(str(fname))
            raw_repo.git.commit("-m", "initial commit")

            io = InputOutput()

            # Case 1: attribute_author = False, attribute_committer = None (default True)
            mock_coder_no_author = MagicMock()
            mock_coder_no_author.args.attribute_co_authored_by = False
            mock_coder_no_author.args.attribute_author = False  # Explicit False
            mock_coder_no_author.args.attribute_committer = None  # Default True
            mock_coder_no_author.args.attribute_commit_message_author = False
            mock_coder_no_author.args.attribute_commit_message_committer = False
            mock_coder_no_author.main_model = MagicMock()
            mock_coder_no_author.main_model.name = "gpt-test-no-author"

            git_repo_no_author = GitRepo(io, None, None)
            fname.write_text("no author content")
            commit_result = await git_repo_no_author.commit(
                fnames=[str(fname)],
                coder_edits=True,
                coder=mock_coder_no_author,
                message="cecli no author",
            )
            assert commit_result is not None
            commit = raw_repo.head.commit
            assert "Co-authored-by:" not in commit.message
            assert commit.author.name == "Test User"  # Explicit False
            assert commit.committer.name == "Test User (cecli)"  # Default True

            # Case 2: attribute_author = None (default True), attribute_committer = False
            mock_coder_no_committer = MagicMock()
            mock_coder_no_committer.args.attribute_co_authored_by = False
            mock_coder_no_committer.args.attribute_author = None  # Default True
            mock_coder_no_committer.args.attribute_committer = False  # Explicit False
            mock_coder_no_committer.args.attribute_commit_message_author = False
            mock_coder_no_committer.args.attribute_commit_message_committer = False
            mock_coder_no_committer.main_model = MagicMock()
            mock_coder_no_committer.main_model.name = "gpt-test-no-committer"

            git_repo_no_committer = GitRepo(io, None, None)
            fname.write_text("no committer content")
            commit_result = await git_repo_no_committer.commit(
                fnames=[str(fname)],
                coder_edits=True,
                coder=mock_coder_no_committer,
                message="cecli no committer",
            )
            assert commit_result is not None
            commit = raw_repo.head.commit
            assert "Co-authored-by:" not in commit.message
            assert (
                commit.author.name == "Test User (cecli)"
            ), "Author name should be modified (default True) when co-author=False"
            assert (
                commit.committer.name == "Test User"
            ), "Committer name should not be modified (explicit False when co-author=False"

    def test_get_tracked_files(self):
        # Create a temporary directory
        tempdir = Path(tempfile.mkdtemp())

        # Initialize a git repository in the temporary directory and set user name and email
        repo = git.Repo.init(tempdir)
        repo.config_writer().set_value("user", "name", "Test User").release()
        repo.config_writer().set_value("user", "email", "testuser@example.com").release()

        # Create three empty files and add them to the git repository
        filenames = ["README.md", "subdir/fänny.md", "systemüber/blick.md", 'file"with"quotes.txt']
        created_files = []
        for filename in filenames:
            file_path = tempdir / filename
            try:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.touch()
                repo.git.add(str(file_path))
                created_files.append(Path(filename))
            except OSError:
                # windows won't allow files with quotes, that's ok
                assert '"' in filename
                assert os.name == "nt"

        assert len(created_files) >= 3

        repo.git.commit("-m", "added")

        tracked_files = GitRepo(InputOutput(), [tempdir], None).get_tracked_files()

        # On windows, paths will come back \like\this, so normalize them back to Paths
        tracked_files = [Path(fn) for fn in tracked_files]

        # Assert that coder.get_tracked_files() returns the three filenames
        assert set(tracked_files) == set(created_files)

    def test_get_tracked_files_with_new_staged_file(self):
        with GitTemporaryDirectory():
            # new repo
            raw_repo = git.Repo()

            # add it, but no commits at all in the raw_repo yet
            fname = Path("new.txt")
            fname.touch()
            raw_repo.git.add(str(fname))

            git_repo = GitRepo(InputOutput(), None, None)

            # better be there
            fnames = git_repo.get_tracked_files()
            assert str(fname) in fnames

            # commit it, better still be there
            raw_repo.git.commit("-m", "new")
            fnames = git_repo.get_tracked_files()
            assert str(fname) in fnames

            # new file, added but not committed
            fname2 = Path("new2.txt")
            fname2.touch()
            raw_repo.git.add(str(fname2))

            # both should be there
            fnames = git_repo.get_tracked_files()
            assert str(fname) in fnames
            assert str(fname2) in fnames

    def test_get_tracked_files_with_cecli_ignore(self):
        with GitTemporaryDirectory():
            # new repo
            raw_repo = git.Repo()

            # add it, but no commits at all in the raw_repo yet
            fname = Path("new.txt")
            fname.touch()
            raw_repo.git.add(str(fname))

            cecli_ignore = Path("cecli.ignore")
            git_repo = GitRepo(InputOutput(), None, None, str(cecli_ignore))

            # better be there
            fnames = git_repo.get_tracked_files()
            assert str(fname) in fnames

            # commit it, better still be there
            raw_repo.git.commit("-m", "new")
            fnames = git_repo.get_tracked_files()
            assert str(fname) in fnames

            # new file, added but not committed
            fname2 = Path("new2.txt")
            fname2.touch()
            raw_repo.git.add(str(fname2))

            # both should be there
            fnames = git_repo.get_tracked_files()
            assert str(fname) in fnames
            assert str(fname2) in fnames

            cecli_ignore.write_text("new.txt\n")
            time.sleep(2)

            # new.txt should be gone!
            fnames = git_repo.get_tracked_files()
            assert str(fname) not in fnames
            assert str(fname2) in fnames

            # This does not work in github actions?!
            # The mtime doesn't change, even if I time.sleep(1)
            # Before doing this write_text()!?
            #
            # cecli.ignore.write_text("new2.txt\n")
            # new2.txt should be gone!
            # fnames = git_repo.get_tracked_files()
            # assert str(fname) in fnames
            # assert str(fname2) not in fnames

    def test_get_tracked_files_from_subdir(self):
        with GitTemporaryDirectory():
            # new repo
            raw_repo = git.Repo()

            # add it, but no commits at all in the raw_repo yet
            fname = Path("subdir/new.txt")
            fname.parent.mkdir()
            fname.touch()
            raw_repo.git.add(str(fname))

            os.chdir(fname.parent)

            git_repo = GitRepo(InputOutput(), None, None)

            # better be there
            fnames = git_repo.get_tracked_files()
            assert str(fname) in fnames

            # commit it, better still be there
            raw_repo.git.commit("-m", "new")
            fnames = git_repo.get_tracked_files()
            assert str(fname) in fnames

    def test_subtree_only(self):
        with GitTemporaryDirectory():
            # Create a new repo
            raw_repo = git.Repo()

            # Create files in different directories
            root_file = Path("root.txt")
            subdir_file = Path("subdir/subdir_file.txt")
            another_subdir_file = Path("another_subdir/another_file.txt")

            root_file.touch()
            subdir_file.parent.mkdir()
            subdir_file.touch()
            another_subdir_file.parent.mkdir()
            another_subdir_file.touch()

            raw_repo.git.add(str(root_file), str(subdir_file), str(another_subdir_file))
            raw_repo.git.commit("-m", "Initial commit")

            # Change to the subdir
            os.chdir(subdir_file.parent)

            # Create GitRepo instance with subtree_only=True
            git_repo = GitRepo(InputOutput(), None, None, subtree_only=True)

            # Test ignored_file method
            assert not git_repo.ignored_file(str(subdir_file))
            assert git_repo.ignored_file(str(root_file))
            assert git_repo.ignored_file(str(another_subdir_file))

            # Test get_tracked_files method
            tracked_files = git_repo.get_tracked_files()
            assert str(subdir_file) in tracked_files
            assert str(root_file) not in tracked_files
            assert str(another_subdir_file) not in tracked_files

    @patch("cecli.models.Model.simple_send_with_retries")
    async def test_noop_commit(self, mock_send):
        mock_send.return_value = '"a good commit message"'

        with GitTemporaryDirectory():
            # new repo
            raw_repo = git.Repo()

            # add it, but no commits at all in the raw_repo yet
            fname = Path("file.txt")
            fname.touch()
            raw_repo.git.add(str(fname))
            raw_repo.git.commit("-m", "new")

            git_repo = GitRepo(InputOutput(), None, None)

            commit_result = await git_repo.commit(fnames=[str(fname)])
            assert commit_result is None

    @pytest.mark.skipif(
        platform.system() == "Windows", reason="Git hook execution differs on Windows"
    )
    async def test_git_commit_verify(self):
        """Test that git_commit_verify controls whether --no-verify is passed to git commit"""
        with GitTemporaryDirectory():
            # Create a new repo
            raw_repo = git.Repo()

            # Create a file to commit
            fname = Path("test_file.txt")
            fname.write_text("initial content")
            raw_repo.git.add(str(fname))

            # Do the initial commit
            raw_repo.git.commit("-m", "Initial commit")

            # Now create a pre-commit hook that always fails
            hooks_dir = Path(raw_repo.git_dir) / "hooks"
            hooks_dir.mkdir(exist_ok=True)

            pre_commit_hook = hooks_dir / "pre-commit"
            pre_commit_hook.write_text("#!/bin/sh\nexit 1\n")  # Always fail
            pre_commit_hook.chmod(0o755)  # Make executable

            # Modify the file
            fname.write_text("modified content")

            # Create GitRepo with verify=True (default)
            io = InputOutput()
            git_repo_verify = GitRepo(io, None, None, git_commit_verify=True)

            # Attempt to commit - should fail due to pre-commit hook
            commit_result = await git_repo_verify.commit(fnames=[str(fname)], message="Should fail")
            assert commit_result is None

            # Create GitRepo with verify=False
            git_repo_no_verify = GitRepo(io, None, None, git_commit_verify=False)

            # Attempt to commit - should succeed by bypassing the hook
            commit_result = await git_repo_no_verify.commit(
                fnames=[str(fname)], message="Should succeed"
            )
            assert commit_result is not None

            # Verify the commit was actually made
            latest_commit_msg = raw_repo.head.commit.message
            assert latest_commit_msg.strip() == "Should succeed"

    @patch("cecli.models.Model.simple_send_with_retries", new_callable=AsyncMock)
    async def test_get_commit_message_uses_system_prompt_prefix(self, mock_send):
        """
        Verify that GitRepo.get_commit_message() prepends the model.system_prompt_prefix
        to the system prompt sent to the LLM.
        """
        mock_send.return_value = "good commit message"

        prefix = "MY-CUSTOM-PREFIX"
        model = Model("gpt-3.5-turbo")
        model.system_prompt_prefix = prefix

        with GitTemporaryDirectory():
            repo = GitRepo(InputOutput(), None, None, models=[model])

            # Call the function under test
            await repo.get_commit_message("dummy diff", "dummy context")

            # Ensure the LLM was invoked once
            mock_send.assert_called_once()

            # Grab the system message sent to the model
            messages = mock_send.call_args[0][0]
            system_msg_content = messages[0]["content"]

            # Verify the prefix is at the start of the system message
            assert system_msg_content.startswith(
                prefix
            ), "system_prompt_prefix should be prepended to the system prompt"
