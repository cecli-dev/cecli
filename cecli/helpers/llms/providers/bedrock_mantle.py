"""AWS Bedrock Mantle provider adapter.

Bedrock Mantle exposes an OpenAI-compatible chat wire (``/v1/chat/completions``)
at ``https://bedrock-mantle.{region}.api.aws/v1``. Auth is either a bearer token
(``BEDROCK_MANTLE_API_KEY`` / ``AWS_BEARER_TOKEN_BEDROCK``) or AWS Signature V4
when no token is set. When a token is present the chat family sends ``Bearer``;
otherwise :meth:`sign_request` (invoked by the chat domain) signs the request
with SigV4, mirroring litellm's ``BedrockMantleAuthMixin``.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional, Tuple

from ..aws_sigv4 import AWSCredentials, resolve_aws_region, sign_request
from .base import ProviderAdapter

#: Host pattern ``https://bedrock-mantle.{region}.api.aws/...``.
_MANTLE_HOST_RE = re.compile(r"^https?://bedrock-mantle\.([^./]+)\.api\.aws", re.IGNORECASE)
_DEFAULT_REGION = "us-east-1"


class BedrockMantleProvider(ProviderAdapter):
    """Bedrock Mantle: OpenAI-compatible chat with Bearer or SigV4 auth."""

    provider: str = "bedrock_mantle"

    def _region_from_base(self, api_base: str) -> Optional[str]:
        match = _MANTLE_HOST_RE.match(api_base.rstrip("/"))

        if match and match.group(1) != "{region}":
            # Skip the literal ``{region}`` placeholder from an unsubstituted
            # template so it never becomes a "region".
            return match.group(1)

        return None
        match = _MANTLE_HOST_RE.match(api_base.rstrip("/"))

        if match:
            return match.group(1)

        return None

    def resolve_region(self, resolved: Dict[str, Any]) -> str:
        """Resolve the signing region (explicit > host > env > default)."""
        if resolved.get("aws_region"):
            return resolved["aws_region"]

        base = resolved.get("api_base") or ""
        host_region = self._region_from_base(base)

        if host_region:
            return host_region

        return os.environ.get("BEDROCK_MANTLE_REGION") or resolve_aws_region() or _DEFAULT_REGION

    def resolve_api_base(self, resolved: Dict[str, Any]) -> str:
        """Substitute the ``{region}`` placeholder in the api_base template."""
        base = resolved["api_base"]
        region = self.resolve_region(resolved)
        resolved["aws_region"] = region

        if "{region}" in base:
            return base.replace("{region}", region)

        return base

    def resolve_api_key(self, resolved: Dict[str, Any], api_key: Optional[str]) -> Optional[str]:
        """Return a bearer token when one is configured (else SigV4 is used)."""
        if api_key:
            return api_key

        return os.environ.get("BEDROCK_MANTLE_API_KEY") or os.environ.get(
            "AWS_BEARER_TOKEN_BEDROCK"
        )

    def build_headers(
        self,
        resolved: Dict[str, Any],
        key: Optional[str],
        family: str,
        headers: Dict[str, str],
    ) -> Dict[str, str]:
        """Add the Bearer token when present (SigV4 path adds its own headers)."""
        merged = dict(headers)

        if key:
            merged["Authorization"] = f"Bearer {key}"

        merged.setdefault("Content-Type", "application/json")
        return merged

    def sign_request(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        key: Optional[str],
    ) -> Tuple[str, Dict[str, str], Optional[bytes]]:
        """Sign a Mantle request with SigV4 (no-op when a bearer token is set)."""
        if key:
            return url, headers, None

        creds = AWSCredentials.from_env()

        if creds is None:
            raise ValueError(
                "Bedrock Mantle requires either a bearer token (BEDROCK_MANTLE_API_KEY or "
                "AWS_BEARER_TOKEN_BEDROCK) or AWS credentials (AWS_ACCESS_KEY_ID / "
                "AWS_SECRET_ACCESS_KEY)."
            )

        region = self.resolve_region(
            {**{k: v for k, v in [("api_base", url)]}, "aws_region": None} or {}
        )
        region = region or _DEFAULT_REGION
        body = json.dumps(payload).encode("utf-8")
        signed = sign_request("POST", url, body, creds, region, "bedrock", headers=headers)
        return url, signed, body


__all__ = ["BedrockMantleProvider"]
