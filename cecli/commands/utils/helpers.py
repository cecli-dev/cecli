import os
from pathlib import Path
from typing import List

from cecli.helpers.file_system import FileSystemService


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

    Uses FileSystemService when available for efficient trie/trigram lookups,
    with fallback to legacy behavior.

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

    # Try using FileSystemService for efficient lookups
    fs = getattr(coder, "fs", None) or FileSystemService.get_instance()
    fs_available = fs.trie is not None or fs.ngram is not None

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
        # Fallback: iterate filesystem directory
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
        if fs_available and fs.trie:
            all_files = fs.list_all()
            if filter_in_chat:
                inchat = set(coder.get_inchat_relative_files())
                all_files = [f for f in all_files if f not in inchat]
            completions = all_files
        else:
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
        io.tool_error(f"Error in {command_name}: {str(error)}")
        return f"Error: {str(error)}"
    else:
        io.tool_output(f"✓ {success_message}")
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

    return []


def iter_all_coders(root_coder):
    """
    Recursively iterate over all coders in the agent/sub-agent hierarchy.

    Yields the root coder first, then all sub-agents (and their sub-agents)
    at every nesting level.

    Args:
        root_coder: The top-level coder instance to start from.

    Yields:
        Coder instances from the entire hierarchy.
    """

    try:
        from cecli.helpers.agents.service import AgentService

        for coder in AgentService.get_all_agents():
            yield coder
    except Exception:
        pass


def update_server_registration(coder, server_name, operation, force=False):
    """
    Unify include/exclude server registration with optional force.

    When *force* is True, the operation always succeeds and the
    opposing set is cleaned up to be non-conflicting.  When *force*
    is False (safe mode), the operation is a no-op if the server
    is already present in the opposing set.

    Args:
        coder: A coder instance with ``registered_servers`` attribute.
        server_name: Name of the server to register.
        operation: ``"include"`` or ``"exclude"``.
        force: When True, always perform the operation.
               When False, respect the opposing set (excluded wins
               for include, included wins for exclude).
    """
    name = server_name.lower()
    included = coder.registered_servers["included"]
    excluded = coder.registered_servers["excluded"]

    if operation == "include":
        if force or name not in excluded:
            included.add(name)
            excluded.discard(name)
    elif operation == "exclude":
        if force or name not in included:
            excluded.add(name)
            included.discard(name)


def is_server_globally_excluded(coder, server_name):
    """
    Check whether *server_name* is excluded from *all* coders in the hierarchy.

    A server is considered "globally excluded" when every coder in the tree
    either:
      - has it in ``registered_servers["excluded"]``, or
      - does **not** have it in ``registered_servers["included"]``
        (empty included means "include all", so the server would be available).

    Args:
        coder: Any coder in the hierarchy (used to discover the full tree).
        server_name: Name of the MCP server to check.

    Returns:
        True if the server is excluded from every coder.
    """
    name = server_name.lower()
    for other in iter_all_coders(coder):
        incl = other.registered_servers["included"]
        excl = other.registered_servers["excluded"]

        # Empty included => implicitly includes all servers
        if not incl:
            if name not in excl:
                return False
        else:
            if name in incl:
                return False
            # Non-empty included means it's an allowlist: not in included => excluded
    return True
