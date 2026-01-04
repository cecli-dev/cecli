"""Worker thread for running Coder in background."""

import asyncio
import logging
import threading
import warnings
from typing import Optional

from cecli.coders import Coder
from cecli.commands import SwitchCoderSignal

# Suppress asyncio task destroyed warnings during shutdown
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# Also suppress via warnings module
warnings.filterwarnings("ignore", message=".*Task was destroyed.*")
warnings.filterwarnings("ignore", message=".*coroutine.*was never awaited.*")


class CoderWorker:
    """Runs Coder in a background thread with its own event loop."""

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
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._async_run())
        except asyncio.CancelledError:
            pass
        except RuntimeError:
            # Event loop stopped - this is expected during shutdown
            pass
        finally:
            self._cleanup_loop()

    def _cleanup_loop(self):
        """Clean up the event loop safely."""
        if not self.loop:
            return

        try:
            # Cancel pending tasks if loop is still running
            if not self.loop.is_closed():
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()

                # Only try to gather if loop isn't stopped
                if self.loop.is_running():
                    pass  # Can't do much if loop is still running
                elif pending:
                    try:
                        self.loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    except RuntimeError:
                        pass  # Loop already stopped

                self.loop.close()
        except Exception:
            pass  # Ignore cleanup errors

    async def _async_run(self):
        """Async entry point - runs coder loop."""
        while self.running:
            try:
                await self.coder.run()
                break  # Normal exit
            except asyncio.CancelledError:
                break
            except SwitchCoderSignal as switch:
                # Handle chat mode switches (e.g., /chat-mode architect)
                try:
                    kwargs = dict(io=self.coder.io, from_coder=self.coder)
                    kwargs.update(switch.kwargs)
                    if "show_announcements" in kwargs:
                        del kwargs["show_announcements"]
                    kwargs["num_cache_warming_pings"] = 0
                    kwargs["args"] = self.coder.args
                    # Skip summarization to avoid blocking LLM calls during mode switch
                    kwargs["summarize_from_coder"] = False

                    new_coder = await Coder.create(**kwargs)
                    new_coder.args = self.coder.args

                    if switch.kwargs.get("show_announcements") is False:
                        new_coder.suppress_announcements_for_next_prompt = True

                    # Notify TUI of mode change
                    self.coder = new_coder
                    edit_format = getattr(self.coder, "edit_format", "code") or "code"
                    self.output_queue.put(
                        {
                            "type": "mode_change",
                            "mode": edit_format,
                        }
                    )
                except Exception as e:
                    self.output_queue.put(
                        {"type": "error", "message": f"Failed to switch mode: {e}"}
                    )
                    break
                # Continue the loop with the new coder
            except Exception as e:
                self.output_queue.put({"type": "error", "message": str(e)})
                break

    def interrupt(self):
        """Cancel the current output task on the coder instance."""
        if self.coder and hasattr(self.coder, "io") and self.coder.io:
            # Cancel the output task if it exists
            if hasattr(self.coder.io, "output_task") and self.coder.io.output_task:
                self.coder.io.output_task.cancel()
                # Also set output_running to False to stop the output_task loop
                if hasattr(self.coder, "output_running"):
                    self.coder.output_running = False

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

        # Wait for thread to finish
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
