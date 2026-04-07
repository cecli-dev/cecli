import os
import selectors
import sys
import threading


class InterruptibleInput:
    """
    Unix-only, interruptible replacement for input(), designed for:
      await asyncio.get_event_loop().run_in_executor(None, obj.input, prompt)

    interrupt() is safe from any thread.
    """

    def __init__(self):
        if os.name == "nt":
            raise RuntimeError("InterruptibleInput is Unix-only (requires selectable stdin).")

        self._cancel = threading.Event()

        # The default selector (Kqueue on macOS, Epoll on Linux) cannot
        # handle pipe-based stdin (e.g. when running inside Emacs comint-mode).
        # Fall back to SelectSelector which works with any fd that supports select().
        if not sys.stdin.isatty():
            self._sel = selectors.SelectSelector()
        else:
            self._sel = selectors.DefaultSelector()

        # self-pipe to wake up select() from interrupt()
        self._r, self._w = os.pipe()
        os.set_blocking(self._r, False)
        os.set_blocking(self._w, False)
        self._sel.register(self._r, selectors.EVENT_READ, data="__wakeup__")

    def close(self) -> None:
        try:
            self._sel.unregister(self._r)
        except Exception:
            pass
        try:
            os.close(self._r)
        except Exception:
            pass
        try:
            os.close(self._w)
        except Exception:
            pass
        try:
            self._sel.close()
        except Exception:
            pass

    def interrupt(self) -> None:
        self._cancel.set()
        try:
            os.write(self._w, b"\x01")  # wake selector immediately
        except BlockingIOError:
            pass
        except OSError:
            pass

    def input(self, prompt: str = "") -> str:
        if prompt:
            sys.stdout.write(prompt)
            sys.stdout.flush()

        if self._cancel.is_set():
            self._cancel.clear()
            raise InterruptedError("Input interrupted")

        stdin = sys.stdin
        fd = stdin.fileno()

        self._sel.register(fd, selectors.EVENT_READ, data="__stdin__")
        try:
            while True:
                for key, _ in self._sel.select():
                    if key.data == "__wakeup__":
                        # drain wake bytes
                        try:
                            while os.read(self._r, 1024):
                                pass
                        except BlockingIOError:
                            pass

                        if self._cancel.is_set():
                            self._cancel.clear()
                            raise InterruptedError("Input interrupted")
                        continue

                    if key.data == "__stdin__":
                        line = stdin.readline()
                        if line == "":
                            raise EOFError
                        return line.rstrip("\n")
        finally:
            try:
                self._sel.unregister(fd)
            except Exception:
                pass
