import base64
import time
from typing import Callable

from cecli.utils import is_image_file


class FileIO:
    def __init__(
        self,
        *,
        encoding: str,
        line_endings: str,
        newline: str | None,
        dry_run: bool,
        tool_error: Callable,
    ):
        self.encoding = encoding
        self.line_endings = line_endings
        self.newline = newline
        self.dry_run = dry_run
        self.tool_error = tool_error

    def read_image(self, filename: str):
        try:
            with open(str(filename), "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read())
                return encoded_string.decode("utf-8")
        except OSError as err:
            self.tool_error(f"{filename}: unable to read: {err}")
            return
        except FileNotFoundError:
            self.tool_error(f"{filename}: file not found error")
            return
        except IsADirectoryError:
            self.tool_error(f"{filename}: is a directory")
            return
        except Exception as e:
            self.tool_error(f"{filename}: {e}")
            return

    def read_text(self, filename: str, silent: bool = False):
        if is_image_file(filename):
            return self.read_image(filename)

        try:
            with open(str(filename), "r", encoding=self.encoding) as f:
                return f.read()
        except FileNotFoundError:
            if not silent:
                self.tool_error(f"{filename}: file not found error")
            return
        except IsADirectoryError:
            if not silent:
                self.tool_error(f"{filename}: is a directory")
            return
        except OSError as err:
            if not silent:
                self.tool_error(f"{filename}: unable to read: {err}")
            return
        except UnicodeError as e:
            if not silent:
                self.tool_error(f"{filename}: {e}")
                self.tool_error("Use --encoding to set the unicode encoding.")
            return

    def _detect_newline(self, filename: str):
        try:
            with open(filename, "rb") as f:
                chunk = f.read(1024)
                if b"\r\n" in chunk:
                    return "\r\n"
                elif b"\n" in chunk:
                    return "\n"
        except (FileNotFoundError, IsADirectoryError):
            pass  # File doesn't exist or is a directory, will use default
        return None

    def write_text(
        self,
        filename: str,
        content: str,
        max_retries: int = 5,
        initial_delay: float = 0.1,
    ):
        """
        Writes content to a file, retrying with progressive backoff if the file is locked.

        :param filename: Path to the file to write.
        :param content: Content to write to the file.
        :param max_retries: Maximum number of retries if a file lock is encountered.
        :param initial_delay: Initial delay (in seconds) before the first retry.
        """
        if self.dry_run:
            return

        newline = self.newline
        if self.line_endings == "preserve":
            newline = self._detect_newline(filename) or self.newline

        delay = initial_delay
        for attempt in range(max_retries):
            try:
                with open(str(filename), "w", encoding=self.encoding, newline=newline) as f:
                    f.write(content)
                return  # Successfully wrote the file
            except PermissionError as err:
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    self.tool_error(
                        f"Unable to write file {filename} after {max_retries} attempts: {err}"
                    )
                    raise
            except OSError as err:
                self.tool_error(f"Unable to write file {filename}: {err}")
                raise
