"""
RAG over source code using LiteLLM embeddings + ChromaDB.

Default persistent location: Path.home() / ".aider" / "caches" / f"rag.{__version__}"

Usage
-----
- from aider.rag_litellm import AiderRAG
- rag = AiderRAG(project_path=".", embedding_config={
    "provider": "openai", "model": "text-embedding-small-3",
  })
- rag.build_index(); ctx = rag.query("find init function", n_results=5)

Notes
-----
- Embeddings are computed via litellm.embedding(model=f"{provider}/{model}", input=...).
- We use token-based chunking via tiktoken (1000 tokens per chunk, 100 overlap).
- Vector store is ChromaDB with a PersistentClient; collection name: "code-collection".
- Respects .gitignore and .aiderignore using pathspec with gitwildmatch rules.
- When provider == "openai", OPENAI_API_BASE is temporarily set to
  original_openai_api_base (if provided) for the embedding call and restored
  after the call, matching Agentic's behavior.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

# Disable Chroma telemetry before import (force off)
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_ENABLED"] = "False"

import chromadb
from chromadb.config import Settings as ChromaSettings
# Use Aider's lazy LiteLLM so it shares global config with chat models
from aider.llm import litellm
import pathspec
import tiktoken
from rich.console import Console

from aider import __version__

# Default embedding model (OpenAI small v3)
DEFAULT_RAG_MODEL = "openai/text-embedding-3-small"


console = Console()


# File selection rules (match Agentic approach):
# Include typical code/text formats; also allow names like "Dockerfile".
INCLUDE_EXTENSIONS = {
    # Code
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".cs", ".rb",
    ".php", ".swift", ".kt", ".m", ".mm", ".sh", ".bash", ".zsh",
    ".fish", ".ps1", ".pl", ".pm", ".r", ".scala", ".dart", ".lua",
    ".sql",
    # Markup / data / docs
    ".md", ".markdown", ".rst", ".txt", ".yml", ".yaml", ".toml",
    ".json", ".json5", ".ini", ".cfg", ".conf", ".dotenv", ".env",
    ".xml", ".html", ".htm", ".css", ".scss", ".less",
    # Build / containers / configs
    ".dockerfile", ".makefile", ".mk", ".gradle", ".groovy",
    ".bazel", ".bzl", ".nix",
    # Not extension-based but allow by filename too (handled separately)
}

# Names to include explicitly (no extension)
INCLUDE_FILENAMES = {
    "Dockerfile", "Makefile", "LICENSE", "LICENSE.txt", "COPYING", "CMakeLists.txt",
}


# Default ignore patterns (augmented by project .gitignore / .aiderignore)
IGNORE_PATTERNS = {
    ".git", "__pycache__", "node_modules", "dist", "build", "out", "target",
    ".venv", "venv", ".env", ".direnv", ".pytest_cache", ".mypy_cache", ".idea",
    ".vscode", "poetry.lock", ".aiderignore",
}


def _get_tokenizer():
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return tiktoken.get_encoding("gpt2")


def _split_text(text: str, tokenizer, chunk_size: int = 1000, chunk_overlap: int = 100) -> List[str]:
    tokens = tokenizer.encode(text)
    chunks: List[str] = []
    step = max(1, chunk_size - chunk_overlap)
    for i in range(0, len(tokens), step):
        chunk_tokens = tokens[i : i + chunk_size]
        chunks.append(tokenizer.decode(chunk_tokens))
    return chunks


def _estimate_tokens(text: str) -> int:
    """Rough token estimate using the current tokenizer; fallback to ~4 chars/token."""
    try:
        enc = _get_tokenizer()
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


class AiderRAG:
    """Source-code RAG using LiteLLM embeddings + ChromaDB.

    Parameters
    ----------
    project_path: str | Path
        Root of the project to index.
    persist_dir: Optional[Path]
        Root directory to store indices. Defaults to
        Path.home()/".aider"/"caches"/f"rag.{__version__}".
        A subfolder named after the project is used for the DB files.
    embedding_config: Optional[dict]
        Dict with keys: provider (e.g. "openai"), model (e.g. "text-embedding-small-3"),
        api_key (optional).
    original_openai_api_base: Optional[str]
        If set and provider=="openai", temporarily set OPENAI_API_BASE during
        embedding calls to this value, then restore.
    """

    def __init__(
        self,
        project_path: str | Path,
        persist_dir: Optional[Path] = None,
        embedding_config: Optional[Dict[str, Any]] = None,
        original_openai_api_base: Optional[str] = None,
    ) -> None:
        self.project_path = Path(project_path).resolve()
        base = (
            persist_dir
            if persist_dir is not None
            else Path.home() / ".aider" / "caches" / f"rag.{__version__}"
        )
        base = Path(base)
        base.mkdir(parents=True, exist_ok=True)

        safe_project = self.project_path.name.replace(os.sep, "_").replace(".", "_")
        self.db_path = base / safe_project
        self.db_path.mkdir(parents=True, exist_ok=True)

        self.embedding_config = embedding_config or {}
        if "provider" not in self.embedding_config:
            self.embedding_config["provider"] = "openai"
        if "model" not in self.embedding_config:
            self.embedding_config["model"] = "text-embedding-3-small"

        self.original_openai_api_base = original_openai_api_base

        # Ensure Chroma telemetry remains disabled in-process
        os.environ["ANONYMIZED_TELEMETRY"] = "False"
        os.environ["CHROMA_TELEMETRY_ENABLED"] = "False"

        # Initialize Chroma persistent client/collection with telemetry off
        self.client = chromadb.PersistentClient(
            path=str(self.db_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(name="code-collection")

        self.tokenizer = _get_tokenizer()

    def has_index(self) -> bool:
        try:
            return self.collection.count() > 0
        except Exception:
            return False

    def _read_ignore_file(self, fname: Path) -> List[str]:
        if not fname.exists():
            return []
        try:
            return fname.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return []

    def _scan_files(self) -> List[Path]:
        ignore_lines = list(IGNORE_PATTERNS)
        ignore_lines += self._read_ignore_file(self.project_path / ".gitignore")
        ignore_lines += self._read_ignore_file(self.project_path / ".aiderignore")

        spec = pathspec.PathSpec.from_lines("gitwildmatch", ignore_lines)

        selected: List[Path] = []
        for root, dirs, files in os.walk(self.project_path, topdown=True):
            rel_root = Path(root).relative_to(self.project_path)
            # Prune ignored dirs early
            rel_dirs = [str((rel_root / d).as_posix()) for d in dirs]
            ignored_dirs = set(spec.match_files(rel_dirs))
            dirs[:] = [d for d in dirs if str((rel_root / d).as_posix()) not in ignored_dirs]

            rel_files = [str((rel_root / f).as_posix()) for f in files]
            ignored_files = set(spec.match_files(rel_files))

            for fname in files:
                rel_path_str = str((rel_root / fname).as_posix())
                if rel_path_str in ignored_files:
                    continue
                fpath = Path(root) / fname
                # Include ALL files that are not ignored; filtering for text happens later
                selected.append(fpath)

        return selected

    def build_index(self, batch_size: int = 100, force_reindex: bool = False, quiet: bool = False) -> None:
        # Early out if already built and not forcing
        if not force_reindex and self.has_index():
            if not quiet:
                console.print("Index already exists; skipping rebuild.")
            return

        # If forcing, drop the collection to re-create
        if force_reindex:
            try:
                if self.collection.count() > 0:
                    self.client.delete_collection(name=self.collection.name)
                    self.collection = self.client.create_collection(name=self.collection.name)
            except Exception:
                # If collection missing, re-create
                self.collection = self.client.get_or_create_collection(name=self.collection.name)

        files = self._scan_files()
        if not files:
            if not quiet:
                console.print("[yellow]No files found to index.[/yellow]")
            return

        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        ids: List[str] = []
        doc_id = 0
        total_tokens = 0

        def _is_probably_binary(path: Path, max_bytes: int = 2048) -> bool:
            try:
                with open(path, "rb") as bf:
                    chunk = bf.read(max_bytes)
                if not chunk:
                    return False
                if b"\x00" in chunk:
                    return True
                # Heuristic: if too many non-text bytes, consider binary
                text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)))
                nontext = sum(b not in text_chars for b in chunk)
                return nontext / len(chunk) > 0.30
            except Exception:
                return True

        for file_path in files:
            try:
                if _is_probably_binary(file_path):
                    continue
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not read {file_path}: {e}[/yellow]")
                continue

            rel = file_path.relative_to(self.project_path)
            chunks = _split_text(content, self.tokenizer)
            for chunk in chunks:
                documents.append(chunk)
                metadatas.append({"source": str(rel)})
                ids.append(f"doc_{doc_id}")
                doc_id += 1
                # accumulate rough token estimate for stats file
                total_tokens += _estimate_tokens(chunk)

        if not documents:
            if not quiet:
                console.print("[yellow]No textual content to index after chunking.[/yellow]")
            return

        provider = str(self.embedding_config.get("provider", "openai")).lower()
        model_name = self.embedding_config.get("model", "text-embedding-3-small")
        # Do not pass api_key or override bases; rely on global Aider/litellm config
        model = f"{provider}/{model_name}"

        embeddings: List[List[float]] = []

        def perform_embedding(batch_docs: List[str]) -> None:
            # Do not change OPENAI_API_BASE; let global config handle routing
            resp = litellm.embedding(model=model, input=batch_docs).data

            for item in resp:
                try:
                    emb = getattr(item, "embedding")
                except Exception:
                    try:
                        emb = item["embedding"]  # type: ignore[index]
                    except (KeyError, TypeError):
                        console.print(
                            "[bold red]Error: Could not find 'embedding' in the API response item.[/bold red]"
                        )
                        console.print(item)
                        raise ValueError("Invalid embedding response format from API.")
                embeddings.append(list(emb))

        if not quiet:
            with console.status("Computing embeddings with LiteLLM..."):
                for i in range(0, len(documents), batch_size):
                    perform_embedding(documents[i : i + batch_size])
        else:
            for i in range(0, len(documents), batch_size):
                perform_embedding(documents[i : i + batch_size])

        # Add to Chroma in batches
        for i in range(0, len(ids), batch_size):
            self.collection.add(
                ids=ids[i : i + batch_size],
                embeddings=embeddings[i : i + batch_size],
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
            )

        # Persist simple stats sidecar for /tokens
        try:
            import json

            stats = {
                "files_indexed": len(files),
                "chunks": len(documents),
                "token_estimate": int(total_tokens),
            }
            (self.db_path / "stats.json").write_text(json.dumps(stats))
        except Exception:
            pass

        if not quiet:
            console.print(
                f"[green]Indexed {len(documents)} chunks from {len(files)} files.[/green]"
            )

    def query(self, text: str, n_results: int = 5) -> str:
        provider = str(self.embedding_config.get("provider", "openai")).lower()
        model_name = self.embedding_config.get("model", "text-embedding-3-small")
        model = f"{provider}/{model_name}"

        try:
            item = litellm.embedding(model=model, input=[text]).data[0]
            try:
                query_emb = getattr(item, "embedding")
            except Exception:
                try:
                    query_emb = item["embedding"]  # type: ignore[index]
                except (KeyError, TypeError):
                    console.print(
                        "[bold red]Error: Could not find 'embedding' in the API response item.[/bold red]"
                    )
                    console.print(item)
                    raise ValueError("Invalid embedding response format from API.")

            results = self.collection.query(query_embeddings=[list(query_emb)], n_results=n_results)
        except Exception as ex:
            raise RuntimeError(f"Failed to embed or query RAG: {ex}")
        context_parts: List[str] = []
        sources_seen = set()
        if results and results.get("documents"):
            docs0 = results["documents"][0]
            metas0 = results.get("metadatas", [[]])[0]
            for i, doc in enumerate(docs0):
                src = metas0[i].get("source") if i < len(metas0) else None
                if src and src not in sources_seen:
                    context_parts.append(f"----- From: {src} -----")
                    sources_seen.add(src)
                context_parts.append(doc)

        return "\n\n".join(context_parts) if context_parts else "No relevant context found in the index."


def cli_handle_rag(action: str, root: str | Path, embedding_model: Optional[str] = None) -> str:
    """Simple CLI hook to init/update/deinit the persistent RAG index.

    - action: "init" | "update" | "deinit"
    - root: project path (string or Path)
    - embedding_model: optional string; if given like "provider/model", split
      and set provider/model accordingly. Otherwise defaults to openai/text-embedding-small-3.
    """

    provider = "openai"
    model = "text-embedding-small-3"
    if embedding_model:
        if "/" in embedding_model:
            provider, model = embedding_model.split("/", 1)
        else:
            # bare model => assume openai provider
            model = embedding_model

    cfg = {
        "provider": provider,
        "model": model,
    }

    rag = AiderRAG(project_path=root, embedding_config=cfg)

    if action == "init":
        rag.build_index(force_reindex=False)
        return f"RAG index initialized at {rag.db_path}"
    if action == "update":
        rag.build_index(force_reindex=True)
        return f"RAG index rebuilt at {rag.db_path}"
    if action == "deinit":
        if rag.db_path.exists():
            shutil.rmtree(rag.db_path, ignore_errors=True)
            return f"RAG index removed from {rag.db_path}"
        return "No RAG index found to remove."

    return "Unsupported RAG action. Use: init | update | deinit"


__all__ = [
    "AiderRAG",
    "cli_handle_rag",
    "_get_tokenizer",
    "_split_text",
    "INCLUDE_EXTENSIONS",
    "INCLUDE_FILENAMES",
    "IGNORE_PATTERNS",
]
