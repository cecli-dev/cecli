"""The /rag-add and /rag-question commands.

``/rag-add`` mirrors the UX of ``/add``: it picks files/folders (via the fuzzy
finder when no args are given, or from arguments accepting absolute/relative
paths and directory/glob expansions) and registers them as RAG objects.
Unlike the old persistent design, these RAG objects live **only for the
current conversation** — they are stored on the coder (``coder.rag_files``
+ ``coder.rag_index``) and disappear when the cecli session ends.

``/rag-question`` retrieves the most relevant chunks from those session RAG
objects and answers the question the way ``/help`` answers about cecli docs:
it builds a temporary coder, injects the retrieved RAG context block into the
user message, runs it, then switches back to the original coder.
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


def _get_rag_state(coder):
    """Return ``(files, index)`` for the coder's session-scoped RAG store.

    The state lives on the coder instance so it disappears when the session
    ends, mirroring how ``/add`` keeps files in ``coder.abs_fnames``.
    """
    files = getattr(coder, "rag_files", None)
    if files is None:
        files = set()
        coder.rag_files = files
    index = getattr(coder, "rag_index", None)
    if index is None:
        index = {"entries": [], "files": []}
        coder.rag_index = index
    return files, index


class RagAddCommand(BaseCommand):
    NORM_NAME = "rag-add"
    DESCRIPTION = "Add files/folders as RAG objects for the current conversation only"
    show_completion_notification = True

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Register the selected files/folders as session-scoped RAG objects."""
        from cecli.rag import build_rag_index, collect_target_files

        root = coder.root
        files, index = _get_rag_state(coder)

        selected = await cls._select_targets(io, coder, args)
        if not selected:
            return format_command_result(io, "rag-add", "No files selected for RAG")

        # Resolve paths into the project root.
        resolved = [cls._resolve(root, p) for p in selected]
        resolved = [p for p in resolved if p is not None]
        if not resolved:
            return format_command_result(
                io, "rag-add", "None of the selected paths exist; nothing to add"
            )

        # Expand directories/globs into concrete files.
        concrete_files = collect_target_files(resolved, root)
        if not concrete_files:
            return format_command_result(
                io, "rag-add", "No indexable files found in selection"
            )

        for f in concrete_files:
            files.add(str(f))

        # Rebuild the in-memory keyword index over the newly added files, then
        # merge it into the session index so previously added files remain.
        new_index_data = build_rag_index(concrete_files)
        seen_ids = {e["id"] for e in index["entries"]}
        for entry in new_index_data["entries"]:
            if entry["id"] not in seen_ids:
                index["entries"].append(entry)
                seen_ids.add(entry["id"])
        for fpath in new_index_data["files"]:
            if fpath not in index["files"]:
                index["files"].append(fpath)

        io.tool_output(
            f"Added {len(concrete_files)} files ({len(new_index_data['entries'])} chunks) to the RAG store."
        )
        io.tool_output(
            "This RAG set is valid for the current conversation only. Use /rag-question to ask questions."
        )
        return format_command_result(
            io, "rag-add", f"RAG objects added: {len(concrete_files)} files"
        )

    @classmethod
    async def _select_targets(cls, io, coder, args):
        """No args -> fuzzy finder; otherwise -> parse file/folder tokens."""
        if not args.strip():
            all_files = coder.get_all_relative_files()
            in_chat = coder.get_inchat_relative_files()
            candidates = sorted(set(all_files) - set(in_chat))
            if not candidates:
                io.tool_output("No files available to add to the RAG set.")
                return []
            selected = run_fzf(candidates, multi=True, coder=coder)
            return selected or []

        # Arguments may include sub-directories and globs; parse quoted names.
        return parse_quoted_filenames(args)

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
        help_text += "  /rag-add              # Open the fuzzy finder to pick files/folders\n"
        help_text += "  /rag-add <path> [...] # Register absolute/relative paths or folders\n"
        help_text += "\nRAG objects are stored for the current conversation only (like /add files).\n"
        help_text += "They disappear when the cecli session ends.\n"
        help_text += "Use /rag-question to ask questions against the registered RAG objects.\n"
        return help_text


class RagQuestionCommand(BaseCommand):
    NORM_NAME = "rag-question"
    DESCRIPTION = "Ask a question about the RAG objects added via /rag-add"
    show_completion_notification = False

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Retrieve from the session RAG store and answer, like /help."""
        from cecli.rag import rag_context_block

        question = (args or "").strip()
        if not question:
            io.tool_output("Usage: /rag-question <your question>")
            return format_command_result(io, "rag-question", "Missing question", error=None)

        index = getattr(coder, "rag_index", None)
        if not index or not index.get("entries"):
            io.tool_output(
                "No RAG objects in this conversation yet. "
                "Run /rag-add first to register files/folders."
            )
            return format_command_result(
                io, "rag-question", "No RAG objects available", error=None
            )

        import traceback
        from uuid import uuid4 as generate_unique_id

        from cecli.coders.base_coder import Coder
        from cecli.commands import SwitchCoderSignal

        has_args = bool(getattr(coder, "args", None))

        try:
            # Use the editor_model from the main_model if it exists, otherwise use the main_model itself
            editor_model = coder.main_model.editor_model or coder.main_model

            original_coder = coder

            create_kwargs = dict()
            create_kwargs["io"] = io
            create_kwargs["uuid"] = str(generate_unique_id())
            create_kwargs["from_coder"] = coder
            create_kwargs["edit_format"] = "help"
            create_kwargs["summarize_from_coder"] = False
            create_kwargs["map_tokens"] = 0
            create_kwargs["map_mul_no_files"] = 1
            create_kwargs["main_model"] = editor_model
            create_kwargs["args"] = coder.args
            create_kwargs["suggest_shell_commands"] = False
            create_kwargs["cache_prompts"] = False
            create_kwargs["num_cache_warming_pings"] = 0

            rag_coder = await Coder.create(**create_kwargs)
            user_msg = rag_context_block(index, question)
            if not user_msg.strip():
                user_msg = f"# Question: {question}\n\n# No RAG context was retrieved.\n"
            user_msg += f"\n\n# Question: {question}\n"
            user_msg += (
                "\nAnswer the above question using only the RAG context provided above.\n"
                "If the context is insufficient, say so and what additional information you need.\n"
            )
            user_msg += "\n# Announcement lines from when this session of cecli was launched:\n\n"
            user_msg += "\n".join(coder.get_announcements() if has_args else []) + "\n"

            await rag_coder.run(user_msg, preproc=False)
        except Exception as err:
            io.tool_error(f"RAG question failed to initialize: {err}")
            io.tool_error(traceback.format_exc())
            return format_command_result(
                io, "rag-question", f"RAG question failed to initialize: {err}"
            )

        if coder.repo_map:
            map_tokens = coder.repo_map.max_map_tokens
            map_mul_no_files = coder.repo_map.map_mul_no_files
        else:
            map_tokens = 0
            map_mul_no_files = 1

        raise SwitchCoderSignal(
            edit_format=coder.edit_format,
            summarize_from_coder=False,
            from_coder=original_coder,
            map_tokens=map_tokens,
            map_mul_no_files=map_mul_no_files,
            show_announcements=False,
        )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """No completions for the free-form question text."""
        return []

    @classmethod
    def get_help(cls) -> str:
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /rag-question <your question>\n"
        help_text += "\nRetrieves the most relevant chunks from the RAG objects added via /rag-add\n"
        help_text += "in this conversation, and answers the question the way /help answers\n"
        help_text += "questions about cecli docs.\n"
        return help_text