"""Broadcast tool - sends a message to one or more sub-agents."""

import time

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "broadcast"
    RESULT_TYPE = "list"
    VALIDATIONS = {
        "targets": ["coerce_list"],
    }
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Broadcast",
            "description": (
                "Broadcast a message to one or more sub-agent instances. Sends the message to the "
                "specified target sub-agents, or to every active sub-agent when empty/omitted. "
                "The message is queued into the target's context if it is actively generating, "
                "and delivered immediately if the target is idle, waking them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to broadcast to the target sub-agent(s).",
                    },
                    "targets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional array of sub-agent IDs (UUIDs, UUID prefixes, or "
                            "agent names) to send the message to, or 'primary' for the primary agent. "
                            "Set as an empty string to broadcast to all active sub-agents."
                        ),
                    },
                },
                "required": ["message"],
            },
        },
    }

    @classmethod
    async def execute(cls, coder, **kwargs):
        """Broadcast a message to one or more sub-agents.

        For each target sub-agent, the message is either queued into its
        conversation (if it is actively generating) or used to start a fresh
        generate task (if it is idle). When no targets are specified, the
        message is broadcast to every active sub-agent except the originator.

        Args:
            coder: The coder instance invoking the tool (the originator).
            message: The message to broadcast.
            targets: Optional list of sub-agent IDs.

        Returns:
            ToolResponse with a per-target delivery summary.
        """
        from cecli.helpers.agents.service import AgentService

        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)

        message = kwargs.get("message")
        if message is None or not str(message).strip():
            response.append_error("'message' parameter must be a non-empty string.")
            return response
        message = str(message).strip()

        targets = kwargs.get("targets")
        if targets is not None and not isinstance(targets, list):
            response.append_error("'targets' parameter must be an array of sub-agent IDs.")
            return response

        agent_service = AgentService.get_instance(coder)
        originator_uuid = str(coder.uuid)

        target_infos, errors = cls._collect_targets(agent_service, targets, originator_uuid)

        for error in errors:
            response.append_error(error)

        delivered = []
        delivery_errors = []
        for info in target_infos:
            try:
                mode = cls._deliver(info, message, agent_service, coder)
                delivered.append((info, mode))
            except Exception as exc:
                delivery_errors.append(f"Broadcast to '{cls._target_label(info)}' failed: {exc}")

        for info, mode in delivered:
            response.append_result(f"{cls._target_label(info)}: {mode}")

        for error in delivery_errors:
            response.append_error(error)

        if not delivered and not errors and not delivery_errors:
            response.append_result("No targets to broadcast to.")

        return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for the Broadcast tool - show the message and targets."""
        color_start, color_end = color_markers(coder)

        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        try:
            params = ToolValidations.validate_params(
                tool_response.function.arguments, cls.VALIDATIONS, cls.SCHEMA
            )
        except ToolError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        message = params.get("message", "")
        targets = params.get("targets", [])

        coder.io.tool_output("")
        coder.io.tool_output(f"{color_start}message:{color_end}")
        coder.io.tool_output(message)
        coder.io.tool_output("")
        if targets:
            coder.io.tool_output(
                f"{color_start}targets:{color_end} {', '.join(str(t) for t in targets)}"
            )
        else:
            coder.io.tool_output(f"{color_start}targets:{color_end} All")

        tool_footer(coder=coder, tool_response=tool_response, params=params)

    @classmethod
    def _collect_targets(cls, service, targets, originator_uuid):
        """Return ``(target_infos, errors)`` for the broadcast.

        When ``targets`` is empty, returns every active sub-agent except the
        originator. When ``targets`` is provided, each entry is resolved by
        UUID, UUID prefix, or agent name (including ``primary`` for the primary
        agent); unknown IDs produce an error.
        """
        from cecli.helpers.agents.service import SubAgentInfo, SubAgentStatus

        if not targets:
            infos = [
                info
                for info in service.sub_agents.values()
                if str(info.coder.uuid) != originator_uuid
                and info.status not in (SubAgentStatus.ERROR,)
            ]
            return infos, []

        infos = []
        errors = []
        for target in targets:
            info = cls._resolve_target(service, target)
            if info is None:
                errors.append(f"Unknown sub-agent target '{target}'.")
                continue
            target_uuid = info.coder.uuid if isinstance(info, SubAgentInfo) else info.uuid
            if str(target_uuid) != originator_uuid:
                infos.append(info)

        return infos, errors

    @staticmethod
    def _resolve_target(service, target):
        """Resolve a target sub-agent by UUID, UUID prefix, or agent name.

        The primary agent is also resolvable by its name (``primary``) or UUID
        so sub-agents can broadcast a message back to their parent.
        """
        target = str(target).strip()
        if not target:
            return None

        info = service.sub_agents.get(target)
        if info is not None:
            return info

        for uuid, candidate in service.sub_agents.items():
            if uuid.startswith(target):
                return candidate

        for candidate in service.sub_agents.values():
            if candidate.name == target:
                return candidate

        primary_coder = service.coder
        primary_uuid = str(getattr(primary_coder, "uuid", ""))
        if primary_coder is not None and (target == "primary" or target == primary_uuid):
            return primary_coder

        return None

    @staticmethod
    def _deliver(info, message, agent_service, sender_coder):
        """Queue, wake, or start a generate task for a single target.

        When the target is the primary agent, ``AgentService.wake_primary()`` is
        used: if the primary is actively generating the message is queued into
        its conversation, otherwise it is woken via its per-coder input queue
        (the primary does not use the sub-agent generate-task architecture).

        When the target is a sub-agent that is still generating, the message is
        queued into its conversation; an idle sub-agent gets a fresh generate
        task via ``AgentService.start_generate_task()``.

        The message is prefixed with the sender's identity so the target
        sub-agent can see who broadcast it.

        Returns a short mode string describing how the message was delivered.
        """
        from cecli.helpers.agents.service import SubAgentInfo
        from cecli.helpers.conversation import ConversationService, MessageTag
        from cecli.helpers.coroutines import is_active

        sender_name = agent_service.get_agent_name(sender_coder) or "primary"
        sender_uuid = str(sender_coder.uuid)
        message = (
            "<context name='broadcast' from='agent'>\n"
            f"[Message Sent from Agent {sender_name} ({sender_uuid})]\n"
            "You may respond with the `Broadcast` tool if the message "
            "is relevant to you\n\n"
            f"{message}"
            "</context>"
        )

        if not isinstance(info, SubAgentInfo):
            # Primary-agent target. The primary does not use the sub-agent
            # generate-task architecture — if it is idle we must wake it via
            # its per-coder input queue (same strategy as on_input_area_submit()).
            return agent_service.wake_primary(info, message)

        if is_active(info.generate_task):
            ConversationService.get_manager(info.coder).queue_message(
                message_dict={
                    "role": "user",
                    "content": message,
                },
                tag=MessageTag.CUR,
                hash_key=("broadcast", str(info.coder.uuid), str(time.monotonic_ns())),
            )
            return "queued"

        agent_service.start_generate_task(info, message)
        return "started"

    @staticmethod
    def _target_label(target):
        """Return a display label for a broadcast target.

        Sub-agents are labelled ``name (uuid)``; the primary agent is labelled
        ``primary (uuid)``.
        """
        from cecli.helpers.agents.service import SubAgentInfo

        if isinstance(target, SubAgentInfo):
            return f"{target.name} ({target.coder.uuid})"
        return f"primary ({target.uuid})"
