"""Compatibility shim: the implementation lives in cecli.helpers.desktop."""

import sys as _sys

from cecli.helpers.desktop import terminal as _impl

_sys.modules[__name__] = _impl
