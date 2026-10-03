"""Helpers for writing Python hooks.

Provides a higher-level API for accessing conversation history, making model
calls, and working with sub-agents from within hook implementations.

Typical usage:

    from cecli.hooks import HookHelpers

    class MyHook(BaseHook):
        type = HookType.POST_TOOL

        async def execute(self, coder, metadata):
            recent = HookHelpers.get_messages(coder, last_n=5)
            reply = await HookHelpers.call(coder, prompt="Summarize the above.")
            HookHelpers.append_message(coder, {"role": "assistant", "content": reply})
            summary = await HookHelpers.call_subagent(
                coder, "reviewer", "Review these changes"
            )
            return True
"""

from typing import Any, Dict, List, Optional, Union


class HookHelpers:
    """Collection of static helper methods for Python hooks.

    All methods receive the ``coder`` instance as their first argument
    so they can access conversation history, make model calls, and
    invoke sub-agents on behalf of the agent running the hook.
    """

    @staticmethod
    def get_messages(
        coder: Any,
        last_n: Optional[int] = None,
        tag: Optional[str] = None,
        reload: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieve conversation messages for the given coder.

        This is a convenience wrapper around
        ``ConversationService.get_manager(coder).get_messages_dict()``.

        Args:
            coder: The coder instance (passed to hook's ``execute()``).
            last_n: If set, return only the *last_n* messages (most recent first).
            tag: Optional tag to filter by (e.g. ``"cur"``, ``"done"``).
                 If ``None``, returns all messages.
            reload: If ``True``, bypass the internal cache.

        Returns:
            A list of message dicts sorted by priority then timestamp,
            each with keys ``role``, ``content``, etc.
        """
        from cecli.helpers.conversation.service import ConversationService

        manager = ConversationService.get_manager(coder)
        # NOTE: intentionally no flush_queue() here. Hooks (esp. post_tool) run
        # mid-turn while tool responses are pending, and tool responses must
        # follow the assistant message exactly; flushing here would insert
        # queued messages between them.
        messages = manager.get_messages_dict(tag=tag, reload=reload)

        if last_n is not None and last_n > 0:
            messages = messages[-last_n:]

        return messages

    @staticmethod
    def append_message(
        coder: Any,
        message_dict: Dict[str, Any],
        tag: str = "cur",
        **kwargs: Any,
    ) -> Any:
        """Append a message to the coder's conversation history.

        This is a convenience wrapper around
        ``ConversationService.get_manager(coder).add_message()``.

        Args:
            coder: The coder instance (passed to hook's ``execute()``).
            message_dict: The message content dict (e.g.
                ``{"role": "user", "content": "..."}``).
            tag: Message tag to use (default ``"cur"``).
            **kwargs: Additional keyword arguments forwarded to
                ``add_message()``, such as ``hash_key``, ``force``,
                ``priority``, ``promotion``, etc.

        Returns:
            The ``BaseMessage`` instance that was created or updated.
        """
        from cecli.helpers.conversation.service import ConversationService

        return ConversationService.get_manager(coder).add_message(
            message_dict=message_dict,
            tag=tag,
            **kwargs,
        )

    @staticmethod
    async def call(
        coder: Any,
        messages: Optional[List[Dict[str, Any]]] = None,
        prompt: Optional[str] = None,
        system: Optional[str] = None,
        model_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        """Make a language model generation call.

        You can provide ``messages`` directly (a list of message dicts), or
        use ``prompt`` (with an optional ``system`` message) to build a
        simple user/assistant exchange.

        Args:
            coder: The coder instance (passed to hook's ``execute()``).
            messages: A list of message dicts (``{"role": ..., "content": ...}``).
                If provided, ``prompt`` and ``system`` are ignored.
            prompt: A simple user prompt string.  Ignored if ``messages`` is set.
            system: An optional system prompt.  Only used when ``prompt`` is set
                and ``messages`` is ``None``.
            model_name: Override the model to use (e.g. ``"gpt-4o"``).
                If ``None``, uses ``coder.main_model``.
            max_tokens: Maximum tokens for the response.
            **kwargs: Additional keyword arguments forwarded to
                ``Model.simple_send_with_retries()``.

        Returns:
            The generated text content, or ``None`` on failure.
        """
        from cecli.models import Model

        if messages is None:
            msgs: List[Dict[str, Any]] = []
            if system:
                msgs.append({"role": "system", "content": system})
            if prompt:
                msgs.append({"role": "user", "content": prompt})
            messages = msgs

        if not messages:
            return None

        if model_name:
            model = Model(
                model_name,
                from_model=coder.main_model,
            )
        else:
            model = coder.main_model

        content, _ = await model.simple_send_with_retries(
            messages=messages,
            max_tokens=max_tokens,
            coder=coder,
            override_kwargs=kwargs,
        )
        return content

    @staticmethod
    async def call_subagent(
        coder: Any,
        name: str,
        prompt: str,
        **kwargs: Any,
    ) -> Optional[str]:
        """Invoke a sub-agent by name with the given prompt (blocking).

        This is a convenience wrapper around
        ``AgentService.get_instance(coder).invoke()``.

        Args:
            coder: The coder instance (passed to hook's ``execute()``).
            name: The registered name of the sub-agent (e.g.
                ``"reviewer"``, ``"tester"``).
            prompt: The user message to pass to the sub-agent.
            **kwargs: Additional keyword arguments forwarded to
                ``AgentService.invoke()``, such as ``blocking``,
                ``parent``, ``auto_reap``.

        Returns:
            The sub-agent's summary string, or ``None`` if it failed or
            was invoked non-blocking.
        """
        from cecli.helpers.agents.service import AgentService

        agent_service = AgentService.get_instance(coder)

        return await agent_service.invoke(name, prompt, **kwargs)

    @staticmethod
    async def system_one(
        coder: Any,
        state: Any = None,
        questions: Optional[Dict[str, Any]] = None,
        decide: Optional[Union[str, Dict[str, Any]]] = None,
        judge: Optional[Union[str, Dict[str, Any]]] = None,
        rate: Optional[Union[List[Any], Dict[str, Any]]] = None,
        model: Optional[str] = None,
        last_n: int = 20,
    ) -> Dict[str, Any]:
        """Ask a System One decision model about the conversation or a state.

        System One endpoints answer typed questions (``noul`` yes/no,
        ``choice`` and ``score``) in a single non-generative pass, so this
        returns structured verdicts rather than prose. Provide exactly one of
        ``questions``, ``decide``, ``judge`` or ``rate``.

        Args:
            coder: The coder instance (passed to hook's ``execute()``).
            state: Content to evaluate (str, object or array). When ``None``,
                the last ``last_n`` conversation messages are used.
            questions: Map of question id to a question dict (see
                ``cecli.helpers.system_one.noul`` / ``choice`` / ``score``).
                A bare string is treated as a yes/no question.
            decide: Option map (or ``{"choices": ..., "instructions": ...}``)
                for a single Choice question.
            judge: Instructions (or ``{"instructions": ..., "criteria": ...}``)
                for a single Noul question.
            rate: ``{"levels": [...], "instructions": ...}``, or a bare list of
                levels, for one Score question.
            model: Endpoint model name override.
            last_n: How many recent messages to build the default state from.

        Returns:
            ``{"model": str, "usage": {...}, "answers": {id: {...}}}`` where
            each answer is a plain dict of the parsed decision. Single-question
            shorthands come back under the ids ``decision``, ``judgment`` and
            ``rating``.

        Raises:
            ValueError: If other than exactly one of the four forms is given.
            Exception: Endpoint errors (``SystemOneError`` and transport
                failures) propagate; guard the call when the decision is only
                advisory or the endpoint may be down.
        """
        from cecli.helpers.system_one import integrations

        if state is None:
            state = HookHelpers.get_messages(coder, last_n=last_n)

        return await integrations.evaluate(
            state, questions=questions, decide=decide, judge=judge, rate=rate, model=model
        )
