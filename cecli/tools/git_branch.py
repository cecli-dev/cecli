from cecli.repo import ANY_GIT_ERROR
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.responses import ToolResponse


class Tool(BaseTool):
    NORM_NAME = "gitbranch"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "GitBranch",
            "description": (
                "List branches in the repository with various filtering and formatting options."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "remotes": {
                        "type": "boolean",
                        "description": "List remote-tracking branches (-r/--remotes flag)",
                    },
                    "all": {
                        "type": "boolean",
                        "description": "List both local and remote branches (-a/--all flag)",
                    },
                    "verbose": {
                        "type": "boolean",
                        "description": (
                            "Show verbose information including commit hash and subject (-v flag)"
                        ),
                    },
                    "very_verbose": {
                        "type": "boolean",
                        "description": (
                            "Show very verbose information including upstream branch (-vv flag)"
                        ),
                    },
                    "merged": {
                        "type": "string",
                        "description": "Show branches merged into specified commit (--merged flag)",
                    },
                    "no_merged": {
                        "type": "string",
                        "description": (
                            "Show branches not merged into specified commit (--no-merged flag)"
                        ),
                    },
                    "sort": {
                        "type": "string",
                        "description": (
                            "Sort branches by key (committerdate, authordate, refname, etc.)"
                            " (--sort flag)"
                        ),
                    },
                    "format": {
                        "type": "string",
                        "description": "Custom output format using placeholders (--format flag)",
                    },
                    "show_current": {
                        "type": "boolean",
                        "description": "Show only current branch name (--show-current flag)",
                    },
                },
                "required": [],
            },
        },
    }

    @classmethod
    def execute(
        cls,
        coder,
        remotes=False,
        all=False,
        verbose=False,
        very_verbose=False,
        merged=None,
        no_merged=None,
        sort=None,
        format=None,
        show_current=False,
        **kwargs,
    ):
        """
        List branches in the repository with various filtering and formatting options.
        """
        response = ToolResponse(cls.NORM_NAME)

        if not coder.repo:
            response.append_result("Not in a git repository.")
            return response

        try:
            # Build git command arguments
            args = []

            # Handle boolean flags
            if remotes:
                args.append("--remotes")
            if all:
                args.append("--all")
            if verbose:
                args.append("--verbose")
            if very_verbose:
                args.append("--verbose")
                args.append("--verbose")
            if show_current:
                args.append("--show-current")

            # Handle string parameters
            if merged:
                args.extend(["--merged", merged])
            if no_merged:
                args.extend(["--no-merged", no_merged])
            if sort:
                args.extend(["--sort", sort])
            if format:
                args.extend(["--format", format])

            # Execute git command
            result = coder.repo.repo.git.branch(*args).strip()

            # If no result and show_current was used, get current branch directly
            if not result and show_current:
                try:
                    head = coder.repo.repo.head
                    if head.is_detached:
                        response.append_result("HEAD (detached)")
                        return response
                    response.append_result(coder.repo.repo.active_branch.name)
                    return response
                except ANY_GIT_ERROR:
                    response.append_result("No current branch found.")
                    return response

            response.append_result(result if result else "No branches found matching the criteria.")
            return response

        except ANY_GIT_ERROR as e:
            coder.io.tool_error(f"Error running git branch: {e}")
            response.append_error(str(e))
            return response
