from aider.repo import ANY_GIT_ERROR

git_diff_schema = {
    "type": "function",
    "function": {
        "name": "git_diff",
        "description": (
            "Show the diff between the current working directory and a git branch or commit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "The branch or commit hash to diff against. Defaults to HEAD.",
                },
            },
            "required": [],
        },
    },
}


def _execute_git_diff(coder, branch=None):
    """
    Show the diff between the current working directory and a git branch or commit.
    """
    if not coder.repo:
        return "Not in a git repository."

    try:
        if branch:
            diff = coder.repo.diff_commits(False, branch, "HEAD")
        else:
            diff = coder.repo.diff_commits(False, "HEAD", None)

        if not diff:
            return "No differences found."
        return diff
    except ANY_GIT_ERROR as e:
        coder.io.tool_error(f"Error running git diff: {e}")
        return f"Error running git diff: {e}"


git_log_schema = {
    "type": "function",
    "function": {
        "name": "git_log",
        "description": "Show the git log.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "The maximum number of commits to show. Defaults to 10.",
                },
            },
            "required": [],
        },
    },
}


def _execute_git_log(coder, limit=10):
    """
    Show the git log.
    """
    if not coder.repo:
        return "Not in a git repository."

    try:
        commits = list(coder.repo.repo.iter_commits(max_count=limit))
        log_output = []
        for commit in commits:
            short_hash = commit.hexsha[:8]
            message = commit.message.strip().split("\n")[0]
            log_output.append(f"{short_hash} {message}")
        return "\n".join(log_output)
    except ANY_GIT_ERROR as e:
        coder.io.tool_error(f"Error running git log: {e}")
        return f"Error running git log: {e}"


git_show_schema = {
    "type": "function",
    "function": {
        "name": "git_show",
        "description": "Show various types of objects (blobs, trees, tags, and commits).",
        "parameters": {
            "type": "object",
            "properties": {
                "object": {
                    "type": "string",
                    "description": "The object to show. Defaults to HEAD.",
                },
            },
            "required": [],
        },
    },
}


def _execute_git_show(coder, object="HEAD"):
    """
    Show various types of objects (blobs, trees, tags, and commits).
    """
    if not coder.repo:
        return "Not in a git repository."

    try:
        return coder.repo.repo.git.show(object)
    except ANY_GIT_ERROR as e:
        coder.io.tool_error(f"Error running git show: {e}")
        return f"Error running git show: {e}"


git_status_schema = {
    "type": "function",
    "function": {
        "name": "git_status",
        "description": "Show the working tree status.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


def _execute_git_status(coder):
    """
    Show the working tree status.
    """
    if not coder.repo:
        return "Not in a git repository."

    try:
        return coder.repo.repo.git.status()
    except ANY_GIT_ERROR as e:
        coder.io.tool_error(f"Error running git status: {e}")
        return f"Error running git status: {e}"


git_branch_schema = {
    "type": "function",
    "function": {
        "name": "git_branch",
        "description": "List, create, or delete branches.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "delete"],
                    "description": "The branch operation to perform.",
                },
                "name": {
                    "type": "string",
                    "description": "Branch name for create/delete operations.",
                },
            },
            "required": ["action"],
        },
    },
}


def _execute_git_branch(coder, action, name=None):
    """
    List, create, or delete branches.
    """
    if not coder.repo:
        return "Not in a git repository."

    try:
        if action == "list":
            # Get all branches and current branch
            branches = []
            current_branch = coder.repo.repo.active_branch.name
            for branch in coder.repo.repo.heads:
                prefix = "* " if branch.name == current_branch else "  "
                branches.append(f"{prefix}{branch.name}")
            return "\n".join(branches)
        
        elif action == "create":
            if not name:
                return "Branch name required for create operation."
            coder.repo.repo.create_head(name)
            return f"Created branch: {name}"
        
        elif action == "delete":
            if not name:
                return "Branch name required for delete operation."
            coder.repo.repo.delete_head(name)
            return f"Deleted branch: {name}"
        
        else:
            return f"Unknown branch action: {action}"
            
    except ANY_GIT_ERROR as e:
        coder.io.tool_error(f"Error running git branch: {e}")
        return f"Error running git branch: {e}"


git_remote_schema = {
    "type": "function",
    "function": {
        "name": "git_remote",
        "description": "Manage set of tracked repositories.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "remove"],
                    "description": "The remote operation to perform.",
                },
                "name": {
                    "type": "string",
                    "description": "Remote name for add/remove operations.",
                },
                "url": {
                    "type": "string",
                    "description": "Remote URL for add operation.",
                },
            },
            "required": ["action"],
        },
    },
}


def _execute_git_remote(coder, action, name=None, url=None):
    """
    Manage set of tracked repositories.
    """
    if not coder.repo:
        return "Not in a git repository."

    try:
        if action == "list":
            remotes = coder.repo.repo.remotes
            if not remotes:
                return "No remotes configured."
            
            result = []
            for remote in remotes:
                result.append(f"{remote.name}\t{remote.url}")
            return "\n".join(result)
        
        elif action == "add":
            if not name or not url:
                return "Remote name and URL required for add operation."
            coder.repo.repo.create_remote(name, url)
            return f"Added remote: {name} -> {url}"
        
        elif action == "remove":
            if not name:
                return "Remote name required for remove operation."
            coder.repo.repo.delete_remote(name)
            return f"Removed remote: {name}"
        
        else:
            return f"Unknown remote action: {action}"
            
    except ANY_GIT_ERROR as e:
        coder.io.tool_error(f"Error running git remote: {e}")
        return f"Error running git remote: {e}"
