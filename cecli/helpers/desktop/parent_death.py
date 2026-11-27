"""Linux parent-death signals for bridge-owned child processes.

Both the bridge and the processes it spawns use ``start_new_session`` so a
terminal or shell cannot signal them. That also means they escape the normal
process-group cleanup when their parent dies, so each one opts into the kernel's
parent-death signal instead.
"""

from __future__ import annotations

import ctypes
import os
import signal
import sys
from typing import Callable

_PR_SET_PDEATHSIG = 1
KEEP_ON_PARENT_EXIT = "CECLI_DESKTOP_KEEP_ON_PARENT_EXIT"


def arm_parent_death() -> None:
    """Ask Linux to terminate this process when its parent exits."""
    if not sys.platform.startswith("linux"):
        return

    if os.environ.get(KEEP_ON_PARENT_EXIT, "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return

    parent_pid = os.getppid()
    if parent_pid <= 1:
        return

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(_PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0) != 0:
            return
    except OSError:
        return

    if os.getppid() != parent_pid:
        raise SystemExit(0)


def child_parent_death_hook() -> Callable[[], None] | None:
    """Return a pre-exec hook that ties a Linux child to this process."""
    if not sys.platform.startswith("linux"):
        return None

    parent_pid = os.getpid()
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None

    def arm() -> None:
        libc.prctl(_PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0)
        if os.getppid() != parent_pid:
            os._exit(0)

    return arm
