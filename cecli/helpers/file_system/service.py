"""
FileSystemService: per-base-path singleton for file path resolution and discovery.

Each distinct base path owns exactly one instance, carrying its own repo,
marisa-trie, and trigram index. Use FileSystemService.for_root(root, repo)
to obtain the instance for a base path. Coders that share a base path share
the same instance; coders on different base paths get independent instances,
so multiple repositories can be served concurrently.

get_instance() remains as a backward-compatible accessor that returns the
most-recently-active base path's instance when no root is given, and delegates
to for_root() when a root is provided.

Uses marisa-trie for memory-efficient prefix/string matching and
ngram for trigram-based fuzzy search. Supports construction from
git repositories (git ls-files) or filesystem scanning (os.scandir).
"""

import os

from cecli.decoding import safe_open

from .builders import GitBuilder, ScandirBuilder
from .ignore import FileIgnoreFilter
from .ngram_index import TrigramIndex
from .trie_index import TrieIndex


class FileSystemService:
    """
    Provides file path resolution, prefix queries, and fuzzy search.

    Singleton per base path — all coders that share a base path use one
    instance; coders on different base paths get independent instances. Use
    FileSystemService.for_root() to obtain the instance for a base path.
    """

    # --- Per-base-path singleton registry ---
    _instances: dict[str, "FileSystemService"] = {}
    _active_root: str | None = None
    _refcounts: dict[str, int] = {}

    # --- Instance attributes ---
    root: str = "."
    _mode: str | None = None  # 'git' or 'scandir'
    _build_hash: str = ""  # Cache invalidation key

    def __init__(
        self,
        root: str = ".",
        repo=None,
        cecli_ignore_file: str | None = None,
    ):
        """
        Initialize the service. Not intended for direct use —
        call for_root() instead.
        """
        self.root = os.path.normpath(root)
        self.repo = repo
        self.cecli_ignore_file = cecli_ignore_file

        # Core data structures
        self.trie_index: TrieIndex | None = None
        self.trigram_index: TrigramIndex | None = None

    @property
    def trie(self):
        """Access underlying marisa_trie.Trie for backward compatibility."""
        return self.trie_index.trie if self.trie_index else None

    @property
    def ngram(self):
        """Access underlying NGram for backward compatibility."""
        return self.trigram_index.ngram if self.trigram_index else None

    # ---------------------------------------------------------------
    # Singleton access
    # ---------------------------------------------------------------
    @staticmethod
    def _normalize_root(root: str) -> str:
        """Normalize a base path into a canonical registry key."""
        return os.path.normpath(os.path.abspath(root))

    @classmethod
    def reset_instance(cls) -> None:
        """Reset all per-base-path singletons — used primarily in test teardown."""
        cls._instances.clear()
        cls._refcounts.clear()
        cls._active_root = None

    @classmethod
    def for_root(cls, root: str | None = None, repo=None) -> "FileSystemService":
        """
        Return the singleton for a base path.

        Each distinct base path owns exactly one instance carrying its own
        repo and indices. The first call for a base path builds it; later
        calls return the cached instance. If a different repo is supplied for
        an already-cached base path, the instance's repo is re-pointed and the
        index is invalidated so the next rebuild uses the new repo.
        """
        root = root or "."
        key = cls._normalize_root(root)
        service = cls._instances.get(key)

        if service is None:
            service = cls._create(root=root, repo=repo)
            cls._instances[key] = service
        elif repo is not None and service.repo is not repo:
            service.repo = repo
            service._build_hash = ""  # Invalidate for lazy rebuild with new repo
        cls._active_root = key
        return service

    @classmethod
    def get_instance(cls, root: str | None = None, repo=None) -> "FileSystemService":
        """
        Backward-compatible accessor (see the module docstring).

        With a root, delegates to for_root(). Without a root, returns the
        most-recently-active base path's instance, building one for the
        current directory if nothing is active yet.
        """
        if root is not None:
            return cls.for_root(root=root, repo=repo)
        if cls._active_root is None:
            return cls.for_root(root=".", repo=repo)
        return cls._instances[cls._active_root]

    @classmethod
    def evict(cls, root: str | None = None) -> None:
        """Drop the instance for a base path (e.g. on coder teardown)."""
        if root is None:
            return
        key = cls._normalize_root(root)
        cls._instances.pop(key, None)
        cls._refcounts.pop(key, None)
        if cls._active_root == key:
            cls._active_root = None

    @classmethod
    def _create(cls, root: str, repo=None) -> "FileSystemService":
        """Internal factory — builds and returns a per-base-path instance."""
        service = cls(root=root, repo=repo)
        service.build()
        return service

    @classmethod
    def _inc_ref(cls, key: str) -> None:
        """Bump the reference count for a base path held by a live coder."""
        cls._refcounts[key] = cls._refcounts.get(key, 0) + 1

    @classmethod
    def _release(cls, key: str) -> None:
        """Drop one reference; evict the base-path service (and its git repo)
        when the last coder using it is destroyed."""
        count = cls._refcounts.get(key, 0)
        if count <= 1:
            cls._evict_pair(key)
        else:
            cls._refcounts[key] = count - 1

    @classmethod
    def _evict_pair(cls, key: str) -> None:
        """Evict the FileSystemService and the matching GitRepoProxy for a base path."""
        cls._instances.pop(key, None)
        cls._refcounts.pop(key, None)
        if cls._active_root == key:
            cls._active_root = None
        try:
            from cecli.repo import GitRepoProxy

            GitRepoProxy.evict(key)
        except Exception:
            pass

    def has_git(self) -> bool:
        """Check if a git repo is available at root."""
        return self.repo is not None or (os.path.isdir(os.path.join(self.root, ".git")))

    # ---------------------------------------------------------------
    # Construction
    # ---------------------------------------------------------------
    def _create_ignore_filter(self):
        """Create ignore filter for scandir mode."""
        path = self.cecli_ignore_file
        if not path and self.repo and hasattr(self.repo, "cecli_ignore_file"):
            path = str(self.repo.cecli_ignore_file)
        return FileIgnoreFilter(cecli_ignore_path=path)

    def build(self) -> None:
        """Build or rebuild the trie and trigram index."""
        if self.has_git():
            if self.repo is not None:
                # Use GitRepo instance when available — leverages its
                # workspace support, cecli_ignore filtering, and caching
                paths = self.repo.get_repo_files()
                self._build_hash = self.repo.get_cache_key()
            else:
                paths = GitBuilder.collect(self.root)
                self._build_hash = GitBuilder.get_cache_key(self.root)
            self._mode = "git"
        else:
            ignore_filter = self._create_ignore_filter()
            paths = ScandirBuilder.collect(self.root, ignore_filter)
            self._mode = "scandir"
            self._build_hash = ScandirBuilder.get_cache_key(self.root)

        self.trie_index = TrieIndex(paths)
        self.trigram_index = TrigramIndex(trie_index=self.trie_index)

    def needs_rebuild(self) -> bool:
        """Check whether the trie/index need rebuilding."""
        if self.trie_index is None:
            return True
        if self._mode == "git":
            if self.repo is not None:
                return self.repo.get_cache_key() != self._build_hash
            return GitBuilder.get_cache_key(self.root) != self._build_hash
        else:
            return ScandirBuilder.get_cache_key(self.root) != self._build_hash

    def rebuild(self) -> None:
        """Force rebuild if needed."""
        if self.needs_rebuild():
            self.build()

    # ---------------------------------------------------------------
    # Path Existence (trie-based)
    # ---------------------------------------------------------------
    def exists(self, rel_path: str) -> bool:
        """
        Check if a relative path exists in the file index.

        O(path_depth) — walks the trie by path segments.
        """
        if self.trie_index is None:
            return False
        norm_path = self._normalize(rel_path)
        return self.trie_index.exists(norm_path)

    def is_file(self, rel_path: str) -> bool:
        """Check if path exists and is a file (not a directory prefix)."""
        return self.exists(rel_path)

    @staticmethod
    def _normalize(path: str) -> str:
        """
        Normalize a path to the canonical form used by the trie.

        - Convert backslashes to forward slashes
        - Strip leading ./ or /
        - Remove redundant . and .. components
        """
        from pathlib import Path

        if not path:
            return path
        return Path(path).as_posix()

    # ---------------------------------------------------------------
    # Prefix Queries (trie-based)
    # ---------------------------------------------------------------
    def list_prefix(self, prefix: str = "") -> list[str]:
        """
        List all files with the given prefix.

        Uses marisa-trie's native keys(prefix) which leverages the
        compressed trie structure for efficient prefix matching.
        """
        if self.trie_index is None:
            return []
        norm_prefix = self._normalize(prefix)
        return self.trie_index.list_prefix(norm_prefix)

    def list_all(self) -> list[str]:
        """List all files in the index."""
        if self.trie_index is None:
            return []
        return self.trie_index.list_all()

    def count(self) -> int:
        """Number of files in the index."""
        if self.trie_index is None:
            return 0
        return self.trie_index.count()

    # ---------------------------------------------------------------
    # Fuzzy Search (trigram-based)
    # ---------------------------------------------------------------
    def search(
        self,
        query: str,
        threshold: float = 0.5,
        max_results: int = 20,
    ) -> list[str]:
        """
        Fuzzy search for files matching a query string.

        Uses the ngram.NGram index for trigram-based similarity matching.

        Args:
            query: Search string (can be partial path, basename, etc.)
            threshold: Minimum similarity (0.0-1.0, default 0.5)
            max_results: Maximum number of results to return

        Returns: List of matching file paths, sorted by relevance
        """
        if self.trigram_index is None or not query:
            return []

        norm_query = self._normalize(query)
        return self.trigram_index.search(
            norm_query,
            threshold=threshold,
            max_results=max_results,
        )

    def search_basenames(
        self,
        basename: str,
        threshold: float = 0.6,
    ) -> list[str]:
        """
        Search for files matching a basename.

        Higher default threshold since basenames are short and trigram
        overlap is naturally lower.
        """
        return self.search(basename, threshold=threshold)

    # ---------------------------------------------------------------
    # Serialization
    # ---------------------------------------------------------------
    def save(self, path: str) -> None:
        """
        Serialize the trie and trigram index to disk for fast startup.
        """
        import json
        import pickle

        trie_path = path + ".marisa"
        ngram_path = path + ".ngram"
        meta_path = path + ".json"

        if self.trie_index:
            self.trie_index.save(trie_path)
        if self.trigram_index:
            with safe_open(ngram_path, "wb") as f:
                pickle.dump(self.trigram_index, f)

        # Store metadata for cache validation
        meta = {
            "root": self.root,
            "mode": self._mode,
            "build_hash": self._build_hash,
            "file_count": self.count(),
        }
        with safe_open(meta_path, "w") as f:
            json.dump(meta, f)

    def load(self, path: str) -> bool:
        """
        Load serialized trie and index from disk.

        Returns True if load was successful, False otherwise.
        """
        import json
        import pickle

        trie_path = path + ".marisa"
        ngram_path = path + ".ngram"
        meta_path = path + ".json"

        try:
            # Load metadata
            with safe_open(meta_path) as f:
                meta = json.load(f)

            self.root = meta["root"]
            self._mode = meta["mode"]
            self._build_hash = meta["build_hash"]

            # Load trie
            self.trie_index = TrieIndex()
            if not self.trie_index.load(trie_path):
                self.trie_index = None
                return False

            # Load ngram index
            with safe_open(ngram_path, "rb") as f:
                self.trigram_index = pickle.load(f)

            # Check if cache is stale
            if self.needs_rebuild():
                self.build()
                return False  # Rebuilt, not loaded from cache
            return True

        except (FileNotFoundError, EOFError, pickle.UnpicklingError, KeyError):
            self.trie_index = None
            self.trigram_index = None
            return False
