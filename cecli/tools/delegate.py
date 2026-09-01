"""Delegate tool - allows the primary agent to spawn sub-agents."""

import asyncio

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "delegate"
    RESULT_TYPE = "list"
    TRACK_INVOCATIONS = True
    VALIDATIONS = {
        "delegations": ["coerce_list"],
        "delegations[]": ["coerce_dict"],
    }
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Delegate",
            "description": (
                "Delegate one or more specialized sub-agents to handle sub-tasks autonomously. "
                "Accepts an array of delegations to enable parallel task dispatch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "delegations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Name of the sub-agent to delegate to.",
                                },
                                "prompt": {
                                    "type": "string",
                                    "description": "Task description to give the sub-agent.",
                                },
                                "async": {
                                    "type": "boolean",
                                    "default": True,
                                    "description": (
                                        "If true (default), delegate asynchronously (fire-and-forget)."
                                        " If false, wait for the result."
                                    ),
                                },
                                "persist": {
                                    "type": "boolean",
                                    "default": False,
                                    "description": (
                                        "If true, keep the sub-agent active after the task is complete."
                                    ),
                                },
                            },
                            "required": ["name", "prompt"],
                        },
                        "description": "Array of delegation tasks to execute in parallel.",
                    }
                },
                "required": ["delegations"],
            },
        },
    }

    @classmethod
    async def execute(cls, coder, **kwargs):
        """Delegate one or more sub-agents to work on sub-tasks in parallel."""

        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)
        delegations = kwargs.get("delegations", [])

        if not delegations or not isinstance(delegations, list):
            response.append_error(
                "'delegations' parameter must be a non-empty array of {name, prompt, async, persist} objects."
            )
            return response

        # Validate each delegation item has the required fields
        for i, d in enumerate(delegations):
            if not isinstance(d, dict):
                response.append_error(f"delegations[{i}] is not an object.")
                return response
            if "name" not in d or not d["name"]:
                response.append_error(f"delegations[{i}] is missing a 'name'.")
                return response
            if "prompt" not in d or not d["prompt"]:
                response.append_error(f"delegations[{i}] is missing a 'prompt'.")
                return response

        from cecli.helpers.agents.service import AgentService

        agent_service = AgentService.get_instance(coder)

        # Separate async (fire-and-forget) and sync (blocking) delegations
        async_delegations = [
            (d["name"], d["prompt"], d.get("persist", False))
            for d in delegations
            if d.get("async", True)
        ]
        sync_delegations = [
            (d["name"], d["prompt"], d.get("persist", False))
            for d in delegations
            if not d.get("async", True)
        ]

        async def _spawn_one(name: str, prompt: str, persist: bool) -> tuple:
            """Spawn a single sub-agent (fire-and-forget). Returns (name, uuid_or_error, error)."""
            auto_reap = None if not persist else False
            try:
                new_coder, info = await agent_service.spawn(
                    name, prompt, parent=coder, auto_reap=auto_reap
                )
                return name, info.coder.uuid, None
            except Exception as e:
                return name, None, f"failed: {e}"

        async def _invoke_one(name: str, prompt: str, persist: bool) -> tuple:
            """Invoke a single sub-agent (blocking). Returns (name, summary_or_error, error)."""
            auto_reap = None if not persist else False
            try:
                summary = await agent_service.invoke(
                    name, prompt, parent=coder, auto_reap=auto_reap
                )
                return name, summary or "(no summary)", None
            except Exception as e:
                return name, None, f"failed: {e}"

        # Process async delegations (fire-and-forget spawn)
        async_results = []
        if async_delegations:
            tasks = [_spawn_one(n, p, persist) for n, p, persist in async_delegations]
            async_results = list(await asyncio.gather(*tasks))

        # Process sync delegations (blocking invoke)
        sync_results = []
        if sync_delegations:
            tasks = [_invoke_one(n, p, persist) for n, p, persist in sync_delegations]
            sync_results = list(await asyncio.gather(*tasks))

        # Build response
        if not sync_delegations:
            # All async: single combined result (current behavior)
            lines = []
            for name, result, error in async_results:
                if error:
                    lines.append(f"✗ **{name}**: {error}")
                else:
                    lines.append(f"✓ **{name}** agent started with id `{result}`")

            n_total = len(async_results)
            n_ok = sum(1 for _, _, e in async_results if not e)
            combined = "\n".join(lines)
            response.append_result(
                f"📋 Delegation results ({n_ok}/{n_total} dispatched):\n{combined}"
            )
        else:
            # Mixed or all sync: individual results per non-async agent
            if async_delegations:
                lines = []
                for name, result, error in async_results:
                    if error:
                        lines.append(f"✗ **{name}**: {error}")
                    else:
                        lines.append(f"✓ **{name}** agent started with id `{result}`")
                combined = "\n".join(lines)
                n_ok = sum(1 for _, _, e in async_results if not e)
                response.append_result(
                    f"📋 Async delegation results ({n_ok}/{len(async_results)} dispatched):\n{combined}"
                )

            for name, summary, error in sync_results:
                if error:
                    response.append_result(f"✗ **{name}** agent failed: {error}")
                else:
                    response.append_result(f"✓ **{name}** agent completed:\n{summary}")

        return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for Delegate tool - show each delegation's agent and task."""
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

        delegations = params.get("delegations", [])
        if delegations:
            coder.io.tool_output("")
            for i, d in enumerate(delegations):
                name = d.get("name", "")
                prompt = d.get("prompt", "")
                is_async = d.get("async", True)
                is_persist = d.get("persist", False)
                coder.io.tool_output(f"{color_start}delegation_{i + 1}:{color_end}")
                coder.io.tool_output(f"agent: {name}")
                coder.io.tool_output(f"mode: {'async' if is_async else 'sync'}")
                coder.io.tool_output(f"persist: {'true' if is_persist else 'false'}")
                coder.io.tool_output(f"task: {prompt}")
                if i < len(delegations) - 1:
                    coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)
