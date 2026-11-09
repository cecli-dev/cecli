"""PTY-backed terminals for the desktop bridge.

Each terminal is an independent interactive shell rooted at a workspace. The
ACP child keeps its own pipes; this module never multiplexes protocol traffic
with terminal input.
"""

from __future__ import annotations

import asyncio
import os
import signal
import struct
import subprocess
import time
from typing import Any

try:
    from .parent_death import child_parent_death_hook
except ImportError:  # pragma: no cover - the module also runs as a script
    from parent_death import child_parent_death_hook

TERMINAL_REPLAY_BYTES = 256 * 1024
TERMINAL_QUEUE_SIZE = 256
TERMINAL_MAX_INPUT = 64 * 1024
TERMINAL_READ_CHUNK = 64 * 1024
TERMINAL_DEFAULT_COLS = 100
TERMINAL_DEFAULT_ROWS = 30
TERMINAL_MAX_TERMINALS = 8
TERMINAL_MAX_PER_BRIDGE = 4
TERMINAL_EXITED_TTL = 900.0
TERMINAL_MAX_COLS = 500
TERMINAL_MAX_ROWS = 200
SHUTDOWN_TIMEOUT = 5.0


class TerminalError(RuntimeError):
    """A terminal API failure carrying the HTTP status it should become."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class TerminalBuffer:
    """A bounded byte ring that tracks absolute sequence offsets."""

    def __init__(self, limit: int = TERMINAL_REPLAY_BYTES) -> None:
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

    def snapshot(self, since: int | None = None) -> tuple[int, bytes, bool]:
        """Return ``(seq, bytes, reset)``; reset means ``since`` fell off the ring."""

        start = self.start_seq
        if since is None or since < start or since > self._seq:
            return (
                self._seq,
                bytes(self._data),
                since is not None and (since < start or since > self._seq),
            )
        offset = max(0, int(since) - start)
        return self._seq, bytes(self._data[offset:]), False

    def clear(self) -> None:
        self._data.clear()


class TerminalSession:
    """One interactive shell attached to a workspace."""

    def __init__(
        self,
        bridge_id: str,
        workspace: str,
        shell: str,
        cols: int = TERMINAL_DEFAULT_COLS,
        rows: int = TERMINAL_DEFAULT_ROWS,
    ) -> None:
        self.bridge_id = bridge_id
        self.id: str | None = None
        self.generation: int = 0
        self.workspace = workspace
        self.shell = shell
        self.cols = _clamp(cols, 20, TERMINAL_MAX_COLS)
        self.rows = _clamp(rows, 5, TERMINAL_MAX_ROWS)
        self.buffer = TerminalBuffer()
        self.process: subprocess.Popen[Any] | None = None
        self.master_fd: int | None = None
        self.started_at: float | None = None
        self.exit_code: int | None = None
        self.ended_at: float | None = None
        self.error: str | None = None
        self._subscribers: set[asyncio.Queue[tuple[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._write_lock: asyncio.Lock | None = None
        self._exit_sent = False
        self._closed = False

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None else None

    async def start(self) -> None:
        if self.running:
            return

        self._loop = asyncio.get_running_loop()
        import pty

        master_fd, slave_fd = pty.openpty()
        _set_winsize(slave_fd, self.cols, self.rows)
        env = dict(os.environ)
        env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor"})
        try:
            self.process = subprocess.Popen(
                [self.shell, "-i"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=self.workspace,
                env=env,
                start_new_session=True,
                close_fds=True,
                preexec_fn=child_parent_death_hook(),
            )
        except OSError as err:
            os.close(master_fd)
            os.close(slave_fd)
            self.error = str(err)
            raise TerminalError(500, f"could not start terminal: {err}") from err
        finally:
            try:
                os.close(slave_fd)
            except OSError:
                pass

        self.master_fd = master_fd
        self.started_at = time.time()
        self.exit_code = None
        self.ended_at = None
        self._exit_sent = False
        self._closed = False
        os.set_blocking(master_fd, False)
        self._loop.add_reader(master_fd, self._on_readable)

    async def stop(self) -> None:
        if self._closed and self.process is None:
            return
        self._closed = True
        self._remove_reader()
        process = self.process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                await asyncio.to_thread(process.wait, SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    try:
                        process.kill()
                    except OSError:
                        pass
                await asyncio.to_thread(process.wait, 2.0)
        self._drain_master()
        self._close_master()
        if self.exit_code is None:
            code = process.returncode if process is not None else None
            self.exit_code = code if code is not None else -1
        self.ended_at = self.ended_at or time.time()
        if not self._exit_sent:
            self._exit_sent = True
            self._publish("exit", self.exit_code)

    def write(self, data: bytes) -> int:
        if not data:
            return 0
        if len(data) > TERMINAL_MAX_INPUT:
            raise TerminalError(413, "terminal input is too large")
        if not self.running or self.master_fd is None:
            raise TerminalError(409, "terminal is not running")
        try:
            return os.write(self.master_fd, data)
        except OSError as err:
            raise TerminalError(409, f"terminal is not writable: {err}") from err

    async def write_async(self, data: bytes) -> int:
        lock = self._write_lock
        if lock is None:
            lock = self._write_lock = asyncio.Lock()
        async with lock:
            return await asyncio.to_thread(self.write, data)

    def resize(self, cols: int, rows: int) -> None:
        self.cols = _clamp(cols, 20, TERMINAL_MAX_COLS)
        self.rows = _clamp(rows, 5, TERMINAL_MAX_ROWS)
        if self.master_fd is not None:
            try:
                _set_winsize(self.master_fd, self.cols, self.rows)
            except OSError:
                pass

    def subscribe(self) -> asyncio.Queue[tuple[str, Any]]:
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=TERMINAL_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[tuple[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def state(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "bridgeId": self.bridge_id,
            "workspace": self.workspace,
            "shell": self.shell,
            "running": self.running,
            "pid": self.pid,
            "cols": self.cols,
            "rows": self.rows,
            "seq": self.buffer.seq,
            "bufferedBytes": self.buffer.seq - self.buffer.start_seq,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "exitCode": self.exit_code,
            "error": self.error,
        }

    def _on_readable(self) -> None:
        fd = self.master_fd
        if fd is None:
            return
        try:
            data = os.read(fd, TERMINAL_READ_CHUNK)
        except BlockingIOError:
            return
        except OSError:
            self._finish()
            return
        if not data:
            self._finish()
            return
        seq = self.buffer.append(data)
        self._publish("data", (seq, data))

    def _finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._remove_reader()
        self._close_master()
        process = self.process
        code = process.poll() if process is not None else None
        self.exit_code = code
        self.ended_at = self.ended_at or time.time()
        if not self._exit_sent:
            self._exit_sent = True
            self._publish("exit", self.exit_code)

    def _drain_master(self) -> None:
        """Flush bytes still queued in the PTY before the fd closes."""
        fd = self.master_fd
        if fd is None:
            return
        while True:
            try:
                data = os.read(fd, TERMINAL_READ_CHUNK)
            except (BlockingIOError, OSError):
                return
            if not data:
                return
            seq = self.buffer.append(data)
            self._publish("data", (seq, data))

    def _remove_reader(self) -> None:
        if self.master_fd is not None and self._loop is not None:
            try:
                self._loop.remove_reader(self.master_fd)
            except (ValueError, RuntimeError):
                pass

    def _close_master(self) -> None:
        if self.master_fd is None:
            return
        fd, self.master_fd = self.master_fd, None
        try:
            os.close(fd)
        except OSError:
            pass

    def _publish(self, kind: str, payload: Any) -> None:
        for queue in list(self._subscribers):
            while True:
                try:
                    queue.put_nowait((kind, payload))
                    break
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break


class PipeTerminalSession(TerminalSession):
    """Line-oriented stdin/stdout shell used when no PTY is available.

    This is deliberately not a full terminal: there is no resize, job control,
    readline editing or full-screen rendering. It exists so prompts and commands
    can be driven by stdin on Windows and other non-POSIX hosts.
    """

    def __init__(
        self,
        bridge_id: str,
        workspace: str,
        shell: str,
        cols: int = TERMINAL_DEFAULT_COLS,
        rows: int = TERMINAL_DEFAULT_ROWS,
    ) -> None:
        super().__init__(bridge_id, workspace, shell, cols, rows)
        self._pipe_process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[Any] | None = None

    @property
    def running(self) -> bool:
        return self._pipe_process is not None and self._pipe_process.returncode is None

    @property
    def pid(self) -> int | None:
        return self._pipe_process.pid if self._pipe_process is not None else None

    async def start(self) -> None:
        if self.running:
            return

        env = dict(os.environ)
        env.setdefault("TERM", "dumb")
        command = _pipe_shell_command(self.shell)
        try:
            self._pipe_process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.workspace,
                env=env,
                preexec_fn=child_parent_death_hook(),
            )
        except OSError as err:
            self.error = str(err)
            raise TerminalError(500, f"could not start terminal: {err}") from err
        self.started_at = time.time()
        self.exit_code = None
        self.ended_at = None
        self._closed = False
        self._exit_sent = False
        self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        if self._closed and self._pipe_process is None:
            return
        self._closed = True
        process = self._pipe_process
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (OSError, RuntimeError):
                    pass
            try:
                process.terminate()
            except (ProcessLookupError, OSError):
                pass
            try:
                await asyncio.wait_for(process.wait(), SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except (ProcessLookupError, OSError):
                    pass
                await process.wait()
        task = self._reader_task
        self._reader_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        code = process.returncode if process is not None else -1
        self._mark_exit(code if code is not None else -1)

    async def write_async(self, data: bytes) -> int:
        if not data:
            return 0
        if len(data) > TERMINAL_MAX_INPUT:
            raise TerminalError(413, "terminal input is too large")
        process = self._pipe_process
        if process is None or process.returncode is not None or process.stdin is None:
            raise TerminalError(409, "terminal is not running")
        lock = self._write_lock
        if lock is None:
            lock = self._write_lock = asyncio.Lock()
        async with lock:
            try:
                process.stdin.write(data)
                await process.stdin.drain()
            except (ConnectionError, OSError) as err:
                raise TerminalError(409, f"terminal is not writable: {err}") from err
        return len(data)

    def write(self, data: bytes) -> int:
        raise TerminalError(409, "pipe terminals use write_async")

    def resize(self, cols: int, rows: int) -> None:
        self.cols = _clamp(cols, 20, TERMINAL_MAX_COLS)
        self.rows = _clamp(rows, 5, TERMINAL_MAX_ROWS)

    async def _read_loop(self) -> None:
        process = self._pipe_process
        if process is None or process.stdout is None:
            return
        try:
            while True:
                data = await process.stdout.read(TERMINAL_READ_CHUNK)
                if not data:
                    break
                seq = self.buffer.append(data)
                self._publish("data", (seq, data))
            code = await process.wait()
        except (ConnectionError, OSError):
            code = process.returncode or -1
        self._mark_exit(code if code is not None else -1)

    def _mark_exit(self, code: int) -> None:
        self.exit_code = code
        self.ended_at = self.ended_at or time.time()
        if self._exit_sent:
            return
        self._exit_sent = True
        self._publish("exit", code)


class ConPtyTerminalSession(PipeTerminalSession):
    """Windows ConPTY shell used only when ``pywinpty`` is installed."""

    backend = "conpty"

    def __init__(
        self,
        bridge_id: str,
        workspace: str,
        shell: str,
        cols: int = TERMINAL_DEFAULT_COLS,
        rows: int = TERMINAL_DEFAULT_ROWS,
    ) -> None:
        super().__init__(bridge_id, workspace, shell, cols, rows)
        self._pty: Any = None

    @property
    def running(self) -> bool:
        return self._pty is not None and bool(self._pty.isalive())

    @property
    def pid(self) -> int | None:
        return getattr(self._pty, "pid", None) if self._pty is not None else None

    async def start(self) -> None:
        if self.running:
            return
        try:
            from winpty import PtyProcess
        except ImportError as err:
            raise TerminalError(
                500, "ConPTY backend requires the optional pywinpty package"
            ) from err
        try:
            self._pty = PtyProcess.spawn(
                self.shell, dimensions=(self.rows, self.cols), cwd=self.workspace
            )
        except OSError as err:
            self.error = str(err)
            raise TerminalError(500, f"could not start terminal: {err}") from err
        self.started_at = time.time()
        self.exit_code = None
        self.ended_at = None
        self._closed = False
        self._exit_sent = False
        self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        pty = self._pty
        if pty is not None:
            try:
                pty.terminate(force=True)
            except Exception:
                pass
        task = self._reader_task
        self._reader_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        code = getattr(pty, "exitstatus", None) if pty is not None else None
        self._mark_exit(code if code is not None else -1)

    async def write_async(self, data: bytes) -> int:
        if not data:
            return 0
        if len(data) > TERMINAL_MAX_INPUT:
            raise TerminalError(413, "terminal input is too large")
        pty = self._pty
        if pty is None or not self.running:
            raise TerminalError(409, "terminal is not running")
        try:
            await asyncio.to_thread(pty.write, data.decode("utf-8", "ignore"))
        except (ConnectionError, OSError) as err:
            raise TerminalError(409, f"terminal is not writable: {err}") from err
        return len(data)

    def resize(self, cols: int, rows: int) -> None:
        self.cols = _clamp(cols, 20, TERMINAL_MAX_COLS)
        self.rows = _clamp(rows, 5, TERMINAL_MAX_ROWS)
        pty = self._pty
        if pty is not None:
            try:
                pty.setwinsize(self.rows, self.cols)
            except Exception:
                pass

    async def _read_loop(self) -> None:
        pty = self._pty
        if pty is None:
            return
        while True:
            try:
                data = await asyncio.to_thread(pty.read, TERMINAL_READ_CHUNK)
            except (EOFError, OSError):
                break
            if not data:
                break
            raw = data.encode("utf-8", "ignore") if isinstance(data, str) else data
            seq = self.buffer.append(raw)
            self._publish("data", (seq, raw))
        code = getattr(pty, "exitstatus", None)
        self._mark_exit(code if code is not None else -1)


class TerminalManager:
    """Owns per-bridge terminal generations with retention and TTL."""

    EXITED_TTL = TERMINAL_EXITED_TTL

    def __init__(
        self,
        enabled: bool = False,
        shell: str | None = None,
        limit: int = TERMINAL_REPLAY_BYTES,
        backend: str | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        requested = (
            (backend or os.environ.get("CECLI_DESKTOP_TERMINAL_BACKEND", "")).strip().lower()
        )
        if requested and requested not in ("pty", "pipe", "conpty"):
            raise TerminalError(400, f"unknown terminal backend: {requested}")
        if not requested:
            requested = "pty" if os.name == "posix" else "pipe"
        self.backend = requested
        if shell:
            self.shell = shell
        elif os.name == "posix":
            self.shell = os.environ.get("SHELL") or "/bin/sh"
        else:
            self.shell = os.environ.get("COMSPEC") or "cmd.exe"
        self.limit = limit
        self.exited_ttl = TERMINAL_EXITED_TTL
        self._terminals: dict[str, TerminalSession] = {}
        self._latest: dict[str, str] = {}
        self._generation: dict[str, int] = {}

    def available(self) -> bool:
        if not self.enabled:
            return False
        if self.backend == "pipe":
            return bool(self.shell)
        if self.backend == "conpty":
            if os.name != "nt":
                return False
            try:
                import winpty  # noqa: F401
            except ImportError:
                return False
            return True
        return os.name == "posix" and os.path.exists(self.shell)

    def get(self, bridge_id: str) -> TerminalSession | None:
        terminal_id = self._latest.get(str(bridge_id))
        return self._terminals.get(terminal_id) if terminal_id else None

    def get_by_id(self, terminal_id: str) -> TerminalSession | None:
        return self._terminals.get(str(terminal_id))

    def terminals(self, bridge_id: str) -> list[dict[str, Any]]:
        return [
            session.state()
            for session in self._terminals.values()
            if str(session.bridge_id) == str(bridge_id)
        ]

    def get_or_create(self, bridge_id: str, workspace: str) -> TerminalSession:
        """Create or reuse a shell; ConPTY falls back to pipe on Windows only."""
        conpty_fallback = False
        if self.backend == "conpty" and not self.available():
            if os.name != "nt":
                raise TerminalError(
                    500,
                    "ConPTY requires Windows with the optional pywinpty package; "
                    "set CECLI_DESKTOP_TERMINAL_BACKEND=pty or pipe",
                )
            conpty_fallback = True
        if not self.available() and not conpty_fallback:
            raise TerminalError(403, "interactive terminal is disabled")
        if not workspace or not os.path.isdir(workspace):
            workspace = os.getcwd()
        bridge_key = str(bridge_id)
        session = self.get(bridge_key)
        if session is not None and session.ended_at is None:
            return session
        retained = sum(1 for item in self._terminals.values() if str(item.bridge_id) == bridge_key)
        if retained >= TERMINAL_MAX_PER_BRIDGE:
            self._drop_expired()
            retained = sum(
                1 for item in self._terminals.values() if str(item.bridge_id) == bridge_key
            )
        if retained >= TERMINAL_MAX_PER_BRIDGE:
            raise TerminalError(
                409, f"At most {TERMINAL_MAX_PER_BRIDGE} terminals per workspace are supported"
            )
        active = sum(1 for item in self._terminals.values() if item.ended_at is None)
        if active >= TERMINAL_MAX_TERMINALS:
            raise TerminalError(409, f"At most {TERMINAL_MAX_TERMINALS} terminals are supported")

        generation = self._generation.get(bridge_key, 0) + 1
        self._generation[bridge_key] = generation
        session_class: type[TerminalSession]
        if self.backend == "conpty" and self.available():
            session_class = ConPtyTerminalSession
        elif self.backend == "pipe" or conpty_fallback or os.name != "posix":
            session_class = PipeTerminalSession
        else:
            session_class = TerminalSession
        session = session_class(bridge_key, workspace, self.shell)
        session.generation = generation
        session.id = f"term:{bridge_key}:{generation}"
        self._terminals[session.id] = session
        self._latest[bridge_key] = session.id
        return session

    async def stop(self, bridge_id: str) -> None:
        session = self.get(bridge_id)
        if session is not None:
            await session.stop()

    async def stop_by_id(self, terminal_id: str) -> None:
        session = self.get_by_id(terminal_id)
        if session is not None:
            await session.stop()

    async def close(self, bridge_id: str) -> None:
        session = self.get(bridge_id)
        if session is None:
            return
        self._terminals.pop(session.id, None)
        if session.id is not None and self._latest.get(str(bridge_id)) == session.id:
            self._latest.pop(str(bridge_id), None)
        await session.stop()

    async def close_by_id(self, terminal_id: str) -> bool:
        session = self.get_by_id(terminal_id)
        if session is None:
            return False
        self._terminals.pop(str(terminal_id), None)
        bridge_key = str(session.bridge_id)
        if self._latest.get(bridge_key) == str(terminal_id):
            self._latest.pop(bridge_key, None)
        await session.stop()
        return True

    async def reap(self, now: float | None = None) -> list[str]:
        """Drop exited terminals older than ``exited_ttl`` and return their ids."""
        return self._drop_expired(now)

    def _drop_expired(self, now: float | None = None) -> list[str]:
        moment = time.time() if now is None else now
        dropped = []
        for terminal_id, session in list(self._terminals.items()):
            if session.ended_at is None:
                continue
            if moment - session.ended_at < self.exited_ttl:
                continue
            dropped.append(terminal_id)
            self._terminals.pop(terminal_id, None)
            bridge_key = str(session.bridge_id)
            if self._latest.get(bridge_key) == terminal_id:
                self._latest.pop(bridge_key, None)
        return dropped

    async def shutdown(self) -> None:
        sessions = list(self._terminals.values())
        self._terminals.clear()
        self._latest.clear()
        await asyncio.gather(*(session.stop() for session in sessions), return_exceptions=True)

    def state(self, bridge_id: str) -> dict[str, Any]:
        session = self.get(bridge_id)
        base = {
            "enabled": bool(self.enabled),
            "available": self.available(),
            "backend": self.backend,
            "effectiveBackend": (
                "pipe" if self.backend == "conpty" and not self.available() else self.backend
            ),
            "bridgeId": str(bridge_id),
            "id": session.id if session is not None else None,
            "running": False,
            "seq": 0,
            "cols": TERMINAL_DEFAULT_COLS,
            "rows": TERMINAL_DEFAULT_ROWS,
            "shell": self.shell,
            "endedAt": None,
            "exitCode": None,
        }
        if session is not None:
            base.update(session.state())
            base["backend"] = self.backend
        return base


def _pipe_shell_command(shell: str) -> str:
    """Command line for the line-oriented pipe backend."""

    quoted = f'"{shell}"'
    if os.name == "nt":
        lowered = shell.lower()
        if lowered.endswith(("powershell.exe", "pwsh.exe")):
            return f"{quoted} -NoLogo -NoProfile -NoExit -Command -"
        return f"{quoted} /Q /K"
    return quoted


def replay_offsets(seq: int, length: int, since: int | None, reset: bool) -> tuple[int, int]:
    """Return FIX A ``(start, first)`` offsets for replay control frames.

    ``seq`` is the END offset and ``length`` the replayed byte count. ``start``
    is the first byte in the replay; ``first`` is the cursor a client adopts —
    the start on reset/first connect, otherwise the requested ``since``.
    """
    start = int(seq) - int(length)
    if reset or since is None:
        return start, start
    return start, max(int(since), start)


def _clamp(value: Any, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = low
    return max(low, min(high, number))


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    import fcntl
    import termios

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
