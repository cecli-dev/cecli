"""Runtime knobs for the llms package (import-light, no heavy deps).

The dispatcher and domain adapters read :data:`VERIFY_SSL` when constructing
httpx clients so ``--no-verify-ssl`` keeps working after the litellm swap
(litellm previously patched ``client_session``/``aclient_session`` globals).

``make_client`` additionally attaches a response hook that appends the body of
any 4xx/5xx response to :data:`ERROR_LOG_PATH` (``.cecli/logs/requests-errors.log``)
so failed provider requests stay diagnosable after the fact.
"""

from __future__ import annotations

import os
import ssl
import threading
import time
from typing import Any

from cecli.http import httpx

#: Global TLS verification flag; set False for ``--no-verify-ssl``.
VERIFY_SSL = True

#: Append-only destination for 4xx/5xx response bodies.
ERROR_LOG_PATH = ".cecli/logs/requests-errors.log"

#: Serializes appends from concurrent sync/async hooks (writes are tiny).
_ERROR_LOG_LOCK = threading.Lock()

#: Maximum decoded body size kept per record.
_MAX_LOGGED_BODY = 64 * 1024


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

    A response hook is always attached so 4xx/5xx bodies land in
    :data:`ERROR_LOG_PATH`; caller-supplied ``event_hooks`` are preserved.
    """
    hooks = dict(kwargs.pop("event_hooks", None) or {})
    hooks["response"] = [*hooks.get("response", []), _log_error_response]

    try:
        return httpx.AsyncClient(timeout=timeout, event_hooks=hooks, **kwargs)

    except ssl.SSLError:
        return httpx.AsyncClient(timeout=timeout, event_hooks=hooks, **kwargs)


def log_error_response(response: Any) -> None:
    """Sync httpx response hook: append 4xx/5xx bodies to :data:`ERROR_LOG_PATH`."""

    if response.status_code < 400:
        return

    try:
        response.read()
        body = response.text

    except Exception:
        body = "<body unavailable>"

    _append_error_record(response, body)


async def _log_error_response(response: Any) -> None:
    """Async httpx response hook: append 4xx/5xx bodies to :data:`ERROR_LOG_PATH`.

    Reading the body here also makes it available to the caller's later
    ``raise_for_status()``/error handling; streaming error responses are
    otherwise left unread.
    """

    if response.status_code < 400:
        return

    try:
        await response.aread()
        body = response.text

    except Exception:
        body = "<body unavailable>"

    _append_error_record(response, body)


def _append_error_record(response: Any, body: str) -> None:
    """Append one error record; logging failures never reach the request path."""

    request = response.request
    body = body or ""

    if len(body) > _MAX_LOGGED_BODY:
        body = f"{body[:_MAX_LOGGED_BODY]}\n<truncated>"

    record = (
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
        f"{getattr(request, 'method', '?')} {getattr(request, 'url', '?')} -> "
        f"{response.status_code}\n{body}\n{'-' * 80}\n"
    )

    try:
        os.makedirs(os.path.dirname(ERROR_LOG_PATH), exist_ok=True)

        with _ERROR_LOG_LOCK, open(ERROR_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(record)

    except Exception:
        pass


__all__ = [
    "ERROR_LOG_PATH",
    "VERIFY_SSL",
    "log_error_response",
    "make_client",
    "set_verify_ssl",
]
