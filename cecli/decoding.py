"""
Encoding-aware file operations with automatic encoding detection for reading
and configurable encoding for writing.

Provides safe_open() as a drop-in replacement for built-in open() that handles
encoding intelligently on reads, smart_read() for direct file reading with
fallback encoding detection via charset_normalizer, and safe_write() for
writing files with a configurable default encoding.

The module-level DEFAULT_ENCODING variable can be overridden at runtime
(e.g., from main.py) to set the preferred encoding for write operations.
"""

import charset_normalizer

# Global encoding setting used by safe_open() and safe_write() for write
# operations. Can be overridden at runtime from main.py or elsewhere.
DEFAULT_ENCODING = "utf-8"


def smart_read(filepath):
    """
    Read a text file, automatically detecting the encoding if not UTF-8.

    Attempts a fast UTF-8 decode first using Python's optimized native
    decoder. Falls back to charset_normalizer for legacy encodings (e.g.
    GBK, Latin-1, Shift-JIS) when a UnicodeDecodeError is raised.

    Args:
        filepath: Path to the file to read.

    Returns:
        The file contents as a string.

    Raises:
        ValueError: If the encoding cannot be determined.
        FileNotFoundError: If the file does not exist.
    """
    try:
        # FAST PATH: Try standard UTF-8 first using Python's optimized
        # native decoder — this handles the vast majority of modern files.
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    except UnicodeDecodeError:
        # SLOW PATH: A decode error means this is likely a legacy encoding.
        # Let the library read the raw bytes and guess the correct encoding.
        results = charset_normalizer.from_path(filepath)
        match = results.best()

        if match is None:
            raise ValueError(f"Could not determine text encoding for {filepath}")

        return str(match)


def safe_write(filepath, content, encoding=None):
    """
    Write string content to a file using the specified or default encoding.

    Args:
        filepath: Path to the file to write.
        content: The string content to write.
        encoding: Encoding to use. Defaults to the module-level
            DEFAULT_ENCODING if not provided.

    Returns:
        The content that was written (for convenience / chaining).
    """
    if encoding is None:
        encoding = DEFAULT_ENCODING

    with open(filepath, "w", encoding=encoding) as f:
        f.write(content)

    return content


def safe_open(filepath, mode="r", encoding=None, **kwargs):
    """
    Open a file with intelligent encoding handling.
    """
    # Binary modes — pass through to built-in open() unchanged.
    if "b" in mode:
        return open(filepath, mode, **kwargs)

    # If the user explicitly provided an encoding, respect it unconditionally.
    if encoding is not None:
        return open(filepath, mode, encoding=encoding, **kwargs)

    # Write / append modes (with no explicit encoding) — use DEFAULT_ENCODING.
    # Note: We don't check for "r+" here because if a file is being read,
    # we must detect its existing encoding first so we don't corrupt it.
    if "w" in mode or "a" in mode or "x" in mode:
        return open(filepath, mode, encoding=DEFAULT_ENCODING, **kwargs)

    # Read modes (and read/write "r+" modes) — Auto-detect the encoding.
    try:
        # FAST PATH: Try UTF-8 first by opening and reading a tiny chunk
        with open(filepath, mode, encoding="utf-8", **kwargs) as f:
            f.read(1)  # Test if it raises a DecodeError

        # If we got here, UTF-8 is valid. Return a fresh file object.
        return open(filepath, mode, encoding="utf-8", **kwargs)

    except UnicodeDecodeError:
        # SLOW PATH: Detect encoding using charset_normalizer
        results = charset_normalizer.from_path(filepath)
        match = results.best()

        if match is None:
            raise ValueError(f"Could not determine text encoding for {filepath}")

        # Return a real file object using the detected encoding
        return open(filepath, mode, encoding=match.encoding, **kwargs)
