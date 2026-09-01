"""
File ignore rules for non-git mode.

In git mode, .gitignore is handled by git ls-files natively.
In scandir mode, we need our own ignore logic.
"""

from pathlib import Path

import pathspec

from cecli.decoding import safe_open

# Directories to always ignore (common noise sources)
DEFAULT_IGNORE_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".eggs",
        "eggs",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        "build",
        "dist",
        ".next",
        "target",
        ".gradle",
    }
)

# File patterns to always ignore
DEFAULT_IGNORE_PATTERNS = frozenset(
    {
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.so",
        "*.dylib",
        "*.dll",
        ".DS_Store",
        "Thumbs.db",
        "*.egg-info/",
    }
)


class FileIgnoreFilter:
    """
    Combined ignore filter that checks:
      1. .cecli.ignore file (if present)
      2. Common default patterns
    """

    def __init__(self, cecli_ignore_path: str | None = None):
        self.cecli_ignore_spec = None
        if cecli_ignore_path and Path(cecli_ignore_path).is_file():
            with safe_open(cecli_ignore_path) as f:
                self.cecli_ignore_spec = pathspec.PathSpec.from_lines(
                    pathspec.patterns.GitWildMatchPattern, f
                )

    def is_dir_ignored(self, rel_dir: str) -> bool:
        """Check if a directory should be ignored during filesystem walk."""
        dirname = Path(rel_dir).name
        if dirname in DEFAULT_IGNORE_DIRS:
            return True
        if self.cecli_ignore_spec and self.cecli_ignore_spec.match_file(rel_dir):
            return True
        return False

    def is_file_ignored(self, rel_path: str) -> bool:
        """Check if a file should be ignored."""
        if self.cecli_ignore_spec and self.cecli_ignore_spec.match_file(rel_path):
            return True
        return False
