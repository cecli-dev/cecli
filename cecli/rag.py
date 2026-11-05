"""Session-scoped, in-memory RAG store over arbitrary files.

This mirrors the UX of ``/help`` RAG (chunk-aligned splitting + a
dependency-free keyword retrieval path) but generalizes it to user-specified
files and folders that are registered for the *current conversation only*.
Unlike the old persistent chromadb design, nothing is written to disk: the
chunks live on the coder (``coder.rag_files`` + ``coder.rag_index``) and
disappear when the cecli session ends, exactly like files added with ``/add``.

The commands in :mod:`cecli.commands.rag` register targets with ``/rag-add``
and ask questions with ``/rag-question``.
"""

import os
import re
from collections import Counter
from pathlib import Path

from cecli.help import _chunk_document

# Chunk size tuned for in-memory retrieval; a little larger than help chunks
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

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_KEYWORD_STOPWORDS = frozenset(
    "a an and are as at be been by can could did do does for from had has have how "
    "i if in into is it its me my no not of on or our should so than that the then "
    "this to us was we were what when where which who why will with would you your".split()
)


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


def _tokenize(text):
    """Split text into lowercase search tokens, dropping stopwords."""
    return [
        token
        for token in _TOKEN_RE.findall((text or "").lower())
        if len(token) > 1 and token not in _KEYWORD_STOPWORDS
    ]


def build_rag_index(files) -> dict:
    """Chunk each file in-memory and build a dependency-free keyword index.

    Returns a dict holding, for each file, its list of chunk entries.  Each
    entry is ``{"id", "path", "document", "document_lower", "heading_tokens",
    "body_tokens"}`` mirroring ``cecli.help._keyword_index`` so callers can score
    relevance without any external embedding backend.
    """
    import os as _os

    entries = []
    for fname in files:
        try:
            text = Path(fname).read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError):
            continue

        filename_tokens = set(_tokenize(_os.path.basename(str(fname))))
        for chunk_index, chunk in enumerate(_chunk_document(text, max_chars=_RAG_CHUNK_CHARS)):
            if not chunk.strip():
                continue
            heading_tokens = set()
            for line in chunk.splitlines():
                if line.lstrip().startswith("#"):
                    heading_tokens.update(_tokenize(line))
            entries.append(
                dict(
                    id=f"{fname}#{chunk_index}",
                    path=str(fname),
                    document=chunk,
                    document_lower=chunk.lower(),
                    filename_tokens=filename_tokens,
                    heading_tokens=heading_tokens,
                    body_tokens=Counter(_tokenize(chunk)),
                )
            )
    return {"entries": entries, "files": sorted(set(str(f) for f in files))}


def _keyword_score(entry, tokens, phrase):
    """Score a chunk using filename, heading, and body keyword overlap."""
    score = 0.0
    matched = 0
    for token in tokens:
        token_score = 0.0
        if token in entry["filename_tokens"]:
            token_score += 8.0
        if token in entry["heading_tokens"]:
            token_score += 5.0
        count = entry["body_tokens"].get(token, 0)
        if count:
            token_score += min(count, 5)
        if token_score:
            matched += 1
            score += token_score
    if matched and len(tokens) > 1 and phrase in entry["document_lower"]:
        score += 6.0
    if matched:
        score += 10.0 * matched / len(tokens)
    return score


def retrieve_from_index(index: dict, question, n_results=_MAX_RESULTS, exclude_ids=None):
    """Score chunks in a :func:`build_rag_index` result against a question.

    Returns ranked chunk dicts in the same shape the old ``RagStore.retrieve``
    produced (``id``, ``path``, ``document``, ``metadata``, ``distance``) so the
    command layer can render them uniformly.
    """
    entries = (index or {}).get("entries") or []
    if not entries:
        return []

    query_tokens = list(dict.fromkeys(_tokenize(question or "")))
    if not query_tokens:
        return []

    phrase = " ".join(query_tokens)
    exclude = set(exclude_ids or ())
    n_results = max(1, int(n_results))

    scored = []
    for entry in entries:
        if entry["id"] in exclude:
            continue
        score = _keyword_score(entry, query_tokens, phrase)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], item[1]["id"]))

    docs = []
    for score, entry in scored:
        docs.append(
            dict(
                id=entry["id"],
                path=entry["path"],
                document=entry["document"],
                metadata=dict(path=entry["path"]),
                distance=round(1.0 / (1.0 + score), 6),
            )
        )
        if len(docs) >= n_results:
            break
    return docs


def rag_context_block(index: dict, question, n_results=_MAX_RESULTS, exclude_ids=None):
    """Render retrieved chunks as an RAG context block for a prompt.

    Mirrors ``Help.ask``: returns a string block prefixed with the question
    and the retrieved ``<doc>`` sections, capped by ``_MAX_CONTEXT_CHARS``.
    """
    documents = retrieve_from_index(index, question, n_results=n_results, exclude_ids=exclude_ids)
    if not documents:
        return ""
    context = f"# Question: {question}\n\n# RAG context (retrieved from the files added this session):\n\n"
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