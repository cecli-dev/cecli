"""AWS SigV4 signing tests for :mod:`cecli.helpers.llms.aws_sigv4`.

The implementation is verified for parity against botocore's own ``SigV4Auth``
(Amazon's reference SDK implementation) with a pinned clock, so the tests are
meaningful without any live AWS credentials. botocore is only used as a test
oracle; the parity tests are skipped when it is not installed.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from cecli.helpers.llms.aws_sigv4 import (
    AWSCredentials,
    resolve_aws_region,
    sign_request,
)

ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
FIXED_NOW = datetime(2015, 8, 30, 12, 36, 0)


@pytest.fixture(autouse=True)
def _pin_botocore_clock(monkeypatch):
    """Pin botocore's clock so the reference signature is deterministic."""
    try:
        import botocore.auth as botauth
    except ImportError:
        return

    monkeypatch.setattr(botauth, "get_current_datetime", lambda: FIXED_NOW)


def _botocore_authorization(method, url, payload, headers, region, service, session=None):
    pytest.importorskip("botocore")
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials

    creds = Credentials(ACCESS_KEY, SECRET_KEY, session)
    request = AWSRequest(method=method, url=url, data=payload, headers=headers)
    SigV4Auth(creds, service, region).add_auth(request)
    return dict(request.headers)["Authorization"]


def _mine_authorization(method, url, payload, headers, region, service, session=None):
    creds = AWSCredentials(ACCESS_KEY, SECRET_KEY, session_token=session)
    signed = sign_request(
        method,
        url,
        payload,
        creds,
        region,
        service,
        headers=headers,
        now=FIXED_NOW,
    )
    return signed["Authorization"]


def test_matches_botocore_get_with_query():
    url = "https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08"
    headers = {"content-type": "application/x-www-form-urlencoded; charset=utf-8"}
    assert _mine_authorization(
        "GET", url, b"", headers, "us-east-1", "iam"
    ) == _botocore_authorization("GET", url, b"", headers, "us-east-1", "iam")


def test_matches_botocore_bedrock_converse_post():
    url = "https://bedrock-runtime.us-east-1.amazonaws.com/model/anthropic.claude-3-5-sonnet-20240620-v1/converse"
    payload = b'{"modelId": "x", "messages": [{"role": "user", "content": [{"text": "hi"}]}]}'
    headers = {"Content-Type": "application/json", "X-Amz-Target": "BedrockRuntime.Converse"}
    assert _mine_authorization(
        "POST", url, payload, headers, "us-east-1", "bedrock"
    ) == _botocore_authorization("POST", url, payload, headers, "us-east-1", "bedrock")


def test_matches_botocore_with_session_token():
    """botocore adds X-Amz-Security-Token automatically; ours must sign it too."""
    url = "https://bedrock-runtime.us-east-1.amazonaws.com/model/m/converse"
    payload = b'{"messages": []}'
    session = "FwoGZXIvYXdzEBEaD..."
    headers = {"content-type": "application/json"}
    assert _mine_authorization(
        "POST", url, payload, headers, "us-east-1", "bedrock", session=session
    ) == (
        _botocore_authorization(
            "POST", url, payload, headers, "us-east-1", "bedrock", session=session
        )
    )


def test_authorization_header_shape():
    url = "https://bedrock-runtime.us-east-1.amazonaws.com/model/m/converse"
    headers = sign_request(
        "POST",
        url,
        b'{"x": 1}',
        AWSCredentials(ACCESS_KEY, SECRET_KEY),
        "us-east-1",
        "bedrock",
        now=FIXED_NOW,
    )
    auth = headers["Authorization"]
    assert auth.startswith(
        f"AWS4-HMAC-SHA256 Credential={ACCESS_KEY}/20150830/us-east-1/bedrock/aws4_request, "
    )
    assert "SignedHeaders=content-type;host;x-amz-date" in auth
    assert "Signature=" in auth
    assert headers["host"] == "bedrock-runtime.us-east-1.amazonaws.com"
    assert headers["x-amz-date"] == "20150830T123600Z"


def test_caller_headers_case_insensitive_no_duplicate():
    """A caller-supplied capitalized Content-Type must not double-sign content-type."""
    url = "https://bedrock-runtime.us-east-1.amazonaws.com/model/m/converse"
    headers = sign_request(
        "POST",
        url,
        b"{}",
        AWSCredentials(ACCESS_KEY, SECRET_KEY),
        "us-east-1",
        "bedrock",
        headers={"Content-Type": "application/json"},
        now=FIXED_NOW,
    )
    signed = headers["Authorization"].split("SignedHeaders=")[1].split(",")[0]
    assert signed.count("content-type") == 1


def test_resolve_aws_region_prefers_region_name(monkeypatch):
    monkeypatch.setenv("AWS_REGION_NAME", "eu-west-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    assert resolve_aws_region() == "eu-west-1"


def test_resolve_aws_region_falls_back(monkeypatch):
    monkeypatch.delenv("AWS_REGION_NAME", raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")
    assert resolve_aws_region() == "ap-southeast-2"


def test_credentials_from_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SECRET")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "TOKEN")
    creds = AWSCredentials.from_env()
    assert creds is not None
    assert creds.access_key == "AKID"
    assert creds.secret_key == "SECRET"
    assert creds.session_token == "TOKEN"


def test_credentials_from_env_missing(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    assert AWSCredentials.from_env() is None
