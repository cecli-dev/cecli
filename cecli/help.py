import os
import re
import threading
import warnings
from collections import Counter
from pathlib import Path

import importlib_resources

from cecli import __version__, utils
from cecli.help_pats import exclude_website_pats

warnings.simplefilter("ignore", category=FutureWarning)

os.environ["TQDM_DISABLE"] = "1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_DATASETS_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "true"

_HELP_INDEX_SCHEMA = "chunks-v1"
_HELP_INDEX_LOCK = threading.Lock()
_help_index_cache = {}
_CHUNK_CHARS = 1000
_MAX_RESULTS = 20
_MAX_CONTEXT_CHARS = 24000

_KEYWORD_INDEX_LOCK = threading.Lock()
_keyword_index_cache = None
_KEYWORD_RESULTS = 3
_KEYWORD_STOPWORDS = frozenset(
    "a an and are as at be been by can could did do does for from had has have how "
    "i if in into is it its me my no not of on or our should so than that the then "
    "this to us was we were what when where which who why will with would you your".split()
)

_HEADING_RE = re.compile(r"^#{1,6}\s")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


async def install_help_extra(io):
    """Ensure the local chromadb backend is installed for interactive /help.

    The previous dependency chain (``llama_index.embeddings.huggingface`` ->
    ``sentence_transformers`` -> ``datasets``) crashed on the WSL2 + OpenSSL 3.5 +
    Python 3.14 lazy-init flake and on a ``datasets`` circular import. Chroma's
    default ONNX embedding needs neither, so it is what ``Help`` uses.
    """
    pip_install_cmd = [
        "cecli-dev[help]",
        "--extra-index-url",
        "https://download.pytorch.org/whl/cpu",
    ]
    return await utils.check_pip_install_extra(
        io,
        "chromadb",
        "To use interactive /help you need to install the help extras",
        pip_install_cmd,
    )


def get_package_files():
    docs = importlib_resources.files("cecli.website") / "docs"
    for path in docs.rglob("*.md"):
        yield path


def fname_to_url(filepath):
    """Map a file path in the website package to its published URL.

    Doc sources live under ``website/docs/`` and docmd renders each ``<name>.md``
    to ``<name>/index.html``, so ``docs/<path>/page.md`` becomes
    ``https://cecli.dev/docs/<path>/page/``. Top-level site files (``index.html``)
    publish to the site root. Everything else — build artifacts, ``_includes``
    partials, okf sources — is not a published page and returns ``""``.
    """
    website = "website"
    docs = "docs"
    index = "index.md"
    md = ".md"

    filepath = filepath.replace("\\", "/")
    parts = Path(filepath).parts

    try:
        website_index = [p.lower() for p in parts].index(website.lower())
    except ValueError:
        return ""

    relevant_parts = parts[website_index + 1 :]
    if not relevant_parts:
        return ""

    # Doc pages live under website/docs/ and publish to /docs/<path>/.
    if relevant_parts[0].lower() == docs:
        url_path = _strip_doc_suffix("/".join(relevant_parts[1:]), index, md)
        return _format_docs_url(url_path)

    # Only top-level site files publish to the site root; anything nested
    # (_includes, _site, .docmd-*, share, etc.) is not a page.
    if len(relevant_parts) == 1:
        return f"https://cecli.dev/{relevant_parts[0].lstrip('/')}"

    return ""


def get_index(coder=None):
    """Build a local chromadb vector index over the bundled help docs.

    Docs are split into heading-aligned chunks so the default ONNX embedding
    can represent each retrieved section instead of only the first few hundred
    tokens of an entire page. The collection is cached per process so repeated
    ``/help`` questions do not rebuild the client or reload the embedding model.
    """
    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    dname = Path.home() / ".cecli" / "caches" / f"help.{__version__}.{_HELP_INDEX_SCHEMA}"
    dname.parent.mkdir(parents=True, exist_ok=True)

    cache_key = str(dname)

    with _HELP_INDEX_LOCK:
        cached = _help_index_cache.get(cache_key)
        if cached is not None:
            return cached

        client = chromadb.PersistentClient(path=cache_key)
        collection = client.get_or_create_collection(
            "help", embedding_function=DefaultEmbeddingFunction()
        )

        if collection.count() == 0:
            documents = []
            ids = []
            metadatas = []

            for fname in get_package_files():
                fname = Path(fname)
                if any(fname.match(pat) for pat in exclude_website_pats):
                    continue

                text = fname.read_text(encoding="utf-8")
                url = fname_to_url(str(fname))

                for chunk_index, chunk in enumerate(_chunk_document(text)):
                    documents.append(chunk)
                    ids.append(f"{fname}#{chunk_index}")
                    metadatas.append(dict(filename=fname.name, url=url, chunk=chunk_index))

            if documents:
                collection.add(ids=ids, documents=documents, metadatas=metadatas)

        _help_index_cache[cache_key] = collection
        return collection


def keyword_retrieve(question, exclude_ids=None, n_results=_KEYWORD_RESULTS):
    """Retrieve help docs with a dependency-free keyword scorer.

    This is the fallback when chromadb or its ONNX embedder cannot be loaded.
    Chunks use the same ``<path>#<chunk_index>`` ids as the vector index so
    callers can keep debouncing already-seen docs. Results have the same shape
    as :meth:`Help.retrieve`.
    """
    query_tokens = _tokenize(question or "")
    if not query_tokens:
        return []

    tokens = list(dict.fromkeys(query_tokens))
    phrase = " ".join(query_tokens)
    exclude = set(exclude_ids or ())
    n_results = max(1, int(n_results))

    scored = []
    for entry in _keyword_index():
        if entry["id"] in exclude:
            continue

        score = _keyword_score(entry, tokens, phrase)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], item[1]["id"]))

    docs = []
    seen_sources = set()
    for score, entry in scored:
        source = entry["id"].rsplit("#", 1)[0]
        if source in seen_sources:
            continue

        seen_sources.add(source)
        docs.append(
            dict(
                id=entry["id"],
                url=entry["url"],
                document=entry["document"],
                metadata=dict(entry["metadata"]),
                distance=round(1.0 / (1.0 + score), 6),
            )
        )

        if len(docs) >= n_results:
            break

    return docs


class Help:
    """Vector retriever over the bundled help docs using a local chromadb store."""

    def __init__(self, coder=None):
        self.collection = get_index(coder=coder)

    def retrieve(self, question, exclude_ids=None, n_results=_MAX_RESULTS):
        """Return ranked help chunks as structured dictionaries.

        ``exclude_ids`` skips chunks already injected in earlier turns, so a
        caller can over-fetch and still receive up to ``n_results`` unseen
        chunks.  Each dictionary contains ``id``, ``url``, ``document``,
        ``metadata``, and ``distance``.
        """
        total = self.collection.count()
        if not total:
            return []

        n_results = max(1, int(n_results))
        exclude = set(exclude_ids or ())
        fetch = min(total, n_results + len(exclude))

        results = self.collection.query(
            query_texts=[question],
            n_results=fetch,
            include=["documents", "metadatas", "ids", "distances"],
        )

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        docs = []
        seen = set(exclude)
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
            if not document or chunk_id in seen:
                continue

            seen.add(chunk_id)
            metadata = metadata or {}
            docs.append(
                dict(
                    id=chunk_id,
                    url=metadata.get("url", ""),
                    document=document,
                    metadata=metadata,
                    distance=distance,
                )
            )

            if len(docs) >= n_results:
                break

        return docs

    def ask(self, question, exclude_ids=None):
        if not self.collection.count():
            return f"# Question: {question}\n\n# Relevant docs:\n\n"

        documents = self.retrieve(question, exclude_ids=exclude_ids)

        context = f"# Question: {question}\n\n# Relevant docs:\n\n"
        seen_urls = set()
        used_chars = 0

        for doc in documents:
            text = doc["document"]
            if not text:
                continue

            if used_chars and used_chars + len(text) > _MAX_CONTEXT_CHARS:
                break

            url = doc.get("url", "")
            url_attr = ""
            if url and url not in seen_urls:
                url_attr = f' from_url="{url}"'
                seen_urls.add(url)

            context += f"<doc{url_attr}>\n"
            context += text
            context += "\n</doc>\n\n"
            used_chars += len(text)

        return context


def _chunk_document(text, max_chars=_CHUNK_CHARS):
    """Split markdown into heading-aligned chunks that fit the embedder."""
    chunks = []
    current = ""

    for section in _split_markdown_sections(text):
        if len(section) > max_chars:
            if current.strip():
                chunks.append(current.strip())

            current = ""
            chunks.extend(chunk.strip() for chunk in _split_long_section(section, max_chars))
        elif current and len(current) + len(section) > max_chars:
            chunks.append(current.strip())
            current = section
        else:
            current += section

    if current.strip():
        chunks.append(current.strip())

    return [chunk for chunk in chunks if chunk]


def _split_markdown_sections(text):
    """Split on headings without breaking fenced code blocks."""
    sections = []
    current = []
    fence = None

    for line in text.splitlines(keepends=True):
        was_in_fence = fence is not None
        fence = _toggle_fence(line, fence)

        if not was_in_fence and _HEADING_RE.match(line) and current:
            sections.append("".join(current))
            current = []

        current.append(line)

    if current:
        sections.append("".join(current))

    return sections


def _split_long_section(section, max_chars):
    """Split an oversized section at paragraph boundaries when possible."""
    chunks = []
    current = []
    size = 0
    fence = None

    for line in section.splitlines(keepends=True):
        was_in_fence = fence is not None
        fence = _toggle_fence(line, fence)
        can_split = not (was_in_fence and fence is None)

        if current and size + len(line) > max_chars and can_split:
            split_at = None if was_in_fence else _last_blank_line(current)

            if split_at is None:
                chunks.append("".join(current))
                current = []
            else:
                chunks.append("".join(current[:split_at]))
                current = current[split_at:]

            size = sum(len(item) for item in current)

        current.append(line)
        size += len(line)

    if current:
        chunks.append("".join(current))

    return chunks


def _toggle_fence(line, fence):
    match = _FENCE_RE.match(line)

    if not match:
        return fence

    marker = match.group(1)[0]

    if fence is None:
        return marker

    if fence == marker:
        return None

    return fence


def _last_blank_line(lines):
    for index in range(len(lines) - 1, -1, -1):
        if not lines[index].strip():
            return index + 1

    return None


def _strip_doc_suffix(url_path, index, md):
    if url_path.lower().endswith(index.lower()):
        return url_path[: -len(index)]

    if url_path.lower().endswith(md.lower()):
        return url_path[: -len(md)]

    return url_path


def _format_docs_url(url_path):
    url_path = url_path.strip("/")

    if not url_path:
        return "https://cecli.dev/docs/"

    return f"https://cecli.dev/docs/{url_path}/"


def _tokenize(text):
    """Split text into lowercase search tokens, dropping stopwords."""
    return [
        token
        for token in _TOKEN_RE.findall((text or "").lower())
        if len(token) > 1 and token not in _KEYWORD_STOPWORDS
    ]


def _keyword_index():
    """Build and cache chunk entries for the dependency-free fallback."""
    global _keyword_index_cache

    with _KEYWORD_INDEX_LOCK:
        if _keyword_index_cache is not None:
            return _keyword_index_cache

        entries = []

        for fname in get_package_files():
            fname = Path(fname)
            if any(fname.match(pat) for pat in exclude_website_pats):
                continue

            try:
                text = fname.read_text(encoding="utf-8")
            except OSError:
                continue

            url = fname_to_url(str(fname))
            filename_tokens = set(_tokenize(f"{fname.parent.name} {fname.stem}"))

            for chunk_index, chunk in enumerate(_chunk_document(text)):
                heading_tokens = set()
                for line in chunk.splitlines():
                    if _HEADING_RE.match(line):
                        heading_tokens.update(_tokenize(line))

                entries.append(
                    dict(
                        id=f"{fname}#{chunk_index}",
                        url=url,
                        document=chunk,
                        document_lower=chunk.lower(),
                        metadata=dict(filename=fname.name, url=url, chunk=chunk_index),
                        filename_tokens=filename_tokens,
                        heading_tokens=heading_tokens,
                        body_tokens=Counter(_tokenize(chunk)),
                    )
                )

        _keyword_index_cache = entries
        return entries


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
