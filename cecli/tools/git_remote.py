from cecli.repo import ANY_GIT_ERROR
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.responses import ToolResponse


class Tool(BaseTool):
    NORM_NAME = "gitremote"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "GitRemote",
            "description": "List remote repositories.",
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
        List remote repositories.
        """
        response = ToolResponse(cls.NORM_NAME)

        if not coder.repo:
            response.append_result("Not in a git repository.")
            return response

        try:
            remotes = coder.repo.repo.remotes
            if not remotes:
                response.append_result("No remotes configured.")
                return response

            result = []
            for remote in remotes:
                result.append(f"{remote.name}\t{remote.url}")
            response.append_result("\n".join(result))
            return response
        except ANY_GIT_ERROR as e:
            coder.io.tool_error(f"Error running git remote: {e}")
            response.append_error(str(e))
            return response
