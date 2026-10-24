"""Shared directory exclusions for repo maps, grep, and filesystem scans.

Keeping the canonical list in one place stops the three consumers from silently
drifting apart as new build tools and ecosystems appear.
"""

# Directories whose contents are vendored, generated, or VCS metadata. The repo
# map never parses them: their tags are noise, and walking them can be slow or
# crash on partially-dangling paths (issue #720).
DEFAULT_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".cecli",
        ".venv",
        "venv",
        "site-packages",
        "node_modules",
        "bower_components",
        "__pycache__",
        ".eggs",
        "eggs",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        ".next",
        ".nuxt",
        "dist",
        "build",
        "target",
        ".build",
        ".cargo",
        ".gradle",
        ".mvn",
        "obj",
        "vendor",
        ".bundle",
        "Pods",
    }
)

# Wildcarded directory names, matched with shell semantics against each path component.
DEFAULT_EXCLUDE_DIR_GLOBS = frozenset({"*.egg-info"})

# Extra names the grep tool hides. These may be ordinary source directories in
# some projects, so the scanner and the repo map keep them visible.
GREP_EXTRA_EXCLUDE_DIRS = (
    "env",
    ".env",
    "bin",
    "lib",
    "lib64",
    ".dub",
    "dub.selections.json",
    "*.pyc",
)

# Entries the scandir builder keeps walking. Most are source-like trees that stay
# searchable in non-git projects; the rest preserve its historical behaviour.
SCANDIR_KEEP_DIRS = frozenset(
    {
        ".hg",
        ".svn",
        ".cecli",
        "site-packages",
        "bower_components",
        ".nox",
        ".nuxt",
        "obj",
        "vendor",
        ".bundle",
        "Pods",
        ".build",
        ".cargo",
        ".mvn",
    }
)
