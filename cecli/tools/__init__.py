# flake8: noqa: F401
# Import tool modules into the cecli.tools namespace

# Import all tool modules
from . import (
    command,
    command_interactive,
    context_manager,
    delete_text,
    explore_symbols,
    finished,
    git_branch,
    git_diff,
    git_log,
    git_remote,
    git_show,
    git_status,
    grep,
    insert_text,
    load_skill,
    ls,
    remove_skill,
    replace_text,
    show_context,
    thinking,
    undo_change,
    update_todo_list,
)

# List of all available tool modules for dynamic discovery
TOOL_MODULES = [
    command,
    command_interactive,
    context_manager,
    delete_text,
    explore_symbols,
    finished,
    git_branch,
    git_diff,
    git_log,
    git_remote,
    git_show,
    git_status,
    grep,
    insert_text,
    load_skill,
    ls,
    remove_skill,
    replace_text,
    show_context,
    thinking,
    undo_change,
    update_todo_list,
]
