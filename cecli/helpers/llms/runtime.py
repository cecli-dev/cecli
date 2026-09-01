"""Runtime knobs for the llms package (import-light, no heavy deps).

The dispatcher and domain adapters read :data:`VERIFY_SSL` when constructing
httpx clients so ``--no-verify-ssl`` keeps working after the litellm swap
(litellm previously patched ``client_session``/``aclient_session`` globals).
"""

from __future__ import annotations

import ssl
from typing import Any

from cecli.http import httpx

#: Global TLS verification flag; set False for ``--no-verify-ssl``.
VERIFY_SSL = True


def set_verify_ssl(verify: bool) -> None:
    """Set whether outbound httpx clients verify TLS certificates."""
    global VERIFY_SSL

    VERIFY_SSL = bool(verify)


def make_client(timeout: float, **kwargs: Any) -> httpx.AsyncClient:
    """Create an httpx AsyncClient, retrying once on the OpenSSL first-init flake.

    On some platforms (observed: WSL2 + OpenSSL 3.5 + Python 3.14) the very
    first ``ssl.create_default_context(cafile=...)`` in a fresh process can
    fail with ``ssl.SSLError`` (``[CONF: MODULE_INITIALIZATION_ERROR]`` /
    "unknown error (0x0)") because the OpenSSL CONF module races its lazy
    initialization. A second attempt succeeds. Retrying keeps per-request
    httpx clients reliable whether or not truststore has been injected.
    """
    try:
        return httpx.AsyncClient(timeout=timeout, **kwargs)

    except ssl.SSLError:
        return httpx.AsyncClient(timeout=timeout, **kwargs)


__all__ = ["VERIFY_SSL", "make_client", "set_verify_ssl"]
