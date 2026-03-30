# Import necessary functions
import os
import platform

from cecli.helpers.background_commands import BackgroundCommandManager
from cecli.run_cmd import run_cmd_subprocess
from cecli.tools.utils.base_tool import BaseTool


class Tool(BaseTool):
    NORM_NAME = "command"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Command",
            "description": "Execute a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command_string": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Run command in background (non-blocking).",
                        "default": False,
                    },
                    "stop_background": {
                        "type": "string",
                        "description": "Command string to stop if running in background.",
                    },
                },
                "required": ["command_string"],
            },
        },
    }

    @classmethod
    async def execute(cls, coder, command_string, background=False, stop_background=None, **kwargs):
        """
        Execute a shell command, optionally in background.
        Commands run with timeout based on agent_config['command_timeout'] (default: 30 seconds).
        """
        # Handle stopping background commands
        if stop_background:
            return await cls._stop_background_command(coder, stop_background)

        # Check for implicit background (trailing & on Linux)
        if not background and command_string.strip().endswith("&"):
            background = True
            command_string = command_string.strip()[:-1].strip()

        # Get user confirmation
        confirmed = await cls._get_confirmation(coder, command_string, background)
        if not confirmed:
            return "Command execution skipped by user."

        # Determine timeout from agent_config (default: 30 seconds)
        timeout = 0
        if hasattr(coder, "agent_config"):
            timeout = coder.agent_config.get("command_timeout", 30)

        if background:
            return await cls._execute_background(coder, command_string)
        elif timeout > 0:
            return await cls._execute_with_timeout(coder, command_string, timeout)
        else:
            return await cls._execute_foreground(coder, command_string)

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
    async def _execute_background(cls, coder, command_string):
        """
        Execute command in background.
        """
        coder.io.tool_output(f"⚙️ Starting background command: {command_string}")

        # Use static manager to start background command
        command_key = BackgroundCommandManager.start_background_command(
            command_string, verbose=coder.verbose, cwd=coder.root, max_buffer_size=4096
        )

        return (
            f"Background command started: {command_string}\n"
            f"Command key: {command_key}\n"
            "Output will be injected into chat stream."
        )

    @classmethod
    async def _execute_with_timeout(cls, coder, command_string, timeout):
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

        coder.io.tool_output(f"⚙️ Executing shell command with {timeout}s timeout: {command_string}")

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
            stdin=subprocess.DEVNULL,
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

        coder.io.tool_output(f"⚙️ Executing shell command: {command_string}")

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

    @classmethod
    async def _handle_errors(cls, coder, command_string, e):
        """Handle errors during command execution."""
        coder.io.tool_error(f"Error executing shell command '{command_string}': {str(e)}")
        return f"Error executing command: {str(e)}"
