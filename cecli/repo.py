import contextlib
import os
import sys
import time
from pathlib import Path, PurePosixPath

try:
    import git

    ANY_GIT_ERROR = [
        git.exc.ODBError,
        git.exc.GitError,
        git.exc.InvalidGitRepositoryError,
        git.exc.GitCommandNotFound,
    ]
except ImportError:
    git = None
    ANY_GIT_ERROR = []

import concurrent.futures
import threading

import pathspec

import cecli.prompts.utils.system as prompts
from cecli import utils
from cecli.decoding import safe_open

from .dump import dump  # noqa: F401

ANY_GIT_ERROR += [
    OSError,
    IndexError,
    BufferError,
    TypeError,
    ValueError,
    AttributeError,
    AssertionError,
    TimeoutError,
]
ANY_GIT_ERROR = tuple(ANY_GIT_ERROR)

git.Git.USE_SHELL = False


@contextlib.contextmanager
def set_git_env(var_name, value, original_value):
    """Temporarily set a Git environment variable."""
    os.environ[var_name] = value
    try:
        yield
    finally:
        if original_value is not None:
            os.environ[var_name] = original_value
        elif var_name in os.environ:
            del os.environ[var_name]


def _close_git_repo(repo: "GitRepo") -> None:
    """Safely close a GitRepo that was just opened but will not be used.

    Prevents leaking the underlying ``git.Repo`` file handle when
    ``GitRepoProxy.for_root`` discovers an already-cached repository.
    """
    try:
        with repo._git_lock:
            if getattr(repo, "repo", None) is not None:
                repo.repo.close()
    except Exception:
        pass


class CommitInfo:
    """
    Data-only container for extracted commit information.

    Wraps the raw git-python commit data into simple Python types
    so that callers never receive a reference to the underlying
    ``git.Commit`` object (which could otherwise be used outside
    of the repository lock, leading to deadlocks).
    """

    def __init__(self, hexsha: str, message: str, parents: tuple[str, ...]):
        self.hexsha = hexsha
        self.message = message
        self.parents = parents

    def __bool__(self):
        return True


class GitRepo:
    repo = None
    cecli_ignore_file = None
    cecli_ignore_spec = None
    cecli_ignore_ts = 0
    cecli_ignore_last_check = 0
    subtree_only = False
    ignore_file_cache = {}
    git_repo_error = None
    gitignore_spec_cache = {}
    gitignore_file_cache = {}
    gitignore_last_check = 0

    def __init__(
        self,
        io,
        fnames,
        git_dname,
        cecli_ignore_file=None,
        models=None,
        attribute_author=True,
        attribute_committer=True,
        attribute_commit_message_author=False,
        attribute_commit_message_committer=False,
        commit_prompt=None,
        subtree_only=False,
        git_commit_verify=True,
        attribute_co_authored_by=False,  # Added parameter
    ):
        self.io = io
        self.models = models

        self.normalized_path = {}
        # Single-entry file cache: (commit_sha, interned_set_of_paths)
        # Using a single entry (not per-commit dict) limits unbounded memory growth
        self._tree_cache = None

        self.attribute_author = attribute_author
        self.attribute_committer = attribute_committer
        self.attribute_commit_message_author = attribute_commit_message_author
        self.attribute_commit_message_committer = attribute_commit_message_committer
        self.attribute_co_authored_by = attribute_co_authored_by  # Assign from parameter
        self.commit_prompt = commit_prompt
        self.subtree_only = subtree_only
        self.git_commit_verify = git_commit_verify
        self.ignore_file_cache = {}
        self._git_lock = threading.RLock()

        if git_dname:
            check_fnames = [git_dname]
        elif fnames:
            check_fnames = fnames
        else:
            check_fnames = ["."]

        repo_paths = []
        for fname in check_fnames:
            fname = Path(fname)
            fname = fname.resolve()

            if not fname.exists() and fname.parent.exists():
                fname = fname.parent

            try:
                with git.Repo(
                    fname, search_parent_directories=True, odbt=git.GitCmdObjectDB
                ) as temp_repo:
                    repo_path = utils.safe_abs_path(temp_repo.working_dir)
                    repo_paths.append(repo_path)
            except ANY_GIT_ERROR:
                pass

        num_repos = len(set(repo_paths))

        if num_repos == 0:
            raise FileNotFoundError
        if num_repos > 1:
            self.io.tool_error(
                "Files are in different git repos. Each coder operates on a single base path."
            )
            raise FileNotFoundError
        self._init_repo_path = repo_paths.pop()

        self.init_repo()
        if cecli_ignore_file:
            self.cecli_ignore_file = Path(cecli_ignore_file)

    def init_repo(self):
        with self._git_lock:
            if not self.repo:
                self.repo = git.Repo(self._init_repo_path, odbt=git.GitCmdObjectDB)
                self.root = utils.safe_abs_path(self.repo.working_tree_dir)

            try:
                self.repo.head.commit  # just access to check for errors, discard
            except ANY_GIT_ERROR:
                self.repo = git.Repo(self._init_repo_path, odbt=git.GitCmdObjectDB)
                self.root = utils.safe_abs_path(self.repo.working_tree_dir)

    def __del__(self):
        with self._git_lock:
            if self.repo:
                self.repo.close()

    async def commit(self, fnames=None, context=None, message=None, coder_edits=False, coder=None):
        """
        Commit the specified files or all dirty files if none are specified.

        Args:
            fnames (list, optional): List of filenames to commit. Defaults to None (commit all
                                     dirty files).
            context (str, optional): Context for generating commit message. Defaults to None.
            message (str, optional): Explicit commit message. Defaults to None (generate message).
            coder_edits (bool, optional): Whether the changes were made by cecli. Defaults to False.
                                          This affects attribution logic.
            coder (Coder, optional): The Coder instance, used for config and model info.
                                     Defaults to None.

        Returns:
            tuple(str, str) or None: The commit hash and commit message if successful,
                                     else None.

        Attribution Logic:
        ------------------
        This method handles Git commit attribution based on configuration flags and whether
        cecli generated the changes (`coder_edits`).

        Key Concepts:
        - Author: The person who originally wrote the code changes.
        - Committer: The person who last applied the commit to the repository.
        - coder_edits=True: Changes were generated by cecli (LLM).
        - coder_edits=False: Commit is user-driven (e.g., /commit manually staged changes).
        - Explicit Setting: A flag (--attribute-...) is set to True or False
          via command line or config file.
        - Implicit Default: A flag is not explicitly set, defaulting to None in args, which is
          interpreted as True unless overridden by other logic.

        Flags:
        - --attribute-author: Modify Author name to "User Name (cecli)".
        - --attribute-committer: Modify Committer name to "User Name (cecli)".
        - --attribute-co-authored-by: Add
          "Co-authored-by: cecli (<model>)" trailer to commit message.

        Behavior Summary:

        1. When coder_edits = True (AI Changes):
           - If --attribute-co-authored-by=True:
             - Co-authored-by trailer IS ADDED.
             - Author/Committer names are NOT modified by default (co-authored-by takes precedence).
             - EXCEPTION: If --attribute-author/--attribute-committer is EXPLICITLY True, the
               respective name IS modified (explicit overrides precedence).
           - If --attribute-co-authored-by=False:
             - Co-authored-by trailer is NOT added.
             - Author/Committer names ARE modified by default (implicit True).
             - EXCEPTION: If --attribute-author/--attribute-committer is EXPLICITLY False,
               the respective name is NOT modified.

        2. When coder_edits = False (User Changes):
           - --attribute-co-authored-by is IGNORED (trailer never added).
           - Author name is NEVER modified (--attribute-author ignored).
           - Committer name IS modified by default (implicit True, as cecli runs `git commit`).
           - EXCEPTION: If --attribute-committer is EXPLICITLY False, the name is NOT modified.

        Resulting Scenarios:
        - Standard AI edit (defaults): Co-authored-by=False -> Author=You(cecli),
          Committer=You(cecli)
        - AI edit with Co-authored-by (default): Co-authored-by=True -> Author=You,
          Committer=You, Trailer added
        - AI edit with Co-authored-by + Explicit Author: Co-authored-by=True,
          --attribute-author -> Author=You(cecli), Committer=You, Trailer added
        - User commit (defaults): coder_edits=False -> Author=You, Committer=You(cecli)
        - User commit with explicit no-committer: coder_edits=False,
          --no-attribute-committer -> Author=You, Committer=You
        """
        with self._git_lock:
            if not fnames and not self.repo.is_dirty():
                return

            diffs = self.get_diffs(fnames)
            if not diffs:
                return

        if message:
            commit_message = message
        else:
            user_language = None
            if coder:
                user_language = coder.commit_language
                if not user_language:
                    user_language = coder.get_user_language()
            commit_message = await self.get_commit_message(diffs, context, user_language)

        # Retrieve attribute settings, prioritizing coder.args if available
        if coder and hasattr(coder, "args") and coder.args:
            attribute_author = coder.args.attribute_author
            attribute_committer = coder.args.attribute_committer
            attribute_commit_message_author = coder.args.attribute_commit_message_author
            attribute_commit_message_committer = coder.args.attribute_commit_message_committer
            attribute_co_authored_by = coder.args.attribute_co_authored_by
        else:
            # Fallback to self attributes (initialized from config/defaults)
            attribute_author = self.attribute_author
            attribute_committer = self.attribute_committer
            attribute_commit_message_author = self.attribute_commit_message_author
            attribute_commit_message_committer = self.attribute_commit_message_committer
            attribute_co_authored_by = self.attribute_co_authored_by

        # Determine explicit settings (None means use default behavior)
        author_explicit = attribute_author is not None
        committer_explicit = attribute_committer is not None

        # Determine effective settings (apply default True if not explicit)
        effective_author = True if attribute_author is None else attribute_author
        effective_committer = True if attribute_committer is None else attribute_committer

        # Determine commit message prefixing
        prefix_commit_message = coder_edits and (
            attribute_commit_message_author or attribute_commit_message_committer
        )

        # Determine Co-authored-by trailer
        commit_message_trailer = ""
        if coder_edits and attribute_co_authored_by:
            model_name = "unknown-model"
            if coder and hasattr(coder, "main_model") and coder.main_model.name:
                model_name = coder.main_model.name
            commit_message_trailer = f"\n\nCo-authored-by: cecli ({model_name})"

        # Determine if author/committer names should be modified
        # Author modification applies only to cecli edits.
        # It's used if effective_author is True AND
        # (co-authored-by is False OR author was explicitly set).
        use_attribute_author = (
            coder_edits and effective_author and (not attribute_co_authored_by or author_explicit)
        )

        # Committer modification applies regardless of coder_edits (based on tests).
        # It's used if effective_committer is True AND
        # (it's not an cecli edit with co-authored-by OR committer was explicitly set).
        use_attribute_committer = effective_committer and (
            not (coder_edits and attribute_co_authored_by) or committer_explicit
        )

        if not commit_message:
            commit_message = "(no commit message provided)"

        if prefix_commit_message:
            commit_message = "cecli: " + commit_message

        full_commit_message = commit_message + commit_message_trailer

        with self._git_lock:
            cmd = ["-m", full_commit_message]
            if not self.git_commit_verify:
                cmd.append("--no-verify")
            if fnames:
                fnames = [str(self.abs_root_path(fn)) for fn in fnames]
                added_fnames = []
                for fname in fnames:
                    try:
                        # Check if file is git-ignored before trying to add
                        if (
                            coder
                            and hasattr(coder, "add_gitignore_files")
                            and coder.add_gitignore_files
                        ):
                            rel_fname = self.get_rel_fname(fname)
                            if self.git_ignored_file(rel_fname):
                                # Skip git-ignored files when add_gitignore_files is enabled
                                continue
                        self.repo.git.add(fname)
                        added_fnames.append(fname)
                    except ANY_GIT_ERROR as err:
                        self.io.tool_error(f"Unable to add {fname}: {err}")
                if added_fnames:
                    cmd += ["--"] + added_fnames
                else:
                    # No files to commit (all were git-ignored or failed to add)
                    return
            else:
                cmd += ["-a"]

            original_user_name = self.repo.git.config("--get", "user.name")
            original_committer_name_env = os.environ.get("GIT_COMMITTER_NAME")
            original_author_name_env = os.environ.get("GIT_AUTHOR_NAME")
            committer_name = f"{original_user_name} (cecli)"

            try:
                # Use context managers to handle environment variables
                with contextlib.ExitStack() as stack:
                    if use_attribute_committer:
                        stack.enter_context(
                            set_git_env(
                                "GIT_COMMITTER_NAME", committer_name, original_committer_name_env
                            )
                        )
                    if use_attribute_author:
                        stack.enter_context(
                            set_git_env("GIT_AUTHOR_NAME", committer_name, original_author_name_env)
                        )

                    # Perform the commit
                    self.repo.git.commit(cmd)
                    commit_hash = self.get_head_commit_sha(short=True)
                    self.io.tool_success(f"Commit {commit_hash} {commit_message}")
                    return commit_hash, commit_message

            except ANY_GIT_ERROR as err:
                self.io.tool_error(f"Unable to commit: {err}")
                # No return here, implicitly returns None

    def get_rel_repo_dir(self):
        with self._git_lock:
            try:
                return os.path.relpath(self.repo.git_dir, os.getcwd())
            except (ValueError, OSError):
                return self.repo.git_dir

    def get_rel_fname(self, fname):
        try:
            return os.path.relpath(fname, self.root)
        except ValueError:
            return fname

    async def get_commit_message(self, diffs, context, user_language=None):
        diffs = "# Diffs:\n" + diffs

        content = ""
        if context:
            content += context + "\n"
        content += diffs

        system_content = self.commit_prompt or prompts.commit_system

        language_instruction = ""
        if user_language:
            language_instruction = f"\n- Is written in {user_language}."
        system_content = system_content.format(language_instruction=language_instruction)

        commit_message = None
        for model in self.models:
            spinner_text = f"Generating commit message with {model.name}\n"

            self.io.start_spinner(spinner_text, update_last_text=False)

            if model.system_prompt_prefix:
                current_system_content = model.system_prompt_prefix + "\n" + system_content
            else:
                current_system_content = system_content

            messages = [
                dict(role="system", content=current_system_content),
                dict(role="user", content=content),
            ]

            num_tokens = model.token_count(messages)
            max_tokens = model.info.get("max_input_tokens") or 0

            if max_tokens and num_tokens > max_tokens:
                continue

            commit_message = await model.simple_send_with_retries(
                messages,
                override_kwargs={
                    "reasoning_effort": None,
                    "thinking": None,
                    "drop_params": True,
                },
            )
            if commit_message:
                break  # Found a model that could generate the message

        if not commit_message:
            self.io.tool_error("Failed to generate commit message!")
            return

        commit_message = commit_message.strip()
        if commit_message and commit_message[0] == '"' and commit_message[-1] == '"':
            commit_message = commit_message[1:-1].strip()

        self.io.start_spinner(self.io.last_spinner_text, update_last_text=False)
        return commit_message

    def get_diffs(self, fnames=None):
        # We always want diffs of index and working dir

        with self._git_lock:
            current_branch_has_commits = False
            try:
                active_branch = self.repo.active_branch
                try:
                    commits = self.repo.iter_commits(active_branch)
                    current_branch_has_commits = any(commits)
                except ANY_GIT_ERROR:
                    pass
            except (TypeError,) + ANY_GIT_ERROR:
                pass

            if not fnames:
                fnames = []

            diffs = ""
            for fname in fnames:
                if not self.path_in_repo(fname):
                    diffs += f"Added {fname}\n"

            try:
                if current_branch_has_commits:
                    args = ["HEAD", "--"] + list(fnames)
                    diffs += self.repo.git.diff(*args, stdout_as_string=False).decode(
                        self.io.encoding, "replace"
                    )
                    return diffs

                wd_args = ["--"] + list(fnames)
                index_args = ["--cached"] + wd_args

                diffs += self.repo.git.diff(*index_args, stdout_as_string=False).decode(
                    self.io.encoding, "replace"
                )
                diffs += self.repo.git.diff(*wd_args, stdout_as_string=False).decode(
                    self.io.encoding, "replace"
                )

                return diffs
            except ANY_GIT_ERROR as err:
                self.io.tool_error(f"Unable to diff: {err}")

    def diff_commits(self, pretty, from_commit, to_commit=None):
        with self._git_lock:
            args = []
            if pretty:
                args += ["--color"]
            else:
                args += ["--color=never"]

            if to_commit is not None:
                args += [from_commit, to_commit]
            else:
                args += [from_commit]
            diffs = self.repo.git.diff(*args, stdout_as_string=False).decode(
                self.io.encoding, "replace"
            )

            return diffs

    def get_tracked_files(self):
        with self._git_lock:
            if not self.repo:
                return []

            self.init_repo()

            try:
                commit = self.repo.head.commit
            except ValueError:
                commit = None
            except ANY_GIT_ERROR as err:
                self.git_repo_error = err
                self.io.tool_error(f"Unable to list files in git repo: {err}")
                self.io.tool_output("Is your git repo corrupted?")
                return []

            files = set()
            if commit:
                if self._tree_cache is not None and self._tree_cache[0] == commit.hexsha:
                    files = self._tree_cache[1]
                else:
                    try:
                        iterator = commit.tree.traverse()
                        blob = None  # Initialize blob
                        while True:
                            try:
                                blob = next(iterator)
                                if blob.type == "blob":  # blob is a file
                                    # Use sys.intern() to deduplicate path strings in memory
                                    files.add(sys.intern(blob.path))
                            except IndexError:
                                # Handle potential index error during tree traversal
                                # without relying on potentially unassigned 'blob'
                                self.io.tool_warning(
                                    "GitRepo: Index error encountered while reading git tree object."
                                    " Skipping."
                                )
                                continue
                            except StopIteration:
                                break
                    except ANY_GIT_ERROR as err:
                        self.git_repo_error = err
                        self.io.tool_error(f"Unable to list files in git repo: {err}")
                        self.io.tool_output("Is your git repo corrupted?")
                        return []
                    files = set(self.normalize_path(path) for path in files)
                    # Use single-entry cache (not per-commit dict) to limit memory growth
                    # Store only the SHA string (not the Commit object) to avoid retaining
                    # the entire git object graph (tree, blobs, parent commits, etc.)
                    self._tree_cache = (commit.hexsha, files)

            # Add staged files
            index = self.repo.index
            try:
                staged_files = [path for path, _ in index.entries.keys()]
                files.update(self.normalize_path(path) for path in staged_files)
            except ANY_GIT_ERROR as err:
                self.io.tool_error(f"Unable to read staged files: {err}")

            res = [fname for fname in files if not self.ignored_file(fname)]

            return res

    def normalize_path(self, path):
        orig_path = path
        res = self.normalized_path.get(orig_path)
        if res:
            return res

        path = str(Path(PurePosixPath((Path(self.root) / path).relative_to(self.root))))

        self.normalized_path[orig_path] = path
        return path

    def refresh_cecli_ignore(self):
        if not self.cecli_ignore_file:
            return

        current_time = time.time()
        if current_time - self.cecli_ignore_last_check < 1:
            return

        self.cecli_ignore_last_check = current_time

        if not self.cecli_ignore_file or not self.cecli_ignore_file.is_file():
            return

        mtime = self.cecli_ignore_file.stat().st_mtime
        if mtime != self.cecli_ignore_ts:
            self.cecli_ignore_ts = mtime
            self.ignore_file_cache = {}
            lines = self.cecli_ignore_file.read_text().splitlines()
            self.cecli_ignore_spec = pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern,
                lines,
            )

    def _get_gitignore_spec(self, dir_path):
        """Get or create a GitIgnoreSpec for a directory, caching for performance."""
        dir_path = Path(dir_path).resolve()

        # Check cache first
        if dir_path in self.gitignore_spec_cache:
            return self.gitignore_spec_cache[dir_path]

        # Read .gitignore from this directory
        patterns = []
        gitignore_path = dir_path / ".gitignore"
        if gitignore_path.is_file():
            try:
                with safe_open(gitignore_path, "r") as f:
                    patterns = [
                        line.rstrip("\n") for line in f if line.strip() and not line.startswith("#")
                    ]
            except (OSError, IOError):
                pass

        # Create spec for this directory
        if patterns:
            spec = pathspec.GitIgnoreSpec.from_lines(patterns)
        else:
            spec = pathspec.GitIgnoreSpec.from_lines([])

        self.gitignore_spec_cache[dir_path] = spec
        return spec

    def _resolve_path_in_repo(self, path):
        """Resolve *path* under this repo root (not process cwd)."""
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (Path(self.root) / file_path).resolve()
        else:
            file_path = file_path.resolve()
        return file_path

    def _is_gitignored_by_pathspec(self, path):
        """Check if a file is ignored by any .gitignore file using pathspec."""
        if not self.repo:
            return False

        try:
            file_path = self._resolve_path_in_repo(path)
            root = Path(self.root).resolve()
            if not file_path.is_relative_to(root):
                return False

            # Walk up from file's directory to root
            current_dir = file_path.parent
            relative_path = file_path.relative_to(root)

            # Check each directory level
            while current_dir.is_relative_to(root):
                spec = self._get_gitignore_spec(current_dir)

                # Get path relative to the directory containing the .gitignore
                if current_dir == root:
                    path_to_check = str(relative_path)
                else:
                    path_to_check = str(relative_path.relative_to(current_dir.relative_to(root)))

                if spec.match_file(path_to_check):
                    return True

                # Move up one directory
                if current_dir == root:
                    break
                current_dir = current_dir.parent

            return False
        except (ValueError, OSError):
            return False

    def git_ignored_file(self, path):
        if not self.repo:
            return
        try:
            if not self.cecli_ignore_file or not self.cecli_ignore_file.is_file():
                return self._is_gitignored_by_pathspec(path)
            else:
                return self.ignored_file(path)
        except ANY_GIT_ERROR:
            return False

    def ignored_file(self, fname):
        self.refresh_cecli_ignore()

        if fname in self.ignore_file_cache:
            return self.ignore_file_cache[fname]

        result = self.ignored_file_raw(fname)
        self.ignore_file_cache[fname] = result
        return result

    def ignored_file_raw(self, fname):
        if self.subtree_only:
            try:
                fname_path = Path(self.normalize_path(fname))
                cwd_path = Path.cwd().resolve().relative_to(Path(self.root).resolve())
            except ValueError:
                # Issue #1524
                # ValueError: 'C:\\dev\\squid-certbot' is not in the subpath of
                # 'C:\\dev\\squid-certbot'
                # Clearly, fname is not under cwd... so ignore it
                return True

            if cwd_path not in fname_path.parents and fname_path != cwd_path:
                return True

        if not self.cecli_ignore_file or not self.cecli_ignore_file.is_file():
            return False

        try:
            fname = self.normalize_path(fname)
        except ValueError:
            return True

        return self.cecli_ignore_spec.match_file(fname)

    def get_non_ignored_files_from_root(self):
        """
        Return a set of all files in the repository that match the cecli ignore spec.

        Uses pathspec's match_tree_files method to efficiently find all matching files
        from the project root directory.

        Returns:
            set: Set of relative file paths that are ignored by the cecli ignore spec.
        """
        self.refresh_cecli_ignore()

        if not self.cecli_ignore_file or not self.cecli_ignore_file.is_file():
            return []

        if not self.cecli_ignore_spec:
            return []

        with self._git_lock:
            try:
                all_files = self.repo.git.ls_files(
                    "--others", "--cached", f"--exclude-from={str(self.cecli_ignore_file)}"
                ).splitlines()

                return [f for f in all_files if not self.ignored_file(f)]
            except Exception as e:
                # Fall back to empty set if there's an error
                self.io.tool_warning(f"Error getting ignored files from root: {e}")
                return []

    def get_repo_files(self) -> list[str]:
        """
        Get all relevant files from the repository for this single base path.
        """
        if self.cecli_ignore_file and self.cecli_ignore_file.is_file():
            return self.get_non_ignored_files_from_root()
        return self.get_tracked_files()

    def get_cache_key(self) -> str:
        """
        Generate a cache key for the current repository state.

        Combines the HEAD commit SHA with the list of staged (but not yet
        committed) files so that the cache is invalidated when either:
        - New commits are made (HEAD changes)
        - Files are staged (index differs from HEAD)

        Returns:
            SHA-256 hex digest, or empty string if repo is unavailable
        """
        with self._git_lock:
            import hashlib

            if not self.repo:
                return ""

            sha = self.get_head_commit_sha() or ""
            try:
                staged = [item.a_path for item in self.repo.index.diff("HEAD")]
            except ANY_GIT_ERROR:
                staged = []

            combined = sha + "|" + "".join(sorted(staged))
            return hashlib.sha256(combined.encode()).hexdigest()

    def path_in_repo(self, path):
        if not self.repo:
            return
        if not path:
            return

        tracked_files = set(self.get_tracked_files())
        return self.normalize_path(path) in tracked_files

    def abs_root_path(self, path):
        res = Path(self.root) / path
        return utils.safe_abs_path(res)

    def get_dirty_files(self):
        """
        Returns a list of all files which are dirty (not committed), either staged or in the working
        directory.
        """
        with self._git_lock:
            dirty_files = set()

            # Get staged files
            staged_files = self.repo.git.diff("--name-only", "--cached").splitlines()
            dirty_files.update(staged_files)

            # Get unstaged files
            unstaged_files = self.repo.git.diff("--name-only").splitlines()
            dirty_files.update(unstaged_files)

            return list(dirty_files)

    def is_dirty(self, path=None):
        with self._git_lock:
            if path and not self.path_in_repo(path):
                return True

            return self.repo.is_dirty(path=path)

    def get_head_commit(self):
        with self._git_lock:
            try:
                commit = self.repo.head.commit
                return CommitInfo(
                    hexsha=commit.hexsha,
                    message=commit.message,
                    parents=tuple(p.hexsha for p in commit.parents),
                )
            except (ValueError,) + ANY_GIT_ERROR:
                return None

    def get_head_commit_sha(self, short=False):
        with self._git_lock:
            try:
                commit = self.repo.head.commit
            except (ValueError,) + ANY_GIT_ERROR:
                return
            if not commit:
                return
            if short:
                return commit.hexsha[:7]
            return commit.hexsha

    def get_head_commit_message(self, default=None):
        with self._git_lock:
            try:
                commit = self.repo.head.commit
            except (ValueError,) + ANY_GIT_ERROR:
                return default
            if not commit:
                return default
            return commit.message


class _GitObjectProxy:
    """Routes all operations on a git sub-object through a shared single-thread executor.

    Wraps objects like ``git.Repo.git``, ``git.Repo.head``, ``git.Repo.index``
    so that every method call and attribute access is dispatched on the
    executor thread, preventing deadlocks when the underlying ``git.Repo``
    is accessed from multiple asyncio workers.

    Iterators returned by git-python methods are eagerly materialised into
    lists so that iteration happens on the executor thread, not the caller's.
    """

    def __init__(self, obj, executor):
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_executor", executor)

    def __getattr__(self, name):
        attr = getattr(self._obj, name)

        # Recursively wrap git-python objects (check FIRST since git.cmd.Git
        # is callable via __call__, but we want chained access like
        # ``repo.git.status(...)`` to stay on the executor thread).
        cls = type(attr)
        if cls.__module__ and cls.__module__.startswith("git"):
            return _GitObjectProxy(attr, self._executor)

        if callable(attr):

            def proxy_fn(*args, **kwargs):
                future = self._executor.submit(attr, *args, **kwargs)
                result = future.result()
                # Materialise iterators eagerly in the executor thread so
                # iteration never touches git objects from the caller's thread.
                if hasattr(result, "__iter__") and not isinstance(result, (str, bytes, dict)):
                    try:
                        return list(result)
                    except TypeError:
                        pass
                return result

            return proxy_fn

        return attr


class GitRepoProxy:
    """Thread-safe proxy for ``GitRepo`` that serialises all git operations
    through a single dedicated thread.

    Prevents deadlocks by ensuring only one thread ever touches the
    underlying ``git.Repo`` at any time.  Follows the same delegation
    pattern as ``IOProxy``:

    * Sync methods that access ``self.repo`` are explicitly dispatched
      to the executor and block on the result.
    * Non-git attributes and methods are forwarded transparently via
      ``__getattr__`` / ``__setattr__``.
    * Access to ``.repo`` (the raw ``git.Repo``) returns a
      ``_GitObjectProxy`` that routes every attribute and call through
      the same executor, so even callers that reach through to the
      underlying git object stay thread-safe.

    Usage::

        repo = GitRepoProxy(GitRepo(io, fnames, git_dname))
        files = repo.get_tracked_files()   # runs on executor thread
        sha = repo.get_head_commit_sha()   # runs on executor thread
    """

    def __init__(self, target):
        self._target = target
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="git-repo"
        )

    _instances: dict[str, "GitRepoProxy"] = {}

    @classmethod
    def for_root(
        cls,
        root: str | None,
        io,
        fnames=None,
        git_dname=None,
        cecli_ignore_file=None,
        **kwargs,
    ) -> "GitRepoProxy":
        """
        Return a per-base-path ``GitRepoProxy`` singleton.

        Coders that share a base path share one proxy (and its underlying
        ``git.Repo`` plus single-thread executor), so multi-repository work can
        keep each repository on its own proxy while coders on the same base path
        stay consistent. Coders on different base paths get independent proxies.

        If *root* is provided it is used as the registry key and to discover the
        repository; otherwise it is derived from *fnames* (the same discovery the
        ``GitRepo`` constructor performs).
        """
        if root is None:
            target = GitRepo(io, fnames, git_dname, cecli_ignore_file, **kwargs)
            key = os.path.normpath(os.path.abspath(target.root))
            proxy = cls._instances.get(key)
            if proxy is None:
                proxy = cls(target)
                cls._instances[key] = proxy
            else:
                _close_git_repo(target)  # Discard the just-opened duplicate
            return proxy

        key = os.path.normpath(os.path.abspath(root))
        proxy = cls._instances.get(key)
        if proxy is None:
            target = GitRepo(io, fnames or [root], git_dname, cecli_ignore_file, **kwargs)
            proxy = cls(target)
            cls._instances[key] = proxy
        return proxy

    @classmethod
    def evict(cls, root: str | None = None) -> None:
        """Drop the proxy for a base path (e.g. on coder teardown)."""
        if root is None:
            return
        key = os.path.normpath(os.path.abspath(root))
        cls._instances.pop(key, None)

    @classmethod
    def reset_instances(cls) -> None:
        """Reset all per-base-path proxies — used primarily in test teardown."""
        cls._instances.clear()

    # ------------------------------------------------------------------
    # Sync methods that access self.repo (the git.Repo object)
    # ------------------------------------------------------------------
    # Sync methods that access self.repo (the git.Repo object)
    # ------------------------------------------------------------------

    def init_repo(self):
        return self._executor.submit(self._target.init_repo).result()

    @classmethod
    def unwrap(cls, repo):
        """Unwrap a ``GitRepoProxy`` to get the underlying ``GitRepo``.

        If *repo* is already a ``GitRepo`` (not a proxy) it is returned
        unchanged.  This mirrors ``IOProxy.unwrap()`` and prevents nested
        proxy chains during coder switching (``SwitchCoderSignal``).

        Usage::

            raw = GitRepoProxy.unwrap(maybe_proxied_repo)
        """
        return repo._target if isinstance(repo, cls) else repo

    def __del__(self):
        try:
            if hasattr(self, "_target") and self._target is not None:
                self._executor.submit(self._target.__del__).result(timeout=5)
        except Exception:
            pass

    def get_rel_repo_dir(self):
        return self._executor.submit(self._target.get_rel_repo_dir).result()

    def get_diffs(self, fnames=None):
        return self._executor.submit(self._target.get_diffs, fnames).result()

    def diff_commits(self, pretty, from_commit, to_commit=None):
        return self._executor.submit(
            self._target.diff_commits, pretty, from_commit, to_commit
        ).result()

    def get_tracked_files(self):
        return self._executor.submit(self._target.get_tracked_files).result()

    def path_in_repo(self, path):
        return self._executor.submit(self._target.path_in_repo, path).result()

    def get_dirty_files(self):
        return self._executor.submit(self._target.get_dirty_files).result()

    def is_dirty(self, path=None):
        return self._executor.submit(self._target.is_dirty, path).result()

    def get_head_commit(self):
        return self._executor.submit(self._target.get_head_commit).result()

    def get_head_commit_sha(self, short=False):
        return self._executor.submit(self._target.get_head_commit_sha, short).result()

    def get_head_commit_message(self, default=None):
        return self._executor.submit(self._target.get_head_commit_message, default).result()

    def get_cache_key(self):
        return self._executor.submit(self._target.get_cache_key).result()

    def git_ignored_file(self, path):
        return self._executor.submit(self._target.git_ignored_file, path).result()

    def get_non_ignored_files_from_root(self):
        return self._executor.submit(self._target.get_non_ignored_files_from_root).result()

    def get_repo_files(self):
        return self._executor.submit(self._target.get_repo_files).result()

    # ------------------------------------------------------------------
    # Async methods  –  called from the main asyncio task only, and
    # already protected by ``_git_lock`` on the target; we do *not*
    # proxy them through the executor because they mix git operations
    # with LLM calls (``get_commit_message``) that must stay async.
    # ------------------------------------------------------------------

    # commit() is forwarded via __getattr__

    # ------------------------------------------------------------------
    # Access to the raw ``git.Repo``  –  return a sub-proxy that routes
    # every call through the same executor, so callers that reach
    # through to the underlying git object stay thread-safe.
    # ------------------------------------------------------------------

    @property
    def repo(self):
        raw = self._target.repo
        return _GitObjectProxy(raw, self._executor) if raw is not None else None

    # ------------------------------------------------------------------
    # Non-git attributes  –  transparent forwarding
    # ------------------------------------------------------------------

    def __getattr__(self, name):
        return getattr(self._target, name)

    def __setattr__(self, name, value):
        if name.startswith("_") or name in ("_target", "_executor"):
            super().__setattr__(name, value)
        else:
            setattr(self._target, name, value)
