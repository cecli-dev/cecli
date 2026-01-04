import os
from pathlib import Path
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    expand_subdir,
    format_command_result,
    parse_quoted_filenames,
)


class DropCommand(BaseCommand):
    NORM_NAME = "drop"
    DESCRIPTION = "Remove files from the chat session to free up context space"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        try:
            if not args.strip():
                if kwargs.get("original_read_only_fnames"):
                    io.tool_output(
                        "Dropping all files from the chat session except originally read-only"
                        " files."
                    )
                else:
                    io.tool_output("Dropping all files from the chat session.")
                cls._drop_all_files(io, coder, kwargs.get("original_read_only_fnames"))

                # Recalculate context block tokens after dropping all files
                if hasattr(coder, "use_enhanced_context") and coder.use_enhanced_context:
                    if hasattr(coder, "_calculate_context_block_tokens"):
                        coder._calculate_context_block_tokens()

                return format_command_result(io, "drop", "Dropped all files from chat")

            filenames = parse_quoted_filenames(args)
            files_changed = False

            for word in filenames:
                # Expand tilde in the path
                expanded_word = os.path.expanduser(word)

                # Handle read-only files
                cls._handle_read_only_files(
                    io, coder, expanded_word, coder.abs_read_only_fnames, "read-only"
                )
                cls._handle_read_only_files(
                    io, coder, expanded_word, coder.abs_read_only_stubs_fnames, "read-only (stub)"
                )

                # For editable files, use glob if word contains glob chars, otherwise use substring
                if any(c in expanded_word for c in "*?[]"):
                    matched_files = cls._glob_filtered_to_repo(coder, expanded_word)
                else:
                    # Use substring matching like we do for read-only files
                    matched_files = [
                        coder.get_rel_fname(f)
                        for f in coder.abs_fnames
                        if coder.abs_root_path(expanded_word) in f
                    ]

                if not matched_files:
                    matched_files.append(expanded_word)

                for matched_file in matched_files:
                    abs_fname = coder.abs_root_path(matched_file)
                    if abs_fname in coder.abs_fnames:
                        coder.abs_fnames.remove(abs_fname)
                        io.tool_output(f"Removed {matched_file} from the chat")
                        files_changed = True

            # Recalculate context block tokens if any files were changed and using agent mode
            if (
                files_changed
                and hasattr(coder, "use_enhanced_context")
                and coder.use_enhanced_context
            ):
                if hasattr(coder, "_calculate_context_block_tokens"):
                    coder._calculate_context_block_tokens()

            return format_command_result(io, "drop", "Removed files from chat")

        finally:
            # This mimics the SwitchCoderSignal behavior in the original cmd_drop
            if coder.repo_map:
                map_tokens = coder.repo_map.max_map_tokens
                map_mul_no_files = coder.repo_map.map_mul_no_files
            else:
                map_tokens = 0
                map_mul_no_files = 1

            # Raise SwitchCoderSignal to trigger coder recreation
            from . import SwitchCoderSignal

            raise SwitchCoderSignal(
                edit_format=coder.edit_format,
                summarize_from_coder=False,
                from_coder=coder,
                map_tokens=map_tokens,
                map_mul_no_files=map_mul_no_files,
                show_announcements=False,
            )

    @classmethod
    def _drop_all_files(cls, io, coder, original_read_only_fnames):
        coder.abs_fnames = set()
        coder.abs_read_only_stubs_fnames = set()

        # When dropping all files, keep those that were originally provided via args.read
        if original_read_only_fnames:
            # Keep only the original read-only files
            to_keep = set()
            for abs_fname in coder.abs_read_only_fnames:
                rel_fname = coder.get_rel_fname(abs_fname)
                if abs_fname in original_read_only_fnames or rel_fname in original_read_only_fnames:
                    to_keep.add(abs_fname)
            coder.abs_read_only_fnames = to_keep
        else:
            coder.abs_read_only_fnames = set()

    @classmethod
    def _handle_read_only_files(cls, io, coder, expanded_word, file_set, description=""):
        """Handle read-only files with substring matching, samefile check, and glob pattern matching"""
        matched = []
        for f in file_set:
            # Check if the expanded_word contains glob characters
            if any(c in expanded_word for c in "*?[]"):
                # Use pathlib.Path.match() for glob pattern matching
                try:
                    # Convert file path to Path object
                    file_path = Path(f)
                    # Check if the file path matches the glob pattern
                    if file_path.match(os.path.abspath(expanded_word)):
                        matched.append(f)
                        continue
                except Exception:
                    # If path matching fails, fall back to other methods
                    pass
            else:
                # Original substring matching for non-glob patterns
                if expanded_word in f:
                    matched.append(f)
                    continue

            # Try samefile comparison for relative paths
            try:
                abs_word = os.path.abspath(expanded_word)
                if os.path.samefile(abs_word, f):
                    matched.append(f)
            except (FileNotFoundError, OSError):
                continue

        for matched_file in matched:
            file_set.remove(matched_file)
            io.tool_output(f"Removed {description} file {matched_file} from the chat")

    @classmethod
    def _glob_filtered_to_repo(cls, coder, pattern):
        """Helper method to glob pattern and filter results to repository files."""
        if not pattern.strip():
            return []
        try:
            if os.path.isabs(pattern):
                # Handle absolute paths
                raw_matched_files = [Path(pattern)]
            else:
                try:
                    raw_matched_files = list(Path(coder.root).glob(pattern))
                except (IndexError, AttributeError):
                    raw_matched_files = []
        except ValueError:
            # Note: io is not available in this static method context
            # Error will be handled by the caller
            raw_matched_files = []

        matched_files = []
        for fn in raw_matched_files:
            matched_files += list(expand_subdir(fn))

        matched_files = [
            fn.relative_to(coder.root) for fn in matched_files if fn.is_relative_to(coder.root)
        ]

        # if repo, filter against it
        if coder.repo:
            git_files = coder.repo.get_tracked_files()
            matched_files = [fn for fn in matched_files if str(fn) in git_files]

        return matched_files

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for drop command."""
        # Return files currently in chat
        files = coder.get_inchat_relative_files()
        return [cls._quote_fname(fn) for fn in files]

    @classmethod
    def _quote_fname(cls, fname):
        """Quote filename if it contains spaces."""
        if " " in fname and '"' not in fname:
            fname = f'"{fname}"'
        return fname

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the drop command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /drop [file1] [file2] ...  # Remove specific files from chat\n"
        help_text += "  /drop                       # Remove all files from chat\n"
        help_text += "\nExamples:\n"
        help_text += "  /drop main.py              # Remove main.py from chat\n"
        help_text += "  /drop *.py                 # Remove all Python files from chat\n"
        help_text += "  /drop                      # Remove all files from chat\n"
        return help_text
