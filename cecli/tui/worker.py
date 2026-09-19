"""Worker thread for running Coder in background."""

import asyncio
import logging
import os
import sys
import threading
import time
import traceback
import warnings
from typing import Optional

from cecli.coders import Coder
from cecli.commands import ReloadProgramSignal, SwitchCoderSignal
from cecli.helpers.conversation import ConversationService, MessageTag
from cecli.helpers.coroutines import (
    cancel_and_abandon,
    task_is_cancelling,
)

logger = logging.getLogger(__name__)
# Suppress asyncio task destroyed warnings during shutdown
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# Also suppress via warnings module
warnings.filterwarnings("ignore", message=".*Task was destroyed.*")
warnings.filterwarnings("ignore", message=".*coroutine.*was never awaited.*")

CRASH_LOG_DIR = ".cecli/logs"
CRASH_LOG_PATH = os.path.join(CRASH_LOG_DIR, "worker-crash.log")


class CoderWorker:
    """Runs Coder in a background thread with its own event loop."""

    # A KeyboardInterrupt raised inside a child task is re-raised out of the
    # event loop by asyncio; give the loop a few chances to settle back into
    # waiting for input before treating the repeated interrupt as a crash.
    MAX_CONSECUTIVE_INTERRUPTS = 5

    def __init__(self, coder, output_queue, input_queue):
        """Initialize worker with coder instance and communication queues.

        Args:
            coder: The Coder instance to run
            output_queue: queue.Queue for sending output to TUI
            input_queue: queue.Queue for receiving input from TUI
        """
        self.coder = coder
        self.output_queue = output_queue  # queue.Queue
        self.input_queue = input_queue  # queue.Queue
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.running = False

    def start(self):
        """Start the worker thread."""
        self.running = True
        self.thread = threading.Thread(target=self._run_thread, daemon=True)
        self.thread.start()

    def _run_thread(self):
        """Thread entry point - creates event loop and runs coder."""
        self.loop = self._create_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.set_exception_handler(self.worker_loop_exception_handler)

        # Bind the global input wake-up state to this worker loop so
        # producers (TUI, WebSocket, ACP) wake consumers on the correct
        # loop. A fresh binding is required after a hot reload, where the
        # previous worker loop was closed.
        from cecli.helpers import queues

        queues.set_input_loop(self.loop)

        self._register_async_dump()

        consecutive_interrupts = 0
        run_task = None
        try:
            while self.running:
                if run_task is None or run_task.done():
                    run_task = self.loop.create_task(self._async_run())

                try:
                    self.loop.run_until_complete(run_task)
                    break
                except KeyboardInterrupt as e:
                    # asyncio re-raises KeyboardInterrupt (and SystemExit) out
                    # of the event loop when a *child task* raises it, so it
                    # escapes run_until_complete instead of being caught by the
                    # coroutine awaiting that task. Treat it as a soft interrupt:
                    # resume the same task if it is still pending, or let the top
                    # of the loop start a fresh run loop if it already finished.
                    self._log_worker_error("KeyboardInterrupt escaped the worker loop", e)
                    consecutive_interrupts += 1
                    if consecutive_interrupts > self.MAX_CONSECUTIVE_INTERRUPTS:
                        logger.error(
                            "Repeated KeyboardInterrupt escaped the worker loop", exc_info=e
                        )
                        self._notify_crash(e)
                        break
                    if run_task.done() and not run_task.cancelled():
                        run_task.exception()
                    time.sleep(0.05)
                except BaseException as e:
                    if not self._is_graceful_shutdown(e):
                        self._log_worker_error("Coder worker thread stopped unexpectedly", e)
                        logger.error("Coder worker thread stopped unexpectedly", exc_info=e)
                        self._notify_crash(e)
                    break
        finally:
            self._cleanup_loop()

    def _cleanup_loop(self):
        """Clean up the event loop safely."""
        if not self.loop:
            return

        try:
            # Disconnect MCP servers on this loop (connections live here) so
            # main-loop disconnect_all() becomes a no-op instead of racing
            # loop-bound cleanup across threads.
            mcp_manager = getattr(self.coder, "mcp_manager", None)
            if mcp_manager is not None and mcp_manager.is_connected and not self.loop.is_closed():
                try:
                    self.loop.run_until_complete(
                        asyncio.wait_for(mcp_manager.disconnect_all(), timeout=10)
                    )
                except Exception:
                    pass  # Ignore cleanup errors

            # Cancel pending tasks if loop is still running
            if not self.loop.is_closed():
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()

                # Let the cancelled tasks unwind, but only for a bounded time:
                # a task that ignores cancellation (see coroutines.interruptible)
                # must not wedge this thread, which would then never finish.
                if self.loop.is_running():
                    pass  # Can't do much if loop is still running
                elif pending:
                    try:
                        self.loop.run_until_complete(cancel_and_abandon(list(pending)))
                    except RuntimeError:
                        pass  # Loop already stopped
                    except KeyboardInterrupt:
                        pass  # Loop already stopped

                self.loop.close()
        except Exception:
            pass  # Ignore cleanup errors

    async def _async_run(self):
        """Async entry point - runs coder loop."""
        # MCP servers connect lazily on the coder's event loop (see main.py)
        # so loop-bound MCP state (sessions, locks, keepalive tasks) stays on
        # the same loop the coder runs on instead of migrating across loops.
        mcp_manager = getattr(self.coder, "mcp_manager", None)
        if mcp_manager is not None:
            try:
                await mcp_manager.connect_all()
            except asyncio.CancelledError:
                # connect_all uses gather; a single transport (e.g. MCP's
                # streamable-HTTP) can surface an ordinary connection failure
                # as CancelledError and abort the whole gather. Only propagate
                # a genuine cancellation of this worker.
                if task_is_cancelling():
                    raise
                logger.warning("MCP connect_all was cancelled by a server transport; continuing")
            except Exception as e:
                logger.error("Failed to connect MCP servers in worker: %s", e, exc_info=True)

        while self.running:
            try:
                await self.coder.run()
                break  # Normal exit
            except asyncio.CancelledError:
                break
            except KeyboardInterrupt:
                continue
            except ReloadProgramSignal:
                # Store the signal and tell the TUI to exit so the
                # full program reload can propagate to main()
                self._reload_signal = True
                self.output_queue.put({"type": "exit"})
                break
            except SwitchCoderSignal as switch:
                await self._handle_switch_coder_signal(switch)
                # Continue the loop with the new coder
            except Exception as e:
                logger.error(e, exc_info=True)

                self.output_queue.put(
                    {
                        "type": "error",
                        "message": str(e),
                        "coder_uuid": self.coder.uuid,
                    }
                )
                break

    async def _handle_switch_coder_signal(self, switch):
        """Handle a SwitchCoderSignal, creating a new coder and notifying the TUI."""
        try:
            from cecli.helpers.agents.service import AgentService

            # Determine the active coder — could be a sub-agent in the foreground
            target_coder = self.coder
            try:
                agent_service = AgentService.get_instance(target_coder)
                foreground = agent_service.foreground_coder
                if foreground is not None:
                    target_coder = foreground
            except Exception:
                pass

            await target_coder.auto_save_session(force=True)
            kwargs = dict(io=target_coder.io, from_coder=target_coder)
            kwargs.update(switch.kwargs)
            if "show_announcements" in kwargs:
                del kwargs["show_announcements"]
            kwargs["num_cache_warming_pings"] = 0
            kwargs["args"] = target_coder.args
            # Skip summarization to avoid blocking LLM calls during mode switch
            kwargs["summarize_from_coder"] = False

            new_coder = await Coder.create(**kwargs)
            new_coder.args = target_coder.args

            for tag in [MessageTag.SYSTEM, MessageTag.EXAMPLES, MessageTag.STATIC]:
                ConversationService.get_manager(new_coder).clear_tag(tag)

            if switch.kwargs.get("show_announcements") is False:
                new_coder.suppress_announcements_for_next_prompt = True

            # Notify TUI of mode change
            if target_coder == self.coder:
                self.coder = new_coder
            else:
                new_coder.show_announcements()

            edit_format = kwargs.get(
                "edit_format", getattr(target_coder, "edit_format", "code") or "code"
            )
            self.output_queue.put(
                {
                    "type": "mode_change",
                    "mode": edit_format,
                    "coder_uuid": new_coder.uuid,
                }
            )
        except Exception as e:
            self.output_queue.put(
                {
                    "type": "error",
                    "message": f"Failed to switch mode: {e}",
                    "coder_uuid": target_coder,
                }
            )

    def worker_loop_exception_handler(self, loop, context):
        """
        This runs directly on the worker thread whenever an unhandled
        exception occurs in a task or callback.

        Catches SwitchCoderSignal from fire-and-forget tasks and dispatches
        them to the dedicated handler so mode switches work even when the
        signal is raised outside the main coder.run() loop.
        """
        exception = context.get("exception")

        if isinstance(exception, SwitchCoderSignal):
            logger.info("Worker thread caught SwitchCoderSignal in global handler.")
            # Schedule a coroutine to handle the switch logic on the loop
            loop.create_task(self._handle_switch_coder_signal(exception))
        else:
            # Always fall back to the default handler so you don't swallow
            # normal bugs, tracebacks, or connection errors.
            loop.default_exception_handler(context)

    def interrupt(self):
        """Cancel the current output task on the active (foreground) coder.

        Resolves the foreground coder via AgentService so that the interrupt
        targets whichever agent (primary or sub-agent) is currently active.
        """
        # Determine the active coder — could be a sub-agent in the foreground
        target_coder = self.coder
        try:
            from cecli.helpers.agents.service import AgentService

            agent_service = AgentService.get_instance(self.coder)
            foreground = agent_service.foreground_coder
            if foreground is not None:
                target_coder = foreground
        except Exception:
            pass

        if not target_coder or not getattr(target_coder, "io", None):
            return

        # The output task, output flag, and interrupt event live on the worker
        # loop, but interrupt() runs on the TUI thread, so marshal the touch
        # onto that loop instead of mutating loop-bound state directly.
        loop = self.loop
        if loop is not None and loop.is_running() and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._apply_interrupt, target_coder)
                return
            except RuntimeError:
                pass

        # Loop is stopped or gone; apply directly so a stuck turn still stops.
        self._apply_interrupt(target_coder)

    def stop(self):
        """Stop the worker thread gracefully."""
        self.running = False

        # Signal the coder to stop
        if hasattr(self.coder, "input_running"):
            self.coder.input_running = False
        if hasattr(self.coder, "output_running"):
            self.coder.output_running = False

        if self.loop and self.loop.is_running():
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError:
                # Loop may already be closed
                pass
            except KeyboardInterrupt:
                # An interrupt was not caught within the async run loop.
                # We'll just pass to allow the thread to exit gracefully
                # without a scary traceback.
                pass
        self.interrupt()

        # Wait for thread to finish
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def _is_graceful_shutdown(self, exc) -> bool:
        """Return True when a worker-loop exception is an expected shutdown artifact.

        A normal stop() stops the loop, which surfaces from run_until_complete
        as RuntimeError; a cancellation after running goes False surfaces as
        CancelledError. Neither is a crash.
        """
        return not self.running and isinstance(exc, (asyncio.CancelledError, RuntimeError))

    def _notify_crash(self, exc):
        """Tell the TUI the worker died so it can surface the error and exit.

        Without this the TUI keeps running with a dead worker and appears hung.
        The full traceback is included so the failure is actionable instead of a
        bare ``KeyboardInterrupt()``.
        """
        detail = self._format_exception(exc)

        try:
            self.output_queue.put(
                {
                    "type": "error",
                    "message": f"Worker stopped unexpectedly: {exc!r}\n{detail}",
                    "coder_uuid": getattr(self.coder, "uuid", None),
                }
            )
            self.output_queue.put({"type": "exit"})
        except Exception:
            pass

    def _create_event_loop(self):
        """Create the event loop used by the coder worker thread.

        On Windows, use a ProactorEventLoop so MCP stdio servers can spawn real
        asynchronous subprocesses. The process-wide policy forces a
        SelectorEventLoop (required by prompt_toolkit on the main loop), but a
        SelectorEventLoop cannot create subprocesses, so MCP falls back to
        blocking ``Popen.wait()`` calls on the AnyIO thread pool. Those waits are
        uninterruptible and can hang forever, wedging MCP teardown and leaving the
        coder stuck mid-processing.
        """
        if sys.platform == "win32" and hasattr(asyncio, "ProactorEventLoop"):
            return asyncio.ProactorEventLoop()

        return asyncio.new_event_loop()

    def _apply_interrupt(self, target_coder):
        """Stop the coder's output loop, cancel its output task, and signal its interrupt event.

        Runs on the worker loop (see interrupt) so the loop-bound task and
        event are only touched from their owning loop.
        """
        if hasattr(target_coder, "output_running"):
            target_coder.output_running = False

        output_task = getattr(target_coder.io, "output_task", None)
        if output_task:
            output_task.cancel()

        interrupt_event = getattr(target_coder, "interrupt_event", None)
        if interrupt_event:
            interrupt_event.set()

    def _format_exception(self, exc):
        """Return a readable traceback string for an exception."""
        if exc is None:
            return "No exception details available."

        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    def _log_worker_error(self, message, exc):
        """Append a worker error and its traceback to a log file.

        The TUI owns stdout/stderr while it runs, so a traceback printed there
        is lost as soon as the program exits. Persisting it to disk lets the
        user report the exact failure.
        """
        try:
            os.makedirs(CRASH_LOG_DIR, exist_ok=True)

            with open(CRASH_LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"\n===== {stamp} | {message} =====\n")
                f.write(self._format_exception(exc))
                f.write("\n")
        except Exception:
            pass

    def _register_async_dump(self):
        """Register the worker loop for thread dumps when debug tracing is on.

        The thread-dump monitor only runs in debug mode, so skip registration
        otherwise; a normal run should not stream periodic task dumps to
        ``.cecli/logs/threads.log``.
        """
        if "cecli.helpers.lock_detect" not in sys.modules or not self._thread_dump_enabled():
            return

        from cecli.helpers import lock_detect

        lock_detect.register_async_loop("worker", self.loop)
        lock_detect.register_async_state_provider("worker", self._format_async_state)

    def _thread_dump_enabled(self):
        """Return True when debug tracing that starts the thread monitor is on."""
        env_override = os.getenv("CECLI_DEBUG_THREAD_LOG", "").lower() in ("1", "true", "yes")
        env_debug = os.getenv("CECLI_DEBUG", "").lower() in ("1", "true", "yes")
        args = getattr(getattr(self, "coder", None), "args", None)

        return bool(env_override or env_debug or getattr(args, "debug", False))

    def _format_async_state(self):
        """Return coder task/flag state for the lock_detect async dump."""
        from cecli.helpers.background_commands import BackgroundCommandManager
        from cecli.helpers.coroutines import is_active

        lines = ["\n------------------- CODER STATE -------------------\n"]
        coder = self.coder

        try:
            io = getattr(coder, "io", None)
            lines.append(f"input_task active: {is_active(getattr(io, 'input_task', None))}\n")
            lines.append(f"output_task active: {is_active(getattr(io, 'output_task', None))}\n")
            interrupt_event = getattr(coder, "interrupt_event", None)
            lines.append(
                f"interrupt_event set: {bool(interrupt_event and interrupt_event.is_set())}\n"
            )
            lines.append(f"input_running: {getattr(coder, 'input_running', None)}\n")
            lines.append(f"output_running: {getattr(coder, 'output_running', None)}\n")

            commands = getattr(coder, "commands", None)
            lines.append(
                f"cmd_running_event set: {bool(commands and commands.cmd_running_event.is_set())}\n"
            )
            lines.append(f"worker running: {self.running}\n")

            background = BackgroundCommandManager.list_background_commands()
            if not background:
                lines.append("  (no background commands)\n")

            for key, info in sorted(background.items()):
                lines.append(
                    f"  - {key}: running={info.get('running')} pages={info.get('pages', 0)}\n"
                )
        except Exception as e:
            lines.append(f"<coder state error: {e}>\n")

        return "".join(lines)
