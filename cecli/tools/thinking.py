from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "thinking"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Thinking",
            "description": (
                "Use this tool to store useful facts for later, "
                "keep a scratch pad of your current efforts, "
                "and clarify your thoughts and intentions for your next steps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Textual information to record in the context",
                    },
                },
                "required": ["content"],
            },
        },
    }

    @classmethod
    def execute(cls, coder, content, **kwargs):
        """
        A place to allow the model to record freeform text as it
        iterates over tools to ideally help it guide itself to a proper solution
        """
        response = ToolResponse(cls.NORM_NAME)
        coder.io.tool_output("🧠 Thoughts recorded in context", type="tool-result")
        response.append_result("🧠 Thoughts recorded in context. Please proceed with your task")
        return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        color_start, color_end = color_markers(coder)

        # Output header
        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        try:
            params = ToolValidations.validate_params(
                tool_response.function.arguments, cls.VALIDATIONS, cls.SCHEMA
            )
        except ToolError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        coder.io.tool_output("")
        coder.io.tool_output(f"{color_start}Thoughts:{color_end}")
        coder.io.tool_output(params["content"])
        coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)
