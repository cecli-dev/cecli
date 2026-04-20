# Import necessary functions
import json
import os
import platform

from cecli.helpers.background_commands import BackgroundCommandManager
from cecli.run_cmd import run_cmd_subprocess
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.output import color_markers, tool_footer, tool_header


class Tool(BaseTool):
    NORM_NAME = "command"
    TRACK_INVOCATIONS = False
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Command",
            "description": "Execute a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "The shell command to execute. To send stdin to an existing background"
                            " command, use the format 'command_key::{key}'."
                        ),
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Run command in background (non-blocking).",
                        "default": False,
                    },
                    "stop": {
                        "type": "boolean",
                        "description": (
                            "If true, stop the background command specified in the 'command'"
                            " parameter (format 'command_key::{key}')."
                        ),
                        "default": False,
                    },
                    "pty": {
                        "type": "boolean",
                        "description": (
                            "Run the command in a pseudo-terminal (PTY). Useful for interactive"
                            " programs like 'vi' or 'top'."
                        ),
                        "default": False,
                    },
                    "stdin": {
                        "type": "string",
                        "description": (
                            "Input to send to the command's stdin. Supports escape sequences like"
                            " \\n, \\r, \\t, and hex escapes like \\x1b."
                        ),
                    },
                },
                "required": ["command"],
            },
        },
    }

    @staticmethod
    def _parse_command_key(command):
        """Extract command key from command string if it follows the pattern."""
        if command and command.startswith("command_key::"):
            return command.split("::", 1)[1].strip()
        return None

    @classmethod
    async def execute(
        cls, coder, command, background=False, stop=None, stdin=None, pty=False, **kwargs
    ):
        """
        Execute a shell command, optionally in background.
        Commands run with timeout based on agent_config['command_timeout'] (default: 30 seconds).
        """
        command_key = cls._parse_command_key(command)

        # Handle stopping background commands
        if stop:
            if not command_key:
                return (
                    "Error: 'command' in format 'command_key::{key}' is required when 'stop' is"
                    " true."
                )
            return await cls._stop_background_command(coder, command_key)

        # Handle sending stdin to an existing background command
        if stdin:
            if not command_key:
                return (
                    "Error: 'command' in format 'command_key::{key}' is required when using"
                    " 'stdin'."
                )

            cls.clear_invocation_cache()

            success = BackgroundCommandManager.send_command_input(command_key, stdin)
            if success:
                return f"Sent input to background command {command_key}: {stdin}"
            else:
                return f"Error: Background command {command_key} not found or not running."

        if not command:
            return "Error: 'command' must be provided."

        # Check for implicit background (trailing & on Linux)
        if not background and command.strip().endswith("&"):
            background = True
            command = command.strip()[:-1].strip()

        # Get user confirmation
        confirmed = await cls._get_confirmation(coder, command, background)
        if not confirmed:
            return "Command execution skipped by user."

        # Determine timeout from agent_config (default: 30 seconds)
        timeout = 0
        if hasattr(coder, "agent_config"):
            timeout = coder.agent_config.get("command_timeout", 30)

        if background:
            return await cls._execute_background(coder, command, use_pty=pty)
        elif timeout > 0:
            return await cls._execute_with_timeout(coder, command, timeout, use_pty=pty)
        else:
            return await cls._execute_foreground(coder, command)

    @classmethod
    async def _get_confirmation(cls, coder, command_string, background):
        """Get user confirmation for command execution."""
        if coder.skip_cli_confirmations:
            return True

        command_string = coder.format_command_with_prefix(command_string)

        if background:
            prompt = "Allow execution of this background command?"
        else:
            prompt = "Allow execution of this command?"

        return await coder.io.confirm_ask(
            prompt,
            subject=command_string,
            explicit_yes_required=True,
            allow_never=True,
            group_response="Command Tool",
        )

    @classmethod
    async def _execute_background(cls, coder, command_string, use_pty=False):
        """
        Execute command in background.
        """
        coder.io.tool_output(f"⚙️ Starting background command: {command_string}")

        # Use static manager to start background command
        command_key = BackgroundCommandManager.start_background_command(
            command_string,
            verbose=coder.verbose,
            cwd=coder.root,
            max_buffer_size=4096,
            use_pty=use_pty,
        )

        return (
            f"Background command started: {command_string}\n"
            f"Command key: {command_key}\n"
            "Output will be injected into chat stream."
        )

    @classmethod
    async def _execute_with_timeout(cls, coder, command_string, timeout, use_pty=False):
        """
        Execute command with timeout. If timeout elapses, move to background.

        IMPORTANT: We use a different approach to avoid pipe conflicts.
        Instead of reading pipes directly, we let BackgroundCommandManager
        handle all pipe reading from the start.
        """
        import asyncio
        import subprocess
        import time

        from cecli.helpers.background_commands import CircularBuffer

        coder.io.tool_output(f"⚙️ Executing shell command with {timeout}s timeout.")

        shell = os.environ.get("SHELL", "/bin/sh")

        # Create output buffer
        buffer = CircularBuffer(max_size=4096)

        # Start process with pipes for output capture
        process = subprocess.Popen(
            command_string,
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
        )

        # Now monitor the process with timeout
        start_time = time.time()

        while True:
            # Check if process has completed
            exit_code = process.poll()
            if exit_code is not None:
                # Process completed
                output = buffer.get_all(clear=True)

                # Format output
                output_content = output or ""
                output_limit = coder.large_file_token_threshold
                if coder.context_management_enabled and len(output_content) > output_limit:
                    output_content = (
                        output_content[:output_limit]
                        + f"\n... (output truncated at {output_limit} characters, based on"
                        " large_file_token_threshold)"
                    )

                # Remove from background tracking since it's done
                BackgroundCommandManager.stop_background_command(command_key)

                # Output to TUI console if TUI exists (same logic as _execute_foreground)
                if coder.tui and coder.tui():
                    coder.io.tool_output(output_content)

                if exit_code == 0:
                    return (
                        f"Shell command completed within {timeout}s timeout (exit code 0)."
                        f" Output:\n{output_content}"
                    )
                else:
                    return (
                        f"Shell command completed within {timeout}s timeout with exit code"
                        f" {exit_code}. Output:\n{output_content}"
                    )

            # Check if timeout has expired
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                # Timeout elapsed, process continues in background
                coder.io.tool_output(
                    f"⏱️ Command exceeded {timeout}s timeout, continuing in background..."
                )

                # Get any output captured so far
                current_output = buffer.get_all(clear=False)

                return (
                    f"Command exceeded {timeout}s timeout and is continuing in background.\n"
                    f"Command key: {command_key}\n"
                    f"Output captured so far:\n{current_output}\n"
                )

            # Wait a bit before checking again
            await asyncio.sleep(1)

    @classmethod
    async def _execute_foreground(cls, coder, command_string):
        """
        Execute command in foreground (blocking).
        """
        should_print = True
        tui = None
        if coder.tui and coder.tui():
            tui = coder.tui()
            should_print = False

        coder.io.tool_output("⚙️ Executing shell command.")

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
        if coder.context_management_enabled and len(output_content) > output_limit:
            output_content = (
                output_content[:output_limit]
                + f"\n... (output truncated at {output_limit} characters, based on"
                " large_file_token_threshold)"
            )

        if tui:
            coder.io.tool_output(output_content)

        if exit_status == 0:
            return f"Shell command executed successfully (exit code 0). Output:\n{output_content}"
        else:
            return f"Shell command failed with exit code {exit_status}. Output:\n{output_content}"

    @classmethod
    async def _stop_background_command(cls, coder, command_key):
        """
        Stop a running background command.
        """
        success, output, exit_code = BackgroundCommandManager.stop_background_command(command_key)

        if success:
            return (
                f"Background command stopped: {command_key}\n"
                f"Exit code: {exit_code}\n"
                f"Final output:\n{output}"
            )
        else:
            return output  # Error message from manager

    async def _handle_errors(cls, coder, command_string, e):
        """Handle errors during command execution."""
        coder.io.tool_error(f"Error executing shell command: {str(e)}")
        return f"Error executing command: {str(e)}"

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for Command tool."""
        color_start, color_end = color_markers(coder)

        try:
            params = json.loads(tool_response.function.arguments)
        except json.JSONDecodeError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        # Output header
        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        command = params.get("command", "")
        background = params.get("background", False)
        stop = params.get("stop", False)
        stdin = params.get("stdin")
        pty = params.get("pty", False)

        coder.io.tool_output("")

        # Show additional parameters if they are not default
        extras = []
        if background:
            extras.append("background=True")
        if stop:
            extras.append("stop=True")
        if pty:
            extras.append("pty=True")

        if extras:
            coder.io.tool_output(f"{color_start}Options:{color_end} {', '.join(extras)}")

        if stdin:
            coder.io.tool_output(f"{color_start}Stdin:{color_end}")
            coder.io.tool_output(stdin)

        coder.io.tool_output(f"{color_start}Command:{color_end}")
        coder.io.tool_output(command)
        coder.io.tool_output("")

        # Output footer
        tool_footer(coder=coder, tool_response=tool_response)
