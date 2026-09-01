from cecli.repo import ANY_GIT_ERROR
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.responses import ToolResponse


class Tool(BaseTool):
    NORM_NAME = "gitshow"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "GitShow",
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

    @classmethod
    def execute(cls, coder, object="HEAD", **kwargs):
        """
        Show various types of objects (blobs, trees, tags, and commits).
        """
        response = ToolResponse(cls.NORM_NAME)

        if not coder.repo:
            response.append_result("Not in a git repository.")
            return response

        try:
            result = coder.repo.repo.git.show(object)
            response.append_result(result)
            return response
        except ANY_GIT_ERROR as e:
            coder.io.tool_error(f"Error running git show: {e}")
            response.append_error(str(e))
            return response
