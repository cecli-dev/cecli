import os
import warnings
from pathlib import Path

import importlib_resources

from cecli import __version__, utils
from cecli.help_pats import exclude_website_pats

warnings.simplefilter("ignore", category=FutureWarning)

os.environ["TQDM_DISABLE"] = "1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_DATASETS_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "true"


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

    Chroma's default ONNX embedding needs no ``sentence_transformers`` or
    ``datasets``, so it avoids the WSL2 + OpenSSL 3.5 + Python 3.14 lazy-init
    flake and the ``datasets`` circular import that broke ``/help <question>``.
    Returns the chromadb collection ready for text queries.
    """
    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    dname = Path.home() / ".cecli" / "caches" / ("help." + __version__)
    dname.parent.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(dname))
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
            documents.append(fname.read_text(encoding="utf-8"))
            ids.append(str(fname))
            metadatas.append(dict(filename=fname.name, url=fname_to_url(str(fname))))

        if documents:
            collection.add(ids=ids, documents=documents, metadatas=metadatas)

    return collection


class Help:
    """Vector retriever over the bundled help docs using a local chromadb store."""

    def __init__(self, coder=None):
        self.collection = get_index(coder=coder)

    def ask(self, question):
        results = self.collection.query(
            query_texts=[question],
            n_results=20,
            include=["documents", "metadatas"],
        )
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        context = f"# Question: {question}\n\n# Relevant docs:\n\n"
        for doc, meta in zip(documents, metadatas):
            url = (meta or {}).get("url", "")
            if url:
                url = f' from_url="{url}"'
            context += f"<doc{url}>\n"
            context += doc
            context += "\n</doc>\n\n"
        return context


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
