import difflib
import fnmatch
import os
import re
import threading
import warnings
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlparse

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
_HEADING_TEXT_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_KEY_ANCHOR_RE = re.compile(r"^#\s*([a-z0-9][a-z0-9_.-]*)\s*:\s*(.*)$")
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


def navigate_docs(question, n_files=5, n_sections=10):
    """Rank documentation files and heading sections by query-term coverage.

    Unlike :func:`keyword_retrieve`, this returns navigation targets rather
    than chunk text. Each file and heading section is scored by how many
    unique query terms it contains, which helps locate the right page when
    embedding search misses the relevant chunk.
    """
    query_tokens = list(dict.fromkeys(_tokenize(question or "")))
    query_terms = set(query_tokens)

    if not query_terms:
        return dict(files=[], sections=[])

    max_files = max(1, int(n_files))
    max_sections = max(1, int(n_sections))
    file_matches = {}
    section_matches = []

    for fname in get_package_files():
        fname = Path(fname)
        if any(fname.match(pattern) for pattern in exclude_website_pats):
            continue

        try:
            text = fname.read_text(encoding="utf-8")
        except OSError:
            continue

        path = _doc_display_path(fname)
        url = fname_to_url(str(fname))
        anchors_by_line = {anchor["start"]: anchor["slug"] for anchor in _document_anchors(text)}
        file_terms = set(_tokenize(f"{fname.parent.name} {fname.stem}"))
        matched_terms = query_terms & file_terms
        matched_sections = 0

        for heading, line_number, section_text in _iter_doc_sections(text):
            token_counts = Counter(_tokenize(f"{heading} {section_text}"))
            section_terms = [token for token in query_tokens if token in token_counts]

            if not section_terms:
                continue

            matched_terms.update(section_terms)
            matched_sections += 1
            heading_terms = set(_tokenize(heading))
            heading_hits = sum(1 for token in section_terms if token in heading_terms)
            frequency = sum(token_counts[token] for token in section_terms)
            slug = anchors_by_line.get(line_number, "")

            section_matches.append(
                dict(
                    path=path,
                    url=url,
                    heading=heading,
                    line=line_number,
                    slug=slug,
                    address=f"{path}#{slug}" if slug else path,
                    matched_terms=section_terms,
                    score=len(section_terms),
                    heading_hits=heading_hits,
                    frequency=frequency,
                )
            )

        if matched_terms:
            file_matches[path] = dict(
                path=path,
                url=url,
                filename=fname.name,
                matched_terms=[token for token in query_tokens if token in matched_terms],
                score=len(matched_terms),
                section_count=matched_sections,
            )

    files = sorted(
        file_matches.values(),
        key=lambda item: (-item["score"], -item["section_count"], item["path"]),
    )[:max_files]
    sections = sorted(
        section_matches,
        key=lambda item: (
            -item["score"],
            -item["heading_hits"],
            -item["frequency"],
            item["path"],
            item["line"],
        ),
    )[:max_sections]

    return dict(files=files, sections=sections)


def get_doc(path, max_results=20):
    """Read one docs file or browse matching docs paths.

    An exact docs-relative path (or docs URL) returns the whole markdown file.
    A directory, glob, or missing basename returns matching paths, descriptions,
    and immediate subdirectories so callers can pick the next path to read.
    """
    normalized = _normalize_doc_path(path)

    if normalized is None:
        return _empty_doc_result(
            error=(
                f"Invalid documentation path: {path}. Use a docs-relative path such as "
                "config/hooks.md."
            )
        )

    doc_path, force_browse, is_glob, anchor, anchor_requested = normalized

    try:
        max_results = max(1, int(max_results))
    except (TypeError, ValueError):
        max_results = 20

    entries = _doc_entries()

    if not is_glob and not force_browse:
        exact = _find_exact_doc(entries, doc_path)

        if exact:
            fname, display_path = exact

            try:
                text = fname.read_text(encoding="utf-8")
            except OSError as exc:
                return _empty_doc_result(error=f"Could not read {display_path}: {exc}")

            file_entry = _doc_file_entry(fname, display_path, text)

            if anchor_requested and not anchor:
                return _doc_toc_result(file_entry)

            if anchor:
                return _doc_section_result(file_entry, anchor)

            file_entry["text"] = _strip_frontmatter(file_entry["text"])

            return dict(
                file=file_entry,
                files=[],
                dirs=[],
                suggestions=[],
                total=0,
                path=display_path,
            )

    if anchor_requested:
        return _empty_doc_result(
            error=(
                f'Anchors require an exact file path: "{path}" did not match one. '
                "Read the file first, then append #heading."
            )
        )

    if is_glob or force_browse or _has_doc_prefix(entries, doc_path):
        result = _browse_docs(entries, doc_path, max_results, is_glob)

        if result["files"] or result["dirs"]:
            return result

        return _empty_doc_result(error=f"No documentation matched path={path!r}.")

    suggestions = _suggest_docs(entries, doc_path, max_results=min(3, max_results))

    if not suggestions:
        return _empty_doc_result(error=f"No documentation matched path={path!r}.")

    return dict(
        file=None,
        files=[],
        dirs=[],
        suggestions=suggestions,
        total=len(suggestions),
        path=doc_path,
    )


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
            include=["documents", "metadatas", "distances"],
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


def _doc_display_path(fname):
    """Return the docs-relative path used in navigation results."""
    parts = Path(fname).parts

    try:
        docs_index = [part.lower() for part in parts].index("docs")
    except ValueError:
        return Path(fname).name

    relative = "/".join(parts[docs_index + 1 :])
    return relative or Path(fname).name


def _iter_doc_sections(text):
    """Yield ``(heading_path, line_number, section_text)`` for each heading.

    Heading paths include parent headings (``Parent > Child``). Content before
    the first heading, including front matter, is skipped because it is not a
    navigable section.
    """
    sections = []
    heading_stack = []
    current_heading = ""
    current_line = 0
    current = []
    fence = None

    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        was_in_fence = fence is not None
        fence = _toggle_fence(line, fence)
        match = None if was_in_fence else _HEADING_RE.match(line)

        if match:
            if current_heading:
                sections.append((current_heading, current_line, "".join(current)))

            level = len(match.group(0)) - len(match.group(0).lstrip("#"))
            title = line.strip().lstrip("#").strip()
            heading_stack = heading_stack[: level - 1] + [title]
            current_heading = " > ".join(heading_stack)
            current_line = line_number
            current = [line]
        elif current_heading:
            current.append(line)

    if current_heading:
        sections.append((current_heading, current_line, "".join(current)))

    return sections


def _empty_doc_result(error=None):
    return dict(file=None, files=[], dirs=[], suggestions=[], total=0, path="", error=error)


def _doc_entries():
    """Return ``(file path, docs-relative display path)`` pairs sorted by path."""
    entries = []

    for fname in get_package_files():
        entries.append((Path(fname), _doc_display_path(fname)))

    entries.sort(key=lambda item: item[1].lower())
    return entries


def _normalize_doc_path(path):
    """Normalize a path, docs URL, or glob into a docs-relative lookup."""
    raw = str(path or "").strip()
    anchor_requested = "#" in raw

    if not raw:
        return "", True, False, "", False

    if raw in ("/", "\\"):
        return "", True, False, "", False

    is_url = raw.lower().startswith(("http://", "https://"))

    if not is_url and raw.startswith("~"):
        return None

    if not is_url and raw.startswith("/"):
        relative = raw.lstrip("/").lower()

        if not (
            relative in ("docs", "website/docs") or relative.startswith(("docs/", "website/docs/"))
        ):
            return None

    anchor = ""

    if is_url:
        parsed = urlparse(raw)
        raw = parsed.path
        anchor = unquote(parsed.fragment)

    raw, _, raw_anchor = raw.partition("#")

    if raw_anchor:
        anchor = unquote(raw_anchor)

    force_browse = not is_url and raw.endswith(("/", "\\"))
    parts = []

    for part in raw.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)

    if len(parts) >= 2 and parts[0].lower() == "website" and parts[1].lower() == "docs":
        parts = parts[2:]
    elif parts and parts[0].lower() == "docs":
        parts = parts[1:]

    doc_path = "/".join(parts)
    is_glob = any(char in doc_path for char in "*?[")

    if not doc_path:
        force_browse = True

    return doc_path, force_browse, is_glob, anchor.strip(), anchor_requested


def _find_exact_doc(entries, doc_path):
    targets = [doc_path]

    if not doc_path.lower().endswith(".md"):
        targets.append(f"{doc_path}.md")

    for target in targets:
        lowered = target.lower()
        for fname, display_path in entries:
            if display_path.lower() == lowered:
                return fname, display_path

    return None


def _has_doc_prefix(entries, doc_path):
    if not doc_path:
        return True

    prefix = doc_path.lower().rstrip("/") + "/"
    return any(display_path.lower().startswith(prefix) for _, display_path in entries)


def _doc_file_entry(fname, display_path, text):
    return dict(
        path=display_path,
        url=fname_to_url(str(fname)),
        text=text,
        lines=len(text.splitlines()),
        description=_doc_description(text),
    )


def _doc_browse_entry(fname, display_path):
    try:
        text = fname.read_text(encoding="utf-8")
    except OSError:
        return None

    return dict(
        kind="file",
        path=display_path,
        url=fname_to_url(str(fname)),
        lines=len(text.splitlines()),
        sections=len(_doc_sections(text)),
        description=_doc_description(text),
    )


def _browse_docs(entries, doc_path, max_results, is_glob):
    if is_glob:
        matches = [
            (fname, display_path)
            for fname, display_path in entries
            if fnmatch.fnmatchcase(display_path.lower(), doc_path.lower())
        ]
        files = [
            entry for entry in (_doc_browse_entry(*match) for match in matches) if entry is not None
        ]

        return dict(
            file=None,
            files=files[:max_results],
            dirs=[],
            suggestions=[],
            total=len(files),
            path=doc_path,
            error=None,
        )

    prefix = f"{doc_path}/" if doc_path else ""
    files = []
    dir_counts = {}

    for fname, display_path in entries:
        if prefix and not display_path.lower().startswith(prefix.lower()):
            continue

        relative = display_path[len(prefix) :]
        if "/" in relative:
            dir_name = relative.split("/", 1)[0]
            dir_counts[dir_name] = dir_counts.get(dir_name, 0) + 1
            continue

        entry = _doc_browse_entry(fname, display_path)
        if entry is not None:
            files.append(entry)

    dirs = [
        dict(kind="dir", path=f"{doc_path}/{name}".strip("/"), count=count)
        for name, count in sorted(dir_counts.items())
    ]
    visible = []

    for index in range(max_results):
        if index < len(dirs):
            visible.append(dirs[index])

        if len(visible) >= max_results:
            break

        if index < len(files):
            visible.append(files[index])

        if len(visible) >= max_results:
            break

    return dict(
        file=None,
        files=[entry for entry in visible if entry["kind"] == "file"],
        dirs=[entry for entry in visible if entry["kind"] == "dir"],
        suggestions=[],
        total=len(dirs) + len(files),
        path=doc_path or ".",
        error=None,
    )


def _suggest_docs(entries, doc_path, max_results=3):
    if not doc_path:
        return []

    stem = (
        Path(doc_path).stem.lower()
        if doc_path.lower().endswith(".md")
        else Path(doc_path).name.lower()
    )
    suggestions = []

    for fname, display_path in entries:
        name = Path(display_path).stem.lower()
        if stem and (stem in name or name in stem):
            entry = _doc_browse_entry(fname, display_path)
            if entry is not None:
                suggestions.append(entry)

        if len(suggestions) >= max_results:
            break

    return suggestions


def _doc_description(text):
    """Return the front-matter description, falling back to the first heading."""
    description = ""
    lines = text.splitlines()

    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.lower().startswith("description:"):
                description = line.split(":", 1)[1].strip().strip("\"'")
                break

    if not description:
        description = _first_doc_heading(text)

    if not description:
        description = _first_doc_line(text)

    return _clip_text(description)


def _first_doc_heading(text):
    fence = None

    for line in text.splitlines():
        was_in_fence = fence is not None
        fence = _toggle_fence(line, fence)

        if not was_in_fence and _HEADING_RE.match(line):
            return line.strip().lstrip("#").strip()

    return ""


def _first_doc_line(text):
    in_frontmatter = False

    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()

        if not stripped:
            continue

        if index == 0 and stripped == "---":
            in_frontmatter = True
            continue

        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue

        return stripped

    return ""


def _clip_text(text, limit=100):
    text = " ".join(str(text or "").split())

    if len(text) <= limit:
        return text

    return text[: limit - 3].rstrip() + "..."


def _doc_sections(text):
    """Return ``(heading_path, level, start_line, end_line)`` per heading.

    Ranges are subtrees: a section runs until the next heading of the same or
    higher level, so ``## A`` includes its ``### B`` children. Headings inside
    fenced code blocks are ignored, as are front-matter lines.
    """
    lines = text.splitlines(keepends=True)
    headings = []
    stack = []
    fence = None

    for line_number, line in enumerate(lines, start=1):
        was_in_fence = fence is not None
        fence = _toggle_fence(line, fence)

        if was_in_fence:
            continue

        match = _HEADING_TEXT_RE.match(line)

        if not match:
            continue

        level = len(match.group(1))
        stack = stack[: level - 1] + [match.group(2).strip()]
        headings.append((line_number, level, " > ".join(stack)))

    sections = []

    for index, (start, level, heading) in enumerate(headings):
        end = len(lines) + 1

        for later_start, later_level, _ in headings[index + 1 :]:
            if later_level <= level:
                end = later_start
                break

        sections.append((heading, level, start, end))

    return sections


def _doc_slug(text):
    """Return a URL-fragment slug for a heading title, key, or anchor."""
    return "-".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def _doc_section_slug(text):
    """Normalize a heading or anchor to a space-separated comparison key."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def _document_anchors(text):
    """Return heading anchors with unique, feed-back-able slugs.

    Each entry holds ``heading``, ``level``, ``start``, ``end`` and ``slug``.
    A leaf slug is used when it is unique in the document; ambiguous leaves are
    qualified with their parent headings, so ``#examples`` never dangles.
    """
    sections = _doc_sections(text)
    leaves = Counter(_doc_slug(heading.split(" > ")[-1]) for heading, *_ in sections)
    anchors = []
    used = set()

    for heading, level, start, end in sections:
        leaf = _doc_slug(heading.split(" > ")[-1])
        slug = leaf if leaves[leaf] == 1 else _doc_slug(heading.replace(" > ", " "))
        base = slug or "section"
        slug = base
        suffix = 2

        while slug in used:
            slug = f"{base}-{suffix}"
            suffix += 1

        used.add(slug)
        anchors.append(dict(heading=heading, level=level, start=start, end=end, slug=slug))

    return anchors


def _doc_keys(text):
    """Return sample-config key anchors from commented defaults in fences.

    Each entry holds ``key``, ``value``, ``description``, ``start`` (the
    description line) and ``end`` (the key line).
    """
    keys = []
    fence = None
    description = ""
    description_line = 0

    for line_number, line in enumerate(text.splitlines(), start=1):
        was_in_fence = fence is not None
        fence = _toggle_fence(line, fence)

        if not was_in_fence:
            description, description_line = "", 0
            continue

        if line.startswith("## "):
            description, description_line = line[3:].strip(), line_number
            continue

        match = _KEY_ANCHOR_RE.match(line)

        if not match or not description_line:
            continue

        value = match.group(2).strip()

        if value.startswith(("//", "http")) or "://" in value:
            continue

        keys.append(
            dict(
                key=match.group(1),
                value=value,
                description=description,
                start=description_line or line_number,
                end=line_number,
            )
        )

    return keys


def _find_doc_key(text, wanted):
    """Return the sample-config key anchor matching *wanted*, or ``None``."""
    wanted_slug = _doc_slug(wanted)

    if not wanted_slug:
        return None

    for entry in _doc_keys(text):
        if _doc_slug(entry["key"]) == wanted_slug:
            return entry

    return None


def _find_doc_section(text, heading):
    """Return ``(heading_path, level, start, end)`` for *heading*, or ``None``.

    Resolves a generated slug first, then the full heading path, then any
    single ``>``-separated segment, so ``Deduplication`` resolves inside
    ``Merge Precedence`` without the caller knowing the parent heading.
    """
    wanted_slug = _doc_slug(heading)

    if wanted_slug:
        for anchor in _document_anchors(text):
            if anchor["slug"] == wanted_slug:
                return (
                    anchor["heading"],
                    anchor["level"],
                    anchor["start"],
                    anchor["end"],
                )

    wanted = _doc_section_slug(heading)

    if not wanted:
        return None

    sections = _doc_sections(text)

    for section in sections:
        if _doc_section_slug(section[0]) == wanted:
            return section

    for section in sections:
        if wanted in [_doc_section_slug(part) for part in section[0].split(" > ")]:
            return section

    return None


def _doc_section_result(file_entry, anchor):
    """Slice one heading section or config key out of *file_entry*."""
    text = file_entry.get("text") or ""
    section = _find_doc_section(text, anchor)

    if section is None:
        key_entry = _find_doc_key(text, anchor)

        if key_entry is not None:
            return _doc_key_result(file_entry, key_entry)

        return _empty_doc_result(error=_doc_anchor_error(file_entry, anchor))

    heading_path, level, start, end = section
    lines = text.splitlines(keepends=True)
    clipped = dict(file_entry)
    clipped["text"] = "".join(lines[start - 1 : end - 1])
    clipped["section"] = heading_path
    clipped["level"] = level
    clipped["slug"] = _anchor_at(text, start).get("slug", "")
    clipped["start_line"] = start
    clipped["end_line"] = end - 1

    return _doc_result(clipped, file_entry)


def _doc_key_result(file_entry, key_entry):
    """Return one sample-config key pair as a file-shaped result."""
    text = file_entry.get("text") or ""
    lines = text.splitlines(keepends=True)
    start, end = key_entry["start"], key_entry["end"]
    clipped = dict(file_entry)
    clipped["text"] = "".join(lines[start - 1 : end])
    clipped["key"] = key_entry["key"]
    clipped["key_value"] = key_entry["value"]
    clipped["slug"] = _doc_slug(key_entry["key"])
    clipped["start_line"] = start
    clipped["end_line"] = end

    return _doc_result(clipped, file_entry)


def _doc_result(clipped, file_entry):
    """Wrap one sliced file entry in the standard ``get_doc`` result shape."""
    return dict(
        file=clipped,
        files=[],
        dirs=[],
        suggestions=[],
        total=0,
        path=file_entry.get("path", ""),
        error=None,
    )


def _doc_toc_result(file_entry):
    """Return a heading and config-key outline for one docs file."""
    text = file_entry.get("text") or ""
    anchors = _document_anchors(text)
    keys = _doc_keys(text)

    return dict(
        file=None,
        files=[],
        dirs=[],
        suggestions=[],
        total=len(anchors),
        path=file_entry.get("path", ""),
        error=None,
        toc=dict(
            path=file_entry.get("path", ""),
            url=file_entry.get("url", ""),
            lines=file_entry.get("lines", 0),
            sections=anchors,
            keys=[entry["key"] for entry in keys],
        ),
    )


def _doc_anchor_error(file_entry, anchor):
    """Explain an unmatched anchor, naming the closest headings and keys."""
    text = file_entry.get("text") or ""
    names = [section[0] for section in _doc_sections(text)]
    keys = [entry["key"] for entry in _doc_keys(text)]
    path = file_entry.get("path", "")
    closest_headings = difflib.get_close_matches(str(anchor), names, n=3, cutoff=0.3)
    closest_keys = difflib.get_close_matches(str(anchor), keys, n=3, cutoff=0.3)

    if keys:
        message = f'No heading or key matched "{anchor}" in {path}.'
    else:
        message = f'No heading matched "{anchor}" in {path}.'

    if closest_headings:
        message += " Closest heading: " + "; ".join(closest_headings) + "."

    if closest_keys:
        message += " Closest key: " + "; ".join(closest_keys) + "."

    counts = f"{len(names)} headings"

    if keys:
        counts += f", {len(keys)} keys"

    return message + f" ({counts}; read the file to list them all.)"


def _strip_frontmatter(text):
    """Drop ``parent``/``nav_order`` lines from YAML front matter.

    Whole-file reads keep the rest of the front matter, including the
    ``description`` line, but the navigation-only keys are noise for an agent.
    """
    lines = text.splitlines(keepends=True)

    if len(lines) < 3 or lines[0].strip() != "---":
        return text

    closing = None

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break

    if closing is None:
        return text

    body = [
        line
        for line in lines[1:closing]
        if not line.lstrip().lower().startswith(("parent:", "nav_order:"))
    ]

    return "".join([lines[0]] + body + lines[closing:])


def _anchor_at(text, line):
    """Return the heading anchor starting at *line*, or ``None``."""
    for anchor in _document_anchors(text):
        if anchor["start"] == line:
            return anchor

    return None


def locate_doc_chunk(chunk_id):
    """Return the docs path, heading, and line range for a chunk id."""
    source, separator, index = str(chunk_id or "").rpartition("#")

    if not separator or not index.isdigit():
        return None

    fname = Path(source)

    try:
        text = fname.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None

    chunks = _chunk_document(text)
    position = int(index)

    if position >= len(chunks):
        return None

    chunk = chunks[position]
    start_offset = text.find(chunk)

    if start_offset < 0:
        start_offset = text.find(chunk.strip())

    if start_offset < 0:
        return None

    start_line = text.count("\n", 0, start_offset) + 1
    end_offset = start_offset + len(chunk)
    end_line = text.count("\n", 0, end_offset) + (0 if chunk.endswith("\n") else 1)
    heading = ""
    active_start = -1

    for section_heading, _, section_start, section_end in _doc_sections(text):
        if section_start <= start_line < section_end and section_start > active_start:
            heading = section_heading
            active_start = section_start

    return dict(
        path=_doc_display_path(fname),
        url=fname_to_url(str(fname)),
        heading=heading,
        start_line=start_line,
        end_line=max(start_line, end_line),
        lines=len(text.splitlines()),
    )


def rank_doc_addresses(query, max_results=5):
    """Rank feed-back-able docs addresses for *query*, one address per file.

    Addresses are ``path#slug`` for a matched heading and ``path`` for a page
    with no matching section. Ranking reuses :func:`navigate_docs`, so no
    embeddings or index rebuild are involved, and each file contributes at most
    one address so a large page cannot flood the results.
    """
    query = str(query or "").strip()

    if not query:
        return dict(addresses=[], total=0, query=query)

    try:
        limit = max(1, int(max_results))
    except (TypeError, ValueError):
        limit = 5

    navigation = navigate_docs(query, n_files=max(limit * 3, 15), n_sections=max(limit * 4, 12))
    files_by_path = {display: fname for fname, display in _doc_entries()}
    sections_by_file = {}

    for section in navigation.get("sections") or []:
        sections_by_file.setdefault(section.get("path", ""), section)

    addresses = []

    for item in navigation.get("files") or []:
        if len(addresses) >= limit:
            break

        path = item.get("path", "")
        fname = files_by_path.get(path)

        if fname is None:
            continue

        try:
            text = fname.read_text(encoding="utf-8")
        except OSError:
            continue

        section = sections_by_file.get(path)
        anchor = _anchor_at(text, section.get("line", 0)) if section else None

        if anchor is not None:
            addresses.append(
                dict(
                    kind="section",
                    path=path,
                    address=f"{path}#{anchor['slug']}",
                    heading=anchor["heading"],
                    lines=[anchor["start"], anchor["end"] - 1],
                )
            )
        else:
            addresses.append(
                dict(
                    kind="file",
                    path=path,
                    address=path,
                    heading="",
                    description=_doc_description(text),
                    lines=[1, len(text.splitlines())],
                )
            )

    return dict(
        addresses=addresses,
        total=len(navigation.get("files") or []),
        query=query,
    )
