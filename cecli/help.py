import json
import os
import shutil
import warnings
from pathlib import Path

import importlib_resources

from cecli import __version__, utils
from cecli.dump import dump  # noqa
from cecli.help_pats import exclude_website_pats
from cecli.helpers.file_searcher import handle_core_files

warnings.simplefilter("ignore", category=FutureWarning)


async def install_help_extra(io):
    pip_install_cmd = ["cecli[help]", "--extra-index-url", "https://download.pytorch.org/whl/cpu"]
    res = await utils.check_pip_install_extra(
        io,
        "llama_index.embeddings.huggingface",
        "To use interactive /help you need to install the help extras",
        pip_install_cmd,
    )
    return res


def get_package_files():
    for path in importlib_resources.files("cecli.website").iterdir():
        if path.is_file():
            yield path
        elif path.is_dir():
            for subpath in path.rglob("*.md"):
                yield subpath


def fname_to_url(filepath):
    website = "website"
    index = "index.md"
    md = ".md"
    filepath = filepath.replace("\\", "/")
    path = Path(filepath)
    parts = path.parts
    try:
        website_index = [p.lower() for p in parts].index(website.lower())
    except ValueError:
        return ""
    relevant_parts = parts[website_index + 1 :]
    if relevant_parts and relevant_parts[0].lower() == "_includes":
        return ""
    url_path = "/".join(relevant_parts)
    if url_path.lower().endswith(index.lower()):
        url_path = url_path[: -len(index)]
    elif url_path.lower().endswith(md.lower()):
        url_path = url_path[: -len(md)] + ".html"
    url_path = url_path.strip("/")
    return f"https://cecli.dev/{url_path}"


def get_index():
    from llama_index.core import (
        Document,
        StorageContext,
        VectorStoreIndex,
        load_index_from_storage,
    )
    from llama_index.core.node_parser import MarkdownNodeParser

    dname = handle_core_files(Path.home() / ".cecli" / "caches" / ("help." + __version__))
    index = None
    try:
        if dname.exists():
            storage_context = StorageContext.from_defaults(persist_dir=dname)
            index = load_index_from_storage(storage_context)
    except (OSError, json.JSONDecodeError):
        shutil.rmtree(dname)
    if index is None:
        parser = MarkdownNodeParser()
        nodes = []
        for fname in get_package_files():
            fname = Path(fname)
            if any(fname.match(pat) for pat in exclude_website_pats):
                continue
            doc = Document(
                text=importlib_resources.files("cecli.website")
                .joinpath(fname)
                .read_text(encoding="utf-8"),
                metadata=dict(
                    filename=fname.name, extension=fname.suffix, url=fname_to_url(str(fname))
                ),
            )
            nodes += parser.get_nodes_from_documents([doc])
        index = VectorStoreIndex(nodes, show_progress=True)
        dname.parent.mkdir(parents=True, exist_ok=True)
        index.storage_context.persist(dname)
    return index


class Help:
    def __init__(self):
        from llama_index.core import Settings
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        os.environ["TOKENIZERS_PARALLELISM"] = "true"
        Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
        index = get_index()
        self.retriever = index.as_retriever(similarity_top_k=20)

    def ask(self, question):
        nodes = self.retriever.retrieve(question)
        context = f"# Question: {question}\n\n# Relevant docs:\n\n"
        for node in nodes:
            url = node.metadata.get("url", "")
            if url:
                url = f' from_url="{url}"'
            context += f"<doc{url}>\n"
            context += node.text
            context += "\n</doc>\n\n"
        return context
