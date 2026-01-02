import glob
import os
from os.path import expanduser
from pathlib import Path
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    format_command_result,
    parse_quoted_filenames,
    quote_filename,
)
from cecli.utils import is_image_file, run_fzf


class ReadOnlyStubCommand(BaseCommand):
    NORM_NAME = "read-only-stub"
    DESCRIPTION = (
        "Add files to the chat as read-only stubs, or turn added files to read-only (stubs)"
    )

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the read-only-stub command with given parameters."""
        if not args.strip():
            # If no args provided, use fuzzy finder to select files to add as read-only stubs
            all_files = coder.get_all_relative_files()
            files_in_chat = coder.get_inchat_relative_files()
            addable_files = sorted(set(all_files) - set(files_in_chat))
            if not addable_files:
                # If no files available to add, convert all editable files to read-only stubs
                await cls._cmd_read_only_base(
                    io,
                    coder,
                    "",
                    source_set=coder.abs_read_only_fnames,
                    target_set=coder.abs_read_only_stubs_fnames,
                    source_mode="read-only",
                    target_mode="read-only (stub)",
                )
                return format_command_result(
                    io, "read-only-stub", "Converted all editable files to read-only stubs"
                )

            selected_files = run_fzf(addable_files, multi=True, coder=coder)
            if not selected_files:
                # If user didn't select any files, convert all editable files to read-only stubs
                await cls._cmd_read_only_base(
                    io,
                    coder,
                    "",
                    source_set=coder.abs_read_only_fnames,
                    target_set=coder.abs_read_only_stubs_fnames,
                    source_mode="read-only",
                    target_mode="read-only (stub)",
                )
                return format_command_result(
                    io, "read-only-stub", "Converted all editable files to read-only stubs"
                )

            args = " ".join([quote_filename(f) for f in selected_files])

        await cls._cmd_read_only_base(
            io,
            coder,
            args,
            source_set=coder.abs_read_only_fnames,
            target_set=coder.abs_read_only_stubs_fnames,
            source_mode="read-only",
            target_mode="read-only (stub)",
        )
        return format_command_result(io, "read-only-stub", "Processed read-only stub files")

    @classmethod
    async def _cmd_read_only_base(
        cls, io, coder, args, source_set, target_set, source_mode, target_mode
    ):
        """Base implementation for read-only and read-only-stub commands"""
        if not args.strip():
            # Handle editable files
            for fname in list(coder.abs_fnames):
                coder.abs_fnames.remove(fname)
                target_set.add(fname)
                rel_fname = coder.get_rel_fname(fname)
                io.tool_output(f"Converted {rel_fname} from editable to {target_mode}")

            # Handle source set files if provided
            if source_set:
                for fname in list(source_set):
                    source_set.remove(fname)
                    target_set.add(fname)
                    rel_fname = coder.get_rel_fname(fname)
                    io.tool_output(f"Converted {rel_fname} from {source_mode} to {target_mode}")
            return

        filenames = parse_quoted_filenames(args)
        all_paths = []

        # First collect all expanded paths
        for pattern in filenames:
            expanded_pattern = expanduser(pattern)
            path_obj = Path(expanded_pattern)
            is_abs = path_obj.is_absolute()
            if not is_abs:
                path_obj = Path(coder.root) / path_obj

            matches = []
            # Check for literal path existence first
            if path_obj.exists():
                matches = [path_obj]
            else:
                # If literal path doesn't exist, try globbing
                if is_abs:
                    # For absolute paths, glob it
                    matches = [Path(p) for p in glob.glob(expanded_pattern)]
                else:
                    # For relative paths and globs, use glob from the root directory
                    matches = list(Path(coder.root).glob(expanded_pattern))

            if not matches:
                io.tool_error(f"No matches found for: {pattern}")
            else:
                all_paths.extend(matches)

        # Then process them in sorted order
        for path in sorted(all_paths):
            abs_path = coder.abs_root_path(path)
            if os.path.isfile(abs_path):
                cls._add_read_only_file(
                    io,
                    coder,
                    abs_path,
                    path,
                    target_set,
                    source_set,
                    source_mode=source_mode,
                    target_mode=target_mode,
                )
            elif os.path.isdir(abs_path):
                cls._add_read_only_directory(
                    io, coder, abs_path, path, source_set, target_set, target_mode
                )
            else:
                io.tool_error(f"Not a file or directory: {abs_path}")

    @classmethod
    def _add_read_only_file(
        cls,
        io,
        coder,
        abs_path,
        original_name,
        target_set,
        source_set,
        source_mode="read-only",
        target_mode="read-only",
    ):
        if is_image_file(original_name) and not coder.main_model.info.get("supports_vision"):
            io.tool_error(
                f"Cannot add image file {original_name} as the"
                f" {coder.main_model.name} does not support images."
            )
            return

        if abs_path in target_set:
            io.tool_error(f"{original_name} is already in the chat as a {target_mode} file")
            return
        elif abs_path in coder.abs_fnames:
            coder.abs_fnames.remove(abs_path)
            target_set.add(abs_path)
            io.tool_output(
                f"Moved {original_name} from editable to {target_mode} files in the chat"
            )
        elif source_set and abs_path in source_set:
            source_set.remove(abs_path)
            target_set.add(abs_path)
            io.tool_output(
                f"Moved {original_name} from {source_mode} to {target_mode} files in the chat"
            )
        else:
            target_set.add(abs_path)
            io.tool_output(f"Added {original_name} to {target_mode} files.")

    @classmethod
    def _add_read_only_directory(
        cls, io, coder, abs_path, original_name, source_set, target_set, target_mode
    ):
        added_files = 0
        for root, _, files in os.walk(abs_path):
            for file in files:
                file_path = os.path.join(root, file)
                if (
                    file_path not in coder.abs_fnames
                    and file_path not in target_set
                    and (source_set is None or file_path not in source_set)
                ):
                    target_set.add(file_path)
                    added_files += 1

        if added_files > 0:
            io.tool_output(
                f"Added {added_files} files from directory {original_name} to {target_mode} files."
            )
        else:
            io.tool_output(f"No new files added from directory {original_name}.")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for read-only command."""
        from pathlib import Path

        root = Path(coder.root) if hasattr(coder, "root") else Path.cwd()

        # Handle the prefix - could be partial path like "src/ma" or just "ma"
        if "/" in args:
            # Has directory component
            dir_part, file_part = args.rsplit("/", 1)
            search_dir = root / dir_part
            search_prefix = file_part.lower()
            path_prefix = dir_part + "/"
        else:
            search_dir = root
            search_prefix = args.lower()
            path_prefix = ""

        completions = []
        try:
            if search_dir.exists() and search_dir.is_dir():
                for entry in search_dir.iterdir():
                    name = entry.name
                    if search_prefix and search_prefix not in name.lower():
                        continue
                    # Add trailing slash for directories
                    if entry.is_dir():
                        completions.append(path_prefix + name + "/")
                    else:
                        completions.append(path_prefix + name)
        except (PermissionError, OSError):
            pass

        add_completions = coder.commands.get_completions("/add")
        for c in add_completions:
            if args.lower() in str(c).lower() and str(c) not in completions:
                completions.append(str(c))

        return sorted(completions)

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the read-only-stub command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += (
            "  /read-only-stub              # Interactive file selection or convert editable"
            " files\n"
        )
        help_text += "  /read-only-stub <files>      # Add specific files as read-only stubs\n"
        help_text += "\nExamples:\n"
        help_text += "  /read-only-stub              # Use fuzzy finder to select files\n"
        help_text += "  /read-only-stub *.py         # Add all Python files as read-only stubs\n"
        help_text += "  /read-only-stub main.py      # Add main.py as read-only stub\n"
        help_text += '  /read-only-stub "file with spaces.py"  # Add file with spaces\n'
        help_text += (
            "\nThis command adds files to the chat as read-only stubs (for reference only).\n"
        )
        help_text += "If no files are specified, it opens a fuzzy finder to select files.\n"
        help_text += (
            "If no files are available to add, it converts all editable files to read-only stubs.\n"
        )
        return help_text
