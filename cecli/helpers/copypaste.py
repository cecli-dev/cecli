import threading
import time

import pyperclip


class ClipboardError(Exception):
    """Raised when clipboard operations fail."""


class ClipboardStopped(Exception):
    """Raised when clipboard monitoring stops before a change occurs."""


def copy_to_clipboard(text):
    """Copy text to the system clipboard."""
    try:
        pyperclip.copy(text)
    except Exception as err:  # pragma: no cover - system clipboard errors
        raise ClipboardError(err) from err


def read_clipboard():
    """Read text from the system clipboard."""
    try:
        return pyperclip.paste()
    except Exception as err:  # pragma: no cover - system clipboard errors
        raise ClipboardError(err) from err


def wait_for_clipboard_change(initial=None, poll_interval=0.5, stop_event=None):
    """Block until the clipboard value changes and return the new contents."""
    last_value = initial
    if last_value is None:
        last_value = read_clipboard()

    while True:
        current = read_clipboard()
        if current != last_value:
            return current

        if stop_event:
            if stop_event.wait(poll_interval):
                raise ClipboardStopped()
        else:
            time.sleep(poll_interval)


class ClipboardWatcher:
    """Watches clipboard for changes and updates IO placeholder."""

    def __init__(self, io, verbose=False):
        self.io = io
        self.verbose = verbose
        self.stop_event = None
        self.watcher_thread = None
        self.last_clipboard = None
        self.io.clipboard_watcher = self

    def start(self):
        """Start watching clipboard for changes."""
        self.stop_event = threading.Event()
        self.last_clipboard = read_clipboard()

        def watch_clipboard():
            while not self.stop_event.is_set():
                try:
                    current = wait_for_clipboard_change(
                        initial=self.last_clipboard,
                        stop_event=self.stop_event,
                    )
                except ClipboardStopped:
                    break
                except ClipboardError as err:
                    if self.verbose:
                        from cecli.dump import dump

                        dump(f"Clipboard watcher error: {err}")
                    continue
                except Exception as err:  # pragma: no cover - unexpected errors
                    if self.verbose:
                        from cecli.dump import dump

                        dump(f"Clipboard watcher unexpected error: {err}")
                    continue

                self.last_clipboard = current
                self.io.interrupt_input()
                self.io.placeholder = current
                if len(current.splitlines()) > 1:
                    self.io.placeholder = "\n" + self.io.placeholder + "\n"

        self.watcher_thread = threading.Thread(target=watch_clipboard, daemon=True)
        self.watcher_thread.start()

    def stop(self):
        """Stop watching clipboard for changes."""
        if self.stop_event:
            self.stop_event.set()
        if self.watcher_thread:
            self.watcher_thread.join()
            self.watcher_thread = None
            self.stop_event = None


def main():
    """Example usage of the clipboard watcher."""
    from cecli.io import InputOutput

    io = InputOutput()
    watcher = ClipboardWatcher(io, verbose=True)

    try:
        watcher.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped watching clipboard")
        watcher.stop()


if __name__ == "__main__":
    main()
