import os
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
    # Handle empty input
    if not args.strip():
        return []

    result = []
    i = 0
    n = len(args)

    while i < n:
        # Skip whitespace
        while i < n and args[i].isspace():
            i += 1

        if i >= n:
            break

        # Check for quoted string
        if args[i] == '"':
            i += 1  # Skip opening quote
            start = i
            while i < n and args[i] != '"':
                # Handle escaped quotes inside quoted string
                if args[i] == "\\" and i + 1 < n and args[i + 1] == '"':
                    i += 2  # Skip escaped quote
                else:
                    i += 1

            if i < n:
                result.append(args[start:i])
                i += 1  # Skip closing quote
            else:
                # Unclosed quote, treat everything as the argument
                result.append(args[start:])
                break
        else:
            # Unquoted argument - collect until whitespace or escaped space
            start = i
            while i < n and not args[i].isspace():
                # Check for escaped space or backslash
                if args[i] == "\\" and i + 1 < n:
                    if args[i + 1] == " ":
                        # Escaped space - include both characters and continue
                        i += 2
                        continue
                    elif args[i + 1] == "\\":
                        # Escaped backslash - skip one backslash
                        i += 2
                        continue

                # Regular character or backslash not followed by space/backslash
                if args[i] == "\\" and i + 1 >= n:
                    # Lone backslash at end of input - include it
                    pass

                i += 1

            result.append(args[start:i])

    return result


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
            except (IndexError, AttributeError, ValueError):
                # Handle patterns like "**/*.py" that might fail on empty dirs
                raw_matched_files = []

        # Expand directories and filter
        matched_files = []
        for f in raw_matched_files:
            matched_files.extend(expand_subdir(f))

        # Filter to repository files
        matched_files = [fn.relative_to(root) for fn in matched_files if fn.is_relative_to(root)]

        # if repo, filter against it
        if repo:
            git_files = repo.get_tracked_files()
            matched_files = [fn for fn in matched_files if str(fn) in git_files]

        return matched_files
    except Exception as e:
        raise CommandError(f"Error processing pattern '{pattern}': {e}")


def get_file_completions(
    coder,
    args: str = "",
    completion_type: str = "all",
    include_directories: bool = False,
    filter_in_chat: bool = False,
) -> List[str]:
    """
    Get file completions for command line arguments.

    This function provides unified file completion logic that can be used by
    multiple commands (add, read-only, read-only-stub, etc.).

    Args:
        coder: Coder instance
        args: Command arguments to complete
        completion_type: Type of completion to perform:
            - "all": Return all available files (default)
            - "glob": Treat args as glob pattern and expand
            - "directory": Perform directory-based prefix matching
        include_directories: Whether to include directories in results
        filter_in_chat: Whether to filter out files already in chat

    Returns:
        List of completion strings (quoted if needed)
    """
    from pathlib import Path

    root = Path(coder.root) if hasattr(coder, "root") else Path.cwd()

    if completion_type == "glob":
        # Handle glob pattern completion
        if not args.strip():
            return []

        try:
            matched_files = glob_filtered_to_repo(args, str(root), coder.repo)
            completions = [str(fn) for fn in matched_files]
        except CommandError:
            completions = []

    elif completion_type == "directory":
        # Handle directory-based prefix matching (like read-only commands)
        if "/" in args:
            # Has directory component
            dir_part, file_part = args.rsplit("/", 1)
            if dir_part == "":
                search_dir = Path("/")
                path_prefix = "/"
            else:
                search_dir = (root / dir_part).resolve()
                path_prefix = dir_part + "/"
            search_prefix = file_part.lower()
        else:
            search_dir = root
            search_prefix = args.lower()
            path_prefix = ""

        completions = []
        try:
            if search_dir.exists() and search_dir.is_dir():
                for entry in search_dir.iterdir():
                    name = entry.name
                    if search_prefix and not name.lower().startswith(search_prefix):
                        continue

                    # Add trailing slash for directories if requested
                    if entry.is_dir() and include_directories:
                        completions.append(path_prefix + name + "/")
                    elif entry.is_file():
                        completions.append(path_prefix + name)
        except (PermissionError, OSError):
            pass

    else:  # "all" completion type
        # Get all available files
        if filter_in_chat:
            files = set(coder.get_all_relative_files())
            files = files - set(coder.get_inchat_relative_files())
            completions = list(files)
        else:
            completions = coder.get_all_relative_files()

    # Quote filenames with spaces
    completions = [quote_filename(fn) for fn in completions]
    return sorted(completions)


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
