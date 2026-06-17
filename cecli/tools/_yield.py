import asyncio
import logging

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.validations import ToolValidations

logger = logging.getLogger(__name__)


class Tool(BaseTool):
    NORM_NAME = "yield"
    TRACK_INVOCATIONS = False
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Yield",
            "description": "Yield control back to the user, indicating all sub-goals are complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": (
                            "Optional summary of what was accomplished. "
                            "When called by a sub-agent, this summary is captured "
                            "and returned to the parent agent."
                        ),
                    },
                },
                "required": [],
            },
        },
    }

    @classmethod
    async def execute(cls, coder, **kwargs):
        """
        Mark that the current generation task needs no further effort.

        This gives the LLM explicit control over when it can stop looping
        """
        from cecli.helpers.agents.service import AgentService

        cls.clear_invocation_cache()

        if coder:
            reject = getattr(coder, "reject_yield", None)
            if callable(reject):
                blocked = reject(coder, **kwargs)
                if blocked:
                    return blocked

            # Check for active child sub-agents and await their tasks before finishing
            try:
                agent_service = AgentService.get_instance(coder)
                children = agent_service.get_children(coder)
                active_tasks = [
                    info.generate_task
                    for info in children
                    if info.generate_task is not None and not info.generate_task.done()
                ]

                if active_tasks:
                    coder.io.tool_warning(
                        f"Waiting for {len(active_tasks)} sub-agent(s) to complete before yielding..."
                    )

                    # Single asyncio.wait that includes both the sub-agent tasks and
                    # the interrupt event, avoiding nested asyncio.wait() calls.
                    interrupt_event = coder.interrupt_event
                    if interrupt_event is None:
                        interrupt_event = asyncio.Event()

                    interrupt_task = asyncio.create_task(interrupt_event.wait())
                    pending = set(active_tasks) | {interrupt_task}

                    while any(t in pending for t in active_tasks):
                        done, still_pending = await asyncio.wait(
                            pending, timeout=5.0, return_when=asyncio.FIRST_COMPLETED
                        )
                        pending = still_pending

                        if interrupt_task in done:
                            # Interrupted — cancel remaining sub-agent tasks
                            for t in pending:
                                t.cancel()
                                try:
                                    await t
                                except (asyncio.CancelledError, Exception):
                                    pass
                            return (
                                "Yield interrupted while waiting for sub-agents. "
                                "Sub-agent outputs above may be incomplete."
                            )

                        # Retrieve exceptions from completed sub-agent tasks so they
                        # are not silently lost.
                        for t in done:
                            if t is not interrupt_task:
                                exc = t.exception()
                                if exc:
                                    logger.warning("Sub-agent task raised an exception: %s", exc)

                    # Cancel the interrupt task since we are done waiting
                    if not interrupt_task.done():
                        interrupt_task.cancel()
                        try:
                            await interrupt_task
                        except asyncio.CancelledError:
                            pass

                    # Don't mark as finished — the coder should review sub-agent
                    # outputs and decide how to proceed
                    return (
                        "Sub-agents have finished. Please examine their output above "
                        "in order to decide how you will proceed."
                    )
            except Exception as e:
                logger.warning("Error awaiting child sub-agents before yield: %s", e)

            # Reap all finished sub-agents with auto_reap enabled
            try:
                service = AgentService.get_instance(coder)
                await service.reap_all_finished_agents(parent=service.get_parent(coder))
            except Exception:
                logger.warning("Failed to reap finished sub-agents", exc_info=True)

            coder.agent_finished = True

            # If this is a sub-agent, capture the summary for the parent
            summary = kwargs.get("summary", None)
            parent_uuid = coder.parent_uuid
            if parent_uuid:
                try:

                    AgentService.mark_sub_agent_finished(
                        sub_coder_uuid=coder.uuid,
                        parent_uuid=parent_uuid,
                        summary=summary,
                    )
                except Exception:
                    pass

            if coder.files_edited_by_tools:
                _ = await coder.auto_commit(coder.files_edited_by_tools)
                coder.files_edited_by_tools = set()

            if summary:
                return f"Yielded. Summary: {summary}"
            return "Yielded."

        # coder.io.tool_Error("Error: Could not mark agent task as finished")
        return "Error: Could not yield control"

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

        summary = params.get("summary")
        if summary:
            coder.io.tool_output("")
            coder.io.tool_output(f"{color_start}Summary:{color_end}")
            coder.io.tool_output(summary)
            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)
