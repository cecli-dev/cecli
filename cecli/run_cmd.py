import asyncio
import base64
import os
import platform
import subprocess
import sys
from io import BytesIO

import pexpect
import psutil


def run_cmd(command, verbose=False, error_print=None, cwd=None, should_print=True):
    try:
        if sys.stdin.isatty() and hasattr(pexpect, "spawn") and platform.system() != "Windows":
            return run_cmd_pexpect(command, verbose, cwd, should_print=should_print)

        return run_cmd_subprocess(command, verbose, cwd, should_print=should_print)
    except OSError as e:
        error_message = f"Error occurred while running command '{command}': {str(e)}"
        if error_print is None:
            print(error_message)
        else:
            error_print(error_message)
        return 1, error_message


def get_windows_parent_process_name():
    try:
        current_process = psutil.Process()
        while True:
            parent = current_process.parent()
            if parent is None:
                break
            parent_name = parent.name().lower()
            if parent_name in ["powershell.exe", "cmd.exe"]:
                return parent_name
            current_process = parent
        return None
    except Exception:
        return None


def run_cmd_subprocess(
    command, verbose=False, cwd=None, encoding=sys.stdout.encoding, should_print=True
):
    if verbose:
        print("Using run_cmd_subprocess:", command)

    try:
        shell = os.environ.get("SHELL", "/bin/sh")
        parent_process = None

        # Determine the appropriate shell
        if platform.system() == "Windows":
            parent_process = get_windows_parent_process_name()
            if parent_process == "powershell.exe":
                # Silence progress/error streams at the source to prevent CLIXML
                silenced_command = f"$ProgressPreference='SilentlyContinue'; {command}"
                cmd_bytes = silenced_command.encode("utf-16-le")
                encoded = base64.b64encode(cmd_bytes).decode()
                command = f"powershell -NoProfile -NonInteractive -OutputFormat Text -EncodedCommand {encoded}"
        if verbose:
            print("Running command:", command)
            print("SHELL:", shell)
            if platform.system() == "Windows":
                print("Parent process:", parent_process)

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            executable=shell if platform.system() != "Windows" else None,
            encoding=encoding,
            errors="replace",
            bufsize=1,  # Set bufsize to 0 for unbuffered output
            universal_newlines=True,
            # Never inherit the TUI's stdin; a command that reads it would
            # race Textual for keystrokes. Commands needing input go through
            # the interactive path instead.
            stdin=subprocess.DEVNULL,
            cwd=cwd,
        )

        output = []

        while True:
            # Read one line (it will block until a newline or EOF is received)
            line = process.stdout.readline()

            # Check if the line is empty AND the process has finished
            if not line and process.poll() is not None:
                break  # Exit the loop if nothing more to read and process is done

            if line:
                output.append(line)

                if should_print:
                    print(line, end="", flush=True)

        process.wait()
        return process.returncode, _clean_output("".join(output))
    except Exception as e:
        return 1, str(e)


async def run_cmd_async(
    command,
    interrupt_event,
    verbose=False,
    cwd=None,
    encoding=sys.stdout.encoding,
    should_print=True,
):
    if verbose:
        print("Using run_cmd_async:", command)

    shell = os.environ.get("SHELL", "/bin/sh")
    parent_process = None

    # Determine the appropriate shell
    if platform.system() == "Windows":
        parent_process = get_windows_parent_process_name()
        if parent_process == "powershell.exe":
            # Silence progress/error streams at the source to prevent CLIXML
            silenced_command = f"$ProgressPreference='SilentlyContinue'; {command}"
            cmd_bytes = silenced_command.encode("utf-16-le")
            encoded = base64.b64encode(cmd_bytes).decode()
            command = f"powershell -NoProfile -NonInteractive -OutputFormat Text -EncodedCommand {encoded}"

    if verbose:
        print("Running command:", command)
        print("SHELL:", shell)
        if platform.system() == "Windows":
            print("Parent process:", parent_process)

    if platform.system() == "Windows":
        loop = asyncio.get_running_loop()
        if hasattr(asyncio, "SelectorEventLoop") and not isinstance(
            loop, asyncio.SelectorEventLoop
        ):
            # Fallback to synchronous version if not using SelectorEventLoop
            return await loop.run_in_executor(
                None,
                run_cmd_subprocess,
                command,
                verbose,
                cwd,
                encoding,
                should_print,
            )

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
    except NotImplementedError:
        # On Windows with SelectorEventLoop, asyncio does not support subprocesses.
        # Fall back to synchronous subprocess via loop.run_in_executor.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            run_cmd_subprocess,
            command,
            verbose,
            cwd,
            encoding,
            should_print,
        )
    except FileNotFoundError:
        return 1, f"Command not found: {command}"

    output = []

    async def read_stream(stream):
        while True:
            try:
                line_bytes = await stream.readline()
            except (IOError, OSError):
                # Stream closed
                break
            if not line_bytes:
                break
            line = line_bytes.decode(encoding, errors="replace")
            output.append(line)
            if should_print:
                print(line, end="", flush=True)

    reader_task = asyncio.create_task(read_stream(process.stdout))
    interrupt_task = asyncio.create_task(interrupt_event.wait())

    done, pending = await asyncio.wait(
        {reader_task, interrupt_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if interrupt_task in done:
        # Interrupted
        for task in pending:
            task.cancel()
        try:
            process.terminate()
        except ProcessLookupError:
            pass  # process already finished
        await process.wait()
        return 1, "Interrupted"

    # Not interrupted, wait for process to finish
    await process.wait()
    # wait for reader to finish
    if not reader_task.done():
        await reader_task

    return process.returncode, _clean_output("".join(output))


def run_cmd_pexpect(command, verbose=False, cwd=None, should_print=True):
    """
    Run a shell command interactively using pexpect, capturing all output.

    :param command: The command to run as a string.
    :param verbose: If True, print output in real-time.
    :return: A tuple containing (exit_status, output)
    """
    if verbose:
        print("Using run_cmd_pexpect:", command)

    output = BytesIO()

    def output_callback(b):
        output.write(b)
        return b

    try:
        # Use the SHELL environment variable, falling back to /bin/sh if not set
        shell = os.environ.get("SHELL", "/bin/sh")
        if verbose:
            print("With shell:", shell)

        if os.path.exists(shell):
            # Use the shell from SHELL environment variable
            if verbose:
                print("Running pexpect.spawn with shell:", shell)
            child = pexpect.spawn(shell, args=["-i", "-c", command], encoding="utf-8", cwd=cwd)
        else:
            # Fall back to spawning the command directly
            if verbose:
                print("Running pexpect.spawn without shell.")
            child = pexpect.spawn(command, encoding="utf-8", cwd=cwd)

        # Transfer control to the user, capturing output
        child.interact(output_filter=output_callback)

        # Wait for the command to finish and get the exit status
        child.close()
        return child.exitstatus, output.getvalue().decode("utf-8", errors="replace")

    except (pexpect.ExceptionPexpect, TypeError, ValueError) as e:
        error_msg = f"Error running command {command}: {e}"
        return 1, error_msg


def _clean_output(output):
    """Remove CLIXML progress output from PowerShell commands."""
    if platform.system() != "Windows":
        return output

    if output.startswith("#< CLIXML"):
        lines = output.splitlines()
        filtered = []
        for line in lines:
            # Skip the CLIXML header line
            if line.startswith("#< CLIXML"):
                continue
            # Skip CLIXML XML object tags (progress messages)
            stripped = line.strip()
            if stripped.startswith("<Objs ") or stripped == "</Objs>":
                continue
            if stripped.startswith("<Obj "):
                continue
            filtered.append(line)
        return "\n".join(filtered)
    return output
