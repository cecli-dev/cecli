"""
Background command management for cecli.

Provides a static BackgroundCommandManager class for running shell commands
in the background and capturing their output for injection into chat streams.
"""

import codecs
import os
import platform
import subprocess
import threading
from collections import deque
from typing import Dict, List, Optional, Tuple

try:
    import pty
    import termios

    HAS_PTY = True
except ImportError:
    HAS_PTY = False


class CircularBuffer:
    """
    Thread-safe circular buffer for storing command output with size limit.
    """

    def __init__(self, max_size: int = 4096):
        """
        Initialize circular buffer with maximum size.

        Args:
            max_size: Maximum number of characters to store
        """
        self.max_size = max_size
        self.buffer = deque(maxlen=max_size)
        self.lock = threading.Lock()
        self.total_added = 0  # Track total characters added for new output detection

    def append(self, text: str) -> None:
        """
        Add text to buffer, removing oldest content if exceeds max size.

        Args:
            text: Text to append to buffer
        """
        with self.lock:
            self.buffer.append(text)
            self.total_added += len(text)

    def get_all(self, clear: bool = False) -> str:
        """
        Get all content in buffer.

        Args:
            clear: If True, clear buffer after reading

        Returns:
            Concatenated string of all buffer content
        """
        with self.lock:
            result = "".join(self.buffer)
            if clear:
                self.buffer.clear()
                self.total_added = 0
            return result

    def get_new_output(self, last_read_position: int) -> Tuple[str, int]:
        """
        Get new output since last read position.

        Args:
            last_read_position: Position from last read (self.total_added value)

        Returns:
            Tuple of (new_output, new_position)
        """
        with self.lock:
            if last_read_position >= self.total_added:
                return "", self.total_added

            # Calculate how much new content we have
            new_chars = self.total_added - last_read_position
            # Get the last new_chars characters from the buffer
            all_content = "".join(self.buffer)
            new_output = all_content[-new_chars:] if new_chars > 0 else ""
            return new_output, self.total_added

    def clear(self) -> None:
        """Clear the buffer."""
        with self.lock:
            self.buffer.clear()
            self.total_added = 0

    def size(self) -> int:
        """Get current buffer size in characters."""
        with self.lock:
            return sum(len(chunk) for chunk in self.buffer)


class InputBuffer:
    """
    Thread-safe buffer for queuing input to be sent to a process.
    """

    def __init__(self):
        self.queue = deque()
        self.lock = threading.Lock()

    def append(self, text: str) -> None:
        """Add text to the input queue."""
        with self.lock:
            self.queue.append(text)

    def pop_all(self) -> str:
        """Get and clear all queued input."""
        with self.lock:
            result = "".join(self.queue)
            self.queue.clear()
            return result

    def has_input(self) -> bool:
        """Check if there is queued input."""
        with self.lock:
            return len(self.queue) > 0


class BackgroundProcess:
    """
    Represents a background process with output capture.
    """

    def __init__(
        self,
        command: str,
        process: subprocess.Popen,
        buffer: CircularBuffer,
        persist: bool = False,
        input_buffer: Optional[InputBuffer] = None,
        master_fd: Optional[int] = None,
    ):
        self.master_fd = master_fd
        """
        Initialize background process wrapper.

        Args:
            command: Original command string
            process: Subprocess.Popen object
            buffer: CircularBuffer for output storage
            persist: If True, output buffer won't be cleared when read
        """
        import time

        self.command = command
        self.process = process
        self.buffer = buffer
        self.reader_thread = None
        self.last_read_position = 0
        self.start_time = time.time()
        self.end_time = None
        self.persist = persist
        self.input_buffer = input_buffer or InputBuffer()
        self.writer_thread = None
        self._stop_event = threading.Event()
        self._start_output_reader()
        self._start_input_writer()

    def _start_output_reader(self) -> None:
        """Start thread to read process output."""

        def reader():
            try:
                # Simple approach: read lines when available
                # This will block on readline(), but that's OK because
                # we're in a separate thread and the buffer will capture
                # output as soon as it's available

                if self.master_fd is not None:
                    while not self._stop_event.is_set():
                        try:
                            data = os.read(self.master_fd, 4096).decode(errors="replace")
                            if not data:
                                break
                            self.buffer.append(data)
                        except (OSError, EOFError):
                            break
                else:
                    # Read stdout
                    for line in iter(self.process.stdout.readline, ""):
                        if line:
                            self.buffer.append(line)

                    # Read stderr
                    for line in iter(self.process.stderr.readline, ""):
                        if line:
                            self.buffer.append(line)

            except Exception as e:
                self.buffer.append(f"\n[Error reading process output: {str(e)}]\n")

        self.reader_thread = threading.Thread(target=reader, daemon=True)
        self.reader_thread.start()

    def _start_input_writer(self) -> None:
        """Start thread to write input to process stdin."""

        def writer():
            try:
                while not self._stop_event.is_set() and self.is_alive():
                    if self.input_buffer.has_input():
                        text = self.input_buffer.pop_all()
                        if text:
                            if self.master_fd is not None:
                                os.write(self.master_fd, text.encode("latin-1"))
                            else:
                                try:
                                    # Try to write to the binary buffer for lossless propagation
                                    self.process.stdin.buffer.write(text.encode("latin-1"))
                                    self.process.stdin.buffer.flush()
                                except (AttributeError, ValueError):
                                    # Fallback to text mode if buffer is not available
                                    self.process.stdin.write(text)
                                    self.process.stdin.flush()
                    import time

                    time.sleep(0.1)
            except (BrokenPipeError, OSError):
                pass
            except Exception as e:
                self.buffer.append(f"\n[Error writing to process input: {str(e)}]\n")
            finally:
                try:
                    if self.master_fd is not None:
                        os.close(self.master_fd)
                    else:
                        self.process.stdin.close()
                except Exception:
                    pass

        self.writer_thread = threading.Thread(target=writer, daemon=True)
        self.writer_thread.start()

    def get_output(self, clear: bool = False) -> str:
        """
        Get current output buffer.

        Args:
            clear: If True, clear buffer after reading

        Returns:
            Current output content
        """
        return self.buffer.get_all(clear)

    def get_new_output(self) -> str:
        """
        Get new output since last call.

        Returns:
            New output since last call
        """
        new_output, new_position = self.buffer.get_new_output(self.last_read_position)
        self.last_read_position = new_position
        return new_output

    def is_alive(self) -> bool:
        """Check if process is running."""
        return self.process.poll() is None

    def send_input(self, text: str) -> None:
        """Queue input to be sent to the process."""
        if self.input_buffer:
            self.input_buffer.append(text)

    def stop(self, timeout: float = 5.0) -> Tuple[bool, str, Optional[int]]:
        """
        Stop the process gracefully.

        Args:
            timeout: Seconds to wait for graceful termination

        Returns:
            Tuple of (success, output, exit_code)
        """
        import time

        try:
            # Signal threads to stop
            self._stop_event.set()

            # Try SIGTERM first
            self.process.terminate()
            self.process.wait(timeout=timeout)

            # Get final output
            output = self.get_output(clear=True)
            exit_code = self.process.returncode
            self.end_time = time.time()
            return True, output, exit_code

        except subprocess.TimeoutExpired:
            # Force kill if timeout
            self.process.kill()
            self.process.wait()

            output = self.get_output(clear=True)
            exit_code = self.process.returncode
            self.end_time = time.time()

            return True, output, exit_code

        except Exception as e:
            return False, f"Error stopping process: {str(e)}", None

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        """
        Wait for process completion.

        Args:
            timeout: Timeout in seconds

        Returns:
            Exit code or None if timeout
        """
        try:
            self.process.wait(timeout=timeout)
            return self.process.returncode
        except subprocess.TimeoutExpired:
            return None


class BackgroundCommandManager:
    """
    Static manager for background commands with class-level storage.
    """

    # Class-level storage
    _background_commands: Dict[str, BackgroundProcess] = {}
    _lock = threading.Lock()
    _next_id = 1

    @classmethod
    def _generate_command_key(cls, command: str) -> str:
        """
        Generate a unique key for a command.

        Args:
            command: Command string

        Returns:
            Unique command key
        """
        with cls._lock:
            key = f"bg_{cls._next_id}_{hash(command) % 10000:04d}"
            cls._next_id += 1
            return key

    @classmethod
    def start_background_command(
        cls,
        command: str,
        verbose: bool = False,
        cwd: Optional[str] = None,
        max_buffer_size: int = 4096,
        existing_process: Optional[subprocess.Popen] = None,
        existing_buffer: Optional[CircularBuffer] = None,
        persist: bool = False,
        existing_input_buffer: Optional[InputBuffer] = None,
        use_pty: bool = False,
    ) -> str:
        """
        Start a command in background.

        Args:
            command: Shell command to execute
            verbose: Whether to print verbose output
            cwd: Working directory for command
            max_buffer_size: Maximum buffer size for output
            existing_process: Optional existing subprocess.Popen to register
            existing_buffer: Optional existing CircularBuffer to use
            persist: If True, output buffer won't be cleared when read

        Returns:
            Command key for future reference
        """
        try:
            # Use existing buffer or create new one
            buffer = existing_buffer or CircularBuffer(max_size=max_buffer_size)

            # Use existing process or start new one
            master_fd = None
            if use_pty and HAS_PTY and platform.system() != "Windows":
                master_fd, slave_fd = pty.openpty()

                # Disable echo on the slave PTY
                attr = termios.tcgetattr(slave_fd)
                attr[3] = attr[3] & ~termios.ECHO
                termios.tcsetattr(slave_fd, termios.TCSANOW, attr)

                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    stdin=slave_fd,
                    cwd=cwd,
                    close_fds=True,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                )
                os.close(slave_fd)
            elif existing_process:
                process = existing_process
            else:
                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    cwd=cwd,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                )

            # Create background process wrapper
            bg_process = BackgroundProcess(
                command,
                process,
                buffer,
                persist=persist,
                input_buffer=existing_input_buffer,
                master_fd=master_fd,
            )

            # Generate unique key and store
            command_key = cls._generate_command_key(command)

            with cls._lock:
                cls._background_commands[command_key] = bg_process

            if verbose:
                print(f"[Background] Started command: {command} (key: {command_key})")

            return command_key

        except Exception as e:
            raise RuntimeError(f"Failed to start background command: {str(e)}")

    @classmethod
    def is_command_running(cls, command_key: str) -> bool:
        """
        Check if a background command is running.

        Args:
            command_key: Command key returned by start_background_command

        Returns:
            True if command is running
        """
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
            if not bg_process:
                return False
            return bg_process.is_alive()

    @classmethod
    def get_command_output(cls, command_key: str, clear: bool = False) -> str:
        """
        Get output from a background command.

        Args:
            command_key: Command key returned by start_background_command
            clear: If True, clear buffer after reading

        Returns:
            Command output
        """
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
            if not bg_process:
                return f"[Error] No background command found with key: {command_key}"
            return bg_process.get_output(clear)

    @classmethod
    def get_new_command_output(cls, command_key: str) -> str:
        """
        Get new output from a background command since last call.

        Args:
            command_key: Command key returned by start_background_command

        Returns:
            New command output since last call
        """
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
            if not bg_process:
                return f"[Error] No background command found with key: {command_key}"
            return bg_process.get_new_output()

    @classmethod
    def send_command_input(cls, command_key: str, text: str) -> bool:
        """
        Send input to a background command.

        Args:
            command_key: Command key returned by start_background_command
            text: Text to send to the command's stdin

        Returns:
            True if input was queued, False if command not found
        """
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
            if not bg_process:
                return False
            # Decode escape sequences (like \x1b) if present in the string
            try:
                text = codecs.decode(text, "unicode_escape")
            except Exception:
                pass
            bg_process.send_input(text)
            return True

    @classmethod
    def get_all_command_outputs(cls, clear: bool = False) -> Dict[str, str]:
        """
        Get output from all background commands (running or recently finished).

        Args:
            clear: If True, clear buffers after reading (unless persist=True)

        Returns:
            Dictionary mapping command keys to their output
        """
        with cls._lock:
            outputs = {}
            for command_key, bg_process in cls._background_commands.items():
                # Don't clear if persist flag is set
                should_clear = clear and not getattr(bg_process, "persist", False)
                if clear:
                    output = bg_process.get_output(clear=should_clear)
                else:
                    output = bg_process.get_new_output()
                if output.strip():
                    outputs[command_key] = output
            return outputs

    @classmethod
    def stop_background_command(cls, command_key: str) -> Tuple[bool, str, Optional[int]]:
        """
        Stop a running background command.

        Args:
            command_key: Command key returned by start_background_command

        Returns:
            Tuple of (success, output, exit_code)
        """
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
            if not bg_process:
                return False, f"No background command found with key: {command_key}", None

            # Stop the process
            success, output, exit_code = bg_process.stop()

            # Remove from tracking
            if command_key in cls._background_commands:
                del cls._background_commands[command_key]

            return success, output, exit_code

    @classmethod
    def stop_all_background_commands(cls) -> Dict[str, Tuple[bool, str, Optional[int]]]:
        """
        Stop all running background commands.

        Returns:
            Dictionary mapping command keys to (success, output, exit_code) tuples
        """
        results = {}
        with cls._lock:
            command_keys = list(cls._background_commands.keys())

        for command_key in command_keys:
            success, output, exit_code = cls.stop_background_command(command_key)
            results[command_key] = (success, output, exit_code)

        return results

    @classmethod
    def list_background_commands(cls) -> Dict[str, Dict[str, any]]:
        """
        List all background commands with their status.

        Returns:
            Dictionary with command information including timestamps
        """
        import time

        with cls._lock:
            result = {}
            for command_key, bg_process in cls._background_commands.items():
                result[command_key] = {
                    "command": bg_process.command,
                    "running": bg_process.is_alive(),
                    "buffer_size": bg_process.buffer.size(),
                    "start_time": bg_process.start_time,
                    "end_time": bg_process.end_time,
                    "duration": (
                        time.time() - bg_process.start_time
                        if bg_process.is_alive()
                        else (
                            bg_process.end_time - bg_process.start_time
                            if bg_process.end_time
                            else None
                        )
                    ),
                }
            return result

    @staticmethod
    def save_paginated_output(
        output: str,
        command_key: str,
        page_size: int,
        abs_root_path_func,
        local_agent_folder_func,
    ) -> Optional[Tuple[str, List[str], List[str]]]:
        """
        Save long output to paginated files in a folder for later access.

        When output exceeds the page_size threshold, it is split into multiple
        files named `{page_number}.txt` inside a folder named `{command_key}`
        in the agent's local folder.

        Args:
            output: Full output text to save
            command_key: Command key used for both folder naming and as the filename root
            page_size: Maximum characters per page (typically large_file_token_threshold)
            abs_root_path_func: Callable to convert relative path to absolute (e.g., coder.abs_root_path)
            local_agent_folder_func: Callable to generate relative paths (e.g., coder.local_agent_folder)

        Returns:
            Tuple of (folder path, rel file paths list, alias paths list), or None if output fits in one page.
        """
        if not output or len(output) <= page_size:
            return None

        folder_path = local_agent_folder_func(command_key)
        abs_folder = abs_root_path_func(folder_path)
        os.makedirs(abs_folder, exist_ok=True)

        num_pages = (len(output) + page_size - 1) // page_size

        for i in range(num_pages):
            page_num = i + 1
            filename = f"{page_num}.txt"
            abs_path = os.path.join(abs_folder, filename)
            page_content = output[i * page_size : (i + 1) * page_size]
            with open(abs_path, "w") as f:
                f.write(page_content)

        file_paths = [f"{folder_path}/{page_num}.txt" for page_num in range(1, num_pages + 1)]
        alias_paths = [
            f"command_key::{command_key}/{page_num}.txt" for page_num in range(1, num_pages + 1)
        ]
        return (folder_path, file_paths, alias_paths)
