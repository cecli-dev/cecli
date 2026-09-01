import logging
import threading
import time

logger = logging.getLogger(__name__)

# Global variables for throttling
_LAST_TRIM_TIME = 0.0
_TRIM_THROTTLE_SECONDS = 15.0
_TRIM_LOCK = threading.Lock()


def trim_memory():
    """
    Attempt to release unused memory back to the operating system.

    Runs gc.collect() first, then makes OS-specific calls. On non-Linux
    platforms this degrades to a gc-only pass. Throttled to run at most
    once every 15 seconds.
    """
    global _LAST_TRIM_TIME

    current_time = time.monotonic()

    # Atomically check-and-update the throttle so concurrent callers
    # (TUI, command runner, MCP threads) cannot both pass the window.
    with _TRIM_LOCK:
        if current_time - _LAST_TRIM_TIME < _TRIM_THROTTLE_SECONDS:
            logger.debug(
                f"trim_memory() throttled. (Ran {current_time - _LAST_TRIM_TIME:.1f}s ago)"
            )
            return

        # Update the timestamp for this run
        _LAST_TRIM_TIME = current_time

    # Defensive guard: never let memory-trimming failure break the caller.
    try:
        _trim_memory_impl()
    except Exception as e:
        logger.warning(f"trim_memory() failed: {e}", exc_info=True)


def _rss_kb():
    """Return current RSS in KB from /proc/self/status (0 if unavailable)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _load_libc():
    """Load the C library and configure the malloc_trim signature."""
    import ctypes
    import ctypes.util

    libc_name = ctypes.util.find_library("c") or "libc.so.6"
    libc = ctypes.CDLL(libc_name)
    libc.malloc_trim.argtypes = [ctypes.c_size_t]
    libc.malloc_trim.restype = ctypes.c_int
    return libc


def _trim_memory_impl():
    """Run the gc.collect() + OS-specific memory trimming work."""
    import gc
    import sys

    # 1. First, force Python to clean up unreferenced objects
    reclaimed = gc.collect()
    logger.debug(f"Python GC reclaimed {reclaimed} objects.")

    # 2. Make OS-specific calls to release the empty space
    if sys.platform.startswith("linux"):
        try:
            libc = _load_libc()
            result = libc.malloc_trim(0)
            if result:
                logger.debug("Linux: malloc_trim(0) successfully released memory to the OS.")
            else:
                logger.debug("Linux: malloc_trim(0) ran, but no memory was released.")
        except OSError as e:
            logger.info(f"Linux: glibc not found (likely musl). Skipping malloc_trim. ({e})")
        except AttributeError as e:
            logger.info(f"Linux: malloc_trim not supported by this C library. ({e})")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    before = _rss_kb()
    trim_memory()
    after = _rss_kb()

    print(f"RSS before: {before} KB, after: {after} KB, delta: {after - before} KB")
