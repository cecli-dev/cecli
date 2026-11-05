"""The /rag command.

Mirrors the UX of ``/add`` (no-args opens a fuzzy finder; arguments accept
absolute or relative paths and directory/glob expansions) but instead of
adding files to the chat as editable targets, it registers them as RAG
objects: every file in the selection is chunked, embedded into a persistent
chromadb vector store, and becomes retrievable for retrieval-augmented
generation.
"""

import os
from pathlib import Path
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    format_command_result,
    get_file_completions,
    parse_quoted_filenames,
)
from cecli.utils import run_fzf


class RagCommand(BaseCommand):
    NORM_NAME = "rag"
    DESCRIPTION = "Register files/folders as RAG objects (chunk + embed for retrieval)"
    show_completion_notification = True

    async def execute(cls, io, coder, args, **kwargs):
        """Build the RAG index over the selected files/folders, or query it."""
        from cecli.rag import get_rag_store

        root = coder.root

        # Sub-mode: /rag q <query>  -> retrieve top chunks without indexing.
        parts = (args or "").strip().split(maxsplit=1)
        if parts and parts[0].lower() in ("q", "query", "retrieve", "search"):
            query = parts[1] if len(parts) > 1 else ""
            if not query:
                io.tool_output("Usage: /rag q <query>")
                return format_command_result(io, "rag", "Missing query", error=None)
            return await cls._retrieve(io, coder, query)

        selected = await cls._select_targets(io, coder, args)
        if not selected:
            return format_command_result(io, "rag", "No files selected for RAG indexing")

        # Resolve paths into the project root.
        resolved = [cls._resolve(root, p) for p in selected]
        resolved = [p for p in resolved if p is not None]
        if not resolved:
            return format_command_result(
                io, "rag", "None of the selected paths exist; nothing to index"
            )

        # Expand directories/globs into concrete files.
        from cecli.rag import collect_target_files

        files = collect_target_files(resolved, root)
        if not files:
            return format_command_result(io, "rag", "No indexable files found in selection")

        io.tool_output(f"RAG indexing {len(files)} files under {root} ...")
        try:
            store = get_rag_store(root, files)
            store.index_files(files)
        except Exception as exc:  # pragma: no cover - chromadb/onnx init failures
            io.tool_error(f"RAG indexing failed: {exc}")
            return format_command_result(io, "rag", "RAG indexing failed", error=exc)

        io.tool_output(
            f"Indexed {len(files)} files ({store.count()} chunks) into the RAG store."
        )
        io.tool_output("Use /rag q <query> to retrieve the most relevant chunks.")
        return format_command_result(
            io, "rag", f"RAG index built over {len(files)} files"
        )

    @classmethod
    async def _select_targets(cls, io, coder, args):
        """No args -> fuzzy finder; otherwise -> parse file/folder tokens."""
        if not args.strip():
            all_files = coder.get_all_relative_files()
            in_chat = coder.get_inchat_relative_files()
            candidates = sorted(set(all_files) - set(in_chat))
            if not candidates:
                io.tool_output("No files available to add to the RAG index.")
                return []
            selected = run_fzf(candidates, multi=True, coder=coder)
            return selected or []

        # Arguments may include sub-directories and globs; parse quoted names.
        return parse_quoted_filenames(args)

    @classmethod
    async def _retrieve(cls, io, coder, query):
        """Query the existing RAG store and print the most relevant chunks."""
        from cecli.rag import _store_path, get_rag_store

        root = coder.root
        store_path = _store_path(root)
        if not Path(store_path).exists():
            io.tool_output(
                f"No RAG index yet under {root}. Run /rag first to index files/folders."
            )
            return format_command_result(io, "rag", "No RAG index available", error=None)

        store = get_rag_store(root, [], verbose=True)
        documents = store.retrieve(query)
        if not documents:
            io.tool_output(f"No chunks matched the query: {query!r}")
            return format_command_result(io, "rag", "No matching chunks", error=None)

        io.tool_output(f"Top {len(documents)} RAG chunks for {query!r}:")
        for doc in documents:
            rel = coder.get_rel_fname(doc["path"]) if doc.get("path") else doc.get("path")
            score = round(1.0 - doc.get("distance", 0.0), 3)
            preview = " ".join((doc["document"] or "").split())[:200]
            io.tool_output(f"  [{score}] {rel}\n    {preview}")
        return format_command_result(io, "rag", f"Retrieved {len(documents)} RAG chunks")

    @staticmethod
    def _resolve(root, pattern):
        pattern = os.path.expanduser(pattern)
        p = Path(pattern)
        if not p.is_absolute():
            p = Path(root) / p
        # Keep it even if the literal path does not exist (it may be a glob).
        return p

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Complete both directory-based and full-file paths (like /add)."""
        directory_completions = get_file_completions(
            coder,
            args=args,
            completion_type="directory",
            include_directories=True,
            filter_in_chat=False,
        )
        all_completions = get_file_completions(
            coder,
            args=args,
            completion_type="all",
            include_directories=True,
            filter_in_chat=False,
        )
        return sorted(set(directory_completions) | set(all_completions))

    @classmethod
    def get_help(cls) -> str:
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /rag                    # Open the fuzzy finder to pick files/folders\n"
        help_text += "  /rag <path> [...]       # Register absolute/relative paths or folders\n"
        help_text += "\nEach target file (or every file inside each target folder) is\n"
        return help_text