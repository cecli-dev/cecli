"""Python client for the ``ce-underscore`` app-harness bridge.

``EXPECTED_BRIDGE_VERSION`` must match the Cargo workspace version, so bump
both together or the client rejects the bridge.
"""

from .client import (
    EXPECTED_BRIDGE_VERSION,
    AppClient,
    AppHarnessError,
    BridgeFile,
    BridgeUnavailable,
    VersionMismatch,
    _find_binary,
    discover_bridge_file,
    load_bridge_file,
)
from .models import (
    ActionResult,
    CheckResult,
    DoctorReport,
    Element,
    Rect,
    Snapshot,
    StateInfo,
    Window,
)


def is_app_harness_available():
    """Return True when the app-harness bridge is installed or already running."""

    return _find_binary() is not None or discover_bridge_file() is not None


__all__ = [
    "EXPECTED_BRIDGE_VERSION",
    "ActionResult",
    "AppClient",
    "AppHarnessError",
    "BridgeFile",
    "BridgeUnavailable",
    "CheckResult",
    "DoctorReport",
    "Element",
    "Rect",
    "Snapshot",
    "StateInfo",
    "VersionMismatch",
    "Window",
    "discover_bridge_file",
    "is_app_harness_available",
    "load_bridge_file",
]
