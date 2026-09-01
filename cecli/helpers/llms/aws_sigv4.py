"""Self-contained AWS Signature Version 4 request signing (stdlib only).

Reimplements the subset of botocore's ``SigV4Auth`` that cecli needs for the
Bedrock / Bedrock Mantle providers, so ``boto3`` is not a runtime dependency.
The signing-header filter mirrors litellm's
``BaseAWSLLM._filter_headers_for_aws_signature``: only ``host``,
``content-type``, ``date``, ``x-amz-*`` and ``x-amzn-*`` headers participate in
canonicalization (forwarded client headers stay unsigned).

Verified against the AWS SigV4 test vector from the official docs (IAM
``ListUsers`` example) in ``tests/helpers/test_llms_aws_sigv4.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Optional

#: Headers AWS SigV4 includes in the canonical request / signed headers.
_SIGNABLE_HEADERS = {
    "host",
    "content-type",
    "date",
    "x-amz-date",
    "x-amz-security-token",
    "x-amz-content-sha256",
    "x-amz-algorithm",
    "x-amz-credential",
    "x-amz-signedheaders",
    "x-amz-signature",
}


class AWSCredentials:
    """Minimal AWS credential holder (access key / secret / optional session token)."""

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        session_token: Optional[str] = None,
        expiry: Optional[datetime] = None,
    ) -> None:
        self.access_key = access_key
        self.secret_key = secret_key
        self.session_token = session_token
        self.expiry = expiry

    @classmethod
    def from_env(cls) -> Optional["AWSCredentials"]:
        """Build credentials from the standard AWS environment variables."""
        import os

        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not access_key or not secret_key:
            return None
        return cls(
            access_key=access_key,
            secret_key=secret_key,
            session_token=os.environ.get("AWS_SESSION_TOKEN"),
        )


def _filter_headers_for_signature(headers: Dict[str, str]) -> Dict[str, str]:
    """Return only the headers AWS SigV4 includes in the signature."""
    out: Dict[str, str] = {}
    for name, value in headers.items():
        if value is None:
            continue
        lower = name.lower()
        if lower in _SIGNABLE_HEADERS or lower.startswith("x-amz-") or lower.startswith("x-amzn-"):
            out[name] = value
    return out


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _canonical_uri(path: str) -> str:
    """URI-encode each path segment, never re-encoding the ``/`` separator."""
    if not path or path == "/":
        return "/"
    segments = [urllib.parse.quote(seg, safe="/-_.~") for seg in path.split("/")]
    return "/".join(segments)


def _canonical_query(query: str) -> str:
    """Sort query params by (encoded key, encoded value) and join with '&'."""
    params = urllib.parse.parse_qsl(query, keep_blank_values=True)
    encoded = [
        (urllib.parse.quote(k, safe="-_.~"), urllib.parse.quote(v, safe="-_.~")) for k, v in params
    ]
    encoded.sort()
    return "&".join(f"{k}={v}" for k, v in encoded)


def _canonical_headers(headers: Dict[str, str]) -> tuple[str, str]:
    """Return (canonical_headers, signed_headers) sorted by lower-cased name."""
    items = sorted(
        ((name.lower(), value.strip()) for name, value in headers.items() if value is not None),
        key=lambda pair: pair[0],
    )
    canonical = "".join(f"{name}:{value}\n" for name, value in items)
    signed = ";".join(name for name, _ in items)
    return canonical, signed


def sign_request(
    method: str,
    url: str,
    payload: bytes,
    credentials: AWSCredentials,
    region: str,
    service: str,
    headers: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    """Sign a request with AWS SigV4 and return the headers to send.

    Args:
        method: HTTP method (``POST`` for the Bedrock APIs).
        url: Full request URL.
        payload: Encoded request body.
        credentials: AWS credentials (access key / secret / optional session token).
        region: AWS region (e.g. ``us-east-1``).
        service: AWS service name (``bedrock`` for Bedrock / Mantle).
        headers: Extra headers to sign (e.g. ``content-type``); ``host`` and
            ``x-amz-date`` are added automatically.
        now: Fixed timestamp (for deterministic tests).

    Returns:
        The complete headers dict including ``Authorization``, ``X-Amz-Date``
        and ``X-Amz-Security-Token`` (when a session token is set). The payload
        hash is part of the canonical request but not sent as a header, matching
        the AWS reference examples.
    """
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc
    path = parsed.path or "/"
    query = parsed.query

    payload_hash = _sha256_hex(payload)

    # Normalize header names to lowercase so a caller-supplied ``Content-Type``
    # and our ``setdefault`` can never collide into a duplicate signed header.
    sig_headers = {
        name.lower(): value for name, value in (headers or {}).items() if value is not None
    }
    sig_headers.setdefault("host", host)
    sig_headers.setdefault("x-amz-date", amz_date)
    sig_headers.setdefault("content-type", "application/json")
    if credentials.session_token:
        sig_headers.setdefault("x-amz-security-token", credentials.session_token)

    # Only AWS-relevant headers participate in canonicalization (mirrors litellm).
    sig_headers = _filter_headers_for_signature(sig_headers)

    canonical_headers, signed_headers = _canonical_headers(sig_headers)
    canonical_request = "\n".join(
        [
            method.upper(),
            _canonical_uri(path),
            _canonical_query(query),
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            _sha256_hex(canonical_request.encode("utf-8")),
        ]
    )

    k_date = _hmac(("AWS4" + credentials.secret_key).encode("utf-8"), date_stamp.encode("utf-8"))
    k_region = _hmac(k_date, region.encode("utf-8"))
    k_service = _hmac(k_region, service.encode("utf-8"))
    k_signing = _hmac(k_service, b"aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={credentials.access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    out = dict(sig_headers)
    out["Authorization"] = authorization
    return out


def resolve_aws_region() -> Optional[str]:
    """Resolve the AWS region from the environment (litellm-compatible order)."""
    import os

    return os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION") or None


__all__ = [
    "AWSCredentials",
    "resolve_aws_region",
    "sign_request",
]
