"""
Construction strategies for FileSystemService.

- GitBuilder: uses git ls-files (respects .gitignore)
- ScandirBuilder: uses os.walk with ignore filtering
"""

import hashlib
import os
import subprocess
import time
from pathlib import Path

from .ignore import FileIgnoreFilter


class GitBuilder:
    """Build file list from git repository."""

    @staticmethod
    def collect(root: str) -> list[str]:
        """
        Collect all tracked files relative to root.

        Uses ``git ls-files -z`` for null-delimited, encoding-safe output.
        Respects .gitignore naturally (git's built-in behavior).

        Args:
            root: Root directory of the git repository

        Returns:
            Sorted list of root-relative paths
        """
        try:
            result = subprocess.check_output(
                ["git", "ls-files", "-z"],
                cwd=root,
                text=True,
            )
            paths = [p for p in result.split("\0") if p]
            return sorted(paths)
        except subprocess.CalledProcessError:
            return []
        except FileNotFoundError:
            return []
        return sorted(paths)

    @staticmethod
    def staged_only(root: str) -> list[str]:
        """
        Get only staged files (currently staged but not committed).

        Args:
            root: Root directory of the git repository

        Returns:
            List of staged file paths relative to root
        """
        result = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "-z"],
            cwd=root,
            text=True,
        )
        return [p for p in result.split("\0") if p]

    @staticmethod
    def get_head_sha(root: str) -> str:
        """
        Get current HEAD SHA for cache invalidation.

        Args:
            root: Root directory of the git repository

        Returns:
            HEAD commit SHA string, or empty string on failure
        """
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            return ""

    @staticmethod
    def get_cache_key(root: str) -> str:
        """
        Generate a cache key combining HEAD SHA and staged file paths.

        Combines the current HEAD commit hash with the list of staged
        (but not yet committed) files so that new files appear in the
        index even before they are committed.

        Args:
            root: Root directory of the git repository

        Returns:
            SHA-256 hex digest as cache key
        """
        sha = GitBuilder.get_head_sha(root)
        staged = GitBuilder.staged_only(root)
        combined = sha + "|" + "".join(sorted(staged))
        return hashlib.sha256(combined.encode()).hexdigest()


class ScandirBuilder:
    """Build file list by walking filesystem."""

    @staticmethod
    def collect(
        root: str,
        ignore_filter: "FileIgnoreFilter | None" = None,
        max_files: int = 65536,  # 2^14 hard limit
        max_depth: int = 5,  # 5 levels deep limit
    ) -> list[str]:
        """
        Walk filesystem collecting files relative to root using Breadth-First Search.
        Highly optimized: lazy iteration, single-pass evaluation, and raw string paths.
        """
        start_time = time.monotonic()

        paths = []

        # Only use pathlib for initial resolution, then stick to raw strings for speed
        root_path_obj = Path(root).resolve()
        root_path_str = str(root_path_obj)

        path_parts = [part.lower() for part in root_path_obj.parts]
        is_subfolder_of_user = "home" in path_parts[:-1] or "users" in path_parts[:-1]

        # Queue: (absolute_path_string, relative_posix_path, current_depth)
        dirs_to_scan = [(root_path_str, ".", 0)]
        path_count = 0

        while dirs_to_scan:
            if time.monotonic() - start_time > 120:
                break

            next_dirs = []

            for current_path, rel_dir, depth in dirs_to_scan:
                try:
                    # Keep it as an iterator; do NOT cast to list()
                    with os.scandir(current_path) as it:
                        file_count = 0

                        # Single pass through the directory contents
                        for entry in it:
                            # --- Handle Directories ---
                            if entry.is_dir(follow_symlinks=False):
                                if depth < max_depth:
                                    child_rel_path = (
                                        entry.name if rel_dir == "." else f"{rel_dir}/{entry.name}"
                                    )

                                    if ignore_filter and ignore_filter.is_dir_ignored(
                                        child_rel_path
                                    ):
                                        continue

                                    # Append the raw string path, avoiding slow pathlib instantiations
                                    next_dirs.append((entry.path, child_rel_path, depth + 1))

                            # --- Handle Files ---
                            elif entry.is_file(follow_symlinks=False):
                                # Short-circuit if we hit the 256 file cap (saves ignore_filter overhead)
                                if not is_subfolder_of_user and file_count >= 256:
                                    continue

                                child_rel_path = (
                                    entry.name if rel_dir == "." else f"{rel_dir}/{entry.name}"
                                )

                                if ignore_filter and ignore_filter.is_file_ignored(child_rel_path):
                                    continue

                                paths.append(child_rel_path)
                                file_count += 1
                                path_count += 1

                                # Global safety hard-stop
                                if not is_subfolder_of_user and path_count >= max_files:
                                    return sorted(paths)
                except (PermissionError, OSError, TimeoutError):
                    continue  # Skip folders we don't have read access to

            dirs_to_scan = next_dirs

        return sorted(paths)

    @staticmethod
    def get_cache_key(root: str) -> str:
        """
        Generate a cache key from directory mtime.

        Hashes the mtimes of all immediate children under root to detect
        filesystem changes. A more robust approach would hash mtimes of
        all nested entries, but this provides a good trade-off for speed.

        Args:
            root: Root directory to scan

        Returns:
            SHA-256 hex digest as cache key
        """
        mtimes = []
        for entry in os.scandir(root):
            try:
                mtimes.append(str(entry.stat().st_mtime))
            except OSError:
                continue
        return hashlib.sha256("|".join(sorted(mtimes)).encode()).hexdigest()
