# Import necessary functions
import fnmatch
import os
import platform

# PTY support for interactive commands (avoids pipe buffering issues)
try:
    import pty
    import termios

    HAS_PTY = True
except ImportError:
    HAS_PTY = False

import xxhash

from cecli.helpers.background_commands import BackgroundCommandManager
from cecli.run_cmd import run_cmd, run_cmd_subprocess
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "command"
    TRACK_INVOCATIONS = False
    ALLOWED_SESSION_COMMANDS = {}
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Command",
            "description": "Execute a shell command or interact with background processes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "The shell command to execute. "
                            "Required unless background_key is provided."
                        ),
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Run command in background (non-blocking).",
                        "default": False,
                    },
                    "background_key": {
                        "type": "string",
                        "description": (
                            "Key of an existing background command to interact with. "
                            "Use with 'action' (stdin/stop)."
                        ),
                    },
                    "action": {
                        "type": "string",
                        "enum": ["stdin", "stop"],
                        "description": (
                            "Action on a background command. Requires background_key: "
                            "'stdin' to send input, 'stop' to terminate."
                        ),
                    },
                    "stdin": {
                        "type": "string",
                        "description": (
                            "Input to send. Use with background=True to send at "
                            "start time, or with background_key + action='stdin'."
                        ),
                    },
                    "pty": {
                        "type": "boolean",
                        "description": (
                            "Use a pseudo-terminal (PTY). Auto-enabled on Unix for "
                            "background commands. Useful for interactive programs "
                            "like 'vi' or 'top'."
                        ),
                        "default": False,
                    },
                    "user_input_required": {
                        "type": "boolean",
                        "description": (
                            "When True, runs the command interactively using a "
                            "pseudo-terminal (PTY), allowing the user to provide "
                            "inputs like passwords or navigate terminal interfaces. "
                        ),
                        "default": False,
                    },
                    "timeout": {
                        "type": "integer",
                        "description": (
                            "Timeout in seconds for command execution. "
                            "Default is 30 seconds. Maximum 300 seconds. "
                            "If the command exceeds this time, it will continue in the background."
                        ),
                        "default": 30,
                    },
                },
                "required": [],
            },
        },
    }

    @staticmethod
    @staticmethod
    def _hash_command(command):
        """Compute an xxhash of the full command text for session tracking."""
        if not command:
            return command

        return xxhash.xxh64(command.encode("utf-8")).hexdigest()

    @classmethod
    async def execute(
        cls,
        coder,
        command=None,
        background=False,
        background_key=None,
        action=None,
        stdin=None,
        pty=False,
        user_input_required=False,
        timeout=0,
        **kwargs,
    ):
        """
        Execute a shell command or interact with background processes.

        For new commands: provide 'command' (and optionally 'background', 'stdin', 'pty').
        When 'user_input_required' is True, runs the command interactively using a
        pseudo-terminal (PTY), allowing the user to provide inputs like passwords
        or navigate terminal interfaces.
        For background interactions: provide 'background_key' + 'action' (stdin/stop).

        Commands run with timeout from agent_config['command_timeout'] (default: 30 seconds),
        """
        response = ToolResponse(
            "command",
            result_type=cls.RESULT_TYPE if hasattr(cls, "RESULT_TYPE") else "str",
        )
        # Handle interactions with an existing background command
        if background_key:
            if action == "stdin":
                if not stdin:
                    response.append_error("'stdin' is required when action='stdin'.")
                    return response
                cls.clear_invocation_cache()
                success = BackgroundCommandManager.send_command_input(background_key, stdin)
                if success:
                    response.append_result(
                        f"Sent input to background command {background_key}: {stdin}"
                    )
                    return response
                else:
                    response.append_error(
                        f"Background command {background_key} not found or not running."
                    )
                    return response

            elif action == "stop":
                return await cls._stop_background_command(coder, background_key)

            else:
                response.append_error(f"Unknown action '{action}'. Use one of: stdin, stop.")
                return response

        if not command:
            response.append_error("'command' must be provided.")
            return response

        # Check for implicit background (trailing & on Linux)
        if ".cecli/agents" in command:
            response.append_error(
                "Do not attempt to access internal files with "
                "standard cli tools. Please use the tools you have been provided."
            )
            return response

        if not background and command.strip().endswith("&"):
            background = True
            command = command.strip()[:-1].strip()

        # Get user confirmation
        confirmed = await cls._get_confirmation(coder, command, background)
        if not confirmed:
            response.append_result("Command execution skipped by user.")
            return response

        command = coder.format_command_with_prefix(command)

        # Determine timeout from agent_config (default: 30 seconds) as fallback
        config_timeout = 0
        if hasattr(coder, "agent_config"):
            config_timeout = coder.agent_config.get("command_timeout", 30)
        # Use LLM-specified timeout if provided, otherwise fallback to config
        if timeout == 0:
            timeout = config_timeout
        # Clamp LLM timeout between config_timeout (minimum) and max(300, config_timeout) (maximum)
        timeout = max(config_timeout, min(timeout, max(300, config_timeout)))

        if user_input_required:
            return await cls._execute_interactive(coder, command)
        elif background:
            return await cls._execute_background(coder, command, use_pty=pty, stdin=stdin)
        elif timeout > 0:
            return await cls._execute_with_timeout(coder, command, timeout, use_pty=pty)
        else:
            return await cls._execute_foreground(coder, command)

    @classmethod
    async def _get_confirmation(cls, coder, command_string, background):
        """Get user confirmation for command execution.

        NOTE: This does NOT print the command itself. The caller (format_output
        via _print_tool_call_info) is responsible for displaying the command
        before this runs. Do not print the command here or it will appear twice.
        """
        # Hash command for dict key lookup
        command_hash = cls._hash_command(command_string)

        # Check if command is already handled for this session
        if command_hash in cls.ALLOWED_SESSION_COMMANDS:
            if cls.ALLOWED_SESSION_COMMANDS[command_hash]:
                return True  # Previously approved for session
            # Previously declined - skip session question, continue to normal confirmation

        if coder.skip_cli_confirmations or getattr(coder.args, "yes_always_commands", False):
            return True

        # Check if command matches any allowed_commands patterns
        if hasattr(coder, "agent_config"):
            allowed_commands = coder.agent_config.get("allowed_commands", [])
            if allowed_commands:
                for pattern in allowed_commands:
                    if fnmatch.fnmatch(command_string, pattern):
                        return True

        if background:
            prompt = "Allow execution of this background command?"
        else:
            prompt = "Allow execution of this command?"

        confirmed = await coder.io.confirm_ask(
            prompt,
            explicit_yes_required=True,
            allow_never=True,
            group_response="Command Tool",
        )

        if confirmed:
            # Ask if user wants to allow for the entire session (only once per command)
            if command_hash not in cls.ALLOWED_SESSION_COMMANDS:
                session_allowed = await coder.io.confirm_ask(
                    "Allow this command for the rest of the session?",
                )
                cls.ALLOWED_SESSION_COMMANDS[command_hash] = session_allowed

        return confirmed

    @classmethod
    async def _execute_background(cls, coder, command_string, use_pty=None, stdin=None):
        """
        Execute command in background.

        Args:
            stdin: Optional text to send to the command's stdin after starting
        """
        coder.io.tool_output(f"⛭ Starting background command: {command_string}", type="tool-result")

        # Default to PTY on Unix platforms for proper line-buffered output
        # (Python and other programs buffer output aggressively on pipes)
        if use_pty is None:
            use_pty = platform.system() != "Windows"

        # Use static manager to start background command
        command_key = BackgroundCommandManager.start_background_command(
            command_string,
            verbose=coder.verbose,
            cwd=coder.root,
            max_buffer_size=4096,
            use_pty=use_pty,
        )

        # Send stdin to the background command if provided
        if stdin:
            BackgroundCommandManager.send_command_input(command_key, stdin)

        response = ToolResponse(cls.NORM_NAME)
        response.append_result(
            f"Background command started: {command_string}\n"
            f"Command key: {command_key}\n"
            "Output will be injected into chat stream."
        )
        return response

    @classmethod
    async def _execute_with_timeout(cls, coder, command_string, timeout, use_pty=None):
        """
        Execute command with timeout. If timeout elapses, move to background.

        When use_pty is True (or auto-defaulted on Unix), a pseudo-terminal
        is used to avoid the full-buffering issue that occurs when stdout is
        connected to a pipe instead of a TTY.
        """
        import asyncio
        import subprocess

        from cecli.helpers.background_commands import CircularBuffer

        response = ToolResponse(cls.NORM_NAME)

        coder.io.tool_output(
            f"⛭ Executing shell command with {timeout}s timeout.", type="tool-result"
        )

        # Auto-default to PTY on Unix unless explicitly set otherwise
        if use_pty is None:
            use_pty = platform.system() != "Windows"

        # Create output buffer
        buffer = CircularBuffer(max_size=4096)

        # Decide whether to use PTY
        master_fd = None

        if use_pty and HAS_PTY and platform.system() != "Windows":
            master_fd, slave_fd = pty.openpty()

            # Disable echo on the slave PTY
            attr = termios.tcgetattr(slave_fd)
            attr[3] = attr[3] & ~termios.ECHO
            termios.tcsetattr(slave_fd, termios.TCSANOW, attr)

            process = subprocess.Popen(
                command_string,
                shell=True,
                executable=os.environ.get("SHELL", "/bin/sh"),
                stdout=slave_fd,
                stderr=slave_fd,
                stdin=slave_fd,
                cwd=coder.root,
                close_fds=True,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            os.close(slave_fd)
        else:
            # Start process with pipes for output capture
            # When PTY was requested but unavailable, wrap with stdbuf for line-buffered output
            resolved_cmd = (
                BackgroundCommandManager._wrap_line_buffered(command_string)
                if use_pty and not HAS_PTY
                else command_string
            )
            shell = os.environ.get("SHELL", "/bin/sh")
            process = subprocess.Popen(
                resolved_cmd,
                shell=True,
                executable=shell if platform.system() != "Windows" else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                cwd=coder.root,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

        # Immediately register with background manager to handle pipe reading
        command_key = BackgroundCommandManager.start_background_command(
            command_string,
            verbose=coder.verbose,
            cwd=coder.root,
            max_buffer_size=4096,
            existing_process=process,
            existing_buffer=buffer,
            persist=True,
            master_fd=master_fd,
        )

        # Now monitor the process with an event-driven race instead of
        # polling: wait for process completion, user interrupt, or timeout.
        # Popen.wait() is cross-platform (waitpid on POSIX, WaitForSingleObject
        # on Windows) and runs in a worker thread via asyncio.to_thread, so it
        # blocks without consuming CPU.
        interrupt_task = asyncio.create_task(coder.interrupt_event.wait())
        wait_task = asyncio.create_task(asyncio.to_thread(process.wait))
        timeout_task = asyncio.create_task(asyncio.sleep(timeout))

        try:
            done, _ = await asyncio.wait(
                {interrupt_task, wait_task, timeout_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if interrupt_task in done:
                # User interrupted: terminate the process (Windows uses
                # TerminateProcess — a hard kill; POSIX sends SIGTERM). Same
                # semantics as the previous polling loop.
                try:
                    process.terminate()
                except ProcessLookupError:
                    # Process already exited
                    pass

                try:
                    # wait_task is already reaping the process; wait briefly
                    # for it to complete instead of starting a second wait.
                    await asyncio.wait_for(asyncio.shield(wait_task), timeout=1)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        # Process already exited and was reaped by wait_task
                        pass

                    try:
                        await wait_task
                    except Exception:
                        pass
                except Exception:
                    pass

                BackgroundCommandManager.stop_background_command(command_key)
                response.append_result("Command execution interrupted by user.")
                return response

            if wait_task in done:
                # Process completed
                exit_code = wait_task.result()
                output = buffer.get_all(clear=True)

                # Format output
                output_content = output or ""
                # Tokens are roughly 3-4 characters
                output_limit = int(coder.large_file_token_threshold * 3.5)

                if coder.context_management_enabled and len(output_content) > output_limit * 1.25:
                    # Save full output to paginated files instead of truncating
                    folder_path, file_list, alias_paths = (
                        BackgroundCommandManager.save_paginated_output(
                            output=output_content,
                            command_key=command_key,
                            page_size=output_limit,
                            abs_root_path_func=coder.abs_root_path,
                            local_agent_folder_func=coder.local_agent_folder,
                        )
                    )
                    # Build a summary with full file list
                    total_size = len(output_content)
                    alias_list_str = "\n".join(f"  - {a}" for a in alias_paths)
                    output_content = (
                        f"[Large Response ({total_size} characters). "
                        "Output saved to paginated files.]\n"
                        f"File Aliases (for use with ResourceManager):\n{alias_list_str}\n"
                        "Use the `ResourceManager` tool to view these files."
                        "Do not use standard cli tools to view these files."
                        "Remove them from context after taking notes on the relevant information "
                        "to prevent overfilling stale context."
                    )

                # Remove from background tracking since it's done
                BackgroundCommandManager.stop_background_command(command_key)

                # Output to TUI console if TUI exists (same logic as _execute_foreground)
                if coder.tui and coder.tui():
                    coder.io.tool_output(output_content, type="tool-result")

                if exit_code == 0:
                    response.append_result(
                        f"Shell command completed within {timeout}s timeout (exit code 0)."
                        f" Output:\n{output_content}"
                    )
                    return response
                else:
                    response.append_result(
                        f"Shell command completed within {timeout}s timeout with exit code"
                        f" {exit_code}. Output:\n{output_content}"
                    )
                    return response

            # Timeout elapsed, process continues in background
            coder.io.tool_output(
                f"\u23f1\ufe0f Command exceeded {timeout}s timeout, continuing in background...",
                type="tool-result",
            )

            # Get any output captured so far
            current_output = buffer.get_all(clear=False)

            response.append_result(
                f"Command exceeded {timeout}s timeout and is continuing in background.\n"
                f"Command key: {command_key}\n"
                f"Output captured so far:\n{current_output}\n"
            )
            return response
        finally:
            interrupt_task.cancel()
            timeout_task.cancel()

            if wait_task.done() and not wait_task.cancelled():
                # Retrieve any exception to avoid "task exception was never
                # retrieved" warnings. On timeout the process continues in the
                # background, so wait_task may legitimately still be pending.
                wait_task.exception()

    @classmethod
    async def _execute_foreground(cls, coder, command_string):
        """
        Execute command in foreground (blocking).
        """
        response = ToolResponse(cls.NORM_NAME)
        should_print = True
        tui = None
        if coder.tui and coder.tui():
            tui = coder.tui()
            should_print = False

        coder.io.tool_output("⛭ Executing shell command.", type="tool-result")

        # Use run_cmd_subprocess for non-interactive execution
        exit_status, combined_output = run_cmd_subprocess(
            command_string,
            verbose=coder.verbose,
            cwd=coder.root,
            should_print=should_print,
        )

        # Format the output for the result message
        output_content = combined_output or ""
        output_limit = coder.large_file_token_threshold
        if coder.context_management_enabled and len(output_content) > output_limit * 1.25:
            # Generate a unique key for file naming
            fg_key = BackgroundCommandManager._generate_command_key(command_string)
            # Save full output to paginated files instead of truncating
            folder_path, file_list, alias_paths = BackgroundCommandManager.save_paginated_output(
                output=output_content,
                command_key=fg_key,
                page_size=output_limit,
                abs_root_path_func=coder.abs_root_path,
                local_agent_folder_func=coder.local_agent_folder,
            )
            # Build a summary with full file list
            total_size = len(output_content)
            alias_list_str = "\n".join(f"  - {a}" for a in alias_paths)
            output_content = (
                f"[Large Response ({total_size} characters). "
                "Output saved to paginated files.]\n"
                f"File Aliases (for use with ResourceManager):\n{alias_list_str}\n"
                "Use the `ResourceManager` tool to view these files."
                "Do not use standard cli tools to view these files."
                "Remove them from context after taking note of the relevant information "
                "in the output to prevent overfilling stale context."
            )

        if tui:
            coder.io.tool_output(output_content, type="tool-result")

        if exit_status == 0:
            response.append_result(
                f"Shell command executed successfully (exit code 0). Output:\n{output_content}"
            )
            return response
        else:
            response.append_result(
                f"Shell command failed with exit code {exit_status}. Output:\n{output_content}"
            )
            return response

    @classmethod
    async def _execute_interactive(cls, coder, command_string):
        """
        Execute command interactively, allowing the user to provide inputs
        like passwords or navigate terminal interfaces.
        Handles TUI suspension automatically.
        """
        import asyncio

        response = ToolResponse(cls.NORM_NAME)

        coder.io.tool_output(
            f"\u26ed Starting interactive shell command: {command_string}", type="tool-result"
        )

        tui = coder.tui() if coder.tui else None

        def _run_interactive():
            return run_cmd(
                command_string,
                verbose=coder.verbose,
                error_print=coder.io.tool_error,
                cwd=coder.root,
                should_print=True,
            )

        if tui:
            coder.io.tool_output(
                ">>> Suspending TUI for interactive command <<<", type="tool-result"
            )
            exit_status, combined_output = tui.run_obstructive(_run_interactive)
        else:
            coder.io.tool_output(
                ">>> You may need to interact with the command below <<<", type="tool-result"
            )
            coder.io.tool_output(" \n")
            await coder.io.stop_input_task()
            await asyncio.sleep(1)
            exit_status, combined_output = _run_interactive()
            await asyncio.sleep(1)
            coder.io.tool_output(" \n", type="tool-result")
            coder.io.tool_output(" \n", type="tool-result")

        coder.io.tool_output(">>> Interactive command finished <<<", type="tool-result")

        # Format the output for the result message, include more content
        output_content = combined_output or ""
        output_limit = coder.large_file_token_threshold
        if coder.context_management_enabled and len(output_content) > output_limit:
            output_content = (
                output_content[:output_limit]
                + f"\n... (output truncated at {output_limit} characters, based on"
                " large_file_token_threshold)"
            )

        cls.clear_invocation_cache()

        if exit_status == 0:
            response.append_result(
                "Interactive command finished successfully (exit code 0)."
                f" Output:\n{output_content}"
            )
            return response
        else:
            response.append_result(
                f"Interactive command finished with exit code {exit_status}."
                f" Output:\n{output_content}"
            )
            return response

    @classmethod
    async def _stop_background_command(cls, coder, command_key):
        """
        Stop a running background command.
        """
        success, output, exit_code = BackgroundCommandManager.stop_background_command(command_key)

        if success:
            response = ToolResponse(cls.NORM_NAME)
            response.append_result(
                f"Background command stopped: {command_key}\n"
                f"Exit code: {exit_code}\n"
                f"Final output:\n{output}"
            )
            return response
        else:
            response = ToolResponse(cls.NORM_NAME)
            response.append_result(output)
            return response

    @classmethod
    async def _handle_errors(cls, coder, command_string, e):
        """Handle errors during command execution."""
        coder.io.tool_error(f"Error executing shell command: {str(e)}")
        response = ToolResponse(cls.NORM_NAME)
        response.append_error(f"Error executing command: {str(e)}")
        return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for Command tool."""
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

        command = params.get("command", "")
        background = params.get("background", False)
        background_key = params.get("background_key")
        action = params.get("action")
        stdin = params.get("stdin")
        pty = params.get("pty", False)
        timeout = params.get("timeout", 30)
        user_input_required = params.get("user_input_required", False)

        coder.io.tool_output("")

        coder.io.tool_output("")

        # Show additional parameters if they are not default
        extras = []
        if background:
            extras.append("background=True")
        if action:
            extras.append(f"action={action}")
        if pty:
            extras.append("pty=True")
        if timeout != 30:
            extras.append(f"timeout={timeout}s")
        if user_input_required:
            extras.append("user_input_required=True")

        if extras:
            coder.io.tool_output(f"{color_start}Options:{color_end} {', '.join(extras)}")

        if stdin:
            coder.io.tool_output(f"{color_start}Stdin:{color_end}")
            coder.io.tool_output(stdin)

        if background_key and action:
            coder.io.tool_output(f"{color_start}Background Key:{color_end} {background_key}")
            coder.io.tool_output(f"{color_start}Action:{color_end} {action}")
        elif command:
            coder.io.tool_output(f"{color_start}Command:{color_end}")
            coder.io.tool_output(coder.format_command_with_prefix(command))
        else:
            # No command and no background_key/action pair: this call will
            # be rejected by execute() before it ever reaches confirmation.
            # Say so explicitly instead of leaving the panel looking blank,
            # which is otherwise indistinguishable from a display bug.
            coder.io.tool_output(
                f"{color_start}(no command provided — call will be rejected){color_end}"
            )

        coder.io.tool_output("")

        # Output footer
        tool_footer(coder=coder, tool_response=tool_response, params=params)
