"""TextualInputOutput - IO adapter for Textual TUI."""

import asyncio
import time

from rich.console import Console

from cecli.helpers import queues
from cecli.helpers.server import signals as server_signals
from cecli.io import InputOutput, get_rel_fname


class TextualInputOutput(InputOutput):
    """InputOutput subclass that communicates with Textual TUI via queues."""

    def __init__(self, output_queue, input_queue, **kwargs):
        """Initialize TextualInputOutput.

        Args:
            output_queue: queue.Queue for sending output to TUI
            input_queue: queue.Queue for receiving input from TUI
            **kwargs: Passed to InputOutput parent class
        """
        # Lazy-initialized console for TUI rendering
        self._tui_console = None

        # Store queues
        self.output_queue = output_queue
        self.input_queue = input_queue

        # Initialize parent (fancy_input should already be False from caller)
        super().__init__(**kwargs)

        # Current task tracking
        self.current_task_id = None

        # LLM response streaming state
        # LLM response streaming state — per-coder tracking
        # Dict keyed by coder_uuid to support simultaneous multi-coder streaming
        self._streaming_response: dict[str, bool] = {}

        # Disable fallback spinner so it doesn't clutter terminal output
        self.fallback_spinner_enabled = False

        # Task detection patterns
        self.task_markers = [
            ("Tool:", "tool"),
            ("Running", "execution"),
            ("Git:", "git"),
            ("Linting", "lint"),
            ("Testing", "test"),
            ("Adding", "file_op"),
            ("Removing", "file_op"),
        ]

        # Tool call buffering for styled panel rendering — per-coder tracking
        # Dicts keyed by coder_uuid to support simultaneous multi-coder streaming
        self._tool_call_buffers: dict[str, list] = {}
        self._in_tool_call: dict[str, bool] = {}
        self._expect_tool_result: dict[str, bool] = {}

    def rule(self):
        pass

    def get_bottom_toolbar(self):
        pass

    def _detect_task_start(self, text):
        """Detect if this output should start a new task.

        Args:
            text: Output text to check

        Returns:
            Tuple of (should_start, title, task_type) or (False, None, None)
        """
        for marker, task_type in self.task_markers:
            if marker in text:
                # Extract title from first line, max 50 chars
                title = text.split("\n")[0][:50]
                return True, title, task_type

        return False, None, None

    def start_task(self, title, task_type="general", **kwargs):
        """Start a new output task.

        Args:
            title: Task title
            task_type: Type of task
            coder_uuid: Optional uuid string to include in the message
        """
        coder_uuid = kwargs.get("coder_uuid", None)
        self.current_task_id = f"task_{time.time()}"
        msg = {
            "type": "start_task",
            "task_id": self.current_task_id,
            "title": title,
            "task_type": task_type,
        }
        if coder_uuid:
            msg["coder_uuid"] = coder_uuid
        self.output_queue.put(msg)
        server_signals.send_start_task(
            self,
            task_id=self.current_task_id,
            title=title,
            task_type=task_type,
            coder_uuid=coder_uuid,
        )

    def _get_tui_console(self):
        """Get or create console for TUI rendering."""
        if self._tui_console is None:
            self._tui_console = Console(
                force_terminal=True,
                color_system="truecolor",
            )
        return self._tui_console

    def stream_print(self, *messages, **kwargs):
        """Override stream_print to send output to TUI queue.

        Args:
            *messages: Messages to print
            **kwargs: Additional arguments for console.print
        """
        # Pop coder_uuid from kwargs before passing to console
        coder_uuid = kwargs.pop("coder_uuid", None)
        kwargs.pop("type", None)

        # Capture Rich rendering with forced ANSI output
        console = self._get_tui_console()
        with console.capture() as capture:
            console.print(*messages, **kwargs)
        text = capture.get()

        # Send to TUI via queue
        msg = {
            "type": "output",
            "text": text,
            "task_id": self.current_task_id,
        }
        if coder_uuid:
            msg["coder_uuid"] = coder_uuid
        self.output_queue.put(msg)
        server_signals.send_tool_output(self, text=text, msg_type="output", coder_uuid=coder_uuid)

    def stream_output(self, text, final=False, **kwargs):
        """Override stream_output to send streaming text to TUI.

        Uses Textual's RichLog for efficient rendering.

        Args:
            text: Text to stream
            final: Whether this is the final chunk
            coder_uuid: Optional uuid string to include in the message
        """
        coder_uuid = kwargs.get("coder_uuid", None)

        # Start response on first chunk
        # Start response on first chunk — per-coder tracking
        if coder_uuid and coder_uuid not in self._streaming_response and text:
            self._streaming_response[coder_uuid] = True
            msg = {"type": "start_response", "coder_uuid": coder_uuid}
            self.output_queue.put(msg)
            server_signals.send_start_response(self, coder_uuid=coder_uuid)

        # Stream the chunk
        if text:
            msg = {
                "type": "stream_chunk",
                "text": text,
            }
            if coder_uuid:
                msg["coder_uuid"] = coder_uuid
            self.output_queue.put(msg)
            server_signals.send_stream_chunk(self, text=text, coder_uuid=coder_uuid)

        # End response on final chunk
        # End response on final chunk — per-coder tracking
        if final and coder_uuid and coder_uuid in self._streaming_response:
            del self._streaming_response[coder_uuid]
            msg = {"type": "end_response", "coder_uuid": coder_uuid}
            self.output_queue.put(msg)
            server_signals.send_end_response(self, coder_uuid=coder_uuid)

    def reset_streaming_response(self, **kwargs):
        """Reset streaming state between responses.

        Args:
            coder_uuid: Optional uuid of the coder to reset.
                         If None, resets all streaming states.
        """
        coder_uuid = kwargs.get("coder_uuid", None)

        if coder_uuid:
            if coder_uuid in self._streaming_response:
                del self._streaming_response[coder_uuid]
                self.output_queue.put(
                    {
                        "type": "end_response",
                        "coder_uuid": coder_uuid,
                    }
                )
                server_signals.send_end_response(self, coder_uuid=coder_uuid)
        else:
            # Reset all remaining streams
            for uuid in list(self._streaming_response.keys()):
                self.output_queue.put(
                    {
                        "type": "end_response",
                        "coder_uuid": uuid,
                    }
                )
                server_signals.send_end_response(self, coder_uuid=uuid)
            self._streaming_response.clear()

    def assistant_output(self, message, pretty=None, **kwargs):
        """Override assistant_output to send LLM response through streaming path.

        This ensures non-streaming mode output gets the same markdown rendering
        treatment as streaming mode.

        Args:
            message: The assistant's response message
            pretty: Whether to use pretty formatting (unused in TUI, kept for compatibility)
            coder_uuid: Optional uuid string to include in the message
        """
        coder_uuid = kwargs.get("coder_uuid", None)

        if not message:
            message = "(empty response)"

        # Use the streaming path so markdown rendering is applied
        start_msg = {"type": "start_response"}
        if coder_uuid:
            start_msg["coder_uuid"] = coder_uuid
        self.output_queue.put(start_msg)
        server_signals.send_start_response(self, coder_uuid=coder_uuid)

        chunk_msg = {"type": "stream_chunk", "text": message}
        if coder_uuid:
            chunk_msg["coder_uuid"] = coder_uuid
        self.output_queue.put(chunk_msg)
        server_signals.send_stream_chunk(self, text=message, coder_uuid=coder_uuid)

        end_msg = {"type": "end_response"}
        if coder_uuid:
            end_msg["coder_uuid"] = coder_uuid
        self.output_queue.put(end_msg)
        server_signals.send_end_response(self, coder_uuid=coder_uuid)

    def tool_output(self, *messages, **kwargs):
        """Override tool_output to detect task boundaries and queue output.

        Args:
            *messages: Messages to output
            **kwargs: Additional arguments
        """
        # Pop coder_uuid from kwargs for routing
        coder_uuid = kwargs.get("coder_uuid", None)

        if messages:
            text = " ".join(str(m) for m in messages)
            msg_type = kwargs.get("type", None)

            if not self._reroute_output(text, msg_type, **kwargs):
                # Check if this should start a new task
                should_start, title, task_type = self._detect_task_start(text)

                if msg_type:
                    should_start = True
                    title = msg_type

                if should_start:
                    self.start_task(title, task_type, coder_uuid=coder_uuid)
            else:
                return

        # Call parent to handle logging and actual output
        super().tool_output(*messages, **kwargs)

    def _reroute_output(self, text, msg_type, **kwargs):
        # Handle tool call buffering for styled panel rendering
        coder_uuid = kwargs.get("coder_uuid", None)
        key = coder_uuid if coder_uuid else "default"

        if msg_type == "Tool Call":
            # Start buffering a new tool call
            self._in_tool_call[key] = True
            self._tool_call_buffers[key] = [text]
            # Log to history
            self.append_chat_history(text, linebreak=True, blockquote=True)
            return True
        elif msg_type == "tool-footer":
            # End of tool call - flush buffer as styled panel
            if self._in_tool_call.get(key, False) and self._tool_call_buffers.get(key):
                msg = {
                    "type": "tool_call",
                    "lines": self._tool_call_buffers[key],
                }
                if coder_uuid:
                    msg["coder_uuid"] = coder_uuid
                self.output_queue.put(msg)
                server_signals.send_tool_call(
                    self, lines=self._tool_call_buffers[key], coder_uuid=coder_uuid
                )
                # Expect a tool result next
                self._expect_tool_result[key] = True
            self._in_tool_call[key] = False
            self._tool_call_buffers[key] = []
            return True
        elif self._in_tool_call.get(key, False):
            # Add to tool call buffer
            if text.strip():
                self._tool_call_buffers[key].append(text)
                # Log to history
                self.append_chat_history(text, linebreak=True, blockquote=True)
            return True

        # Check if this is a tool result (comes right after tool call)
        if self._expect_tool_result.get(key, False) and text.strip():
            if msg_type != "tool-result":
                self._expect_tool_result[key] = False
            msg = {
                "type": "tool_result",
                "text": text,
            }
            if coder_uuid:
                msg["coder_uuid"] = coder_uuid
            self.output_queue.put(msg)
            server_signals.send_tool_result(self, text=text, coder_uuid=coder_uuid)
            # Log to history
            self.append_chat_history(text, linebreak=True, blockquote=True)
            return True

        return False

    def start_spinner(self, text, update_last_text=True, **kwargs):
        """Override start_spinner to send spinner state to TUI.

        Args:
            text: Spinner text
            update_last_text: Whether to update last_spinner_text
            coder_uuid: Optional uuid string to include in the message
        """
        coder_uuid = kwargs.get("coder_uuid", None)
        # Call parent to maintain state
        super().start_spinner(text, update_last_text)

        # Send to TUI
        self.output_queue.put(
            {
                "type": "spinner",
                "action": "start",
                "text": text,
                "coder_uuid": coder_uuid,
            }
        )
        server_signals.send_spinner(self, action="start", text=text, coder_uuid=coder_uuid)

        self.output_queue.put(
            {
                "type": "spinner",
                "coder_uuid": coder_uuid,
                "action": "update_suffix",
                "text": "",
            }
        )
        server_signals.send_spinner(self, action="update_suffix", text="", coder_uuid=coder_uuid)

    def update_spinner(self, text, **kwargs):
        """Override update_spinner to send updates to TUI.

        Args:
            text: New spinner text
            coder_uuid: Optional uuid string to include in the message
        """
        coder_uuid = kwargs.get("coder_uuid", None)
        # Call parent
        super().update_spinner(text)

        # Send to TUI
        self.output_queue.put(
            {
                "type": "spinner",
                "action": "update",
                "text": text,
                "coder_uuid": coder_uuid,
            }
        )
        server_signals.send_spinner(self, action="update", text=text, coder_uuid=coder_uuid)

    def update_spinner_suffix(self, text=None, **kwargs):
        """Override update_spinner_suffix to send updates to TUI.

        Args:
            text: New spinner suffix text
            coder_uuid: Optional uuid string to include in the message
        """
        coder_uuid = kwargs.get("coder_uuid", None)
        # Call parent
        super().update_spinner_suffix(text)

        # Send to TUI
        self.output_queue.put(
            {
                "type": "spinner",
                "action": "update_suffix",
                "text": text,
                "coder_uuid": coder_uuid,
            }
        )
        server_signals.send_spinner(self, action="update_suffix", text=text, coder_uuid=coder_uuid)

    def stop_spinner(self, **kwargs):
        """Override stop_spinner to send stop state to TUI."""
        coder_uuid = kwargs.get("coder_uuid", None)
        # Call parent
        super().stop_spinner()

        # Send to TUI
        self.output_queue.put({"type": "spinner", "action": "stop", "coder_uuid": coder_uuid})
        server_signals.send_spinner(self, action="stop", text="", coder_uuid=coder_uuid)

    def interrupt_input(self):
        self.interrupted = True

    async def get_input(
        self,
        root,
        rel_fnames,
        addable_rel_fnames,
        commands,
        abs_read_only_fnames=None,
        abs_read_only_stubs_fnames=None,
        edit_format=None,
    ):
        """Override get_input to get input from TUI instead of prompt_toolkit.

        Args:
            root: Project root directory
            rel_fnames: Relative filenames in chat
            addable_rel_fnames: Files that can be added
            commands: Commands object
            abs_read_only_fnames: Read-only files
            abs_read_only_stubs_fnames: Stub files
            edit_format: Edit format string

        Returns:
            tuple[str, str | None]: (user_input, coder_uuid) tuple.
            The IOProxy wrapper uses coder_uuid for routing.
        """
        self.interrupted = False

        if commands.last_command_show_notification:
            self.notify_user_input_required()

        # Signal TUI that we're ready for input
        command_names = commands.get_commands() if commands else []

        # Process read-only files
        rel_read_only_fnames = []
        if abs_read_only_fnames:
            rel_read_only_fnames = [get_rel_fname(f, root) for f in abs_read_only_fnames]

        rel_read_only_stubs_fnames = []
        if abs_read_only_stubs_fnames:
            rel_read_only_stubs_fnames = [
                get_rel_fname(f, root) for f in abs_read_only_stubs_fnames
            ]

        self.output_queue.put(
            {
                "type": "ready_for_input",
                "files": list(addable_rel_fnames) if addable_rel_fnames else [],
                "commands": command_names,
                "chat_files": {
                    "rel_fnames": list(rel_fnames),
                    "rel_read_only_fnames": rel_read_only_fnames,
                    "rel_read_only_stubs_fnames": rel_read_only_stubs_fnames,
                },
            }
        )

        # Wait for input from TUI. The per-coder and shared queues are
        # thread-safe payloads; wait_for_input() blocks natively until a push
        # wakes us, so no polling is required.
        while True:
            if hasattr(self, "file_watcher") and self.file_watcher:
                if not self.file_watcher.is_running:
                    self.file_watcher.start()

                # Check if we were interrupted by a file change
                if self.interrupted:
                    cmd = self.file_watcher.process_changes()
                    return cmd

            import queue

            # Check all per-coder queues first (non-blocking)
            for _uuid, _q in list(queues._per_coder_queues.items()):
                try:
                    result = _q.get_nowait()
                except queue.Empty:
                    continue

                if "text" in result:
                    user_input = result["text"]
                    target_uuid = result.get("coder_uuid", _uuid)
                    self.user_input(user_input)
                    return user_input, target_uuid

            # Fall back to shared queue (non-blocking)
            try:
                result = self.input_queue.get_nowait()
            except queue.Empty:
                result = None

            if result is not None and "text" in result:
                user_input = result["text"]
                target_uuid = result.get("coder_uuid")

                # Log the input (same as parent)
                self.user_input(user_input)

                return user_input, target_uuid

            # Nothing available yet — block until the next push
            await queues.wait_for_input()

    async def confirm_ask(
        self,
        question,
        default="y",
        subject=None,
        explicit_yes_required=False,
        group=None,
        group_response=None,
        allow_never=False,
        allow_tweak=False,
        acknowledge=False,
        coder_uuid=None,
    ):
        """Override confirm_ask to show modal instead of inline prompt.

        Args:
            question: Question to ask
            default: Default response
            subject: Optional subject/context
            explicit_yes_required: Require explicit yes
            group: Confirmation group
            group_response: Group response key
            allow_never: Allow "don't ask again"
            allow_tweak: Allow "tweak" option
            acknowledge: Require acknowledgement

        Returns:
            User's response (True, False, "tweak", etc.)
        """
        self.num_user_asks += 1

        question_id = (question, subject)

        try:
            if question_id in self.never_prompts:
                return False

            if group and not group.show_group:
                group = None
            if group:
                allow_never = True

            valid_responses = ["yes", "no", "skip", "all"]

            if allow_tweak:
                valid_responses.append("tweak")
            if allow_never:
                valid_responses.append("don't")

            if default.lower().startswith("y"):
                question += " [Yes]: "
            elif default.lower().startswith("n"):
                question += " [No]: "
            else:
                question += f" [{default}]: "

            # Handle self.yes parameter (auto-yes for non-explicit confirmations)
            if self.yes is True and not explicit_yes_required:
                res = "y"
                # Log the auto-response
                hist = f"{question.strip()} {res}"
                self.append_chat_history(hist, linebreak=True, blockquote=True)
                return True
            elif group_response and group_response in self.group_responses:
                return self.group_responses[group_response]
            elif group and group.preference:
                res = group.preference
                self.user_input(f"{question} - {res}", log_only=False)
            else:
                # Ring the bell to notify user
                self.notify_user_input_required()

                # Send confirmation request to TUI with full options
                self.output_queue.put(
                    {
                        "type": "confirmation",
                        "question": question,
                        "subject": subject,
                        "options": {
                            "default": default,
                            "explicit_yes_required": explicit_yes_required,
                            "group": group,
                            "group_response": group_response,
                            "allow_never": allow_never,
                            "allow_tweak": allow_tweak,
                            "acknowledge": acknowledge,
                            "valid_responses": valid_responses,
                        },
                        "coder_uuid": coder_uuid,
                    }
                )

            # Wait for response from TUI. Sweep the per-coder queues
            # (non-blocking), then block natively until the next push.
            while True:
                import queue

                for _uuid, _q in list(queues._per_coder_queues.items()):
                    try:
                        result = _q.get_nowait()
                    except queue.Empty:
                        continue

                    if "confirmed" in result:
                        response = result["confirmed"]

                        # Handle special responses
                        if response == "never":
                            self.never_prompts.add(question_id)
                            return False
                        elif response == "tweak":
                            return "tweak"
                        elif response == "all":
                            if group:
                                group.preference = "all"
                            if group_response:
                                self.group_responses[group_response] = True
                            return True
                        elif response == "skip":
                            if group:
                                group.preference = "skip"
                            if group_response:
                                self.group_responses[group_response] = False
                            return False
                        else:
                            return bool(response)

                await queues.wait_for_input()
        except asyncio.CancelledError:
            return False

    async def stop_task_streams(self):
        """Override to avoid asyncio issues in worker thread.

        TUI doesn't use the same parallel streaming, so this is a no-op.
        """
        pass

    async def stop_input_task(self):
        """Override to avoid asyncio issues in worker thread."""
        pass

    async def stop_output_task(self):
        """Override to avoid asyncio issues in worker thread."""
        pass

    def request_exit(self):
        """Request the TUI to exit gracefully.

        This sends an exit signal to the TUI instead of calling sys.exit()
        directly, allowing Textual to properly restore terminal state.
        """
        self.output_queue.put({"type": "exit"})
