"""
Repository RAG indexing for arbitrary projects.

This module provides a small, persistent RAG index for source files in a
project directory. It mirrors the patterns used by aider.help for llama_index
usage, storage, and embeddings, while extending to arbitrary repos.

Example
-------
- Build index:
    from aider.rag import RepoRAG
    rag = RepoRAG(project_root=".")  # uses ~/.aider/caches/rag.<version>/<hash>
    rag.build_index(force_reindex=False)

- Query index:
    context = rag.query("How do I initialize the database?", top_k=5)
    # Then include `context` in an LLM prompt as Aider does for help documents

Design Notes
------------
- Uses llama_index StorageContext/VectorStoreIndex and a configurable embedding
  backend. By default this uses LiteLLM with "openai/text-embedding-small-3".
  If configured to provider="huggingface", it falls back to
  llama_index.embeddings.huggingface.HuggingFaceEmbedding like aider.help.
- Persists under ~/.aider/caches/rag.<aider.__version__>/<project-hash> by
  default, so multiple repos can be indexed independently.
- Respects .gitignore and .aiderignore via pathspec. Also filters to a
  conservative set of code/text extensions and excludes common binary/image
  types using aider.utils.IMAGE_EXTENSIONS.
- Returns results formatted similarly to aider.help.Help.ask(), wrapping each
  retrieved chunk as <doc ...> ... </doc>.

If llama_index or embedding extras are not installed, RepoRAG will raise a
user-friendly error. Tests importorskip on llama_index to keep CI light unless
the extras are available.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import pathspec

from aider import __version__, utils
from aider.embeddings_litellm import LitellmEmbeddingAdapter


DEFAULT_RAG_MODEL = "openai/text-embedding-small-3"


@dataclass
class EmbeddingConfig:
    """Configuration for embeddings provider.

    Supports litellm (default) or HuggingFace via llama_index.embeddings.huggingface,
    matching aider.help defaults when provider == 'huggingface'.
    """

    provider: str = "litellm"  # or "huggingface"
    model_name: str = DEFAULT_RAG_MODEL
    api_key: Optional[str] = None
    batch_size: int = 100


class RepoRAG:
    """Persistent RAG index for an arbitrary repository directory.

    - Initializes a llama_index VectorStoreIndex and persists it.
    - Respects .gitignore and .aiderignore filtering.
    - Restricts to typical source/text files.
    - Exposes build_index() and query() convenience methods.

    Parameters
    ----------
    project_root:
        Root path of the repository or project tree to index.
    persist_dir:
        Base directory to persist indexes. If None, defaults to
        ~/.aider/caches/rag.<version>. Project data is stored in a subfolder
        named by a stable hash of the absolute project_root.
    embedding_config:
        Dict matching EmbeddingConfig fields to configure embeddings.
    """

    # A conservative set of code/text file extensions to include in the index.
    CODE_TEXT_EXTENSIONS = {
        # code
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".go",
        ".rs",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".hh",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".m",
        ".mm",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".pl",
        ".pm",
        ".r",
        ".scala",
        ".dart",
        ".lua",
        ".sql",
        # markup / data / docs
        ".md",
        ".rst",
        ".txt",
        ".html",
        ".htm",
        ".xml",
        ".yml",
        ".yaml",
        ".json",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".gradle",
        ".properties",
        ".make",
        ".mk",
        ".cmake",
        ".dockerfile",
        ".env",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
    }

    # Common directory names to prune quickly; .gitignore/.aiderignore still applied.
    PRUNE_DIRS = {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "dist",
        "build",
        "out",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".idea",
        ".vscode",
        "target",
    }

    def __init__(
        self,
        project_root: Path | str,
        persist_dir: Optional[Path] = None,
        embedding_config: Optional[dict] = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        if persist_dir is None:
            default_base = Path.home() / ".aider" / "caches" / ("rag." + __version__)
        else:
            default_base = Path(persist_dir)

        # Persist each project to a stable subfolder derived from its absolute path.
        project_key = hashlib.sha1(str(self.project_root).encode("utf-8")).hexdigest()[:16]
        self.persist_base = default_base
        self.persist_dir = default_base / project_key

        # Config embeddings similarly to aider.help.Help
        cfg = EmbeddingConfig(**(embedding_config or {}))
        self.embedding_config = cfg

        self._index = None

    # Internal helper: configure embeddings in llama_index Settings
    def _configure_embeddings(self) -> None:
        try:
            from llama_index.core import Settings
        except Exception as ex:  # pragma: no cover - import-time failures
            raise RuntimeError(
                "llama_index is required for RepoRAG. Install the rag extras:"
                " pip install 'aider-ce[rag]'"
            ) from ex

        # Enable tokenizer parallelism for HF models, like aider.help
        os.environ["TOKENIZERS_PARALLELISM"] = "true"

        if self.embedding_config.provider == "huggingface":
            try:
                from llama_index.embeddings.huggingface import HuggingFaceEmbedding
            except Exception as ex:  # pragma: no cover
                raise RuntimeError(
                    "HuggingFace embeddings unavailable. Install the rag extras:"
                    " pip install 'aider-ce[rag]'"
                ) from ex

            Settings.embed_model = HuggingFaceEmbedding(
                model_name=self.embedding_config.model_name
            )
        elif self.embedding_config.provider == "litellm":
            # Use LiteLLM-backed embeddings via our adapter
            # Preserve any original OPENAI_API_BASE for embedding calls
            original_api_base = os.environ.get("OPENAI_API_BASE")
            adapter = LitellmEmbeddingAdapter(
                model=self.embedding_config.model_name,
                api_key=self.embedding_config.api_key or os.getenv("OPENAI_API_KEY"),
                batch_size=self.embedding_config.batch_size,
                original_openai_api_base=original_api_base,
            )
            Settings.embed_model = adapter
        else:
            # Allow alternative providers via Settings.embed_model injection by caller.
            # If provider is unknown, leave Settings.embed_model unchanged.
            pass

    def _existing_index(self):
        # Try to load an existing persisted index
        try:
            from llama_index.core import StorageContext, load_index_from_storage
        except Exception as ex:  # pragma: no cover
            raise RuntimeError(
                "llama_index is required for RepoRAG. Install the rag extras:"
                " pip install 'aider-ce[rag]'"
            ) from ex

        if not self.persist_dir.exists():
            return None

        try:
            storage_context = StorageContext.from_defaults(persist_dir=self.persist_dir)
            return load_index_from_storage(storage_context)
        except (OSError, json.JSONDecodeError):
            # Corrupted cache, remove and rebuild
            shutil.rmtree(self.persist_dir, ignore_errors=True)
            return None

    def _iter_files(self) -> Iterable[Path]:
        # Iterate files under project_root with pruning; pathspec filters applied by scan_files()
        for root, dirs, files in os.walk(self.project_root):
            # prune directories early
            dirs[:] = [d for d in dirs if d not in self.PRUNE_DIRS and not d.startswith(".git/")]
            for fname in files:
                yield Path(root) / fname

    def _load_ignore_spec(self, file: Path) -> Optional[pathspec.PathSpec]:
        if not file or not file.is_file():
            return None
        try:
            lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return None
        if not lines:
            return None
        return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, lines)

    def scan_files(self) -> List[Path]:
        """Recursively scan project_root and return included files.

        Applies .aiderignore and .gitignore rules, and filters to code/text
        extensions while excluding aider.utils.IMAGE_EXTENSIONS.
        """
        project_root = self.project_root

        aider_ignore = self._load_ignore_spec(project_root / ".aiderignore")
        git_ignore = self._load_ignore_spec(project_root / ".gitignore")

        allowed_exts = self.CODE_TEXT_EXTENSIONS
        image_exts = utils.IMAGE_EXTENSIONS

        selected: List[Path] = []
        for path in self._iter_files():
            rel = path.relative_to(project_root)
            rel_str = str(rel).replace("\\", "/")

            # Skip obvious binary/image formats early
            if path.suffix.lower() in image_exts:
                continue

            # Filter to allowed code/text extensions
            if path.suffix.lower() not in allowed_exts:
                continue

            # Apply ignore specs
            if aider_ignore and aider_ignore.match_file(rel_str):
                continue
            if git_ignore and git_ignore.match_file(rel_str):
                continue

            selected.append(path)

        return selected

    def build_index(self, force_reindex: bool = False, batch_size: int = 100, quiet: bool = False):
        """Build and persist the vector index for the repository.

        If the index exists and force_reindex is False, this returns quickly.
        """
        # Configure embeddings before using llama_index
        self._configure_embeddings()

        if not force_reindex:
            existing = self._existing_index()
            if existing is not None:
                self._index = existing
                return

        try:
            from llama_index.core import Document, StorageContext, VectorStoreIndex
            from llama_index.core.node_parser import MarkdownNodeParser
            try:
                # SimpleNodeParser is sufficient for non-markdown text/code
                from llama_index.core.node_parser import SimpleNodeParser  # type: ignore
            except Exception:  # pragma: no cover - optional fallback
                SimpleNodeParser = None  # type: ignore
        except Exception as ex:  # pragma: no cover
            raise RuntimeError(
                "llama_index is required for RepoRAG. Install the rag extras:"
                " pip install 'aider-ce[rag]'"
            ) from ex

        files = self.scan_files()
        if not quiet:
            print(f"RAG indexing {len(files)} files under {self.project_root}")
        if not files:
            # Nothing to index; create cache dir and return gracefully
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            # Write a marker to indicate an empty index for diagnostics
            try:
                (self.persist_dir / "EMPTY").write_text("no files matched for RAG indexing\n")
            except OSError:
                pass
            self._index = None
            return

        md_parser = MarkdownNodeParser()
        simple_parser = SimpleNodeParser() if SimpleNodeParser else None

        nodes = []
        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                # Gracefully skip unreadable files
                continue

            rel = fpath.relative_to(self.project_root)
            metadata = {
                "source": str(rel),
                "filename": fpath.name,
                "extension": fpath.suffix,
                # Use the same key that Help.ask() expects for nice formatting
                # (we store a pseudo-URL as the relative path for display)
                "url": str(rel),
            }

            doc = Document(text=text, metadata=metadata)

            # Use markdown-aware chunking for markdown, otherwise simple parser
            if fpath.suffix.lower() == ".md":
                nodes.extend(md_parser.get_nodes_from_documents([doc]))
            elif simple_parser:
                nodes.extend(simple_parser.get_nodes_from_documents([doc]))
            else:  # Fallback to whole-document nodes
                nodes.append(doc)

        # Build and persist index
        try:
            storage_context = StorageContext.from_defaults(persist_dir=self.persist_dir)
            index = VectorStoreIndex(
                nodes, storage_context=storage_context, show_progress=not quiet
            )
            self.persist_base.mkdir(parents=True, exist_ok=True)
            index.storage_context.persist(self.persist_dir)
            self._index = index
        except Exception as ex:
            raise RuntimeError(f"Failed to build RAG index: {ex}")

    def _ensure_index(self):
        if self._index is not None:
            return self._index
        # Try load existing without rebuilding
        idx = self._existing_index()
        if idx is None:
            raise RuntimeError(
                "No RAG index found; call build_index() first or set force_reindex=True."
            )
        self._index = idx
        return idx

    def query(self, question: str, top_k: int = 5) -> str:
        """Retrieve top-k relevant chunks and format them as a single string.

        Returns a string similar to aider.help.Help.ask() which wraps each
        retrieved text block in <doc ...> tags and includes a from_url attribute
        pointing to the source (here we use the relative path).
        """
        self._configure_embeddings()
        index = self._ensure_index()

        retriever = index.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(question)

        context = f"""# Question: {question}

# Relevant repo files:

"""
        for node in nodes:
            url = node.metadata.get("url", "")
            url_attr = f' from_url="{url}"' if url else ""
            context += f"<doc{url_attr}>\n"
            context += node.text
            context += "\n</doc>\n\n"

        return context


# CLI integration helper (optional): kept minimal and internal to avoid adding
# new global commands outside aider package. Other modules can import and use
# this function to implement /rag commands if desired.
def cli_handle_rag(
    action: str, project_root: Path | str = ".", embedding_model: Optional[str] = None
) -> Optional[str]:
    """A tiny helper intended for wiring into Commands.

    - action = 'init' -> build index if not present
    - action = 'update' -> force reindex
    - action = 'deinit' -> delete persisted index for this project
    Returns a status string for user feedback, or None.
    """

    # Parse embedding_model which may be "provider/model" or just "model"
    # Defaults: provider=litellm, model=openai/text-embedding-small-3
    embedding_config = {"provider": "litellm", "model_name": DEFAULT_RAG_MODEL}
    if embedding_model:
        if "://" in embedding_model:
            # Not expected, but avoid confusing provider parsing on URLs
            embedding_config["model_name"] = embedding_model
        elif "/" in embedding_model:
            maybe_provider, rest = embedding_model.split("/", 1)
            # If the prefix is a known provider, treat as provider/model
            if maybe_provider.lower() in {"litellm", "huggingface", "openai"}:
                if maybe_provider.lower() == "huggingface":
                    embedding_config["provider"] = "huggingface"
                    embedding_config["model_name"] = rest
                else:
                    # litellm or openai/<model> both go through litellm
                    embedding_config["provider"] = "litellm"
                    embedding_config["model_name"] = embedding_model
            else:
                # Unrecognized prefix, assume it's a litellm provider/model string
                embedding_config["provider"] = "litellm"
                embedding_config["model_name"] = embedding_model
        else:
            # Bare model name, assume litellm
            embedding_config["provider"] = "litellm"
            embedding_config["model_name"] = embedding_model

    rag = RepoRAG(project_root, embedding_config=embedding_config)
    if action == "init":
        rag.build_index(force_reindex=False)
        return f"RAG index initialized at {rag.persist_dir}"
    elif action == "update":
        rag.build_index(force_reindex=True)
        return f"RAG index rebuilt at {rag.persist_dir}"
    elif action == "deinit":
        if rag.persist_dir.exists():
            shutil.rmtree(rag.persist_dir, ignore_errors=True)
            return f"RAG index removed from {rag.persist_dir}"
        return "No RAG index found to remove."
    else:
        return "Unsupported RAG action. Use: init | update | deinit"
