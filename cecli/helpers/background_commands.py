"""
Background command management for cecli.

Provides a static BackgroundCommandManager class for running shell commands
in the background and capturing their output for injection into chat streams.
"""

import os
import platform
import re
import signal
import subprocess
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import xxhash

from cecli.decoding import safe_open

try:
    import pty
    import termios

    HAS_PTY = True
except ImportError:
    HAS_PTY = False
BG_REPLAY_BYTES = 256 * 1024
BG_INPUT_MAX = 64 * 1024
BG_EXITED_TTL = 900.0
BG_INPUT_LEASE_SECONDS = 30.0
BG_PROMPT_QUIET_SECONDS = 0.30
BG_PROMPT_REEMIT_SECONDS = 30.0

_ANSI_ESCAPE = re.compile(
    r"\x1b\[[0-9;]*[a-zA-Z]|\x1b[\]^_]|[\x1b\x9b][][()#;?]*"
    r"(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-PRZcf-nqry=><~]"
)
_PROMPT_RE = re.compile(
    r"(?i)(?:password|passphrase|sudo|\[sudo\]|are you sure|continue\?|"
    r"press (?:any key|enter)|login|username|token|otp|verification code)"
    r"[^\n]{0,80}[:?]?\s*$"
)


def strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


class StreamRing:
    """Bounded raw-byte ring with absolute byte sequence numbers."""

    def __init__(self, limit: int = BG_REPLAY_BYTES):
        self.limit = max(1024, int(limit))
        self._data = bytearray()
        self._seq = 0

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def start_seq(self) -> int:
        return self._seq - len(self._data)

    def append(self, data: bytes) -> int:
        if not data:
            return self._seq
        self._data.extend(data)
        self._seq += len(data)
        excess = len(self._data) - self.limit
        if excess > 0:
            del self._data[:excess]
        return self._seq

    def snapshot(self, since: Optional[int] = None) -> Tuple[int, bytes, bool]:
        start = self.start_seq
        if since is None or since < start:
            return self._seq, bytes(self._data), since is not None and since < start
        offset = max(0, int(since) - start)
        return self._seq, bytes(self._data[offset:]), False

    def clear(self) -> None:
        self._data.clear()


class BackgroundInputError(Exception):
    """Semantic input failure mapped to an HTTP status by the desktop server."""

    def __init__(self, code: str, owner: Optional[str] = None):
        super().__init__(code)
        self.code = code
        self.owner = owner


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
        """Append text, retaining only the newest ``max_size`` characters.

        Store individual characters so the deque limit measures characters, not
        output chunks. Slice oversized inputs before extending to avoid processing
        characters that would immediately be evicted. Track all received characters
        in ``total_added`` so incremental read positions survive eviction.
        """
        with self.lock:
            if self.max_size:
                self.buffer.extend(text[-self.max_size :])

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
            return len(self.buffer)


class PagedOutputBuffer:
    """
    Thread-safe output window that spills full pages to disk.

    Output accumulates in memory until it reaches ``page_size`` characters.
    Full pages are written to ``pages_dir`` as ``{n}.txt`` and dropped from
    memory, so the in-memory window never grows beyond ``page_size``. Unlike
    ``CircularBuffer``, ``total_added`` is a monotonic stream offset that is
    never reset, so incremental readers can resume after content has been
    flushed; anything older than the in-memory window lives on disk.
    """

    def __init__(self, page_size: int = 4096, pages_dir: Optional[str] = None):
        self.page_size = max(1, int(page_size))
        self.pages_dir = pages_dir
        self.buffer = deque()
        self.lock = threading.Lock()
        self.total_added = 0
        self.window_start = 0
        self.page_count = 0

    def append(self, text: str) -> None:
        """Append text, spilling full pages to disk once the window fills."""
        if not text:
            return

        with self.lock:
            self.buffer.extend(text)
            self.total_added += len(text)

            if self.total_added - self.window_start >= self.page_size:
                self._spill_locked()

    def get_all(self, clear: bool = False) -> str:
        """Return the in-memory window (content not yet flushed to disk)."""
        with self.lock:
            result = "".join(self.buffer)

            if clear:
                self.buffer.clear()
                self.window_start = self.total_added

            return result

    def get_new_output(self, last_read_position: int) -> Tuple[str, int]:
        """Return window content past ``last_read_position`` and the new offset.

        Content older than the window has already been paged to disk, so the
        read position is clamped forward to the window start rather than
        replaying bytes that are only available as pages.
        """
        with self.lock:
            if last_read_position >= self.total_added:
                return "", self.total_added

            start = max(last_read_position, self.window_start)
            new_output = "".join(self.buffer)[start - self.window_start :]

            return new_output, self.total_added

    def clear(self) -> None:
        """Drop the in-memory window; flushed pages are unaffected."""
        with self.lock:
            self.buffer.clear()
            self.window_start = self.total_added

    def size(self) -> int:
        """Get current buffer size in characters."""
        with self.lock:
            return len(self.buffer)

    def _spill_locked(self) -> None:
        content = "".join(self.buffer)

        if not self.pages_dir:
            # Without a page directory, retain only the newest page in memory.
            if len(content) > self.page_size:
                dropped = len(content) - self.page_size
                content = content[dropped:]
                self.window_start += dropped
                self.buffer = deque(content)

            return

        while len(content) >= self.page_size:
            page = content[: self.page_size]
            content = content[self.page_size :]
            self.page_count += 1
            self._write_page_locked(self.page_count, page)
            self.window_start += self.page_size

        self.buffer = deque(content)

    def _write_page_locked(self, page_number: int, content: str) -> None:
        os.makedirs(self.pages_dir, exist_ok=True)
        abs_path = os.path.join(self.pages_dir, f"{page_number}.txt")
        tmp_path = f"{abs_path}.tmp"

        with safe_open(tmp_path, "w") as page_file:
            page_file.write(content)

        os.replace(tmp_path, abs_path)


class InputBuffer:
    """Thread-safe, byte-oriented, bounded queue for process stdin."""

    def __init__(self, max_bytes: int = BG_INPUT_MAX):
        self.queue = deque()
        self.lock = threading.Lock()
        self._data_ready = threading.Event()
        self.max_bytes = max_bytes
        self._size = 0

    @property
    def size(self) -> int:
        with self.lock:
            return self._size

    def append(self, text: str) -> bool:
        return self.append_bytes(text.encode("utf-8"))

    def append_bytes(self, data: bytes) -> bool:
        if not data:
            return True

        with self.lock:
            if self._size + len(data) > self.max_bytes:
                return False
            self.queue.append(bytes(data))
            self._size += len(data)

        self._data_ready.set()
        return True

    def pop_all(self) -> bytes:
        with self.lock:
            result = b"".join(self.queue)
            self.queue.clear()
            self._size = 0
            self._data_ready.clear()
            return result

    def has_input(self) -> bool:
        with self.lock:
            return len(self.queue) > 0

    def wait_for_input(self, timeout: float | None = None) -> bool:
        return self._data_ready.wait(timeout)

    def wake(self) -> None:
        self._data_ready.set()

    def clear(self) -> None:
        with self.lock:
            self.queue.clear()
            self._size = 0
            self._data_ready.clear()


class BackgroundProcess:
    """Represents a background process with raw output and lifecycle capture."""

    def __init__(
        self,
        command: str,
        process: subprocess.Popen,
        buffer: CircularBuffer,
        persist: bool = False,
        input_buffer: Optional[InputBuffer] = None,
        master_fd: Optional[int] = None,
    ):
        self.command = command
        self.process = process
        self.buffer = buffer
        self.persist = persist
        self.continued_in_background = False
        self.input_buffer = input_buffer or InputBuffer()
        self.master_fd = master_fd
        self.read_fd = master_fd
        self.write_fd = None
        self._shared_fd = False
        if master_fd is not None:
            try:
                self.write_fd = os.dup(master_fd)
            except OSError:
                self.write_fd = master_fd
                self._shared_fd = True

        self.command_key: Optional[str] = None
        self.stream = StreamRing()
        self.state = "running" if self.is_alive() else "exited"
        self.exit_code: Optional[int] = None
        self.signal: Optional[int] = None
        self.ended_at: Optional[float] = None
        self.cols = 100
        self.rows = 30
        self.pty = master_fd is not None
        self.needs_input = False
        self.last_prompt: Optional[str] = None
        self.consumed_at: Optional[float] = None
        self.close_requested = False
        self.input_owner: Optional[str] = None
        self.input_lease_until = 0.0
        self.event_sink = None
        self.on_exit = None

        self.reader_thread = None
        self.writer_thread = None
        self.last_read_position = 0
        self.start_time = time.time()
        self.end_time = None

        self._state_lock = threading.RLock()
        self._exit_lock = threading.Lock()
        self._exited_event = threading.Event()
        self._exit_reported = False
        self._kill_timer = None
        self._stop_requested = False
        self._pgid: Optional[int] = None
        self._descendant_pids: set[int] = set()
        self._stop_event = threading.Event()
        self._last_output_at = time.monotonic()
        self._prompt_fingerprint = None
        self._last_prompt_at = 0.0

        self._start_output_reader()
        self._start_input_writer()
        self._start_exit_reaper()
        self._start_prompt_watcher()

    def _start_output_reader(self) -> None:
        def reader():
            try:
                if self.read_fd is not None:
                    while not self._stop_event.is_set():
                        try:
                            data = os.read(self.read_fd, 4096)
                        except (BlockingIOError, InterruptedError):
                            continue
                        except (OSError, EOFError, ValueError):
                            break
                        if not data:
                            break
                        self._append_output(data)
                else:
                    streams = []
                    stdout = getattr(self.process, "stdout", None)
                    stderr = getattr(self.process, "stderr", None)
                    if stdout is not None:
                        streams.append(stdout)
                    if stderr is not None and stderr is not stdout:
                        streams.append(stderr)

                    pumps = [
                        threading.Thread(target=self._pump_stream, args=(stream,), daemon=True)
                        for stream in streams
                    ]
                    for pump in pumps:
                        pump.start()
                    for pump in pumps:
                        pump.join()
            finally:
                self._close_read_fd()

        self.reader_thread = threading.Thread(target=reader, daemon=True)
        self.reader_thread.start()

    def _pump_stream(self, stream) -> None:
        while not self._stop_event.is_set():
            try:
                if hasattr(stream, "fileno"):
                    try:
                        data = os.read(stream.fileno(), 4096)
                    except (BlockingIOError, InterruptedError):
                        continue
                    except (OSError, ValueError):
                        break
                else:
                    data = stream.readline()
            except (OSError, EOFError, ValueError):
                break

            if not data:
                break
            raw = data.encode("utf-8", errors="replace") if isinstance(data, str) else data
            self._append_output(raw)

    def _append_output(self, data: bytes) -> None:
        with self._state_lock:
            seq = self.stream.append(data)
            self._last_output_at = time.monotonic()
            self.needs_input = False
            self.last_prompt = None
            self._emit_output_locked(seq, data)
            text = strip_ansi(data.decode("utf-8", errors="replace"))
            try:
                self.buffer.append(text)
            except Exception:
                pass

    def _start_input_writer(self) -> None:
        stdin = getattr(self.process, "stdin", None)
        if self.write_fd is None and stdin is None:
            self.writer_thread = None
            return

        def writer():
            try:
                while not self._stop_event.is_set() and self.is_alive():
                    if not self.input_buffer.wait_for_input(timeout=0.5):
                        continue
                    data = self.input_buffer.pop_all()
                    if not data:
                        continue
                    try:
                        if self.write_fd is not None:
                            view = memoryview(data)
                            while view:
                                written = os.write(self.write_fd, view)
                                view = view[written:]
                        else:
                            try:
                                stdin.buffer.write(data)
                                stdin.buffer.flush()
                            except AttributeError:
                                stdin.write(data.decode("utf-8", errors="replace"))
                                stdin.flush()
                    except (BrokenPipeError, OSError, ValueError):
                        break
                    except Exception:
                        continue
            finally:
                if self.write_fd is not None and not self._shared_fd:
                    try:
                        os.close(self.write_fd)
                    except OSError:
                        pass
                    self.write_fd = None
                elif stdin is not None and self.write_fd is None:
                    try:
                        stdin.close()
                    except Exception:
                        pass

        self.writer_thread = threading.Thread(target=writer, daemon=True)
        self.writer_thread.start()

    def _start_exit_reaper(self) -> None:
        def reaper():
            try:
                code = self.process.wait()
            except Exception:
                code = None
            if code is None and self.is_alive():
                return
            if code is None:
                code = self.process.poll()
            self._mark_exited(code)

        threading.Thread(target=reaper, daemon=True).start()

    def _start_prompt_watcher(self) -> None:
        def watcher():
            while not self._exited_event.is_set():
                time.sleep(0.1)
                if self.state != "running" or self.needs_input:
                    continue
                if time.monotonic() - self._last_output_at < BG_PROMPT_QUIET_SECONDS:
                    continue
                try:
                    tail = self.buffer.get_all()[-300:]
                except Exception:
                    continue
                if not tail or not _PROMPT_RE.search(tail):
                    continue
                fingerprint = tail[-80:]
                now = time.monotonic()
                if (
                    fingerprint == self._prompt_fingerprint
                    and now - self._last_prompt_at < BG_PROMPT_REEMIT_SECONDS
                ):
                    continue
                with self._state_lock:
                    self.needs_input = True
                    self.last_prompt = tail[-200:]
                    self._prompt_fingerprint = fingerprint
                    self._last_prompt_at = now
                    self._emit_locked(
                        "needs_input",
                        prompt=self.last_prompt,
                        state=self.state,
                    )

        threading.Thread(target=watcher, daemon=True).start()

    def get_output(self, clear: bool = False) -> str:
        return self.buffer.get_all(clear)

    def get_new_output(self) -> str:
        new_output, new_position = self.buffer.get_new_output(self.last_read_position)
        self.last_read_position = new_position
        return new_output

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def send_input(self, text: str) -> None:
        try:
            self.send_input_bytes(text.encode("utf-8"), owner="agent")
        except BackgroundInputError:
            pass

    def send_input_bytes(
        self,
        data: bytes,
        owner: Optional[str] = None,
        release: bool = False,
    ) -> Tuple[int, str]:
        now = time.monotonic()

        if release:
            with self._state_lock:
                if owner is None or self.input_owner == owner or self.input_owner is None:
                    self.input_owner = None
                    self.input_lease_until = 0.0
                    return 0, "released"
                raise BackgroundInputError("input_locked", self.input_owner)

        with self._state_lock:
            if self._exit_reported or not self.is_alive():
                raise BackgroundInputError("not_running")
            if self.input_owner is not None and self.input_lease_until < now:
                self.input_owner = None
            if self.input_owner is not None and self.input_owner != owner:
                raise BackgroundInputError("input_locked", self.input_owner)
            if len(data) > BG_INPUT_MAX:
                raise BackgroundInputError("too_large")
            if not self.input_buffer.append_bytes(data):
                raise BackgroundInputError("queue_full")
            if owner is not None:
                self.input_owner = owner
            self.input_lease_until = now + BG_INPUT_LEASE_SECONDS
            self.needs_input = False
            self.last_prompt = None
            self.input_buffer.wake()
            return len(data), "accepted"

    def mark_consumed(self) -> None:
        with self._state_lock:
            self.consumed_at = time.time()

    def resize(self, cols: Any, rows: Any) -> bool:
        try:
            cols = max(20, min(500, int(cols)))
            rows = max(5, min(200, int(rows)))
        except (TypeError, ValueError):
            return False
        with self._state_lock:
            self.cols = cols
            self.rows = rows
            if not self.pty or self.master_fd is None:
                return False
            try:
                import fcntl
                import struct
                import termios

                fcntl.ioctl(
                    self.master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0)
                )
                return True
            except OSError:
                return False

    def signal_stop(self, timeout: float = 5.0) -> None:
        with self._state_lock:
            if self._exit_reported:
                return
            self.state = "stopping"
            self._stop_event.set()
            self.input_buffer.wake()

        self._stop_requested = True
        self._capture_process_group()
        self._signal_tree(signal.SIGTERM, hard=False)

        timer = threading.Timer(timeout, self._force_kill)
        timer.daemon = True
        self._kill_timer = timer
        timer.start()

    def _force_kill(self) -> None:
        if not self._stop_requested:
            return

        sig = getattr(signal, "SIGKILL", signal.SIGTERM)
        if os.name == "posix" and self.pty and self._pgid:
            try:
                os.killpg(self._pgid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        self._kill_descendants(sig)

        pid = getattr(self.process, "pid", None)
        if pid and os.name == "posix":
            try:
                os.kill(pid, sig)
            except OSError:
                pass

    def _capture_process_group(self) -> None:
        if os.name != "posix":
            return

        pid = getattr(self.process, "pid", None)
        if not pid:
            return

        if self.pty:
            try:
                self._pgid = os.getpgid(pid)
            except OSError:
                self._pgid = pid
            return

        try:
            import psutil

            parent = psutil.Process(pid)
            self._descendant_pids = {child.pid for child in parent.children(recursive=True)}
        except Exception:
            pass

    def _kill_descendants(self, sig: int) -> None:
        if os.name != "posix" or not self._descendant_pids:
            return

        try:
            import psutil
        except Exception:
            return

        pids = set(self._descendant_pids)
        for pid in list(pids):
            try:
                pids.update(child.pid for child in psutil.Process(pid).children(recursive=True))
            except Exception:
                pass

        for pid in pids:
            try:
                psutil.Process(pid).send_signal(sig)
            except Exception:
                pass

        self._descendant_pids = set()

    def _has_live_descendants(self) -> bool:
        if os.name != "posix":
            return False

        if self.pty:
            if not self._pgid:
                return False
            try:
                os.killpg(self._pgid, 0)
                return True
            except OSError:
                return False

        try:
            import psutil
        except Exception:
            return False

        for pid in list(self._descendant_pids):
            try:
                proc = psutil.Process(pid)
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    return True
            except Exception:
                pass

        return False

    def _signal_tree(self, sig: int, hard: bool) -> None:
        process = self.process
        pid = getattr(process, "pid", None)

        if pid and os.name == "posix" and self.pty:
            try:
                os.killpg(self._pgid or os.getpgid(pid), sig)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass

        if pid and os.name == "posix":
            try:
                import psutil

                parent = psutil.Process(pid)
                for child in parent.children(recursive=True):
                    try:
                        child.send_signal(sig)
                    except Exception:
                        pass
                parent.send_signal(sig)
                return
            except Exception:
                pass

        try:
            if hard:
                process.kill()
            else:
                process.terminate()
        except OSError:
            pass

    def wait_exit(self, timeout: Optional[float] = None) -> bool:
        return self._exited_event.wait(timeout)

    def stop(self, timeout: float = 5.0) -> Tuple[bool, str, Optional[int]]:
        self.signal_stop(timeout)
        code = None
        try:
            code = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._force_kill()
            try:
                code = self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                code = self.process.poll()
        self._finish_stop(code)
        return True, self.get_output(clear=False), self.exit_code

    def _finish_stop(self, code: Optional[int]) -> Optional[int]:
        """Mark exit and force-kill any descendants that outlived the leader."""
        if code is None:
            code = self.process.poll()
        if code is not None or not self.is_alive():
            self._mark_exited(code)

        if self._has_live_descendants():
            self._force_kill()
            self.wait_exit(2.0)
            if code is None:
                code = self.process.poll()
            if code is not None or not self.is_alive():
                self._mark_exited(code)

        if self._kill_timer is not None and not self._has_live_descendants():
            self._kill_timer.cancel()
            self._kill_timer = None
        return self.exit_code

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        try:
            self.process.wait(timeout=timeout)
            return self.process.returncode
        except subprocess.TimeoutExpired:
            return None

    def _mark_exited(self, code: Optional[int]) -> None:
        with self._exit_lock:
            if self._exit_reported:
                return
            self._exit_reported = True

        with self._state_lock:
            self.exit_code = code
            self.end_time = time.time()
            self.ended_at = self.end_time
            self.state = "exited" if code is not None else "failed"
            self.input_owner = None
            self.input_lease_until = 0.0
            self.needs_input = False
            self.last_prompt = None
            self._stop_event.set()
            self._exited_event.set()
        if self._kill_timer is not None and not (
            self._stop_requested and self._has_live_descendants()
        ):
            self._kill_timer.cancel()
            self._kill_timer = None

        self.input_buffer.wake()
        self._emit_locked(
            "exited",
            code=code,
            signal=self.signal,
            endedAt=self.ended_at,
            state=self.state,
            command=self._entry_locked(),
        )

        if self.close_requested:
            with self._state_lock:
                self._emit_locked("closed", reason="close", command=self._entry_locked())
            if self.on_exit is not None:
                try:
                    self.on_exit()
                except Exception:
                    pass

    def _close_read_fd(self) -> None:
        fd, self.read_fd = self.read_fd, None
        if fd is None:
            return
        try:
            os.close(fd)
        except OSError:
            pass

    def _entry_locked(self) -> Dict[str, Any]:
        return {
            "key": self.command_key,
            "command": self.command,
            "state": self.state,
            "running": self.is_alive(),
            "persist": self.persist,
            "continuedInBackground": self.continued_in_background,
            "pid": getattr(self.process, "pid", None),
            "cols": self.cols,
            "rows": self.rows,
            "pty": self.pty,
            "seq": self.stream.seq,
            "startSeq": self.stream.start_seq,
            "startedAt": self.start_time,
            "endedAt": self.ended_at,
            "exitCode": self.exit_code,
            "signal": self.signal,
            "needsInput": self.needs_input,
            "lastPrompt": self.last_prompt,
            "inputOwner": self.input_owner,
            "consumedAt": self.consumed_at,
            "closeRequested": self.close_requested,
            "bufferSize": self.buffer.size(),
            "pages": getattr(self.buffer, "page_count", 0),
            "totalChars": getattr(self.buffer, "total_added", self.buffer.size()),
        }

    def entry(self) -> Dict[str, Any]:
        with self._state_lock:
            return self._entry_locked()

    def _emit_output_locked(self, seq: int, data: bytes) -> None:
        sink = self.event_sink
        if sink is None or not self.command_key:
            return
        try:
            sink.publish_output(self.command_key, seq, data)
        except Exception:
            pass

    def _emit_locked(self, event: str, **fields: Any) -> None:
        """Publish an event via the sink while state locks may be held.

        The sink must be a non-blocking enqueue (never a transport send) so
        callers holding `_state_lock` cannot stall on I/O.
        """
        sink = self.event_sink
        if sink is None or not self.command_key:
            return
        params = {
            "schemaVersion": 1,
            "event": event,
            "key": self.command_key,
            "state": self.state,
        }
        params.update(fields)
        try:
            sink.publish(params)
        except Exception:
            pass


class BackgroundCommandManager:
    """
    Static manager for background commands with class-level storage.
    """

    # Class-level storage
    _background_commands: Dict[str, BackgroundProcess] = {}
    _lock = threading.Lock()
    _next_id = 1
    event_sink = None
    _ttl_started = False

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
            digest = xxhash.xxh64(command.encode("utf-8")).intdigest()
            key = f"bg_{cls._next_id}_{digest % 10000:04d}"
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
        master_fd: Optional[int] = None,
        command_key: Optional[str] = None,
        page_size: Optional[int] = None,
        pages_dir: Optional[str] = None,
    ) -> str:
        """
        Start a command in background.

        Args:
            command: Shell command to execute
            verbose: Whether to print verbose output
            cwd: Working directory for command
            max_buffer_size: Maximum buffer size for output
            existing_process: Optional existing subprocess.Popen to register
            existing_buffer: Optional existing buffer to use (CircularBuffer or PagedOutputBuffer)
            persist: If True, output buffer won't be cleared when read
            command_key: Optional pre-generated command key; generated when omitted
            page_size: Characters per page when paging output to disk
            pages_dir: Directory where full output pages are written

        Returns:
            Command key for future reference
        """
        try:
            # Use existing buffer or create a paged/circular one
            if existing_buffer is not None:
                buffer = existing_buffer
            elif page_size and pages_dir:
                buffer = PagedOutputBuffer(page_size=page_size, pages_dir=pages_dir)
            else:
                buffer = CircularBuffer(max_size=max_buffer_size)

            # Use existing process or start new one
            # Use provided master_fd (e.g., from _execute_with_timeout) or default to None
            final_master_fd = master_fd

            # Only create a new PTY if no external master_fd was provided
            # (prevents overwriting an externally-created PTY fd)
            can_use_pty = (
                use_pty and master_fd is None and HAS_PTY and platform.system() != "Windows"
            )
            if can_use_pty:
                final_master_fd, slave_fd = pty.openpty()

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
                    # Detach from the TUI's controlling terminal so the child cannot
                    # steal keystrokes or reset terminal modes that Textual relies on.
                    start_new_session=True,
                    universal_newlines=True,
                )
                os.close(slave_fd)
            elif existing_process:
                process = existing_process
            else:
                # When PTY was requested but isn't available (e.g. Windows),
                # wrap with stdbuf -oL to force line-buffered output at the libc level
                resolved_command = (
                    cls._wrap_line_buffered(command) if use_pty and not HAS_PTY else command
                )
                process = subprocess.Popen(
                    resolved_command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
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
                master_fd=final_master_fd,
            )

            # Generate unique key and store
            command_key = command_key or cls._generate_command_key(command)

            bg_process.command_key = command_key
            bg_process.on_exit = lambda: cls._remove(command_key)
            bg_process.event_sink = cls.event_sink
            if not bg_process.is_alive():
                bg_process.state = "exited"

            with cls._lock:
                cls._background_commands[command_key] = bg_process

            cls._ensure_ttl_thread()
            cls._emit(command_key, "started", command=bg_process.entry())

            if verbose:
                print(f"[Background] Started command: {command} (key: {command_key})")

            return command_key

        except Exception as e:
            raise RuntimeError(f"Failed to start background command: {str(e)}")

    @classmethod
    def mark_continued_in_background(cls, command_key: str) -> bool:
        """Flag a timeout-managed command as continuing after its timeout."""

        with cls._lock:
            bg_process = cls._background_commands.get(command_key)

            if not bg_process:
                return False

            bg_process.continued_in_background = True
            entry = (
                bg_process.entry()
                if hasattr(bg_process, "entry")
                else {"key": command_key, "continuedInBackground": True}
            )

        cls._emit(command_key, "state", command=entry, reason="continued_in_background")
        return True

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
    def set_event_sink(cls, sink) -> None:
        cls.event_sink = sink
        with cls._lock:
            for bg_process in cls._background_commands.values():
                bg_process.event_sink = sink

    @classmethod
    def _emit(cls, command_key: str, event: str, **fields: Any) -> None:
        """Publish an event via the class-level sink.

        The sink must be a non-blocking enqueue (never a transport send).
        """
        sink = cls.event_sink
        if sink is None:
            return
        params = {
            "schemaVersion": 1,
            "event": event,
            "key": command_key,
        }
        params.update(fields)
        try:
            sink.publish(params)
        except Exception:
            pass

    @classmethod
    def send_input_bytes(
        cls,
        command_key: str,
        data: bytes,
        owner: Optional[str] = None,
        release: bool = False,
    ) -> Tuple[int, str]:
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
        if not bg_process:
            return 0, "not_found"

        try:
            return bg_process.send_input_bytes(data, owner=owner, release=release)
        except BackgroundInputError as err:
            return 0, err.code

    @classmethod
    def send_command_input(cls, command_key: str, text: str) -> bool:
        accepted, status = cls.send_input_bytes(command_key, text.encode("utf-8"), owner="agent")
        return status in ("accepted", "released") and accepted >= 0

    @classmethod
    def close_background_command(cls, command_key: str) -> Tuple[bool, str]:
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
        if not bg_process:
            return False, "not_found"

        if bg_process.is_alive():
            bg_process.close_requested = True
            bg_process.signal_stop()
            return True, "closing"

        cls._remove(command_key)
        cls._emit(command_key, "closed", reason="close", command=bg_process.entry())
        return True, "closed"

    @classmethod
    def signal_stop_background_command(cls, command_key: str, timeout: float = 5.0) -> bool:
        """Signal a command without waiting for its exit (reader-safe)."""
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
        if not bg_process or not bg_process.is_alive():
            return False

        bg_process.signal_stop(timeout=timeout)
        return True

    @classmethod
    def signal_stop_all_background_commands(cls, timeout: float = 5.0) -> int:
        """Signal every live command; returns how many were signalled."""
        with cls._lock:
            commands = list(cls._background_commands.values())

        stopped = 0
        for bg_process in commands:
            if bg_process.is_alive():
                bg_process.signal_stop(timeout=timeout)
                stopped += 1

        return stopped

    @classmethod
    def snapshot_background_command(cls, command_key: str, since=None):
        """Return raw ring bytes from ``since`` (or the retained window)."""
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
        if not bg_process:
            return None

        try:
            since_value = None if since is None else int(since)
        except (TypeError, ValueError):
            since_value = None

        with bg_process._state_lock:
            seq, data, reset = bg_process.stream.snapshot(since_value)
            return {
                "seq": seq,
                "startSeq": bg_process.stream.start_seq,
                "data": bytes(data),
                "reset": reset,
                "state": bg_process.state,
            }

    @classmethod
    def resize_background_command(cls, command_key: str, cols, rows):
        """Resize a PTY-backed command; returns None when the key is unknown."""
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
        if not bg_process:
            return None

        resized = bg_process.resize(cols, rows)
        return {"resized": bool(resized), "cols": bg_process.cols, "rows": bg_process.rows}

    @classmethod
    def mark_consumed(cls, command_key: str) -> bool:
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
        if not bg_process:
            return False
        bg_process.mark_consumed()
        return True

    @classmethod
    def _remove(cls, command_key: str) -> None:
        with cls._lock:
            cls._background_commands.pop(command_key, None)

    @classmethod
    def _ensure_ttl_thread(cls) -> None:
        with cls._lock:
            if cls._ttl_started:
                return
            cls._ttl_started = True

        def reaper():
            while True:
                time.sleep(5.0)
                expired = []
                with cls._lock:
                    now = time.time()
                    for command_key, bg_process in list(cls._background_commands.items()):
                        if (
                            not bg_process.is_alive()
                            and bg_process.end_time is not None
                            and now - bg_process.end_time > BG_EXITED_TTL
                        ):
                            expired.append((command_key, bg_process))
                            cls._background_commands.pop(command_key, None)
                for command_key, bg_process in expired:
                    cls._emit(
                        command_key,
                        "closed",
                        reason="ttl",
                        command=bg_process.entry(),
                    )

        threading.Thread(target=reaper, daemon=True).start()

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
    def stop_background_command(
        cls, command_key: str, timeout: float = 5.0
    ) -> Tuple[bool, str, Optional[int]]:
        """Signal a command and retain its metadata and final ring for TTL."""
        with cls._lock:
            bg_process = cls._background_commands.get(command_key)
        if not bg_process:
            return False, f"No background command found with key: {command_key}", None

        return bg_process.stop(timeout=timeout)

    @classmethod
    def stop_all_background_commands(
        cls, timeout: float = 5.0
    ) -> Dict[str, Tuple[bool, str, Optional[int]]]:
        """Signal every command outside the manager lock, bounded in total."""
        with cls._lock:
            commands = list(cls._background_commands.items())

        for _, bg_process in commands:
            if bg_process.is_alive():
                bg_process.signal_stop(timeout=timeout)

        deadline = time.monotonic() + timeout
        results = {}
        for command_key, bg_process in commands:
            remaining = max(0.0, deadline - time.monotonic())
            bg_process.wait_exit(remaining)
            bg_process._finish_stop(bg_process.process.poll())
            results[command_key] = (
                True,
                bg_process.get_output(clear=False),
                bg_process.exit_code,
            )
        return results

    @classmethod
    def list_background_commands(cls) -> Dict[str, Dict[str, any]]:
        """List commands with legacy snake_case keys plus the new CLI fields."""
        with cls._lock:
            processes = list(cls._background_commands.items())

        result = {}
        now = time.time()
        for command_key, bg_process in processes:
            entry = bg_process.entry()
            entry.update(
                {
                    "buffer_size": entry["bufferSize"],
                    "total_chars": entry["totalChars"],
                    "start_time": entry["startedAt"],
                    "end_time": entry["endedAt"],
                    "continued_in_background": entry["continuedInBackground"],
                    "exit_code": entry["exitCode"],
                    "ended_at": entry["endedAt"],
                    "needs_input": entry["needsInput"],
                    "last_prompt": entry["lastPrompt"],
                    "input_owner": entry["inputOwner"],
                    "consumed_at": entry["consumedAt"],
                    "close_requested": entry["closeRequested"],
                    "start_seq": entry["startSeq"],
                    "duration": (
                        now - bg_process.start_time
                        if bg_process.is_alive()
                        else (
                            bg_process.end_time - bg_process.start_time
                            if bg_process.end_time
                            else None
                        )
                    ),
                }
            )
            result[command_key] = entry
        return result

    _line_buffered_tool = None

    @staticmethod
    def _detect_line_buffered_tool() -> str:
        """
        Detect the best available tool for forcing line-buffered stdout.

        Checks for `stdbuf` (GNU coreutils, most Linux distros) and falls
        back to `unbuffer` (expect package, available on many systems).
        If neither is available, returns None.

        Returns:
            The tool command (e.g., 'stdbuf -oL' or 'unbuffer'), or None
        """
        import shutil

        if shutil.which("stdbuf"):
            return "stdbuf -oL"

        if shutil.which("unbuffer"):
            return "unbuffer"

        return None

    @staticmethod
    def _wrap_line_buffered(command: str) -> str:
        """
        Wrap a command to force line-buffered stdout when PTY is unavailable.

        When stdout is connected to a pipe instead of a TTY, most programs
        (Python, C, Ruby, etc.) use full buffering. The stdbuf command uses
        LD_PRELOAD to override buffering at the libc level. The unbuffer
        command (from expect) creates a PTY wrapper.

        The detected tool is cached after first check to avoid repeated
        subprocess/shell calls.

        Args:
            command: The shell command string

        Returns:
            Command wrapped with line-buffering prefix, or the original
            command if no tool is available
        """
        if BackgroundCommandManager._line_buffered_tool is None:
            BackgroundCommandManager._line_buffered_tool = (
                BackgroundCommandManager._detect_line_buffered_tool()
            )

        tool = BackgroundCommandManager._line_buffered_tool
        if tool:
            return f"{tool} {command}"

        return command

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
        import math

        if not output or len(output) <= page_size:
            return None

        folder_path = local_agent_folder_func(command_key)
        abs_folder = abs_root_path_func(folder_path)
        os.makedirs(abs_folder, exist_ok=True)

        num_pages = math.ceil((len(output) + page_size - 1) // page_size)

        for i in range(num_pages):
            page_num = i + 1
            filename = f"{page_num}.txt"
            abs_path = os.path.join(abs_folder, filename)
            page_content = output[i * page_size : (i + 1) * page_size]
            with safe_open(abs_path, "w") as f:
                f.write(page_content)

        file_paths = [f"{folder_path}/{page_num}.txt" for page_num in range(1, num_pages + 1)]
        alias_paths = [
            f"command_key::{command_key}/{page_num}.txt" for page_num in range(1, num_pages + 1)
        ]
        return (folder_path, file_paths, alias_paths)
