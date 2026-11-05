"""Generic local chromadb RAG store over arbitrary files.

This mirrors the ``/help`` RAG mechanism (chromadb + ONNX default embedding,
heading/chunk-aligned splitting) but generalizes it to user-specified files
and folders.  A :class:`RagStore` chunks each target file, embeds the chunks
into a persistent per-project chromadb collection, and can later retrieve the
most relevant chunks for a query (retrieval-augmented generation).

The command in :mod:`cecli.commands.rag` builds the store from files/folders
selected interactively (like ``/add``) or passed as arguments.
"""

import hashlib
import os
import threading
from pathlib import Path

from cecli import __version__
from cecli.help import _chunk_document

_RAG_SCHEMA = "rag-v1"
_RAG_INDEX_LOCK = threading.Lock()
_rag_index_cache = {}

# Chunk size tuned for the ONNX embedder; a little larger than help chunks
# since user files are arbitrary.
_RAG_CHUNK_CHARS = 1500
_MAX_RESULTS = 8
_MAX_CONTEXT_CHARS = 16000

# Extensions we skip: binary/asset/generated content that has no textual value.
_SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp", ".ico",
    ".pdf", ".gz", ".zip", ".tar", ".bz2", ".7z", ".rar",
    ".pyc", ".pyo", ".class", ".o", ".obj", ".bin",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".lock",
}


def _root_hash(root: str) -> str:
    digest = hashlib.sha1(str(Path(root).resolve()).encode("utf-8")).hexdigest()
    return digest[:16]


def _store_path(root: str) -> str:
    dname = (
        Path.home()
        / ".cecli"
        / "caches"
        / f"rag.{__version__}.{_RAG_SCHEMA}.{_root_hash(root)}"
    )
    dname.parent.mkdir(parents=True, exist_ok=True)
    return str(dname)


def _is_skipped(fname: Path) -> bool:
    if fname.name.startswith(".git"):
        return True
    parts = fname.parts
    if any(p in {".git", "node_modules", ".venv", "venv", "__pycache__"} for p in parts):
        return True
    return fname.suffix.lower() in _SKIP_SUFFIXES


def collect_target_files(paths, root: str) -> list:
    """Expand files/directories/globs into a de-duplicated list of target files.

    Mirrors ``/add`` semantics: a file is a file; a directory expands to all
    contained files; a glob pattern expands against the project root.  All
    results are returned as absolute :class:`Path` objects that exist and are
    not skipped.
    """
    import glob as _glob

    root_path = Path(root)
    seen = set()
    result = []
    for raw in paths:
        raw = os.path.expanduser(raw)
        p = Path(raw)
        if not p.is_absolute():
            p = root_path / p
        if p.exists():
            candidates = [p]
        else:
            # Treat as glob relative to root
            candidates = [Path(m) for m in _glob.glob(str(p))]

        for cand in candidates:
            if cand.is_file():
                files = [cand]
            elif cand.is_dir():
                files = [f for f in cand.rglob("*") if f.is_file()]
            else:
                continue
            for f in files:
                try:
                    f = f.resolve()
                except OSError:
                    f = f
                if _is_skipped(f):
                    continue
                key = str(f)
                if key not in seen:
                    seen.add(key)
                    result.append(f)
    return sorted(set(result))


def get_rag_store(root: str, files, verbose: bool = False) -> "RagStore":
    """Build / fetch the chromadb RAG store for a set of files under ``root``."""
    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    key = _store_path(root)
    with _RAG_INDEX_LOCK:
        cached = _rag_index_cache.get(key)
        if cached is not None:
            return cached

        client = chromadb.PersistentClient(path=key)
        store = RagStore(client, "rag", DefaultEmbeddingFunction(), root, files, verbose)
        _rag_index_cache[key] = store
        return store


class RagStore:
    """A chromadb-backed vector store that chunks + embeds a fixed file set."""

    def __init__(self, client, collection_name, embedding_function, root, files, verbose=False):
        self.collection = client.get_or_create_collection(
            collection_name, embedding_function=embedding_function
        )
        self.root = root
        self.files = list(files)
        self.verbose = verbose

    def index_files(self, files=None) -> int:
        """(Re)index the given (or current) files.  Returns number of files indexed."""
        files = self.files if files is None else list(files)
        ids, documents, metadatas = [], [], []
        for fname in files:
            try:
                text = Path(fname).read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeError):
                continue
            chunks = _chunk_document(text, max_chars=_RAG_CHUNK_CHARS)
            for i, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                ids.append(f"{fname}#{i}")
                documents.append(chunk)
                metadatas.append(dict(path=str(fname)))
        if documents:
            # Replace the prior contents so re-indexing reflects current files.
            existing = self.collection.get()
            if existing["ids"]:
                self.collection.delete(ids=existing["ids"])
            self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
        return len(files)

    def count(self) -> int:
        return self.collection.count()

    def retrieve(self, question, n_results=_MAX_RESULTS, exclude_ids=None):
        """Return ranked chunks as structured dicts (same shape as Help.retrieve)."""
        total = self.count()
        if not total:
            return []
        n_results = max(1, int(n_results))
        exclude = set(exclude_ids or ())
        fetch = min(total, n_results + len(exclude))
        results = self.collection.query(
            query_texts=[question],
            n_results=fetch,
            include=["documents", "metadatas", "distances"],
        )
        ids = (results.get("ids") or [[]])[0]
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]

        docs, seen = [], set(exclude)
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            if not document or chunk_id in seen:
                continue
            seen.add(chunk_id)
            metadata = metadata or {}
            docs.append(
                dict(
                    id=chunk_id,
                    path=metadata.get("path", ""),
                    document=document,
                    metadata=metadata,
                    distance=distance,
                )
            )
            if len(docs) >= n_results:
                break
        return docs

    def ask(self, question, exclude_ids=None):
        """Render retrieved chunks as an RAG context block for a prompt."""
        documents = self.retrieve(question, exclude_ids=exclude_ids)
        if not documents:
            return ""
        context = "# RAG context (retrieved from the registered files):\n\n"
        used = 0
        for doc in documents:
            text = doc["document"]
            if not text:
                continue
            if used and used + len(text) > _MAX_CONTEXT_CHARS:
                break
            used += len(text)
            context += f'<doc from_path="{doc.get("path", "")}">\n{text}\n</doc>\n\n'
        return context