"""Desktop bridge hosted by the cecli ACP process.

The implementation in this package used to live under ``desktop/`` and run as
a separate Python process that spawned ``cecli --acp``. It now runs inside the
ACP process so the desktop only needs one interpreter. ``desktop/server.py``
remains as a launcher (and an import-compatible shim for the tests).
"""
