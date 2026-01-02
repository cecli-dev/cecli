"""
File search utilities for aider.

This module provides functions for searching and resolving file paths
relative to various directories (git root, home folder, .aider, .cecli, etc.).
"""

from pathlib import Path
from typing import List, Optional


def generate_search_path_list(
    default_file: str, git_root: Optional[str], command_line_file: Optional[str]
) -> List[str]:
    """
    Generate a list of file paths to search for configuration files.

    The search order is:
    1. Home directory (~/default_file)
    2. Git root directory (git_root/default_file) if git_root is provided
    3. Current directory (default_file)
    4. Command line specified file (command_line_file) if provided

    Args:
        default_file: The default filename to search for
        git_root: The git root directory (optional)
        command_line_file: A file specified on the command line (optional)

    Returns:
        List of resolved file paths in search order (first to last)
    """
    files = []
    files.append(Path.home() / default_file)  # homedir
    if git_root:
        files.append(Path(git_root) / default_file)  # git root
    files.append(default_file)
    if command_line_file:
        files.append(command_line_file)

    resolved_files = []
    for fn in files:
        try:
            resolved_files.append(Path(fn).expanduser().resolve())
        except OSError:
            pass

    files = resolved_files
    files.reverse()
    uniq = []
    for fn in files:
        if fn not in uniq:
            uniq.append(fn)
    uniq.reverse()
    files = uniq
    files = list(map(str, files))
    files = list(dict.fromkeys(files))

    return files


def handle_core_files(
    file_path: str,
    prepend_folder: Optional[str] = None,
    namespace_folder: bool = False,
) -> str:
    """
    Handle core configuration files, migrating from .aider to .cecli if needed.

    This function receives paths with .cecli (new naming) and:
    1. Checks if corresponding .aider versions exist
    2. If .aider exists, copies it to the .cecli version (preserving original as backup)
    3. Returns the .cecli path (whether copied or original)

    Handles both:
    1. Files that start with '.cecli' (e.g., '.cecli-config.yml')
    2. Folders named '.cecli' in the path (e.g., '.cecli/config.yml')

    Args:
        file_path: The target file path with .cecli naming
        prepend_folder: Optional folder to prepend to the path (e.g., 'configs/')
        namespace_folder: If True, prepend '.cecli/' to the path (default: False)

    Returns:
        The processed .cecli file path with any modifications applied

    Example:
        >>> handle_core_files(".cecli/config.yml", "configs", True)
        "configs/.cecli/config.yml"
        # If .aider/config.yml exists, it will be copied to configs/.cecli/config.yml

        >>> handle_core_files(".cecli-settings.json")
        ".cecli-settings.json"
        # If .aider-settings.json exists, it will be copied to .cecli-settings.json

        >>> handle_core_files("project/.cecli/config.yml")
        "project/.cecli/config.yml"
        # If project/.aider/config.yml exists, it will be copied to project/.cecli/config.yml
    """
    import shutil
    from pathlib import Path, PurePath

    is_path_obj = isinstance(file_path, PurePath)

    # Convert to Path object for easier manipulation
    path = Path(file_path)

    # First apply prepend_folder and namespace_folder to get the target .cecli path
    if prepend_folder:
        path = Path(prepend_folder) / path

    if namespace_folder:
        path = Path(".cecli") / path

    # Now check if this .cecli path has a corresponding .aider version that exists
    path_str = str(path)
    if ".cecli" in path_str:
        # Create the corresponding .aider path by replacing .cecli with .aider
        # Handle both folder names (.cecli/) and file names (.cecli)
        aider_path_str = path_str.replace(".cecli/", ".aider/").replace(".cecli", ".aider", 1)
        aider_path = Path(aider_path_str)

        # Check if the .aider file/folder exists (and .cecli doesn't already exist)
        if aider_path.exists() and not path.exists():
            # Create parent directories for the .cecli path if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            # Copy the file/folder from .aider to .cecli (preserve original as backup)
            try:
                if aider_path.is_file():
                    # Copy file with metadata preservation
                    shutil.copy2(str(aider_path), str(path))
                elif aider_path.is_dir():
                    # Copy directory tree
                    shutil.copytree(str(aider_path), str(path), dirs_exist_ok=True)
            except (OSError, shutil.Error) as e:
                # If copy fails, log but continue with .cecli path
                import logging

                logging.debug(f"Failed to copy {aider_path} to {path}: {e}")

    # Return the .cecli path as Path or string
    return path if is_path_obj else str(path)
