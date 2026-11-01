"""HTTP transport for the System One evaluation endpoint.

Sends ``POST {api_base}/v1/systemone`` requests, the wire format shared by
System One decision servers: any endpoint implementing it works, so pointing
:attr:`SystemOneConfig.api_base` at a locally served model (``von serve``) or a
gateway is just a config change.

Retries follow the documented guidance for ``429``/``529`` responses:
exponential backoff, bounded by the config's ``max_retries``.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Dict, Mapping, Optional

from cecli.helpers.system_one.config import SystemOneConfig, get_config
from cecli.helpers.system_one.types import (
    SystemOneResponse,
    build_payload,
    parse_response,
)

logger = logging.getLogger(__name__)

#: HTTP statuses worth retrying (rate limited / overloaded).
RETRY_STATUS = frozenset({429, 529})

#: Statuses that mean the request was rejected for authentication.
AUTH_STATUS = frozenset({401, 403})

#: Base seconds for the exponential backoff sequence.
BACKOFF_BASE_SECONDS = 0.5


class SystemOneError(RuntimeError):
    """Raised when an evaluation request fails after retries."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SystemOneClient:
    """Async client for one System One endpoint."""

    def __init__(self, config: Optional[SystemOneConfig] = None) -> None:
        self.config = config or get_config()

    def questions_for(
        self,
        state: Any,
        questions: Mapping[str, Dict[str, Any]],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the request payload that :meth:`evaluate` would send."""
        return build_payload(
            state,
            questions,
            model=model,
            default_model=self.config.model_name,
        )

    async def evaluate(
        self,
        state: Any,
        questions: Mapping[str, Dict[str, Any]],
        model: Optional[str] = None,
    ) -> SystemOneResponse:
        """Evaluate ``state`` against typed ``questions`` and parse the answer map."""
        payload = self.questions_for(state, questions, model=model)
        body = await self._post(payload)

        return parse_response(body)

    async def raw_evaluate(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Send an already-built payload and return the decoded JSON body."""
        return await self._post(dict(payload))

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from cecli.http import httpx

        headers = self.config.build_headers()
        url = self.config.endpoint_url
        last_error: Optional[str] = None
        last_status: Optional[int] = None

        for attempt in range(self.config.max_retries + 1):
            if attempt:
                await asyncio.sleep(_backoff_delay(attempt - 1))

            try:
                async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                last_status = None
                logger.warning("System One request to %s failed: %s", url, last_error)
                continue

            if response.status_code < 400:
                return _decode_body(response)

            last_status = response.status_code
            last_error = _error_text(response, self.config)

            if response.status_code not in RETRY_STATUS or attempt >= self.config.max_retries:
                break

        raise SystemOneError(
            f"System One request to {url} failed ({last_status or 'transport error'}): "
            f"{last_error}",
            status_code=last_status,
        )


def _decode_body(response: Any) -> Dict[str, Any]:
    try:
        body = response.json()
    except Exception as exc:
        raise SystemOneError(f"System One response was not valid JSON: {exc}") from exc

    if not isinstance(body, Mapping):
        raise SystemOneError(
            f"System One response must be a JSON object, got {type(body).__name__}"
        )

    return dict(body)


def _error_text(response: Any, config: Optional[SystemOneConfig] = None) -> str:
    """Describe a failed response, naming unset key variables on auth errors.

    An endpoint that needs a bearer token answers 401/403 whether the variable
    in ``api_key_env`` is missing or simply empty, which otherwise reads as an
    opaque server-side rejection.
    """
    try:
        text = response.text[:500]
    except Exception:
        text = "<no response body>"

    auth_error = getattr(response, "status_code", 0) in (401, 403)

    if config is not None and auth_error and not config.resolve_api_key():
        names = ", ".join(config.api_key_env) or "(none configured)"
        text += (
            f"\nNo API key was sent: none of {names} is set. Export one of them"
            " or point api_key_env at the variable that holds your key."
        )

    return text
    try:
        return response.text[:500]
    except Exception:
        return "<no response body>"


def _backoff_delay(retry_index: int) -> float:
    return BACKOFF_BASE_SECONDS * (2**retry_index) * random.uniform(0.8, 1.2)
