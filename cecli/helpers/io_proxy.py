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
    # Per-coder queue helpers (non-TUI mode)
    # ------------------------------------------------------------------ #

    def _take_queued(self, key: str):
        """Pop this coder's next queue payload containing *key*, else None.

        A payload meant for a different reader — for example a confirmation
        seen while waiting for text — is put back so its own waiter can still
        consume it.
        """
        try:
            payload = self._input_queue.get_nowait()
        except _queue.Empty:
            return None
        if isinstance(payload, dict) and key in payload:
            return payload
        self._input_queue.put(payload)
        return None

    async def _terminal_or_queued(self, terminal, take):
        """Await *terminal*, returning early when *take()* yields a payload.

        A queued payload is delivered even while the terminal prompt is open:
        the read is raced against the per-coder queue wake. That wake event is
        global (any coder's push sets it), so re-check this coder's own queue
        before racing again.
        """
        queued = take()
        if queued is not None:
            return queued

        if getattr(self, "prompt_session", None) is None:
            # ponytail: the InterruptibleInput/input() fallback reads on a
            # worker thread and cannot be cancelled, so a push arriving
            # mid-read lands on the next get_input() cycle instead of
            # preempting this read. Make the fallback cancellable if it ever
            # needs instant delivery.
            return await terminal()

        from cecli.helpers import queues

        terminal_task = asyncio.create_task(terminal())
        try:
            while True:
                wake_task = asyncio.create_task(queues.wait_for_input())
                try:
                    await asyncio.wait(
                        {terminal_task, wake_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    if not wake_task.done():
                        wake_task.cancel()
                if terminal_task.done():
                    # Surfaces the terminal read's own EOFError/SystemExit.
                    return terminal_task.result()
                queued = take()
                if queued is not None:
                    terminal_task.cancel()
                    return queued
        except BaseException:
            terminal_task.cancel()
            raise

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

    def reset_streaming_response(self, **kwargs) -> Any:
        """Forward reset_streaming_response with coder_uuid injected."""
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid
        return self._target.reset_streaming_response(**kwargs)

    async def get_input(self, *args, **kwargs):
        """Get input for this specific coder via per-coder queue.

        In TUI mode, delegates to TextualInputOutput which iterates all
        per-coder queues. If the returned coder_uuid doesn't match this
        proxy's coder, the input is for a sub-agent — route it via
        AgentService by calling generate() on the sub-agent, then loop.

        In non-TUI mode, delivers a queue-pushed answer (from the WebSocket
        server, ACP, or AgentService) when one is waiting, otherwise reads the
        base InputOutput terminal prompt. The terminal read is raced against
        the queue wake so a push is delivered even while the prompt is open.

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

        # Non-TUI mode: honor a queue-pushed answer, else read the terminal.
        def take_text():
            payload = self._take_queued("text")
            if payload is None:
                return None
            text = payload["text"]
            self.user_input(text)
            return text, payload.get("coder_uuid", self._coder_uuid)

        result = await self._terminal_or_queued(
            lambda: self._target.get_input(*args, **kwargs), take_text
        )
        if isinstance(result, tuple) and len(result) == 2:
            return result

        return (result, None)

    async def confirm_ask(self, *args, **kwargs):
        """Confirm with the TUI queues or the terminal.

        TUI mode: TextualInputOutput.confirm_ask iterates all per-coder queues.
        Non-TUI mode: honor a ``{"confirmed": ...}`` payload pushed to this
        coder's queue (WebSocket server, ACP), otherwise ask on the terminal.
        """
        if "coder_uuid" not in kwargs:
            kwargs["coder_uuid"] = self._coder_uuid

        if hasattr(self._target, "output_queue"):
            return await self._target.confirm_ask(*args, **kwargs)

        question = args[0] if args else kwargs.get("question")
        question_id = (question, kwargs.get("subject"))
        group = kwargs.get("group")
        group_response = kwargs.get("group_response")

        def take_confirmation():
            payload = self._take_queued("confirmed")
            if payload is None:
                return None
            return self._apply_confirmation(
                payload["confirmed"], question_id, group, group_response
            )

        return await self._terminal_or_queued(
            lambda: self._target.confirm_ask(*args, **kwargs), take_confirmation
        )

    def _apply_confirmation(self, response, question_id, group, group_response):
        """Map a queued confirmation payload to a result.

        Mirrors TextualInputOutput.confirm_ask's queue handling.
        """
        if response == "never":
            self.never_prompts.add(question_id)
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
        return bool(response)

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


# --- THE TYPE HINTING TRICK ---
# At type-checking time, make IOProxy(target, coder) appear to return
# type T, so IDEs/type-checkers treat the proxy as the wrapped class.
if TYPE_CHECKING:

    def __new__(cls, target: T, coder: Any) -> T:  # type: ignore[misc]
        ...
