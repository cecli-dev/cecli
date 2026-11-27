"""Compatibility shim: the implementation lives in cecli.helpers.desktop."""

import sys as _sys

from cecli.helpers.desktop import parent_death as _impl

_sys.modules[__name__] = _impl
