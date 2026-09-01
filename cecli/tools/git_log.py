from cecli.repo import ANY_GIT_ERROR
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.responses import ToolResponse


class Tool(BaseTool):
    NORM_NAME = "gitlog"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "GitLog",
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

    @classmethod
    def execute(cls, coder, limit=10, **kwargs):
        """
        Show the git log.
        """
        response = ToolResponse(cls.NORM_NAME)

        if not coder.repo:
            response.append_result("Not in a git repository.")
            return response

        try:
            commits = list(coder.repo.repo.iter_commits(max_count=limit))
            log_output = []
            for commit in commits:
                short_hash = commit.hexsha[:8]
                message = commit.message.strip().split("\n")[0]
                log_output.append(f"{short_hash} {message}")
            response.append_result("\n".join(log_output))
            return response
        except ANY_GIT_ERROR as e:
            coder.io.tool_error(f"Error running git log: {e}")
            response.append_error(str(e))
            return response
