"""Pytest path setup for spec tests (helpers is not an installed package)."""

from __future__ import annotations

import sys
from pathlib import Path

_SPEC_DIR = Path(__file__).resolve().parent
if str(_SPEC_DIR) not in sys.path:
    sys.path.insert(0, str(_SPEC_DIR))
