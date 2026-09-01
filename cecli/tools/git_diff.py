from cecli.repo import ANY_GIT_ERROR
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.responses import ToolResponse


class Tool(BaseTool):
    NORM_NAME = "gitdiff"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "GitDiff",
            "description": (
                "Show the diff between the current working directory and a git branch or commit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": (
                            "The branch or commit hash to diff against. Defaults to HEAD."
                        ),
                    },
                },
                "required": [],
            },
        },
    }

    @classmethod
    def execute(cls, coder, branch=None, **kwargs):
        """
        Show the diff between the current working directory and a git branch or commit.
        """
        response = ToolResponse(cls.NORM_NAME)

        if not coder.repo:
            response.append_result("Not in a git repository.")
            return response

        try:
            if branch:
                # Diff working tree against the requested branch/commit
                diff = coder.repo.diff_commits(False, branch, None)
            else:
                diff = coder.repo.diff_commits(False, "HEAD", None)

            if not diff:
                response.append_result("No differences found.")
                return response
            response.append_result(diff)
            return response
        except ANY_GIT_ERROR as e:
            coder.io.tool_error(f"Error running git diff: {e}")
            response.append_error(str(e))
            return response
