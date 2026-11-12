from __future__ import annotations

import argparse
import asyncio
import os
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.helpers.conversation import ConversationService, MessageTag


def safe_substitute(template_str: str, values: Dict[str, Any]) -> str:
    """Safely replace known placeholders without crashing on literal JSON braces."""
    res = template_str
    for k, v in values.items():
        res = res.replace(f"{{{k}}}", str(v))
    return res


class ForeachCommand(BaseCommand):
    NORM_NAME = "foreach"
    DESCRIPTION = (
        "Iterate over matching files or items and execute a prompt or command for each. "
        "Usage: /foreach [options] <glob_pattern> [::] <prompt_template>"
    )

    @classmethod
    def _create_arg_parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="/foreach", add_help=False)
        parser.add_argument("-u", "--unless-exists", dest="unless_exists", default=None,
                            help="Skip item if the evaluated target file path already exists on disk.")
        parser.add_argument("-c", "--clear", dest="clear", action="store_true", default=False,
                            help="Clear conversation history between iterations to prevent context bloat.")
        parser.add_argument("-n", "--limit", dest="limit", type=int, default=None,
                            help="Process at most N items.")
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False,
                            help="Show matching items and evaluated prompts without executing them.")
        parser.add_argument("--delay", dest="delay", type=float, default=0.0,
                            help="Delay in seconds between iterations.")
        parser.add_argument("--allow-truncation", dest="no_truncation", action="store_false", default=True,
                            help="Allow context management to truncate large files during batch iteration (default: False/never truncate).")
        parser.add_argument("pattern", nargs="?", default=None,
                            help="Glob pattern or directory path matching target files.")
        return parser

    @classmethod
    def parse_args(cls, raw_args: str):
        """Parse raw arguments into options, pattern, and prompt template."""
        parser = cls._create_arg_parser()
        raw = (raw_args or "").strip()
        if not raw:
            return None, None, None

        if "::" in raw:
            head, template = raw.split("::", 1)
            tokens = shlex.split(head.strip())
            parsed, unknown = parser.parse_known_args(tokens)
            if not parsed.pattern and unknown:
                parsed.pattern = unknown[0]
            return parsed, template.strip(), None
        else:
            tokens = shlex.split(raw)
            parsed, unknown = parser.parse_known_args(tokens)
            template = " ".join(unknown).strip()
            return parsed, template, None

    @classmethod
    async def execute(cls, io, coder, args: str, **kwargs: Any) -> Optional[str]:
        raw_args = (args or "").strip()
        if not raw_args:
            io.tool_error(
                "Please specify a glob pattern and prompt template.\n"
                "Usage: /foreach [options] <glob_pattern> [::] <prompt_template>"
            )
            return "Usage: /foreach [options] <glob_pattern> [::] <prompt_template>"

        parsed, template, err = cls.parse_args(raw_args)
        if not parsed or not parsed.pattern or not template:
            io.tool_error(
                "Missing required pattern or prompt template.\n"
                "Usage: /foreach [options] <glob_pattern> [::] <prompt_template>"
            )
            return "Usage: /foreach [options] <glob_pattern> [::] <prompt_template>"

        pattern = parsed.pattern
        root_path = Path(getattr(coder, "root", None) or Path.cwd()).resolve()

        # Resolve glob pattern
        normalized_pattern = pattern.replace("\\", "/")
        if any(char in normalized_pattern for char in ("*", "?", "[", "]")):
            matched_paths = sorted(root_path.glob(normalized_pattern))
        else:
            target = (root_path / pattern).resolve()
            if target.is_dir():
                matched_paths = sorted([p for p in target.glob("*") if p.is_file()])
            elif target.is_file():
                matched_paths = [target]
            else:
                matched_paths = []

        if not matched_paths:
            io.tool_warning(f"No files matched pattern '{pattern}' in {root_path}")
            return f"No files matched pattern '{pattern}'"

        # Build candidate items with placeholders
        candidates: List[Dict[str, Any]] = []
        skipped_count = 0

        for path in matched_paths:
            try:
                rel_path = path.relative_to(root_path).as_posix()
            except ValueError:
                rel_path = path.as_posix()

            try:
                parent_dir = path.parent.relative_to(root_path).as_posix()
            except ValueError:
                parent_dir = path.parent.as_posix()

            placeholders = {
                "file": rel_path,
                "path": rel_path,
                "filename": path.name,
                "name": path.name,
                "stem": path.stem,
                "basename": path.stem,
                "ext": path.suffix,
                "dir": parent_dir,
                "dirname": parent_dir,
            }

            # Check -u / --unless-exists filter (requires non-empty existing file)
            if parsed.unless_exists:
                target_check_rel = safe_substitute(parsed.unless_exists, placeholders)
                target_check_path = root_path / target_check_rel
                if target_check_path.exists() and target_check_path.stat().st_size > 0:
                    skipped_count += 1
                    continue

            candidates.append(placeholders)

        if not candidates:
            io.tool_output(
                f"✓ /foreach: All {len(matched_paths)} matching items already exist "
                f"(skipped by -u '{parsed.unless_exists}'). Nothing to do."
            )
            return "All items skipped (already exist)"

        # Apply limit if requested
        if parsed.limit and parsed.limit > 0:
            candidates = candidates[:parsed.limit]

        total_items = len(candidates)

        # Handle Dry-Run
        if parsed.dry_run:
            io.tool_output(
                f"🔍 /foreach (dry-run): {total_items} item(s) to process "
                f"({skipped_count} skipped by -u):"
            )
            for idx, item in enumerate(candidates, start=1):
                item_vars = dict(item, index=idx, total=total_items)
                preview_prompt = safe_substitute(template, item_vars)
                io.tool_output(f"  [{idx}/{total_items}] {item['file']}")
                if idx <= 3 or idx == total_items:
                    io.tool_output(f"       Prompt: {preview_prompt[:120]}...")
            return f"Dry-run completed: {total_items} items to process."

        io.tool_output(
            f"🔄 /foreach: Starting loop for {total_items} item(s) "
            f"({skipped_count} skipped)..."
        )

        completed_count = 0
        interrupted = False

        orig_context_mgmt = getattr(coder, "context_management_enabled", None)
        orig_threshold = getattr(coder, "large_file_token_threshold", None)
        orig_repo_map_tokens = None
        if hasattr(coder, "repo_map") and coder.repo_map is not None:
            orig_repo_map_tokens = getattr(coder.repo_map, "max_map_tokens", None)
            coder.repo_map.max_map_tokens = 0

        if getattr(parsed, "no_truncation", True):
            if hasattr(coder, "large_file_token_threshold"):
                max_tokens = getattr(getattr(coder, "main_model", None), "max_context_tokens", None) or 87552
                coder.large_file_token_threshold = max(32768, max_tokens // 2)
            if hasattr(coder, "context_management_enabled"):
                coder.context_management_enabled = False

        try:
            for idx, item in enumerate(candidates, start=1):
                # Check interrupt signals
                interrupt_event = getattr(coder, "interrupt_event", None)
                if interrupt_event and interrupt_event.is_set():
                    io.tool_warning(f"Loop interrupted at item {idx}/{total_items}.")
                    interrupted = True
                    break

                item_vars = dict(item, index=idx, total=total_items)
                prompt = safe_substitute(template, item_vars)

                # Clear context between iterations if requested
                if parsed.clear:
                    try:
                        manager = ConversationService.get_manager(coder)
                        for tag in (
                            MessageTag.CUR,
                            MessageTag.DONE,
                            MessageTag.DIFFS,
                            MessageTag.FILE_CONTEXTS,
                            MessageTag.READONLY_FILES,
                            MessageTag.CHAT_FILES,
                            MessageTag.EDIT_FILES,
                            MessageTag.LINT,
                        ):
                            try:
                                manager.clear_tag(tag)
                            except Exception:
                                pass
                        ConversationService.get_files(coder).reset()
                        # Also drop all read-only and editable files to prevent prompt token accumulation
                        if hasattr(coder, "abs_fnames"):
                            coder.abs_fnames = set()
                        if hasattr(coder, "abs_read_only_fnames"):
                            coder.abs_read_only_fnames = set()
                        if hasattr(coder, "abs_read_only_stubs_fnames"):
                            coder.abs_read_only_stubs_fnames = set()
                        if hasattr(coder, "files_added_in_exploration"):
                            coder.files_added_in_exploration = set()
                        ConversationService.get_chunks(coder).flush_removals()
                    except Exception as clear_err:
                        io.tool_warning(f"Context clear warning: {clear_err}")

                io.tool_output(f"\n▶ [{idx}/{total_items}] {item['filename']}")

                try:
                    await coder.run_one(prompt, preproc=True)
                    completed_count += 1
                except KeyboardInterrupt:
                    io.tool_warning(f"\nLoop interrupted by user at item {idx}/{total_items}.")
                    interrupted = True
                    break
                except Exception as e:
                    io.tool_error(f"Error processing {item['filename']}: {e}")
                    # Continue with next item rather than aborting entire batch

                if parsed.delay > 0 and idx < total_items:
                    await asyncio.sleep(parsed.delay)
        finally:
            if orig_context_mgmt is not None and hasattr(coder, "context_management_enabled"):
                coder.context_management_enabled = orig_context_mgmt
            if orig_threshold is not None and hasattr(coder, "large_file_token_threshold"):
                coder.large_file_token_threshold = orig_threshold
            if orig_repo_map_tokens is not None and hasattr(coder, "repo_map") and coder.repo_map is not None:
                coder.repo_map.max_map_tokens = orig_repo_map_tokens

        status_msg = (
            f"Processed {completed_count}/{total_items} item(s) "
            f"({skipped_count} skipped)" + (" [interrupted]" if interrupted else " [completed]")
        )
        return format_command_result(io, "foreach", status_msg)

    @classmethod
    def get_help(cls) -> str:
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /foreach [options] <glob_pattern> [::] <prompt_template>\n"
        help_text += "\nPlaceholders:\n"
        help_text += "  {file}      Relative path to file (e.g. pine_sources/Foo_v1.0.pine)\n"
        help_text += "  {filename}  Filename with extension (e.g. Foo_v1.0.pine)\n"
        help_text += "  {stem}      Filename without extension (e.g. Foo_v1.0)\n"
        help_text += "  {dir}       Parent directory (e.g. pine_sources)\n"
        help_text += "  {index}     Current item index (1-based)\n"
        help_text += "  {total}     Total count of items to process\n"
        help_text += "\nOptions:\n"
        help_text += "  -u, --unless-exists <path>   Skip item if evaluated file path already exists\n"
        help_text += "  -c, --clear                 Clear chat history between iterations (prevents context bloat)\n"
        help_text += "  -n, --limit <count>         Process at most N items\n"
        help_text += "  --dry-run                   Preview matching files and prompts without executing\n"
        help_text += "  --delay <seconds>           Pause between iterations (default: 0)\n"
        help_text += "\nExamples:\n"
        help_text += "  /foreach pine_sources/PBK_*.pine -u doc/indicator/{filename}_manual.md -c :: Delegate to worker for {file}\n"
        help_text += "  /foreach --dry-run src/*.py :: Review {file} for performance\n"
        help_text += "  /foreach -n 3 src/**/*.ts -c :: Add unit tests for {file}\n"
        return help_text
