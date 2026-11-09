"""IOProxy - a facade for InputOutput that injects coder context.

Enables dynamic routing of output messages to the correct TUI container
by injecting the coder's UUID into output queue messages without modifying
every direct call site.
"""

import asyncio
import logging
import queue as _queue
import weakref
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from cecli.report import update_error_prefix
from cecli.signals import ReloadProgramSignal, SwitchCoderSignal

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Non-TUI prompts poll this often for programmatic input. Polling keeps the
# producer side loop-agnostic: queue.Queue is thread-safe, so a driver never
# needs to know which event loop the prompt is running on.
_QUEUE_POLL_INTERVAL = 0.1


class IOProxy(Generic[T]):
    """Facade wrapping an InputOutput instance with coder context.

    Intercepts tool output methods (tool_output, tool_error, etc.) to
    inject the coder's UUID into queue messages for container routing.
    All other attributes are transparently forwarded to the wrapped
    InputOutput (or TextualInputOutput) instance.

    The underlying io instance is shared by all agents, so the coder_uuid
    lives only in the facade — never on the io itself.

    Per-coder task state (input_task, output_task) is stored in a private
    dict keyed by coder_uuid so each coder can manage its own `get_input`
    and `input_task` lifecycle without competing for the same promise
    on the shared InputOutput instance.

    Uses polling for input notification.

    Usage:
        io = IOProxy(TextualInputOutput(...), coder)
        io.tool_output("hello")  # forwards with coder_uuid injected
        io.some_other_method()   # forwarded transparently
    """

    def __init__(self, target: T, coder: Any) -> None:
        super().__setattr__("_target", target)
        # Per-agent data lives on the proxy, never on the shared target
        coder_uuid = getattr(coder, "uuid", None)
        super().__setattr__("_coder_uuid", coder_uuid)
        super().__setattr__("_coder", weakref.ref(coder))
        # Per-coder task storage: {coder_uuid: {attr_name: asyncio.Task}}
        super().__setattr__("_per_coder", {coder_uuid: {}})
        # Last tool `type` emitted via tool_output — lives on the proxy,
        # never on the shared target (like coder_uuid)
        super().__setattr__("_last_type", None)

        # Register a per-coder input queue (TUI mode only)
        # Allows the TUI to push input directly to this coder's queue,
        # eliminating the shared-queue routing loop in get_input().
        # In TUI mode, register this coder's input queue in the global
        # queue registry so the TUI can push input directly to the
        # correct coder without iterating a shared queue.
        from cecli.helpers import queues as _queues

        _input_q = _queue.Queue()
        _queues.register_coder_queue(coder_uuid, _input_q)
        super().__setattr__("_input_queue", _input_q)

    @classmethod
    def unwrap(cls, io):
        return io._target if isinstance(io, cls) else io

    # ------------------------------------------------------------------ #
    # Intercepted methods — inject coder_uuid into each call
    # ------------------------------------------------------------------ #

    def tool_output(self, *messages: Any, **kwargs: Any) -> Any:
        """Forward tool_output with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        self._last_type = kwargs.get("type")
        return self._target.tool_output(*messages, **kwargs)

    def tool_error(self, message: str = "", strip: bool = True, **kwargs: Any) -> Any:
        """Forward tool_error with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target.tool_error(message=message, strip=strip, **kwargs)

    def _tool_message(
        self, message: str = "", strip: bool = True, color: Any = None, **kwargs: Any
    ) -> Any:
        """Forward _tool_message with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target._tool_message(message=message, strip=strip, color=color, **kwargs)

    def tool_warning(self, message: str = "", strip: bool = True, **kwargs: Any) -> Any:
        """Forward tool_warning with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target.tool_warning(message=message, strip=strip, **kwargs)

    def tool_success(self, message: str = "", strip: bool = True, **kwargs: Any) -> Any:
        """Forward tool_success with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target.tool_success(message=message, strip=strip, **kwargs)

    def stream_print(self, *messages: Any, **kwargs: Any) -> Any:
        """Forward stream_print with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target.stream_print(*messages, **kwargs)

    def stream_output(self, text: str = "", final: bool = False, **kwargs: Any) -> Any:
        """Forward stream_output with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target.stream_output(text=text, final=final, **kwargs)

    def assistant_output(self, message: str = "", pretty: Any = None, **kwargs: Any) -> Any:
        """Forward assistant_output with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target.assistant_output(message=message, pretty=pretty, **kwargs)

    def tool_call_event(self, tool_call_id: str, status: str, **kwargs: Any) -> Any:
        """Forward tool_call_event with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target.tool_call_event(tool_call_id, status, **kwargs)

    def diff_event(self, file_path: str, diff: str, **kwargs: Any) -> Any:
        """Forward diff_event with coder_uuid injected, when the backend supports it."""
        handler = getattr(self._target, "diff_event", None)
        if handler is None:
            return None

        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return handler(file_path, diff, **kwargs)

    def reset_streaming_response(self, **kwargs) -> Any:
        """Forward reset_streaming_response with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target.reset_streaming_response(**kwargs)

    def ring_bell(self, **kwargs: Any) -> Any:
        """Forward ring_bell with coder_uuid and is_workflow injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        if "is_workflow" not in kwargs:
            kwargs["is_workflow"] = self._is_workflow_agent()
        return self._target.ring_bell(**kwargs)

    def notify_user_input_required(self, **kwargs: Any) -> Any:
        """Forward notify_user_input_required with coder_uuid and is_workflow injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        if "is_workflow" not in kwargs:
            kwargs["is_workflow"] = self._is_workflow_agent()
        return self._target.notify_user_input_required(**kwargs)

    async def get_input(self, *args, **kwargs):
        """Get input for this specific coder via per-coder queue.

        In TUI mode, delegates to TextualInputOutput which iterates all
        per-coder queues. If the returned coder_uuid doesn't match this
        proxy's coder, the input is for a sub-agent — route it via
        AgentService by calling generate() on the sub-agent, then loop.

        In non-TUI mode, returns a queue-pushed answer when one is waiting,
        otherwise reads the base InputOutput terminal prompt. A push is
        delivered even while that prompt is open.

        Returns:
            tuple[str, str | None]: (user_input, coder_uuid).
        """
        # TUI mode: call target (iterates all per-coder queues)
        if hasattr(self._target, "output_queue"):
            while True:
                result = await self._target.get_input(*args, **kwargs)
                if isinstance(result, tuple) and len(result) == 2:
                    user_input, coder_uuid = result
                    # Check if this input is for a sub-agent
                    if coder_uuid is not None and coder_uuid != self._coder_uuid:
                        # Route to sub-agent via AgentService
                        _ref = getattr(self, "_coder", None)
                        coder = _ref() if _ref is not None else None
                        if coder:
                            from cecli.helpers.agents.service import AgentService

                            agent_service = AgentService.get_instance(coder)
                            for info in agent_service.sub_agents.values():
                                if info.coder.uuid == coder_uuid:
                                    agent_service.start_generate_task(info, user_input)
                                    break
                        # Loop back to wait for our own input.
                        # This allows input to be parallelized across multiple
                        # coders — each coder's get_input() handles the input
                        # meant for the others by routing it appropriately.
                        await asyncio.sleep(0.1)
                        continue
                    return user_input, coder_uuid
                return (result, None)

        # Non-TUI mode: honor a queued answer, else read the terminal prompt.
        payload, result = await self._terminal_or_queued(
            lambda: self._target.get_input(*args, **kwargs),
            key="text",
            keep_draft=True,
        )

        if payload is not None:
            text = payload["text"]
            self.user_input(text)
            return text, payload.get("coder_uuid", self._coder_uuid)

        if isinstance(result, tuple) and len(result) == 2:
            return result

        return (result, None)

    async def confirm_ask(self, *args, **kwargs):
        """Confirm through the TUI queues or the terminal prompt.

        TUI mode delegates to ``TextualInputOutput``, which iterates all
        per-coder queues. Non-TUI mode honors a queued ``{"confirmed": ...}``
        payload when one is waiting, otherwise reads the terminal prompt.

        Coders configured with ``skip_cli_confirmations`` (unattended ``wf:``
        workflow and ``ws:`` workspace workers) are auto-confirmed. They run
        with nobody watching, and — more importantly — a blocking prompt has
        to be awaited from whatever loop the coder happens to run on. A
        scheduler-dispatched workflow runs on the main (Textual) loop, so
        blocking there used to rebind ``queues``' global input-wake slot and
        strand the primary coder's input pump.
        """
        coder_ref = getattr(self, "_coder", None)
        coder = coder_ref() if coder_ref is not None else None

        if coder is not None and getattr(coder, "skip_cli_confirmations", False):
            question = args[0] if args else kwargs.get("question", "")
            logger.debug(
                "auto-confirming %r for unattended coder %s (skip_cli_confirmations)",
                question,
                self._coder_uuid,
            )
            return True

        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid

        if hasattr(self._target, "output_queue"):
            return await self._target.confirm_ask(*args, **kwargs)

        question = args[0] if args else kwargs.get("question", "")
        payload, result = await self._terminal_or_queued(
            lambda: self._target.confirm_ask(*args, **kwargs),
            key="confirmed",
        )

        if payload is None:
            return result

        self.num_user_asks += 1
        return self._apply_confirmation(
            payload["confirmed"],
            question,
            kwargs.get("subject"),
            kwargs.get("group"),
            kwargs.get("group_response"),
        )

    async def recreate_input(self, future=None):
        """Per-coder recreate_input — each coder gets its own input task.

        Unlike InputOutput.recreate_input which stores the task in a
        single shared attribute, this stores the task in a per-coder
        dict so multiple coders can have independent input task
        lifecycles without overwriting each other.
        """
        state = self._per_coder.get(self._coder_uuid, {})
        current = state.get("input_task")
        if current is None or current.done():
            _ref = getattr(self, "_coder", None)
            coder = _ref() if _ref is not None else None
            if coder:
                task = asyncio.create_task(coder.get_input())
            else:
                task = asyncio.create_task(self._target.get_input(None, [], [], []))
            state["input_task"] = task
            await asyncio.sleep(0)

    async def stop_input_task(self):
        """Cancel only this coder's input task."""
        state = self._per_coder.get(self._coder_uuid, {})
        task = state.get("input_task")
        if task:
            try:
                task.cancel()
                await task
            except (asyncio.CancelledError, Exception):
                pass
            state["input_task"] = None

    async def stop_output_task(self):
        """Cancel only this coder's output task."""
        state = self._per_coder.get(self._coder_uuid, {})
        task = state.get("output_task")
        if task:
            try:
                task.cancel()
                await task
            except (
                asyncio.CancelledError,
                EOFError,
                ReloadProgramSignal,
                SystemExit,
                SwitchCoderSignal,
            ):
                pass
            except (
                Exception,
                IndexError,
                RuntimeError,
            ):
                e = task.exception()
                if e:
                    logger.error(e, exc_info=True)

                import traceback

                traceback_str = traceback.format_exc()
                update_error_prefix(traceback_str)
                update_error_prefix(str(task))
                pass
            state["output_task"] = None

    async def stop_task_streams(self):
        """Stop both input and output tasks for this coder."""
        await self.stop_input_task()
        await self.stop_output_task()

    def __getattr__(self, name: str) -> Any:
        # Per-coder task attributes — return from per-coder storage
        if name == "input_task":
            return self._per_coder.get(self._coder_uuid, {}).get("input_task")
        if name == "output_task":
            return self._per_coder.get(self._coder_uuid, {}).get("output_task")
        # Everything else → forward to shared target
        return getattr(self._target, name)

    def __setattr__(self, name: str, value: Any) -> None:
        # Proxy-internal attributes — store on proxy instance only
        if name in ("_target", "_coder_uuid", "_coder", "_per_coder", "_last_type"):
            super().__setattr__(name, value)
        # Per-coder task attributes — isolate per-coder so coders don't
        # compete for the same promise on the shared InputOutput instance
        elif name == "input_task":
            refs = self._per_coder.setdefault(self._coder_uuid, {})
            refs["input_task"] = value
        elif name == "output_task":
            refs = self._per_coder.setdefault(self._coder_uuid, {})
            refs["output_task"] = value
        # Everything else → shared target
        else:
            setattr(self._target, name, value)

    async def _terminal_or_queued(self, terminal, key, keep_draft=False):
        """Return ``(payload, None)`` from the queue, else ``(None, result)``.

        The terminal read is polled against this coder's queue so a push is
        delivered even while the prompt is open. A prompt session that cannot
        be cancelled (``InterruptibleInput``/``input()``) is awaited as-is; the
        queue is checked again on the next prompt.
        """
        from cecli.helpers import queues

        payload = queues.pop_coder_input(self._coder_uuid, key)
        if payload is not None:
            return payload, None

        if getattr(self, "prompt_session", None) is None:
            return None, await terminal()

        terminal_task = asyncio.create_task(terminal())
        try:
            while True:
                done, _ = await asyncio.wait({terminal_task}, timeout=_QUEUE_POLL_INTERVAL)
                if done:
                    return None, terminal_task.result()

                payload = queues.pop_coder_input(self._coder_uuid, key)
                if payload is not None:
                    if keep_draft:
                        self._stash_prompt_draft()
                    return payload, None
        finally:
            if not terminal_task.done():
                terminal_task.cancel()

            try:
                await terminal_task
            except (asyncio.CancelledError, Exception):
                pass

    def _stash_prompt_draft(self):
        """Keep text the user was typing when a queued answer preempts the prompt."""
        session = getattr(self._target, "prompt_session", None)
        buffer = getattr(getattr(session, "app", None), "current_buffer", None)
        draft = getattr(buffer, "text", "")
        if draft:
            self._target.placeholder = draft

    def _apply_confirmation(self, response, question, subject, group, group_response):
        """Map a queued confirmation payload to ``confirm_ask``'s return value."""
        if isinstance(response, str):
            response = response.strip().lower()

        if response == "never":
            self.never_prompts.add((question, subject))
            return False

        if response == "tweak":
            return "tweak"

        if response == "all":
            if group:
                group.preference = "all"
            if group_response:
                self.group_responses[group_response] = True
            return True

        if response == "skip":
            if group:
                group.preference = "skip"
            if group_response:
                self.group_responses[group_response] = False
            return False

        if response in ("no", "n", "false", "0"):
            return False

        return bool(response)

    def _is_workflow_agent(self) -> bool:
        """Return True if the proxied coder is a workflow (wf:*) sub-agent."""
        _ref = getattr(self, "_coder", None)
        coder = _ref() if _ref is not None else None
        if coder is None:
            return False
        try:
            from cecli.helpers.agents.service import AgentService

            name = AgentService.get_agent_name(coder)
            return name is not None and name.startswith("wf:")
        except Exception:
            return False


# --- THE TYPE HINTING TRICK ---
# At type-checking time, make IOProxy(target, coder) appear to return
# type T, so IDEs/type-checkers treat the proxy as the wrapped class.
if TYPE_CHECKING:

    def __new__(cls, target: T, coder: Any) -> T:  # type: ignore[misc]
        ...
