"""
Tests for the throttled memory-trimming helper (cecli/helpers/memory_control.py).

Covers:
- Throttle boundary (first call runs, calls within the window are skipped, expiry re-runs)
- Platform branches (Linux calls malloc_trim; non-Linux does gc-only)
- Defensive error handling (OSError/AttributeError/impl failures are swallowed)
- Concurrent callers cannot both pass the throttle window
- libc signature configuration (argtypes/restype)
"""

import ctypes
import ctypes.util
import threading
from types import SimpleNamespace

import pytest

from cecli.helpers import memory_control


@pytest.fixture(autouse=True)
def _reset_trim_state():
    """Reset throttle state before/after each test."""
    memory_control._LAST_TRIM_TIME = 0.0
    yield
    memory_control._LAST_TRIM_TIME = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_clock(monkeypatch, start=0.0):
    """Replace time.monotonic with a controllable clock; return its state dict."""
    clock = {"now": start}
    monkeypatch.setattr(memory_control.time, "monotonic", lambda: clock["now"])
    return clock


def _install_gc_counter(monkeypatch, counter):
    """Count gc.collect() calls via a dict counter (also swallows real GC)."""

    def _collect():
        counter["gc_calls"] += 1
        return 0

    monkeypatch.setattr("gc.collect", _collect)


# ---------------------------------------------------------------------------
# Throttle behavior
# ---------------------------------------------------------------------------


def test_first_call_runs_gc(monkeypatch):
    counter = {"gc_calls": 0}
    _install_clock(monkeypatch, start=1000.0)
    monkeypatch.setattr("sys.platform", "win32")
    _install_gc_counter(monkeypatch, counter)

    memory_control.trim_memory()

    assert counter["gc_calls"] == 1


def test_calls_within_window_are_throttled(monkeypatch):
    counter = {"gc_calls": 0}
    clock = _install_clock(monkeypatch, start=1000.0)
    monkeypatch.setattr("sys.platform", "win32")
    _install_gc_counter(monkeypatch, counter)

    memory_control.trim_memory()
    clock["now"] += 10.0
    memory_control.trim_memory()

    assert counter["gc_calls"] == 1


def test_call_after_window_elapses_runs_again(monkeypatch):
    counter = {"gc_calls": 0}
    clock = _install_clock(monkeypatch, start=1000.0)
    monkeypatch.setattr("sys.platform", "win32")
    _install_gc_counter(monkeypatch, counter)

    memory_control.trim_memory()
    clock["now"] += 121.0
    memory_control.trim_memory()

    assert counter["gc_calls"] == 2


# ---------------------------------------------------------------------------
# Platform branches
# ---------------------------------------------------------------------------


def test_non_linux_does_gc_only(monkeypatch):
    counter = {"gc_calls": 0}
    _install_clock(monkeypatch, start=1000.0)
    monkeypatch.setattr("sys.platform", "darwin")
    _install_gc_counter(monkeypatch, counter)

    def _fail_if_called():
        raise AssertionError("_load_libc must not be called on non-Linux")

    monkeypatch.setattr(memory_control, "_load_libc", _fail_if_called)

    memory_control.trim_memory()

    assert counter["gc_calls"] == 1


def test_linux_calls_malloc_trim(monkeypatch):
    counter = {"gc_calls": 0, "trim_calls": 0}
    _install_clock(monkeypatch, start=1000.0)
    monkeypatch.setattr("sys.platform", "linux")
    _install_gc_counter(monkeypatch, counter)

    def _fake_load_libc():
        def _malloc_trim(pad):
            counter["trim_calls"] += 1
            return 1

        return SimpleNamespace(malloc_trim=_malloc_trim)

    monkeypatch.setattr(memory_control, "_load_libc", _fake_load_libc)

    memory_control.trim_memory()

    assert counter["gc_calls"] == 1
    assert counter["trim_calls"] == 1


# ---------------------------------------------------------------------------
# Defensive error handling
# ---------------------------------------------------------------------------


def test_linux_oserror_is_swallowed(monkeypatch):
    counter = {"gc_calls": 0}
    _install_clock(monkeypatch, start=1000.0)
    monkeypatch.setattr("sys.platform", "linux")
    _install_gc_counter(monkeypatch, counter)

    def _raise_oserror():
        raise OSError("libc not found (likely musl)")

    monkeypatch.setattr(memory_control, "_load_libc", _raise_oserror)

    memory_control.trim_memory()  # must not raise

    assert counter["gc_calls"] == 1


def test_linux_attribute_error_is_swallowed(monkeypatch):
    _install_clock(monkeypatch, start=1000.0)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("gc.collect", lambda: 0)

    def _no_malloc_trim():
        raise AttributeError("malloc_trim not found")

    monkeypatch.setattr(memory_control, "_load_libc", _no_malloc_trim)

    memory_control.trim_memory()  # must not raise


def test_impl_exception_is_swallowed(monkeypatch):
    _install_clock(monkeypatch, start=1000.0)

    def _boom():
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(memory_control, "_trim_memory_impl", _boom)

    memory_control.trim_memory()  # must not raise


# ---------------------------------------------------------------------------
# Concurrency / libc signature
# ---------------------------------------------------------------------------


def test_concurrent_caller_throttled_during_run(monkeypatch):
    _install_clock(monkeypatch, start=1000.0)
    entered = threading.Event()
    release = threading.Event()

    def _slow_impl():
        entered.set()
        release.wait(5)

    monkeypatch.setattr(memory_control, "_trim_memory_impl", _slow_impl)

    worker = threading.Thread(target=memory_control.trim_memory)
    worker.start()
    assert entered.wait(5)

    # A second caller arriving while the first trim is still running is throttled.
    memory_control.trim_memory()  # must return immediately without re-running

    release.set()
    worker.join(5)

    assert not worker.is_alive()


def test_load_libc_configures_signature(monkeypatch):
    calls = {}
    fake_malloc_trim = SimpleNamespace()

    def _fake_find_library(name):
        calls["name"] = name
        return "libfake.so"

    class _FakeCDLL:
        def __init__(self, name):
            calls["cdll_name"] = name

        @property
        def malloc_trim(self):
            return fake_malloc_trim

    monkeypatch.setattr("ctypes.util.find_library", _fake_find_library)
    monkeypatch.setattr("ctypes.CDLL", _FakeCDLL)

    libc = memory_control._load_libc()

    assert isinstance(libc, _FakeCDLL)
    assert calls["name"] == "c"
    assert calls["cdll_name"] == "libfake.so"
    assert fake_malloc_trim.argtypes == [ctypes.c_size_t]
    assert fake_malloc_trim.restype == ctypes.c_int
