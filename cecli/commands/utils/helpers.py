import os
import re
from pathlib import Path
from typing import List


class CommandError(Exception):
    """Custom exception for command-specific errors."""

    pass


def quote_filename(fname: str) -> str:
    """Quote filename if it contains spaces."""
    if " " in fname and '"' not in fname:
        fname = f'"{fname}"'
    return fname


def parse_quoted_filenames(args: str) -> List[str]:
    """Parse filenames from command arguments, handling quoted names."""
    filenames = re.findall(r"\"(.+?)\"|(\S+)", args)
    filenames = [name for sublist in filenames for name in sublist if name]
    return filenames


def glob_filtered_to_repo(pattern: str, root: str, repo) -> List[Path]:
    """
    Glob pattern and filter results to repository files.

    Args:
        pattern: Glob pattern to match
        root: Project root directory
        repo: GitRepo instance (may be None)

    Returns:
        List of Path objects matching pattern
    """
    if not pattern.strip():
        return []

    try:
        if os.path.isabs(pattern):
            # Handle absolute paths
            raw_matched_files = [Path(pattern)]
        else:
            try:
                raw_matched_files = list(Path(root).glob(pattern))
            except (IndexError, AttributeError):
                # Handle patterns like "**/*.py" that might fail on empty dirs
                raw_matched_files = []

        # Filter out directories and ignored files
        matched_files = []
        for f in raw_matched_files:
            if not f.is_file():
                continue
            if repo and repo.ignored_file(f):
                continue
            matched_files.append(f)

        return matched_files
    except Exception as e:
        raise CommandError(f"Error processing pattern '{pattern}': {e}")


def validate_file_access(io, coder, file_path: str, require_in_chat: bool = False) -> bool:
    """
    Validate file access permissions and state.

    Args:
        io: InputOutput instance
        coder: Coder instance
        file_path: File path to validate
        require_in_chat: Whether file must be in chat context

    Returns:
        True if file is accessible
    """
    abs_path = coder.abs_root_path(file_path)

    if not os.path.isfile(abs_path):
        io.tool_error(f"File not found: {file_path}")
        return False

    if require_in_chat and abs_path not in coder.abs_fnames:
        io.tool_error(f"File not in chat: {file_path}")
        return False

    return True


def format_command_result(
    io, command_name: str, success_message: str, error: Exception | str = None
):
    """
    Format command execution result consistently.

    Args:
        io: InputOutput instance
        command_name: Name of the command
        success_message: Message for successful execution
        error: Exception if command failed

    Returns:
        Formatted result string
    """
    if error:
        io.tool_error(f"\nError in {command_name}: {str(error)}")
        return f"Error: {str(error)}"
    else:
        io.tool_output(f"\n✅ {success_message}")
        return f"Successfully executed {command_name}."


def get_available_files(coder, in_chat: bool = False) -> List[str]:
    """
    Get list of available files (either all files or files in chat).

    Args:
        coder: Coder instance
        in_chat: If True, return files in chat context

    Returns:
        List of relative file paths
    """
    if in_chat:
        return coder.get_inchat_relative_files()
    else:
        return coder.get_all_relative_files()


def expand_subdir(file_path):
    """Expand a directory path to all files within it."""
    if file_path.is_file():
        yield file_path
        return

    if file_path.is_dir():
        for file in file_path.rglob("*"):
            if file.is_file():
                yield file
