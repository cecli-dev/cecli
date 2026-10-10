import os
import time
from pathlib import Path

from cecli.dump import dump  # noqa
from cecli.io import InputOutput
from cecli.watch import FileWatcher


class MinimalCoder:
    def __init__(self, io):
        self.io = io
        self.root = "."
        self.abs_fnames = set()

    def get_rel_fname(self, fname):
        return fname


def test_gitignore_patterns():
    """Test that gitignore patterns are properly loaded and matched"""
    from pathlib import Path

    from cecli.watch import load_gitignores

    # Create a temporary gitignore file with test patterns
    tmp_gitignore = Path("test.gitignore")
    tmp_gitignore.write_text("custom_pattern\n*.custom")

    gitignores = [tmp_gitignore]
    spec = load_gitignores(gitignores)

    # Test built-in patterns
    assert spec.match_file(".cecli.conf")
    assert spec.match_file(".git/config")
    assert spec.match_file("file~")  # Emacs/vim backup
    assert spec.match_file("file.bak")
    assert spec.match_file("file.swp")
    assert spec.match_file("file.swo")
    assert spec.match_file("#temp#")  # Emacs auto-save
    assert spec.match_file(".#lock")  # Emacs lock
    assert spec.match_file("temp.tmp")
    assert spec.match_file("temp.temp")
    assert spec.match_file("conflict.orig")
    assert spec.match_file("script.pyc")
    assert spec.match_file("__pycache__/module.pyc")
    assert spec.match_file(".DS_Store")
    assert spec.match_file("Thumbs.db")
    assert spec.match_file(".idea/workspace.xml")
    assert spec.match_file(".vscode/settings.json")
    assert spec.match_file("project.sublime-workspace")
    assert spec.match_file(".project")
    assert spec.match_file(".settings/config.json")
    assert spec.match_file("workspace.code-workspace")
    assert spec.match_file(".env")
    assert spec.match_file(".venv/bin/python")
    assert spec.match_file("node_modules/package/index.js")
    assert spec.match_file("vendor/lib/module.py")
    assert spec.match_file("debug.log")
    assert spec.match_file(".cache/files")
    assert spec.match_file(".pytest_cache/v/cache")
    assert spec.match_file("coverage/lcov.info")

    # Test custom patterns from gitignore file
    assert spec.match_file("custom_pattern")
    assert spec.match_file("file.custom")

    # Test non-matching patterns
    assert not spec.match_file("regular_file.txt")
    assert not spec.match_file("src/main.py")
    assert not spec.match_file("docs/index.html")

    # Cleanup
    tmp_gitignore.unlink()


def test_get_roots_to_watch(tmp_path):
    # Create a test directory structure
    (tmp_path / "included").mkdir()
    (tmp_path / "excluded").mkdir()

    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)

    # Test with no gitignore
    watcher = FileWatcher(coder, root=tmp_path)
    roots = watcher.get_roots_to_watch()
    assert len(roots) == 1
    assert roots[0] == str(tmp_path)

    # Test with gitignore
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("excluded/")
    watcher = FileWatcher(coder, root=tmp_path, gitignores=[gitignore])
    roots = watcher.get_roots_to_watch()
    assert len(roots) == 2
    assert Path(sorted(roots)[0]).name == ".gitignore"
    assert Path(sorted(roots)[1]).name == "included"


def test_handle_changes():
    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder)

    # Test no changes
    assert not watcher.handle_changes([])
    assert len(watcher.changed_files) == 0

    # Test with changes
    changes = [("modified", "/path/to/file.py")]
    assert watcher.handle_changes(changes)
    assert len(watcher.changed_files) == 1
    assert str(Path("/path/to/file.py")) in watcher.changed_files


def test_ai_comment_pattern():
    # Create minimal IO and Coder instances for testing
    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder)
    fixtures_dir = Path(__file__).parent.parent / "fixtures"

    # Test Python fixture
    py_path = fixtures_dir / "watch.py"
    py_lines, py_comments, py_has_bang = watcher.get_ai_comments(str(py_path))

    # Count unique AI comments (excluding duplicates and variations with extra spaces)
    unique_py_comments = set(comment.strip().lower() for comment in py_comments)

    py_expected = 10
    assert len(unique_py_comments) == 10, (
        f"Expected {py_expected} unique AI comments in Python fixture, found"
        f" {len(unique_py_comments)}"
    )
    assert py_has_bang == "!", "Expected at least one bang (!) comment in Python fixture"

    # Test JavaScript fixture
    js_path = fixtures_dir / "watch.js"
    js_lines, js_comments, js_has_bang = watcher.get_ai_comments(str(js_path))
    js_expected = 16
    assert (
        len(js_lines) == js_expected
    ), f"Expected {js_expected} AI comments in JavaScript fixture, found {len(js_lines)}"
    assert js_has_bang == "!", "Expected at least one bang (!) comment in JavaScript fixture"

    # Test watch_question.js fixture
    question_js_path = fixtures_dir / "watch_question.js"
    question_js_lines, question_js_comments, question_js_has_bang = watcher.get_ai_comments(
        str(question_js_path)
    )
    question_js_expected = 6
    assert len(question_js_lines) == question_js_expected, (
        f"Expected {question_js_expected} AI comments in watch_question.js fixture, found"
        f" {len(question_js_lines)}"
    )
    assert (
        question_js_has_bang == "?"
    ), "Expected at least one bang (!) comment in watch_question.js fixture"

    # Test Lisp fixture
    lisp_path = fixtures_dir / "watch.lisp"
    lisp_lines, lisp_comments, lisp_has_bang = watcher.get_ai_comments(str(lisp_path))
    lisp_expected = 7
    assert (
        len(lisp_lines) == lisp_expected
    ), f"Expected {lisp_expected} AI comments in Lisp fixture, found {len(lisp_lines)}"
    assert lisp_has_bang == "!", "Expected at least one bang (!) comment in Lisp fixture"


def test_catch_up_scan_detects_recent_file(tmp_path):
    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder, root=tmp_path)
    watcher.last_scan_time = 0

    new_file = tmp_path / "new.py"
    new_file.write_text("# ai!\n")

    assert watcher.catch_up_scan()
    assert str(new_file.absolute()) in watcher.changed_files


def test_catch_up_scan_ignores_old_files(tmp_path):
    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder, root=tmp_path)

    old_file = tmp_path / "old.py"
    old_file.write_text("# ai!\n")
    watcher.last_scan_time = time.time() + 5

    assert not watcher.catch_up_scan()
    assert watcher.changed_files == set()


def test_catch_up_scan_respects_gitignore(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("ignored/\n")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "hidden.py").write_text("# ai!\n")
    (tmp_path / "kept.py").write_text("# ai!\n")

    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder, gitignores=[gitignore], root=tmp_path)
    watcher.last_scan_time = 0
    watcher.catch_up_scan()

    assert str((tmp_path / "kept.py").absolute()) in watcher.changed_files
    assert str((tmp_path / "ignored" / "hidden.py").absolute()) not in watcher.changed_files


def test_catch_up_scan_advances_threshold(tmp_path):
    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder, root=tmp_path)
    watcher.last_scan_time = 0
    (tmp_path / "a.py").write_text("# ai!\n")

    assert watcher.catch_up_scan()
    watcher.changed_files = set()

    # Nothing changed since the previous scan, so the same file is not re-found.
    assert not watcher.catch_up_scan()
    assert watcher.changed_files == set()


def test_catch_up_scan_ignores_file_at_threshold(tmp_path):
    """A file sharing the previous scan's clock tick must not be re-found"""
    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder, root=tmp_path)
    watcher.last_scan_time = 0

    target = tmp_path / "a.py"
    target.write_text("# ai!\n")

    assert watcher.catch_up_scan()
    watcher.changed_files = set()

    # Simulate a coarse-grained clock (e.g. Windows) where the file and the new
    # threshold fall in the same timestamp tick.
    ts = watcher.last_scan_time
    os.utime(target, (ts, ts))

    assert not watcher.catch_up_scan()
    assert watcher.changed_files == set()


def test_process_changes_consumes_catch_up(tmp_path):
    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder, root=tmp_path)
    watcher.last_scan_time = 0

    target = tmp_path / "a.py"
    target.write_text("# ai!\n")

    assert watcher.catch_up_scan()
    res = watcher.process_changes()

    assert res
    assert str(target.absolute()) in coder.abs_fnames
    assert not watcher.is_running


def test_start_runs_catch_up_scan(tmp_path):
    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder, root=tmp_path)
    watcher.last_scan_time = 0

    target = tmp_path / "a.py"
    target.write_text("# ai!\n")

    watcher.start()
    try:
        assert str(target.absolute()) in watcher.changed_files
    finally:
        watcher.stop()


def test_catch_up_scan_gates_file_roots(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("ignored/\n")

    top_file = tmp_path / "top.py"
    top_file.write_text("# ai!\n")

    io = InputOutput(pretty=False, fancy_input=False, yes=False)
    coder = MinimalCoder(io)
    watcher = FileWatcher(coder, gitignores=[gitignore], root=tmp_path)
    watcher.last_scan_time = 0

    assert watcher.catch_up_scan()
    assert str(top_file.absolute()) in watcher.changed_files

    # top.py is a watched file root, but its mtime predates the new threshold.
    watcher.changed_files = set()
    assert not watcher.catch_up_scan()
    assert watcher.changed_files == set()
