import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

from cecli.decoding import safe_open
from cecli.dump import dump  # noqa
from cecli.watch_prompts import watch_ask_prompt, watch_code_prompt


def load_gitignores(gitignore_paths: list[Path]) -> Optional[PathSpec]:
    """Load and parse multiple .gitignore files into a single PathSpec"""
    if not gitignore_paths:
        return None

    always_ignore = [
        ".cecli*",
        ".git",
        ".git/",  # Git metadata
        # Common editor backup/temp files
        "*~",  # Emacs/vim backup
        "*.bak",  # Generic backup
        "*.swp",  # Vim swap
        "*.swo",  # Vim swap
        "\\#*\\#",  # Emacs auto-save
        ".#*",  # Emacs lock files
        "*.tmp",  # Generic temp files
        "*.temp",  # Generic temp files
        "*.orig",  # Merge conflict originals
        "*.pyc",  # Python bytecode
        "__pycache__/",  # Python cache dir
        ".DS_Store",  # macOS metadata
        "Thumbs.db",  # Windows thumbnail cache
        "*.svg",
        "*.pdf",
        # IDE files
        ".idea/",  # JetBrains IDEs
        ".vscode/",  # VS Code
        "*.sublime-*",  # Sublime Text
        ".project",  # Eclipse
        ".settings/",  # Eclipse
        "*.code-workspace",  # VS Code workspace
        # Environment files
        ".env",  # Environment variables
        ".venv/",  # Python virtual environments
        "venv/",  # Python virtual environments
        "env/",  # Python virtual environments
        ".tox/",  # Tox environments
        "*.egg-info/",  # Python package metadata
        "node_modules/",  # Node.js dependencies
        "vendor/",  # Various dependencies
        # Logs and caches
        "*.log",  # Log files
        ".cache/",  # Cache directories
        ".pytest_cache/",  # Python test cache
        ".ruff_cache/",  # Ruff cache
        ".mypy_cache/",  # Mypy cache
        "coverage/",  # Code coverage reports
    ]

    patterns = []
    for path in gitignore_paths:
        if path.exists():
            try:
                with safe_open(path, "r", errors="ignore") as f:
                    patterns.extend(f.readlines())
            except Exception:
                pass  # Ignore files that can't be read

    # Always-ignore patterns go last: in gitignore semantics the last matching
    # pattern wins, so a repo's negations (e.g. "!*/") cannot re-enable heavy
    # directories like virtualenvs, caches or .git.
    patterns.extend(always_ignore)

    return PathSpec.from_lines(GitWildMatchPattern, patterns) if patterns else None


class FileWatcher:
    """Watches source files for changes and AI comments"""

    # Compiled regex pattern for AI comments
    ai_comment_pattern = re.compile(
        r"(?:#|//|--|;+) *(ai\b.*|ai\b.*|.*\bai[?!]?) *$", re.IGNORECASE
    )

    def __init__(self, coder, gitignores=None, verbose=False, root=None):
        self.coder = coder
        self.io = coder.io
        self.root = (Path(root) if root else Path(coder.root)).absolute()
        self.verbose = verbose
        self.stop_event = None
        self.watcher_thread = None
        self.changed_files = set()
        self.gitignores = gitignores
        self.is_running = False
        self.last_scan_time = time.time()

        self.gitignore_spec = load_gitignores(
            [Path(g) for g in self.gitignores] if self.gitignores else []
        )

        coder.io.file_watcher = self

    def filter_func(self, change_type, path):
        """Filter function for the file watcher"""
        path_obj = Path(path)
        path_abs = path_obj.absolute()

        if not path_abs.is_relative_to(self.root.absolute()):
            return False

        rel_path = path_abs.relative_to(self.root)
        if self.verbose:
            print("Changed", rel_path)

        if self.gitignore_spec and self.gitignore_spec.match_file(
            rel_path.as_posix() + ("/" if path_abs.is_dir() else "")
        ):
            return False

        # Check file size before reading content
        if path_abs.is_file() and path_abs.stat().st_size > 1 * 1024 * 1024:  # 1MB limit
            return False

        if self.verbose:
            print("Checking", rel_path)

        # Check if file contains AI markers
        try:
            comments, _, _ = self.get_ai_comments(str(path_abs))
            return bool(comments)
        except Exception:
            return

    def get_roots_to_watch(self):
        """Determine which root paths to watch based on gitignore rules"""
        if self.gitignore_spec:
            roots = [
                str(path)
                for path in self.root.iterdir()
                if not self.gitignore_spec.match_file(
                    path.relative_to(self.root).as_posix() + ("/" if path.is_dir() else "")
                )
            ]
            # Fallback to watching root if all top-level items are filtered out
            return roots if roots else [str(self.root)]
        return [str(self.root)]

    def handle_changes(self, changes):
        """Process the detected changes and update state"""
        if not changes:
            return False

        changed_files = {str(Path(change[1])) for change in changes}
        self.changed_files.update(changed_files)
        self.io.interrupt_input()
        return True

    def watch_files(self):
        """Watch for file changes and process them"""
        try:
            from watchfiles import watch

            roots_to_watch = self.get_roots_to_watch()

            for changes in watch(
                *roots_to_watch,
                watch_filter=self.filter_func,
                stop_event=self.stop_event,
                ignore_permission_denied=True,
            ):
                if self.handle_changes(changes):
                    return

        except Exception as e:
            if self.verbose:
                dump(f"File watcher error: {e}")
            raise e

    def start(self):
        """Start watching for file changes"""
        self.stop_event = threading.Event()
        self.changed_files = set()

        # Watchfiles only sees changes that happen while it is running, so pick
        # up anything created while the watcher was stopped before we begin.
        try:
            self.catch_up_scan()
        except Exception as e:
            if self.verbose:
                dump(f"File watcher catch-up scan error: {e}")

        self.is_running = True
        self.watcher_thread = threading.Thread(target=self.watch_files, daemon=True)
        self.watcher_thread.start()

    def stop(self):
        """Stop watching for file changes"""
        if self.stop_event:
            self.stop_event.set()
        if self.watcher_thread:
            self.watcher_thread.join()
            self.watcher_thread = None
            self.stop_event = None

    def process_changes(self):
        """Get any detected file changes"""
        from cecli.helpers.grep_ast import TreeContext

        has_action = None
        added = False
        for fname in self.changed_files:
            _, _, action = self.get_ai_comments(fname)
            if action in ("!", "?"):
                has_action = action

            if fname in self.coder.abs_fnames:
                continue
            self.coder.abs_fnames.add(fname)
            rel_fname = self.coder.get_rel_fname(fname)
            if not added:
                self.io.tool_output()
                added = True
            self.io.tool_output(f"Added {rel_fname} to the chat")

        if not has_action:
            if added:
                self.io.tool_output(
                    "End your comment with AI! to request changes or AI? to ask questions"
                )
            return ""

        self.io.tool_output("Processing your request...")

        if has_action == "!":
            res = watch_code_prompt
        elif has_action == "?":
            res = watch_ask_prompt

        # Refresh all AI comments from tracked files
        for fname in self.coder.abs_fnames:
            line_nums, comments, _action = self.get_ai_comments(fname)
            if not line_nums:
                continue

            code = self.io.read_text(fname)
            if not code:
                continue

            rel_fname = self.coder.get_rel_fname(fname)
            res += f"\n{rel_fname}:\n"

            # Convert comment line numbers to line indices (0-based)
            lois = [ln - 1 for ln, _ in zip(line_nums, comments) if ln > 0]

            try:
                context = TreeContext(
                    rel_fname,
                    code,
                    color=False,
                    line_number=False,
                    child_context=False,
                    last_line=False,
                    margin=0,
                    mark_lois=True,
                    loi_pad=3,
                    show_top_of_file_parent_scope=False,
                )
                context.lines_of_interest = set()
                context.add_lines_of_interest(lois)
                context.add_context()
                res += context.format()
            except ValueError:
                for ln, comment in zip(line_nums, comments):
                    res += f"  Line {ln}: {comment}\n"

        self.is_running = False
        return res

    def get_ai_comments(self, filepath):
        """Extract AI comment line numbers, comments and action status from a file"""
        line_nums = []
        comments = []
        has_action = None  # None, "!" or "?"
        content = self.io.read_text(filepath, silent=True)
        if not content:
            return None, None, None

        for i, line in enumerate(content.splitlines(), 1):
            if match := self.ai_comment_pattern.search(line):
                comment = match.group(0).strip()
                if comment:
                    line_nums.append(i)
                    comments.append(comment)
                    comment = comment.lower()
                    comment = comment.lstrip("/#-;")  # Added semicolon for Lisp comments
                    comment = comment.strip()
                    if comment.startswith("ai!") or comment.endswith("ai!"):
                        has_action = "!"
                    elif comment.startswith("ai?") or comment.endswith("ai?"):
                        has_action = "?"
        if not line_nums:
            return None, None, None
        return line_nums, comments, has_action

    def catch_up_scan(self):
        """Catch AI comments in files changed since the last scan

        watchfiles only reports changes that happen while it is running, so a
        file created while the watcher was stopped (or inside a directory created
        after watching began) would otherwise be missed. This mtime-gated scan
        looks only at files changed since the previous scan and applies the same
        gitignore and comment rules as the live watcher.
        """
        scan_started = time.time()
        # Strict ">", not ">=": on coarse-grained clocks a file written just
        # before this scan can share the threshold tick and must not be re-found.
        threshold = self.last_scan_time
        found = set()

        for root in self.get_roots_to_watch():
            root_path = Path(root)
            if root_path.is_file():
                try:
                    candidates = [root_path] if root_path.stat().st_mtime > threshold else []
                except OSError:
                    candidates = []
            else:
                candidates = self._iter_recent_files(root_path, threshold)

            for path in candidates:
                try:
                    if self.filter_func(None, str(path)):
                        found.add(str(path.absolute()))
                except Exception:
                    continue

        self.last_scan_time = scan_started

        if found:
            self.changed_files.update(found)

        return bool(found)

    def _iter_recent_files(self, directory, threshold):
        """Yield files under directory modified strictly after threshold"""
        for dirpath, dirnames, filenames in os.walk(directory):
            rel_dir = os.path.relpath(dirpath, self.root).replace(os.sep, "/")
            prefix = "" if rel_dir == "." else rel_dir + "/"

            if self.gitignore_spec:
                dirnames[:] = [
                    name
                    for name in dirnames
                    if not self.gitignore_spec.match_file(prefix + name + "/")
                ]

            for name in filenames:
                if self.gitignore_spec and self.gitignore_spec.match_file(prefix + name):
                    continue

                path = Path(dirpath) / name
                try:
                    if path.stat().st_mtime > threshold:
                        yield path
                except OSError:
                    continue


def main():
    """Example usage of the file watcher"""
    import argparse

    parser = argparse.ArgumentParser(description="Watch source files for changes")
    parser.add_argument("directory", help="Directory to watch")
    parser.add_argument(
        "--gitignore",
        action="append",
        help="Path to .gitignore file (can be specified multiple times)",
    )
    args = parser.parse_args()

    directory = args.directory
    print(f"Watching source files in {directory}...")

    # Example ignore function that ignores files with "test" in the name
    def ignore_test_files(path):
        return "test" in path.name.lower()

    watcher = FileWatcher(directory, gitignores=args.gitignore)
    try:
        watcher.start()
        while True:
            if changes := watcher.get_changes():
                for file in sorted(changes.keys()):
                    print(file)
                watcher.changed_files = None
    except KeyboardInterrupt:
        print("\nStopped watching files")
        watcher.stop()


if __name__ == "__main__":
    main()
