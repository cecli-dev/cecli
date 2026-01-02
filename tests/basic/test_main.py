import asyncio
import json
import os
import platform
import subprocess
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import git
import pytest
from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput

from cecli.coders import Coder, CopyPasteCoder
from cecli.commands import SwitchCoder
from cecli.dump import dump
from cecli.helpers.file_searcher import handle_core_files
from cecli.io import InputOutput
from cecli.main import check_gitignore, load_dotenv_files, main, setup_git
from cecli.utils import (
    ChdirTemporaryDirectory,
    GitTemporaryDirectory,
    IgnorantTemporaryDirectory,
    make_repo,
)


def mock_autosave_future():
    """Create an awaitable mock for _autosave_future.

    Returns AsyncMock()() - the first call creates an async mock function,
    the second call invokes it to get an awaitable coroutine object.
    """
    return AsyncMock()()


@pytest.fixture
def temp_cwd():
    """Provide a temporary current working directory with automatic chdir."""
    with ChdirTemporaryDirectory() as tempdir:
        yield tempdir


@pytest.fixture
def temp_home():
    """Provide a temporary home directory."""
    with IgnorantTemporaryDirectory() as homedir:
        yield homedir


@pytest.fixture(autouse=True)
def test_env(mocker, temp_cwd, temp_home):
    """Provide isolated test environment for all tests.

    Automatically sets up:
    - Fake API keys and environment variables (completely isolated)
    - Temporary working directory (with automatic chdir)
    - Fake home directory to prevent ~/.cecli.conf.yml interference
    - Mocked user input and browser opening
    - Windows compatibility (USERPROFILE vs HOME)

    All resources are automatically cleaned up by dependency fixtures and mocker.
    """
    test_env_vars = {
        "OPENAI_API_KEY": "deadbeef",
        "CECLICHECK_UPDATE": "false",
        "CECLIANALYTICS": "false",
    }
    if platform.system() == "Windows":
        test_env_vars["USERPROFILE"] = temp_home
    else:
        test_env_vars["HOME"] = temp_home
    mocker.patch.dict(os.environ, test_env_vars)
    mocker.patch("builtins.input", return_value=None)
    mocker.patch("cecli.io.webbrowser.open")


@pytest.fixture
def dummy_io():
    """Provide DummyInput and DummyOutput for tests."""
    return {"input": DummyInput(), "output": DummyOutput()}


@pytest.fixture
def mock_coder(mocker):
    """Provide a properly configured Mock Coder with autosave future."""
    MockCoder = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MockCoder.return_value
    mock_coder_instance._autosave_future = mock_autosave_future()
    return MockCoder


@pytest.fixture
def git_temp_dir():
    """Provide a temporary git directory."""
    with GitTemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


def test_main_with_empty_dir_no_files_on_command(dummy_io):
    main(["--no-git", "--exit", "--yes-always"], **dummy_io)


def test_main_with_empty_dir_new_file(dummy_io):
    main(["foo.txt", "--yes-always", "--no-git", "--exit"], **dummy_io)
    assert os.path.exists("foo.txt")


def test_main_with_empty_git_dir_new_file(dummy_io, mocker):
    mocker.patch("cecli.repo.GitRepo.get_commit_message", return_value="mock commit message")
    make_repo()
    main(["--yes-always", "foo.txt", "--exit"], **dummy_io)
    assert os.path.exists("foo.txt")


def test_main_with_empty_git_dir_new_files(dummy_io, mocker):
    mocker.patch("cecli.repo.GitRepo.get_commit_message", return_value="mock commit message")
    make_repo()
    main(["--yes-always", "foo.txt", "bar.txt", "--exit"], **dummy_io)
    assert os.path.exists("foo.txt")
    assert os.path.exists("bar.txt")


def test_main_with_subdir_and_fname(dummy_io, git_temp_dir):
    subdir = Path("subdir")
    subdir.mkdir()
    make_repo(str(subdir))
    res = main(["subdir", "foo.txt"], **dummy_io)
    assert res is not None


def test_main_with_subdir_repo_fnames(dummy_io, git_temp_dir, mocker):
    mocker.patch("cecli.repo.GitRepo.get_commit_message", return_value="mock commit message")
    subdir = Path("subdir")
    subdir.mkdir()
    make_repo(str(subdir))
    main(["--yes-always", str(subdir / "foo.txt"), str(subdir / "bar.txt"), "--exit"], **dummy_io)
    assert (subdir / "foo.txt").exists()
    assert (subdir / "bar.txt").exists()


def test_main_copy_paste_model_overrides(dummy_io, git_temp_dir):
    overrides = json.dumps({"gpt-4o": {"fast": {"temperature": 0.42}}})
    coder = main(
        [
            "--no-git",
            "--exit",
            "--yes-always",
            "--model",
            "cp:gpt-4o:fast",
            "--model-overrides",
            overrides,
        ],
        **dummy_io,
        return_coder=True,
    )
    assert isinstance(coder, CopyPasteCoder)
    assert coder.main_model.copy_paste_mode
    assert coder.main_model.copy_paste_transport == "clipboard"
    assert coder.main_model.override_kwargs == {"temperature": 0.42}


def test_main_copy_paste_flag_sets_mode(dummy_io, git_temp_dir, mocker):
    mock_watcher = mocker.patch("cecli.main.ClipboardWatcher")
    mock_watcher.return_value = MagicMock()
    coder = main(
        ["--no-git", "--exit", "--yes-always", "--copy-paste"], **dummy_io, return_coder=True
    )
    assert not isinstance(coder, CopyPasteCoder)
    assert coder.main_model.copy_paste_mode
    assert coder.main_model.copy_paste_transport == "api"
    assert coder.copy_paste_mode
    assert not coder.manual_copy_paste


def test_main_with_git_config_yml(dummy_io, mock_coder, git_temp_dir):
    make_repo()
    Path(".cecli.conf.yml").write_text("auto-commits: false\n")
    main(["--yes-always"], **dummy_io)
    _, kwargs = mock_coder.call_args
    assert kwargs["auto_commits"] is False
    Path(".cecli.conf.yml").write_text("auto-commits: true\n")
    mock_coder.reset_mock()
    mock_coder.return_value._autosave_future = mock_autosave_future()
    main([], **dummy_io)
    _, kwargs = mock_coder.call_args
    assert kwargs["auto_commits"] is True


def test_main_with_empty_git_dir_new_subdir_file(dummy_io, git_temp_dir):
    make_repo()
    subdir = Path("subdir")
    subdir.mkdir()
    fname = subdir / "foo.txt"
    fname.touch()
    subprocess.run(["git", "add", str(subdir)])
    subprocess.run(["git", "commit", "-m", "added"])
    main(["--yes-always", str(fname), "--exit"], **dummy_io)


def test_setup_git(dummy_io):
    io = InputOutput(pretty=False, yes=True)
    git_root = asyncio.run(setup_git(None, io))
    git_root = Path(git_root).resolve()
    assert git_root == Path(os.getcwd()).resolve()
    assert git.Repo(os.getcwd())
    gitignore = Path.cwd() / ".gitignore"
    assert gitignore.exists()
    assert ".cecli*" == gitignore.read_text().splitlines()[0]


def test_check_gitignore(dummy_io, git_temp_dir, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "globalgitconfig")
    io = InputOutput(pretty=False, yes=True)
    cwd = Path.cwd()
    gitignore = cwd / ".gitignore"
    assert not gitignore.exists()
    asyncio.run(check_gitignore(cwd, io))
    assert gitignore.exists()
    assert ".cecli*" == gitignore.read_text().splitlines()[0]
    gitignore.write_text("one\ntwo\n")
    asyncio.run(check_gitignore(cwd, io))
    assert "one\ntwo\n.cecli*\n" == gitignore.read_text()
    env_file = cwd / ".env"
    env_file.touch()
    asyncio.run(check_gitignore(cwd, io))
    assert "one\ntwo\n.cecli*\n.env\n" == gitignore.read_text()


@pytest.mark.parametrize(
    "flag,should_include",
    [(None, False), ("--add-gitignore-files", True), ("--no-add-gitignore-files", False)],
    ids=["default", "enabled", "disabled"],
)
def test_gitignore_files_flag_command_line(dummy_io, git_temp_dir, flag, should_include):
    """Test --add-gitignore-files flag with command-line arguments."""
    ignored_file = _create_gitignore_test_files(git_temp_dir)
    abs_ignored_file = str(ignored_file.resolve())
    args = ["--exit", "--yes-always"]
    if flag:
        args.insert(0, flag)
    args.append(abs_ignored_file)
    coder = main(args, **dummy_io, return_coder=True, force_git_root=git_temp_dir)
    if should_include:
        assert abs_ignored_file in coder.abs_fnames
    else:
        assert abs_ignored_file not in coder.abs_fnames


@pytest.mark.parametrize(
    "flag,should_include",
    [(None, False), ("--add-gitignore-files", True), ("--no-add-gitignore-files", False)],
    ids=["default", "enabled", "disabled"],
)
def test_gitignore_files_flag_add_command(dummy_io, git_temp_dir, flag, should_include):
    """Test --add-gitignore-files flag with /add command."""
    ignored_file = _create_gitignore_test_files(git_temp_dir)
    abs_ignored_file = str(ignored_file.resolve())
    args = ["--exit", "--yes-always"]
    if flag:
        args.insert(0, flag)
    coder = main(args, **dummy_io, return_coder=True, force_git_root=git_temp_dir)
    try:
        asyncio.run(coder.commands.do_run("add", "ignored.txt"))
    except SwitchCoder:
        pass
    if should_include:
        assert abs_ignored_file in coder.abs_fnames
    else:
        assert abs_ignored_file not in coder.abs_fnames


def _create_gitignore_test_files(git_temp_dir):
    """Helper to create gitignore test files."""
    gitignore_file = git_temp_dir / ".gitignore"
    gitignore_file.write_text("ignored.txt\n")
    ignored_file = git_temp_dir / "ignored.txt"
    ignored_file.write_text("This file should be ignored.")
    return ignored_file


@pytest.mark.parametrize(
    "args,expected_kwargs",
    [
        (["--no-auto-commits", "--yes-always"], {"auto_commits": False}),
        (["--auto-commits", "--no-git"], {"auto_commits": True}),
        (["--no-git"], {"dirty_commits": True, "auto_commits": True}),
        (["--no-dirty-commits", "--no-git"], {"dirty_commits": False}),
        (["--dirty-commits", "--no-git"], {"dirty_commits": True}),
    ],
    ids=["no_auto_commits", "auto_commits", "defaults", "no_dirty_commits", "dirty_commits"],
)
def test_main_args(args, expected_kwargs, dummy_io, mock_coder, git_temp_dir):
    main(args, **dummy_io)
    _, kwargs = mock_coder.call_args
    for key, expected_value in expected_kwargs.items():
        assert kwargs[key] is expected_value


def test_env_file_override(dummy_io, git_temp_dir, mocker, monkeypatch):
    git_env = git_temp_dir / ".env"
    fake_home = git_temp_dir / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    home_env = fake_home / ".env"
    cwd = git_temp_dir / "subdir"
    cwd.mkdir()
    os.chdir(cwd)
    cwd_env = cwd / ".env"
    named_env = git_temp_dir / "named.env"
    monkeypatch.setenv("E", "existing")
    home_env.write_text("A=home\nB=home\nC=home\nD=home")
    git_env.write_text("A=git\nB=git\nC=git")
    cwd_env.write_text("A=cwd\nB=cwd")
    named_env.write_text("A=named")
    mocker.patch("pathlib.Path.home", return_value=fake_home)
    main(["--yes-always", "--exit", "--env-file", str(named_env)])
    assert os.environ["A"] == "named"
    assert os.environ["B"] == "cwd"
    assert os.environ["C"] == "git"
    assert os.environ["D"] == "home"
    assert os.environ["E"] == "existing"


def test_message_file_flag(dummy_io, git_temp_dir, mocker, tmp_path):
    message_file_content = "This is a test message from a file."
    message_file = tmp_path / "message.txt"
    message_file.write_text(message_file_content, encoding="utf-8")

    async def mock_run(*args, **kwargs):
        pass

    MockCoder = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MagicMock()
    mock_coder_instance.run = AsyncMock()
    mock_coder_instance._autosave_future = mock_autosave_future()
    MockCoder.return_value = mock_coder_instance
    main(["--yes-always", "--message-file", str(message_file)], **dummy_io)
    mock_coder_instance.run.assert_called_once_with(with_message=message_file_content)


def test_encodings_arg(dummy_io, git_temp_dir, mocker):
    fname = "foo.py"
    MockCoder = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MockCoder.return_value
    mock_coder_instance._autosave_future = mock_autosave_future()
    MockSend = mocker.patch("cecli.main.InputOutput")

    def side_effect(*args, **kwargs):
        assert kwargs["encoding"] == "iso-8859-15"
        mock_io = MagicMock()
        mock_io.confirm_ask = AsyncMock(return_value=True)
        return mock_io

    MockSend.side_effect = side_effect
    main(["--yes-always", fname, "--encoding", "iso-8859-15"])


def test_main_exit_calls_version_check(dummy_io, git_temp_dir, mocker):
    mock_check_version = mocker.patch("cecli.main.check_version")
    mock_input_output = mocker.patch("cecli.main.InputOutput")
    mock_input_output.return_value.confirm_ask = AsyncMock(return_value=True)
    main(["--exit", "--check-update"], **dummy_io)
    mock_check_version.assert_called_once()
    mock_input_output.assert_called_once()


def test_main_message_adds_to_input_history(dummy_io, mocker):
    mocker.patch("cecli.coders.base_coder.Coder.run")
    MockInputOutput = mocker.patch("cecli.main.InputOutput", autospec=True)
    test_message = "test message"
    mock_io_instance = MockInputOutput.return_value
    mock_io_instance.pretty = True
    main(["--message", test_message], **dummy_io)
    mock_io_instance.add_to_input_history.assert_called_once_with(test_message)


def test_yes_always(dummy_io, mocker):
    mocker.patch("cecli.coders.base_coder.Coder.run")
    MockInputOutput = mocker.patch("cecli.main.InputOutput", autospec=True)
    test_message = "test message"
    MockInputOutput.return_value.pretty = True
    main(["--yes-always", "--message", test_message])
    args, kwargs = MockInputOutput.call_args
    assert args[1]


def test_default_of_yes_all_is_none(dummy_io, mocker):
    mocker.patch("cecli.coders.base_coder.Coder.run")
    MockInputOutput = mocker.patch("cecli.main.InputOutput", autospec=True)
    test_message = "test message"
    MockInputOutput.return_value.pretty = True
    main(["--message", test_message])
    args, kwargs = MockInputOutput.call_args
    assert args[1] is None


@pytest.mark.parametrize(
    "mode_flag,expected_theme",
    [("--dark-mode", "monokai"), ("--light-mode", "default")],
    ids=["dark_mode", "light_mode"],
)
def test_mode_sets_code_theme(mode_flag, expected_theme, dummy_io, git_temp_dir, mocker):
    MockInputOutput = mocker.patch("cecli.main.InputOutput")
    MockInputOutput.return_value.get_input.return_value = None
    main([mode_flag, "--no-git", "--exit"], **dummy_io)
    MockInputOutput.assert_called_once()
    _, kwargs = MockInputOutput.call_args
    assert kwargs["code_theme"] == expected_theme


@pytest.mark.parametrize(
    "env_file,env_content,check_attribute,expected_value,use_flag",
    [
        (".env.test", "CECLIDARK_MODE=True", "code_theme", "monokai", True),
        (".env", "CECLIDARK_MODE=True", "code_theme", "monokai", False),
        (".env", "CECLISHOW_DIFFS=off", "show_diffs", False, False),
        (".env", "CECLISHOW_DIFFS=on", "show_diffs", True, False),
    ],
    ids=["dark_mode_with_flag", "dark_mode_default", "bool_false", "bool_true"],
)
def test_env_file_variables(
    dummy_io, mocker, mock_coder, env_file, env_content, check_attribute, expected_value, use_flag
):
    """Test environment file variable loading and parsing."""
    env_file_path = Path(env_file)
    env_file_path.write_text(env_content)
    is_dark_mode_test = check_attribute == "code_theme"
    if is_dark_mode_test:
        MockInputOutput = mocker.patch("cecli.main.InputOutput")
        MockInputOutput.return_value.get_input.return_value = None
        MockInputOutput.return_value.get_input.confirm_ask = True
    args = ["--no-git", "--exit" if is_dark_mode_test else "--yes-always"]
    if use_flag:
        args.extend(["--env-file", str(env_file_path)])
    main(args, **dummy_io)
    if is_dark_mode_test:
        MockInputOutput.assert_called_once()
        _, kwargs = MockInputOutput.call_args
    else:
        mock_coder.assert_called_once()
        _, kwargs = mock_coder.call_args
    assert kwargs[check_attribute] == expected_value


def test_lint_option(dummy_io, git_temp_dir, mocker):
    dirty_file = Path("dirty_file.py")
    dirty_file.write_text("""def foo():
    return 'bar'""")
    repo = git.Repo(".")
    repo.git.add(str(dirty_file))
    repo.git.commit("-m", "new")
    dirty_file.write_text("""def foo():
    return '!!!!!'""")
    subdir = git_temp_dir / "subdir"
    subdir.mkdir()
    os.chdir(subdir)
    MockLinter = mocker.patch("cecli.linter.Linter.lint")
    MockLinter.return_value = ""
    main(["--lint", "--yes-always"], **dummy_io)
    MockLinter.assert_called_once()
    called_arg = MockLinter.call_args[0][0]
    assert called_arg.endswith("dirty_file.py")
    assert not called_arg.endswith(f"subdir{os.path.sep}dirty_file.py")


def test_lint_option_with_explicit_files(dummy_io, git_temp_dir, mocker):
    file1 = Path("file1.py")
    file1.write_text("def foo(): pass")
    file2 = Path("file2.py")
    file2.write_text("def bar(): pass")
    MockLinter = mocker.patch("cecli.linter.Linter.lint")
    MockLinter.return_value = ""
    main(["--lint", "file1.py", "file2.py", "--yes-always"], **dummy_io)
    assert MockLinter.call_count == 2
    called_files = [call[0][0] for call in MockLinter.call_args_list]
    assert any(f.endswith("file1.py") for f in called_files)
    assert any(f.endswith("file2.py") for f in called_files)


def test_lint_option_with_glob_pattern(dummy_io, git_temp_dir, mocker):
    file1 = Path("test1.py")
    file1.write_text("def foo(): pass")
    file2 = Path("test2.py")
    file2.write_text("def bar(): pass")
    file3 = Path("readme.txt")
    file3.write_text("not a python file")
    MockLinter = mocker.patch("cecli.linter.Linter.lint")
    MockLinter.return_value = ""
    main(["--lint", "test*.py", "--yes-always"], **dummy_io)
    assert MockLinter.call_count >= 2
    called_files = [call[0][0] for call in MockLinter.call_args_list]
    assert any(f.endswith("test1.py") for f in called_files)
    assert any(f.endswith("test2.py") for f in called_files)
    assert not any(f.endswith("readme.txt") for f in called_files)


def test_verbose_mode_lists_env_vars(dummy_io, mocker, capsys):
    Path(".env").write_text("CECLIDARK_MODE=on")
    main(["--no-git", "--verbose", "--exit", "--yes-always"], **dummy_io)
    captured = capsys.readouterr()
    output = captured.out
    relevant_output = "\n".join(
        line for line in output.splitlines() if "CECLIDARK_MODE" in line or "dark_mode" in line
    )
    assert "CECLIDARK_MODE" in relevant_output
    assert "dark_mode" in relevant_output
    import re

    assert re.search("CECLIDARK_MODE:\\s+on", relevant_output)
    assert re.search("dark_mode:\\s+True", relevant_output)


def test_yaml_config_loads_from_named_file(dummy_io, git_temp_dir, mocker, monkeypatch):
    fake_home = git_temp_dir / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    mocker.patch("pathlib.Path.home", return_value=fake_home)
    named_config = git_temp_dir / "named.cecli.conf.yml"
    named_config.write_text("model: gpt-4-1106-preview\nmap-tokens: 8192\n")
    MockCoder = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MockCoder.return_value
    mock_coder_instance._autosave_future = mock_autosave_future()
    main(["--yes-always", "--exit", "--config", str(named_config)], **dummy_io)
    _, kwargs = MockCoder.call_args
    assert kwargs["main_model"].name == "gpt-4-1106-preview"
    assert kwargs["map_tokens"] == 8192


def test_yaml_config_loads_from_cwd(dummy_io, git_temp_dir, mocker, monkeypatch):
    fake_home = git_temp_dir / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    mocker.patch("pathlib.Path.home", return_value=fake_home)
    cwd = git_temp_dir / "subdir"
    cwd.mkdir()
    os.chdir(cwd)
    cwd_config = cwd / ".cecli.conf.yml"
    cwd_config.write_text("model: gpt-4-32k\nmap-tokens: 4096\n")
    MockCoder = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MockCoder.return_value
    mock_coder_instance._autosave_future = mock_autosave_future()
    main(["--yes-always", "--exit"], **dummy_io)
    _, kwargs = MockCoder.call_args
    assert kwargs["main_model"].name == "gpt-4-32k"
    assert kwargs["map_tokens"] == 4096


def test_yaml_config_loads_from_git_root(dummy_io, git_temp_dir, mocker, monkeypatch):
    fake_home = git_temp_dir / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    mocker.patch("pathlib.Path.home", return_value=fake_home)
    cwd = git_temp_dir / "subdir"
    cwd.mkdir()
    os.chdir(cwd)
    git_config = git_temp_dir / ".cecli.conf.yml"
    git_config.write_text("model: gpt-4\nmap-tokens: 2048\n")
    MockCoder = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MockCoder.return_value
    mock_coder_instance._autosave_future = mock_autosave_future()
    main(["--yes-always", "--exit"], **dummy_io)
    _, kwargs = MockCoder.call_args
    assert kwargs["main_model"].name == "gpt-4"
    assert kwargs["map_tokens"] == 2048


def test_yaml_config_loads_from_home(dummy_io, git_temp_dir, mocker, monkeypatch):
    fake_home = git_temp_dir / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    mocker.patch("pathlib.Path.home", return_value=fake_home)
    cwd = git_temp_dir / "subdir"
    cwd.mkdir()
    os.chdir(cwd)
    home_config = fake_home / ".cecli.conf.yml"
    home_config.write_text("model: gpt-3.5-turbo\nmap-tokens: 1024\n")
    MockCoder = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MockCoder.return_value
    mock_coder_instance._autosave_future = mock_autosave_future()
    main(["--yes-always", "--exit"], **dummy_io)
    _, kwargs = MockCoder.call_args
    assert kwargs["main_model"].name == "gpt-3.5-turbo"
    assert kwargs["map_tokens"] == 1024


def test_map_tokens_option(dummy_io, git_temp_dir, mocker):
    MockRepoMap = mocker.patch("cecli.coders.base_coder.RepoMap")
    MockRepoMap.return_value.max_map_tokens = 0
    main(["--model", "gpt-4", "--map-tokens", "0", "--exit", "--yes-always"], **dummy_io)
    MockRepoMap.assert_not_called()


def test_map_tokens_option_with_non_zero_value(dummy_io, git_temp_dir, mocker):
    MockRepoMap = mocker.patch("cecli.coders.base_coder.RepoMap")
    MockRepoMap.return_value.max_map_tokens = 1000
    main(["--model", "gpt-4", "--map-tokens", "1000", "--exit", "--yes-always"], **dummy_io)
    MockRepoMap.assert_called_once()


def test_read_option(dummy_io, git_temp_dir):
    test_file = "test_file.txt"
    Path(test_file).touch()
    coder = main(["--read", test_file, "--exit", "--yes-always"], **dummy_io, return_coder=True)
    assert str(Path(test_file).resolve()) in coder.abs_read_only_fnames


def test_read_option_with_external_file(dummy_io, git_temp_dir, tmp_path):
    external_file = tmp_path / "external_file.txt"
    external_file.write_text("External file content")
    coder = main(
        ["--read", str(external_file), "--exit", "--yes-always"], **dummy_io, return_coder=True
    )
    real_external_file_path = str(external_file.resolve())
    assert real_external_file_path in coder.abs_read_only_fnames


def test_model_metadata_file(dummy_io, git_temp_dir):
    from cecli import models

    models.model_info_manager = models.ModelInfoManager()
    from cecli.llm import litellm

    litellm._lazy_module = None
    metadata_file = Path(".cecli.model.metadata.json")
    metadata_content = {"deepseek/deepseek-chat": {"max_input_tokens": 1234}}
    metadata_file.write_text(json.dumps(metadata_content))
    coder = main(
        [
            "--model",
            "deepseek/deepseek-chat",
            "--model-metadata-file",
            str(metadata_file),
            "--exit",
            "--yes-always",
        ],
        **dummy_io,
        return_coder=True,
    )
    assert coder.main_model.info["max_input_tokens"] == 1234


def test_sonnet_and_cache_options(dummy_io, git_temp_dir, mocker):
    MockRepoMap = mocker.patch("cecli.coders.base_coder.RepoMap")
    mock_repo_map = MagicMock()
    mock_repo_map.max_map_tokens = 1000
    MockRepoMap.return_value = mock_repo_map
    main(["--sonnet", "--cache-prompts", "--exit", "--yes-always"], **dummy_io)
    MockRepoMap.assert_called_once()
    call_args, call_kwargs = MockRepoMap.call_args
    assert call_kwargs.get("refresh") == "files"


def test_sonnet_and_cache_prompts_options(dummy_io, git_temp_dir):
    coder = main(
        ["--sonnet", "--cache-prompts", "--exit", "--yes-always"], **dummy_io, return_coder=True
    )
    assert coder.add_cache_headers


def test_4o_and_cache_options(dummy_io, git_temp_dir):
    coder = main(
        ["--4o", "--cache-prompts", "--exit", "--yes-always"], **dummy_io, return_coder=True
    )
    assert not coder.add_cache_headers


def test_return_coder(dummy_io, git_temp_dir):
    result = main(["--exit", "--yes-always"], **dummy_io, return_coder=True)
    assert isinstance(result, Coder)
    result = main(["--exit", "--yes-always"], **dummy_io, return_coder=False)
    assert result == 0


def test_map_mul_option(dummy_io, git_temp_dir):
    coder = main(["--map-mul", "5", "--exit", "--yes-always"], **dummy_io, return_coder=True)
    assert isinstance(coder, Coder)
    assert coder.repo_map.map_mul_no_files == 5


@pytest.mark.parametrize(
    "flag_arg,attr_name,expected",
    [
        (None, "suggest_shell_commands", True),
        ("--no-suggest-shell-commands", "suggest_shell_commands", False),
        ("--suggest-shell-commands", "suggest_shell_commands", True),
        (None, "detect_urls", True),
        ("--no-detect-urls", "detect_urls", False),
        ("--detect-urls", "detect_urls", True),
    ],
    ids=[
        "suggest_default",
        "suggest_disabled",
        "suggest_enabled",
        "urls_default",
        "urls_disabled",
        "urls_enabled",
    ],
)
def test_boolean_flags(flag_arg, attr_name, expected, dummy_io, git_temp_dir):
    args = ["--exit", "--yes-always"]
    if flag_arg:
        args.insert(0, flag_arg)
    coder = main(args, **dummy_io, return_coder=True)
    assert getattr(coder, attr_name) == expected


@pytest.mark.parametrize(
    "model,setting_flag,setting_value,method_name,check_flag,should_warn,should_call",
    [
        (
            "anthropic/claude-3-7-sonnet-20250219",
            "--thinking-tokens",
            "1000",
            "set_thinking_tokens",
            None,
            False,
            True,
        ),
        (
            "gpt-4o",
            "--thinking-tokens",
            "1000",
            "set_thinking_tokens",
            "--check-model-accepts-settings",
            True,
            False,
        ),
        ("o1", "--reasoning-effort", "3", "set_reasoning_effort", None, False, True),
        ("gpt-3.5-turbo", "--reasoning-effort", "3", "set_reasoning_effort", None, True, False),
    ],
    ids=[
        "thinking_tokens_accepted",
        "thinking_tokens_rejected",
        "reasoning_effort_accepted",
        "reasoning_effort_rejected",
    ],
)
def test_accepts_settings_warnings(
    dummy_io,
    git_temp_dir,
    mocker,
    model,
    setting_flag,
    setting_value,
    method_name,
    check_flag,
    should_warn,
    should_call,
):
    mock_warning = mocker.patch("cecli.io.InputOutput.tool_warning")
    mock_method = mocker.patch(f"cecli.models.Model.{method_name}")
    args = ["--model", model, setting_flag, setting_value, "--yes-always", "--exit"]
    if check_flag:
        args.insert(4, check_flag)
    main(args, **dummy_io)
    setting_name = setting_flag.lstrip("--").replace("-", "_")
    warnings = [call[0][0] for call in mock_warning.call_args_list]
    warning_shown = any(setting_name in w for w in warnings)
    assert (
        warning_shown == should_warn
    ), f"Expected warning={should_warn} for {setting_name} but got {warning_shown}"
    if should_call:
        mock_method.assert_called_once_with(setting_value)
    else:
        mock_method.assert_not_called()


def test_no_verify_ssl_sets_model_info_manager(dummy_io, git_temp_dir, mocker):
    mock_set_verify_ssl = mocker.patch("cecli.models.ModelInfoManager.set_verify_ssl")
    mock_model = mocker.patch("cecli.models.Model")
    mock_model.return_value.info = {}
    mock_model.return_value.name = "gpt-4"
    mock_model.return_value.validate_environment.return_value = {
        "missing_keys": [],
        "keys_in_environment": [],
    }
    mocker.patch("cecli.models.fuzzy_match_models", return_value=[])
    main(["--no-verify-ssl", "--exit", "--yes-always"], **dummy_io)
    mock_set_verify_ssl.assert_called_once_with(False)


def test_pytest_env_vars(dummy_io, git_temp_dir):
    assert os.environ.get("CECLIANALYTICS") == "false"


@pytest.mark.parametrize(
    "set_env_args,expected_env,expected_result",
    [
        (["--set-env", "TEST_VAR=test_value"], {"TEST_VAR": "test_value"}, None),
        (
            ["--set-env", "TEST_VAR1=value1", "--set-env", "TEST_VAR2=value2"],
            {"TEST_VAR1": "value1", "TEST_VAR2": "value2"},
            None,
        ),
        (
            ["--set-env", "TEST_VAR=test value with spaces"],
            {"TEST_VAR": "test value with spaces"},
            None,
        ),
        (["--set-env", "INVALID_FORMAT"], {}, 1),
    ],
    ids=["single", "multiple", "with_spaces", "invalid_format"],
)
def test_set_env(set_env_args, expected_env, expected_result, dummy_io, git_temp_dir):
    args = set_env_args + ["--exit", "--yes-always"]
    result = main(args)
    if expected_result is not None:
        assert result == expected_result
    for env_var, expected_value in expected_env.items():
        assert os.environ.get(env_var) == expected_value


@pytest.mark.parametrize(
    "api_key_args,expected_env,expected_result",
    [
        (["--api-key", "anthropic=test-key"], {"ANTHROPIC_API_KEY": "test-key"}, None),
        (
            ["--api-key", "anthropic=key1", "--api-key", "openai=key2"],
            {"ANTHROPIC_API_KEY": "key1", "OPENAI_API_KEY": "key2"},
            None,
        ),
        (["--api-key", "INVALID_FORMAT"], {}, 1),
    ],
    ids=["single", "multiple", "invalid_format"],
)
def test_api_key(api_key_args, expected_env, expected_result, dummy_io, git_temp_dir):
    args = api_key_args + ["--exit", "--yes-always"]
    result = main(args)
    if expected_result is not None:
        assert result == expected_result
    for env_var, expected_value in expected_env.items():
        assert os.environ.get(env_var) == expected_value


def test_git_config_include(dummy_io, git_temp_dir):
    include_config = git_temp_dir / "included.gitconfig"
    include_config.write_text("""[user]
    name = Included User
    email = included@example.com
""")
    repo = git.Repo(git_temp_dir)
    include_path = str(include_config).replace("\\", "/")
    repo.git.config("--local", "include.path", str(include_path))
    assert repo.git.config("user.name") == "Included User"
    assert repo.git.config("user.email") == "included@example.com"
    git_config_path = git_temp_dir / ".git" / "config"
    git_config_content = git_config_path.read_text()
    main(["--yes-always", "--exit"], **dummy_io)
    repo = git.Repo(git_temp_dir)
    assert repo.git.config("user.name") == "Included User"
    assert repo.git.config("user.email") == "included@example.com"
    git_config_content_after = git_config_path.read_text()
    assert git_config_content == git_config_content_after


def test_git_config_include_directive(dummy_io, git_temp_dir):
    include_config = git_temp_dir / "included.gitconfig"
    include_config.write_text("""[user]
    name = Directive User
    email = directive@example.com
""")
    git_config = git_temp_dir / ".git" / "config"
    include_path = str(include_config).replace("\\", "/")
    with open(git_config, "a") as f:
        f.write(f"\n[include]\n    path = {include_path}\n")
    modified_config_content = git_config.read_text()
    assert "[include]" in modified_config_content
    repo = git.Repo(git_temp_dir)
    assert repo.git.config("user.name") == "Directive User"
    assert repo.git.config("user.email") == "directive@example.com"
    main(["--yes-always", "--exit"], **dummy_io)
    config_after_cecli = git_config.read_text()
    assert modified_config_content == config_after_cecli
    repo = git.Repo(git_temp_dir)
    assert repo.git.config("user.name") == "Directive User"
    assert repo.git.config("user.email") == "directive@example.com"


def test_resolve_cecli_ignore_path(dummy_io, git_temp_dir):
    from cecli.args import resolve_cecli_ignore_path

    abs_path = os.path.abspath("/tmp/test/.cecli_ignore")
    assert resolve_cecli_ignore_path(abs_path) == abs_path
    git_root = "/path/to/git/root"
    rel_path = "cecli.ignore"
    assert resolve_cecli_ignore_path(rel_path, git_root) == str(Path(git_root) / rel_path)
    rel_path = "cecli.ignore"
    assert resolve_cecli_ignore_path(rel_path) == rel_path


def test_invalid_edit_format(dummy_io, git_temp_dir, mocker, capsys):
    with pytest.raises(SystemExit) as cm:
        _ = main(["--edit-format", "not-a-real-format", "--exit", "--yes-always"], **dummy_io)
    assert cm.value.code == 2
    captured = capsys.readouterr()
    stderr_output = captured.err
    assert "invalid choice" in stderr_output
    assert "not-a-real-format" in stderr_output


@pytest.mark.parametrize(
    "api_key_env,expected_model_substr",
    [
        ("ANTHROPIC_API_KEY", "sonnet"),
        ("DEEPSEEK_API_KEY", "deepseek"),
        ("OPENROUTER_API_KEY", "openrouter/"),
        ("OPENAI_API_KEY", "gpt-4"),
        ("GEMINI_API_KEY", "gemini"),
    ],
    ids=["anthropic", "deepseek", "openrouter", "openai", "gemini"],
)
def test_default_model_selection(api_key_env, expected_model_substr, dummy_io, git_temp_dir):
    saved_keys = {}
    api_keys = [
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    ]
    for key in api_keys:
        if key in os.environ:
            saved_keys[key] = os.environ[key]
            del os.environ[key]
    try:
        os.environ[api_key_env] = "test-key"
        coder = main(["--exit", "--yes-always"], **dummy_io, return_coder=True)
        assert expected_model_substr in coder.main_model.name.lower()
    finally:
        if api_key_env in os.environ:
            del os.environ[api_key_env]
        for key, value in saved_keys.items():
            os.environ[key] = value


def test_default_model_selection_oauth_fallback(dummy_io, git_temp_dir, mocker):
    saved_keys = {}
    api_keys = [
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    ]
    for key in api_keys:
        if key in os.environ:
            saved_keys[key] = os.environ[key]
            del os.environ[key]
    try:
        mock_offer_oauth = mocker.patch("cecli.onboarding.offer_openrouter_oauth")
        mock_offer_oauth.return_value = None
        result = main(["--exit", "--yes-always"], **dummy_io)
        assert result == 1
        mock_offer_oauth.assert_called_once()
    finally:
        for key, value in saved_keys.items():
            os.environ[key] = value


def test_model_precedence(dummy_io, git_temp_dir, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    coder = main(["--exit", "--yes-always"], **dummy_io, return_coder=True)
    assert "sonnet" in coder.main_model.name.lower()


def test_model_overrides_suffix_applied(dummy_io, git_temp_dir, mocker):
    overrides_file = git_temp_dir / ".cecli.model.overrides.yml"
    overrides_file.write_text("gpt-4o:\n  fast:\n    temperature: 0.1\n")
    MockModel = mocker.patch("cecli.models.Model")
    MockCoder = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MagicMock()
    mock_coder_instance._autosave_future = mock_autosave_future()
    MockCoder.return_value = mock_coder_instance
    mock_instance = MockModel.return_value
    mock_instance.info = {}
    mock_instance.name = "gpt-4o"
    mock_instance.validate_environment.return_value = {
        "missing_keys": [],
        "keys_in_environment": [],
    }
    mock_instance.accepts_settings = []
    mock_instance.weak_model_name = None
    mock_instance.get_weak_model.return_value = None
    main(
        ["--model", "gpt-4o:fast", "--exit", "--yes-always", "--no-git"],
        **dummy_io,
        force_git_root=git_temp_dir,
    )
    matched_call_found = False
    for call_args in MockModel.call_args_list:
        args, kwargs = call_args
        if args and args[0] == "gpt-4o" and kwargs.get("override_kwargs") == {"temperature": 0.1}:
            matched_call_found = True
            break
    assert (
        matched_call_found
    ), "Expected a Model call with base name 'gpt-4o' and override_kwargs {'temperature': 0.1}"


def test_model_overrides_no_match_preserves_model_name(dummy_io, git_temp_dir, mocker):
    MockModel = mocker.patch("cecli.models.Model")
    MockCoder = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MagicMock()
    mock_coder_instance._autosave_future = mock_autosave_future()
    MockCoder.return_value = mock_coder_instance
    mock_instance = MockModel.return_value
    mock_instance.info = {}
    mock_instance.name = "test-model"
    mock_instance.validate_environment.return_value = {
        "missing_keys": [],
        "keys_in_environment": [],
    }
    mock_instance.accepts_settings = []
    mock_instance.weak_model_name = None
    mock_instance.get_weak_model.return_value = None
    model_name = "hf:moonshotai/Kimi-K2-Thinking"
    main(
        ["--model", model_name, "--exit", "--yes-always", "--no-git"],
        **dummy_io,
        force_git_root=git_temp_dir,
    )
    matched_call_found = False
    for call_args in MockModel.call_args_list:
        args, kwargs = call_args
        if args and args[0] == model_name and kwargs.get("override_kwargs") == {}:
            matched_call_found = True
            break
    assert (
        matched_call_found
    ), "Expected a Model call with the full model name preserved and empty override_kwargs"


def test_chat_language_spanish(dummy_io, git_temp_dir):
    coder = main(
        ["--chat-language", "Spanish", "--exit", "--yes-always"], **dummy_io, return_coder=True
    )
    system_info = coder.get_platform_info()
    assert "Spanish" in system_info


def test_commit_language_japanese(dummy_io, git_temp_dir):
    coder = main(
        ["--commit-language", "japanese", "--exit", "--yes-always"], **dummy_io, return_coder=True
    )
    assert "japanese" in coder.commit_language


def test_main_exit_with_git_command_not_found(dummy_io, git_temp_dir, mocker):
    mock_git_init = mocker.patch("git.Repo.init")
    mock_git_init.side_effect = git.exc.GitCommandNotFound("git", "Command 'git' not found")
    result = main(["--exit", "--yes-always"], **dummy_io)
    assert result == 0, "main() should return 0 (success) when called with --exit"


def test_reasoning_effort_option(dummy_io, git_temp_dir):
    coder = main(
        ["--reasoning-effort", "3", "--no-check-model-accepts-settings", "--yes-always", "--exit"],
        **dummy_io,
        return_coder=True,
    )
    assert coder.main_model.extra_params.get("extra_body", {}).get("reasoning_effort") == "3"


def test_thinking_tokens_option(dummy_io, git_temp_dir):
    coder = main(
        ["--model", "sonnet", "--thinking-tokens", "1000", "--yes-always", "--exit"],
        **dummy_io,
        return_coder=True,
    )
    assert coder.main_model.extra_params.get("thinking", {}).get("budget_tokens") == 1000


def test_list_models_includes_metadata_models(dummy_io, git_temp_dir, mocker, capsys):
    metadata_file = Path(".cecli.model.metadata.json")
    test_models = {
        "unique-model-name": {
            "max_input_tokens": 8192,
            "litellm_provider": "test-provider",
            "mode": "chat",
        },
        "another-provider/another-unique-model": {
            "max_input_tokens": 4096,
            "litellm_provider": "another-provider",
            "mode": "chat",
        },
    }
    metadata_file.write_text(json.dumps(test_models))
    main(
        [
            "--list-models",
            "unique-model",
            "--model-metadata-file",
            str(metadata_file),
            "--yes-always",
            "--no-gitignore",
        ],
        **dummy_io,
    )
    captured = capsys.readouterr()
    output = captured.out
    assert "test-provider/unique-model-name" in output


def test_list_models_includes_all_model_sources(dummy_io, git_temp_dir, mocker, capsys):
    metadata_file = Path(".cecli.model.metadata.json")
    test_models = {
        "metadata-only-model": {
            "max_input_tokens": 8192,
            "litellm_provider": "test-provider",
            "mode": "chat",
        }
    }
    metadata_file.write_text(json.dumps(test_models))
    main(
        [
            "--list-models",
            "metadata-only-model",
            "--model-metadata-file",
            str(metadata_file),
            "--yes-always",
            "--no-gitignore",
        ],
        **dummy_io,
    )
    captured = capsys.readouterr()
    output = captured.out
    dump(output)
    assert "test-provider/metadata-only-model" in output


def test_list_models_includes_openai_provider(dummy_io, git_temp_dir, mocker, capsys):
    import cecli.models as models_module

    provider_name = "openai"
    manager = models_module.model_info_manager.provider_manager
    provider_config = {
        "api_base": "https://api.openai.com/v1",
        "models_url": "https://api.openai.com/v1/models",
        "api_key_env": ["OPENAI_API_KEY"],
        "base_url_env": ["OPENAI_API_BASE"],
        "default_headers": {},
    }
    had_config = provider_name in manager.provider_configs
    previous_config = manager.provider_configs.get(provider_name)
    had_cache = provider_name in manager._provider_cache
    previous_cache = manager._provider_cache.get(provider_name)
    had_loaded = provider_name in manager._cache_loaded
    previous_loaded = manager._cache_loaded.get(provider_name)
    manager.provider_configs[provider_name] = provider_config
    manager._provider_cache[provider_name] = None
    manager._cache_loaded[provider_name] = False
    payload = {
        "data": [
            {
                "id": "demo/foo",
                "max_input_tokens": 4096,
                "pricing": {"prompt": "0.0001", "completion": "0.0002"},
            }
        ]
    }

    def _fake_get(url, *, headers=None, timeout=None, verify=None):
        return types.SimpleNamespace(status_code=200, json=lambda: payload)

    try:
        mocker.patch("requests.get", _fake_get)
        main(["--list-models", "openai/demo/foo", "--yes", "--no-gitignore"], **dummy_io)
        captured = capsys.readouterr()
        output = captured.out
        assert "openai/demo/foo" in output
    finally:
        if had_config:
            manager.provider_configs[provider_name] = previous_config
        else:
            manager.provider_configs.pop(provider_name, None)
        if had_cache:
            manager._provider_cache[provider_name] = previous_cache
        else:
            manager._provider_cache.pop(provider_name, None)
        if had_loaded:
            manager._cache_loaded[provider_name] = previous_loaded
        else:
            manager._cache_loaded.pop(provider_name, None)


def test_check_model_accepts_settings_flag(dummy_io, git_temp_dir, mocker):
    mock_set_thinking = mocker.patch("cecli.models.Model.set_thinking_tokens")
    main(
        [
            "--model",
            "gpt-4o",
            "--thinking-tokens",
            "1000",
            "--check-model-accepts-settings",
            "--yes-always",
            "--exit",
        ],
        **dummy_io,
    )
    mock_set_thinking.assert_not_called()


def test_list_models_with_direct_resource_patch(dummy_io, mocker, capsys):
    test_file = Path(os.getcwd()) / "test-model-metadata.json"
    test_resource_models = {
        "special-model": {
            "max_input_tokens": 8192,
            "litellm_provider": "resource-provider",
            "mode": "chat",
        }
    }
    test_file.write_text(json.dumps(test_resource_models))
    mock_resource_path = MagicMock()
    mock_resource_path.__str__.return_value = str(test_file)
    mock_files = MagicMock()
    mock_files.joinpath.return_value = mock_resource_path
    mocker.patch("cecli.main.importlib_resources.files", return_value=mock_files)
    main(["--list-models", "special", "--yes-always", "--no-gitignore"], **dummy_io)
    captured = capsys.readouterr()
    output = captured.out
    assert "resource-provider/special-model" in output


def test_reasoning_effort_applied_without_check_flag(dummy_io, mocker):
    mock_set_reasoning = mocker.patch("cecli.models.Model.set_reasoning_effort")
    main(
        [
            "--model",
            "gpt-3.5-turbo",
            "--reasoning-effort",
            "3",
            "--no-check-model-accepts-settings",
            "--yes-always",
            "--exit",
        ],
        **dummy_io,
    )
    mock_set_reasoning.assert_called_once_with("3")


def test_model_accepts_settings_attribute(dummy_io, git_temp_dir, mocker):
    MockModel = mocker.patch("cecli.models.Model")
    mock_instance = MockModel.return_value
    mock_instance.name = "test-model"
    mock_instance.accepts_settings = ["reasoning_effort"]
    mock_instance.validate_environment.return_value = {
        "missing_keys": [],
        "keys_in_environment": [],
    }
    mock_instance.info = {}
    mock_instance.weak_model_name = None
    mock_instance.get_weak_model.return_value = None
    main(
        [
            "--model",
            "test-model",
            "--reasoning-effort",
            "3",
            "--thinking-tokens",
            "1000",
            "--check-model-accepts-settings",
            "--yes-always",
            "--exit",
        ],
        **dummy_io,
    )
    mock_instance.set_reasoning_effort.assert_called_once_with("3")
    mock_instance.set_thinking_tokens.assert_not_called()


@pytest.mark.parametrize(
    "flags,should_warn",
    [
        (["--stream", "--cache-prompts"], True),
        (["--stream"], False),
        (["--cache-prompts", "--no-stream"], False),
    ],
    ids=["stream_and_cache", "stream_only", "cache_only"],
)
def test_stream_cache_warning(dummy_io, git_temp_dir, mocker, flags, should_warn):
    """Test warning shown only when both streaming and caching are enabled."""
    MockInputOutput = mocker.patch("cecli.main.InputOutput", autospec=True)
    mock_io_instance = MockInputOutput.return_value
    mock_io_instance.pretty = True
    args = flags + ["--exit", "--yes-always"]
    main(args, **dummy_io)
    if should_warn:
        mock_io_instance.tool_warning.assert_called_with(
            "Cost estimates may be inaccurate when using streaming and caching."
        )
    else:
        for call in mock_io_instance.tool_warning.call_args_list:
            assert "Cost estimates may be inaccurate" not in call[0][0]


def test_argv_file_respects_git(dummy_io, git_temp_dir):
    fname = Path("not_in_git.txt")
    fname.touch()
    with open(".gitignore", "w+") as f:
        f.write("not_in_git.txt")
    coder = main(argv=["--file", "not_in_git.txt"], **dummy_io, return_coder=True)
    assert "not_in_git.txt" not in str(coder.abs_fnames)
    assert not asyncio.run(coder.allowed_to_edit("not_in_git.txt"))


def test_load_dotenv_files_override(dummy_io, git_temp_dir, mocker):
    fake_home = git_temp_dir / "fake_home"
    fake_home.mkdir()
    cecli_dir = handle_core_files(fake_home / ".cecli")
    cecli_dir.mkdir()
    oauth_keys_file = cecli_dir / "oauth-keys.env"
    oauth_keys_file.write_text("OAUTH_VAR=oauth_val\nSHARED_VAR=oauth_shared\n")
    git_root_env = git_temp_dir / ".env"
    git_root_env.write_text("GIT_VAR=git_val\nSHARED_VAR=git_shared\n")
    cwd_subdir = git_temp_dir / "subdir"
    cwd_subdir.mkdir()
    cwd_env = cwd_subdir / ".env"
    cwd_env.write_text("CWD_VAR=cwd_val\nSHARED_VAR=cwd_shared\n")
    original_cwd = os.getcwd()
    os.chdir(cwd_subdir)
    for var in ["OAUTH_VAR", "SHARED_VAR", "GIT_VAR", "CWD_VAR"]:
        if var in os.environ:
            del os.environ[var]
    mocker.patch("pathlib.Path.home", return_value=fake_home)
    loaded_files = load_dotenv_files(str(git_temp_dir), None)
    assert str(oauth_keys_file.resolve()) in loaded_files
    assert str(git_root_env.resolve()) in loaded_files
    assert str(cwd_env.resolve()) in loaded_files
    assert loaded_files.index(str(oauth_keys_file.resolve())) < loaded_files.index(
        str(git_root_env.resolve())
    )
    assert loaded_files.index(str(git_root_env.resolve())) < loaded_files.index(
        str(cwd_env.resolve())
    )
    assert os.environ.get("OAUTH_VAR") == "oauth_val"
    assert os.environ.get("GIT_VAR") == "git_val"
    assert os.environ.get("CWD_VAR") == "cwd_val"
    assert os.environ.get("SHARED_VAR") == "cwd_shared"
    os.chdir(original_cwd)


def test_mcp_servers_parsing(dummy_io, git_temp_dir, mocker):
    mock_coder_create = mocker.patch("cecli.coders.Coder.create")
    mock_coder_instance = MagicMock()
    mock_coder_instance._autosave_future = mock_autosave_future()
    mock_coder_create.return_value = mock_coder_instance
    main(
        [
            "--mcp-servers",
            '{"mcpServers":{"git":{"command":"uvx","args":["mcp-server-git"]}}}',
            "--exit",
            "--yes-always",
        ],
        **dummy_io,
    )
    mock_coder_create.assert_called_once()
    _, kwargs = mock_coder_create.call_args
    assert "mcp_servers" in kwargs
    assert kwargs["mcp_servers"] is not None
    assert len(kwargs["mcp_servers"]) > 0
    assert hasattr(kwargs["mcp_servers"][0], "name")
    mock_coder_create.reset_mock()
    mock_coder_instance._autosave_future = mock_autosave_future()
    mcp_file = Path("mcp_servers.json")
    mcp_content = {"mcpServers": {"git": {"command": "uvx", "args": ["mcp-server-git"]}}}
    mcp_file.write_text(json.dumps(mcp_content))
    main(["--mcp-servers-file", str(mcp_file), "--exit", "--yes-always"], **dummy_io)
    mock_coder_create.assert_called_once()
    _, kwargs = mock_coder_create.call_args
    assert "mcp_servers" in kwargs
    assert kwargs["mcp_servers"] is not None
    assert len(kwargs["mcp_servers"]) > 0
    assert hasattr(kwargs["mcp_servers"][0], "name")
