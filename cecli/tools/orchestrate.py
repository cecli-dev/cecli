import logging

from cecli.helpers.orchestration.service import OrchestrationService
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations

logger = logging.getLogger(__name__)


class Tool(BaseTool):
    NORM_NAME = "orchestrate"
    TRACK_INVOCATIONS = False
    VALIDATIONS = {}
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Orchestrate",
            "description": (
                "Run Python in a sandbox where you can call other tools programmatically. "
                "Use for batch or loop-heavy workflows. Provides `Agent` tool proxies, "
                "`gather()` for parallelism, and persistent `state`; use `values` to "
                "inject variables without escaping issues."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "Python code to execute in the sandbox. See the orchestration "
                            "context block for available primitives and calling conventions."
                        ),
                    },
                    "values": {
                        "type": "object",
                        "description": (
                            "Optional key-value dictionary of variables to inject "
                            "into the execution environment. Values must be strings "
                            "or numbers. Each key is exposed as a global variable "
                            "with the prefix '_o_' (e.g., '{\"file_content\": \"...\"}' "
                            "becomes '_o_file_content' in the code). Non-string/number "
                            "values are omitted with an error message."
                            "This is useful especially for longer strings like file contents."
                        ),
                    },
                },
                "required": ["code"],
            },
        },
    }

    @classmethod
    async def execute(cls, coder, code, values=None, **kwargs):
        BaseTool.clear_invocation_cache()
        env = OrchestrationService.get_instance(coder)

        errors = []
        sanitized = {}

        if values and isinstance(values, dict):
            for key, value in values.items():
                if not isinstance(key, str):
                    errors.append(f"Values key '{key}' is not a string, skipping.")
                    continue

                if isinstance(value, (int, float, str, bool)):
                    sanitized[key] = value
                else:
                    errors.append(
                        f"Value for '{key}' is not a string or number "
                        f"(got {type(value).__name__}), skipping."
                    )

        result = await env.execute(code, values=sanitized)
        response = ToolResponse(cls.NORM_NAME, result_type="list")
        response.append_result(
            content=result["results"], metadata={"state_variables": result["state_variables"]}
        )

        for error in errors:
            response.append_error(error)

        return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):

        color_start, color_end = color_markers(coder)

        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        try:
            params = ToolValidations.validate_params(
                tool_response.function.arguments, cls.VALIDATIONS, cls.SCHEMA
            )
        except ToolError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        if params.get("values"):
            coder.io.tool_output(f"{color_start}values:{color_end} True")

        code = params.get("code", "")
        if code:
            coder.io.tool_output("")
            coder.io.tool_output(f"{color_start}Code:{color_end}")
            for line in code.strip().splitlines():
                coder.io.tool_output(f"  {line}")
            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)
