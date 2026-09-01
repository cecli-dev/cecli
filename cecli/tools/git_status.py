from cecli.repo import ANY_GIT_ERROR
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.responses import ToolResponse


class Tool(BaseTool):
    NORM_NAME = "gitstatus"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "GitStatus",
            "description": "Show the working tree status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }

    @classmethod
    def execute(cls, coder, **kwargs):
        """
        Show the working tree status.
        """
        response = ToolResponse(cls.NORM_NAME)

        if not coder.repo:
            response.append_result("Not in a git repository.")
            return response

        try:
            result = coder.repo.repo.git.status()
            response.append_result(result)
            return response
        except ANY_GIT_ERROR as e:
            coder.io.tool_error(f"Error running git status: {e}")
            response.append_error(str(e))
            return response
