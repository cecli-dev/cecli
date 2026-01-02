import os
import re
from pathlib import Path
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    format_command_result,
    parse_quoted_filenames,
    quote_filename,
)
from cecli.utils import is_image_file, run_fzf


class AddCommand(BaseCommand):
    NORM_NAME = "add"
    DESCRIPTION = "Add files to the chat so cecli can edit them or review them in detail"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the add command with given parameters."""
        if not args.strip():
            all_files = coder.get_all_relative_files()
            files_in_chat = coder.get_inchat_relative_files()
            addable_files = sorted(set(all_files) - set(files_in_chat))
            if not addable_files:
                io.tool_output("No files available to add.")
                return format_command_result(io, "add", "No files available to add")
            selected_files = run_fzf(addable_files, multi=True, coder=coder)
            if not selected_files:
                return format_command_result(io, "add", "No files selected")
            args = " ".join([quote_filename(f) for f in selected_files])

        all_matched_files = set()

        filenames = parse_quoted_filenames(args)
        for word in filenames:
            if Path(word).is_absolute():
                fname = Path(word)
            else:
                fname = Path(coder.root) / word

            if coder.repo and coder.repo.ignored_file(fname):
                io.tool_warning(f"Skipping {fname} due to cecli.ignore or --subtree-only.")
                continue

            if fname.exists():
                if fname.is_file():
                    all_matched_files.add(str(fname))
                    continue
                # an existing dir, escape any special chars so they won't be globs
                word = re.sub(r"([\*\?\[\]])", r"[\1]", word)

            matched_files = cls.glob_filtered_to_repo(coder, word)
            if matched_files:
                all_matched_files.update(matched_files)
                continue

            if "*" in str(fname) or "?" in str(fname):
                io.tool_error(f"No match, and cannot create file with wildcard characters: {fname}")
                continue

            if fname.exists() and fname.is_dir() and coder.repo:
                io.tool_error(f"Directory {fname} is not in git.")
                io.tool_output(f"You can add to git with: /git add {fname}")
                continue

            if await io.confirm_ask(f"No files matched '{word}'. Do you want to create {fname}?"):
                try:
                    fname.parent.mkdir(parents=True, exist_ok=True)
                    fname.touch()
                    all_matched_files.add(str(fname))
                except OSError as e:
                    io.tool_error(f"Error creating file {fname}: {e}")

        for matched_file in sorted(all_matched_files):
            abs_file_path = coder.abs_root_path(matched_file)

            if not abs_file_path.startswith(coder.root) and not is_image_file(matched_file):
                io.tool_error(f"Can not add {abs_file_path}, which is not within {coder.root}")
                continue

            if (
                coder.repo
                and coder.repo.git_ignored_file(matched_file)
                and not coder.add_gitignore_files
            ):
                io.tool_error(f"Can't add {matched_file} which is in gitignore")
                continue

            if abs_file_path in coder.abs_fnames:
                io.tool_error(f"{matched_file} is already in the chat as an editable file")
                continue
            elif abs_file_path in coder.abs_read_only_stubs_fnames:
                if coder.repo and coder.repo.path_in_repo(matched_file):
                    coder.abs_read_only_stubs_fnames.remove(abs_file_path)
                    coder.abs_fnames.add(abs_file_path)
                    io.tool_output(
                        f"Moved {matched_file} from read-only (stub) to editable files in the chat"
                    )
                else:
                    io.tool_error(f"Cannot add {matched_file} as it's not part of the repository")
            elif abs_file_path in coder.abs_read_only_fnames:
                if coder.repo and coder.repo.path_in_repo(matched_file):
                    coder.abs_read_only_fnames.remove(abs_file_path)
                    coder.abs_fnames.add(abs_file_path)
                    io.tool_output(
                        f"Moved {matched_file} from read-only to editable files in the chat"
                    )
                else:
                    io.tool_error(f"Cannot add {matched_file} as it's not part of the repository")
            else:
                if is_image_file(matched_file) and not coder.main_model.info.get("supports_vision"):
                    io.tool_error(
                        f"Cannot add image file {matched_file} as the"
                        f" {coder.main_model.name} does not support images."
                    )
                    continue
                content = io.read_text(abs_file_path)
                if content is None:
                    io.tool_error(f"Unable to read {matched_file}")
                else:
                    coder.abs_fnames.add(abs_file_path)
                    fname = coder.get_rel_fname(abs_file_path)
                    io.tool_output(f"Added {fname} to the chat")
                    coder.check_added_files()

                    # Recalculate context block tokens if using agent mode
                    if hasattr(coder, "use_enhanced_context") and coder.use_enhanced_context:
                        if hasattr(coder, "_calculate_context_block_tokens"):
                            coder._calculate_context_block_tokens()

        if coder.repo_map:
            map_tokens = coder.repo_map.max_map_tokens
            map_mul_no_files = coder.repo_map.map_mul_no_files
        else:
            map_tokens = 0
            map_mul_no_files = 1

        from cecli.commands import SwitchCoder

        raise SwitchCoder(
            edit_format=coder.edit_format,
            summarize_from_coder=False,
            from_coder=coder,
            map_tokens=map_tokens,
            map_mul_no_files=map_mul_no_files,
            show_announcements=False,
        )

    @classmethod
    def glob_filtered_to_repo(cls, coder, pattern: str) -> List[str]:
        """Glob pattern and filter results to repository files."""
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
            # This error will be handled by the caller
            raw_matched_files = []

        matched_files = []
        for fn in raw_matched_files:
            matched_files += cls.expand_subdir(fn)

        matched_files = [
            fn.relative_to(coder.root) for fn in matched_files if fn.is_relative_to(coder.root)
        ]

        # if repo, filter against it
        if coder.repo:
            git_files = coder.repo.get_tracked_files()
            matched_files = [fn for fn in matched_files if str(fn) in git_files]

        return list(map(str, matched_files))

    @staticmethod
    def expand_subdir(file_path: Path) -> List[Path]:
        """Expand a directory path to all files within it."""
        if file_path.is_file():
            return [file_path]

        if file_path.is_dir():
            files = []
            for file in file_path.rglob("*"):
                if file.is_file():
                    files.append(file)
            return files

        return []

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for add command."""
        files = set(coder.get_all_relative_files())
        files = files - set(coder.get_inchat_relative_files())
        files = [quote_filename(fn) for fn in files]
        return files

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the add command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /add              # Interactive file selection using fuzzy finder\n"
        help_text += "  /add <files>      # Add specific files or glob patterns\n"
        help_text += "\nExamples:\n"
        help_text += "  /add              # Use fuzzy finder to select files\n"
        help_text += "  /add *.py         # Add all Python files\n"
        help_text += "  /add main.py      # Add main.py\n"
        help_text += '  /add "file with spaces.py"  # Add file with spaces\n'
        help_text += (
            "\nThis command adds files to the chat so cecli can edit them or review them in"
            " detail.\n"
        )
        help_text += "If a file doesn't exist, you'll be asked if you want to create it.\n"
        help_text += "Files can be moved from read-only to editable status.\n"
        help_text += "Image files can be added if the model supports vision.\n"
        return help_text
