"""Tests for cecli/helpers/extensions/skills_importer.py."""

import json
import ssl

import pytest
import requests
from requests.exceptions import SSLError as RequestsSSLError

from cecli.helpers.extensions import skills_importer

imp = skills_importer


class FakeResponse:
    """Minimal stand-in for a requests.Response returned by a successful GET."""

    def __init__(self):
        self.content = b"fake"
        self.status_code = 200


@pytest.mark.parametrize("exc", [ssl.SSLError, RequestsSSLError])
def test_ssl_safe_get_retries_once_on_ssl_flake(monkeypatch, exc):
    """The OpenSSL CONF module lazy-init flake must be retried once."""
    calls = {"n": 0}
    sentinel = FakeResponse()

    def flaky_get(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise exc("unknown error (0x0) (_ssl.c:3187)")
        return sentinel

    monkeypatch.setattr(skills_importer.requests, "get", flaky_get)

    result = skills_importer._ssl_safe_get("https://example.test/fake")

    assert result is sentinel
    assert calls["n"] == 2


@pytest.mark.parametrize("exc", [ssl.SSLError, RequestsSSLError])
def test_ssl_safe_get_propagates_persistent_ssl_error(monkeypatch, exc):
    """A persistent SSL flake must propagate after the single retry."""
    calls = {"n": 0}

    def always_fail(url, **kwargs):
        calls["n"] += 1
        raise exc("unknown error (0x0) (_ssl.c:3187)")

    monkeypatch.setattr(skills_importer.requests, "get", always_fail)

    with pytest.raises(exc):
        skills_importer._ssl_safe_get("https://example.test/fake")

    assert calls["n"] == 2


def _response(status_code=200, payload=None):
    """Build a minimal requests.Response carrying a JSON payload."""
    resp = requests.Response()
    resp.status_code = status_code
    if payload is not None:
        resp._content = json.dumps(payload).encode()
    return resp


def _audit(provider, slug, status="pass", **extra):
    """Build an audit entry like the skills.sh audit endpoint returns."""
    entry = {"provider": provider, "slug": slug, "status": status}
    entry.update(extra)
    return entry


class TestFetchSkillAudits:
    def test_returns_payload_on_200(self, monkeypatch):
        payload = {"id": "a/b/c", "audits": [_audit("Socket", "socket")]}
        monkeypatch.setattr(imp, "_ssl_safe_get", lambda *a, **k: _response(200, payload))
        assert imp.fetch_skill_audits("a/b/c") == payload

    def test_none_on_404(self, monkeypatch):
        monkeypatch.setattr(
            imp, "_ssl_safe_get", lambda *a, **k: _response(404, {"error": "not_found"})
        )
        assert imp.fetch_skill_audits("a/b/c") is None

    def test_none_on_network_error(self, monkeypatch):
        def boom(*a, **k):
            raise requests.exceptions.ConnectionError("boom")

        monkeypatch.setattr(imp, "_ssl_safe_get", boom)
        assert imp.fetch_skill_audits("a/b/c") is None

    def test_none_on_bad_body(self, monkeypatch):
        monkeypatch.setattr(imp, "_ssl_safe_get", lambda *a, **k: _response(200, {"nope": True}))
        assert imp.fetch_skill_audits("a/b/c") is None


class TestSkillPassesSecurityAudits:
    def test_all_pass(self, monkeypatch):
        payload = {
            "audits": [
                _audit("Gen Agent Trust Hub", "agent-trust-hub"),
                _audit("Socket", "socket"),
                _audit("Snyk", "snyk"),
            ]
        }
        monkeypatch.setattr(imp, "fetch_skill_audits", lambda p: payload)
        ok, msg = imp.skill_passes_security_audits("a/b/c")
        assert ok is True
        assert "pass" in msg.lower()

    def test_missing_required_audit(self, monkeypatch):
        payload = {"audits": [_audit("Socket", "socket")]}
        monkeypatch.setattr(imp, "fetch_skill_audits", lambda p: payload)
        ok, msg = imp.skill_passes_security_audits("a/b/c")
        assert ok is False
        assert "missing required security audit" in msg.lower()

    def test_non_pass_status(self, monkeypatch):
        payload = {
            "audits": [
                _audit("Gen Agent Trust Hub", "agent-trust-hub"),
                _audit("Socket", "socket"),
                _audit("Snyk", "snyk", status="warn"),
            ]
        }
        monkeypatch.setattr(imp, "fetch_skill_audits", lambda p: payload)
        ok, msg = imp.skill_passes_security_audits("a/b/c")
        assert ok is False
        assert "did not pass" in msg

    def test_extra_non_pass_audit_fails(self, monkeypatch):
        payload = {
            "audits": [
                _audit("Gen Agent Trust Hub", "agent-trust-hub"),
                _audit("Socket", "socket"),
                _audit("Snyk", "snyk"),
                _audit("Runlayer", "runlayer", status="warn"),
            ]
        }
        monkeypatch.setattr(imp, "fetch_skill_audits", lambda p: payload)
        ok, _ = imp.skill_passes_security_audits("a/b/c")
        assert ok is False

    def test_no_audits_found(self, monkeypatch):
        monkeypatch.setattr(imp, "fetch_skill_audits", lambda p: None)
        ok, msg = imp.skill_passes_security_audits("a/b/c")
        assert ok is False
        assert "no security audit results" in msg.lower()


class TestInstallSkillAuditGate:
    def test_skills_sh_audit_fail_blocks_download(self, monkeypatch):
        src = imp.SkillSource(
            repo="anthropics/skills",
            skill_id="frontend-design",
            name="frontend-design",
            source="skills.sh",
        )
        monkeypatch.setattr(imp, "resolve_skill", lambda name, force=False: src)
        monkeypatch.setattr(imp, "skill_passes_security_audits", lambda p: (False, "did not pass"))
        res = imp.install_skill("frontend-design")
        assert res["ok"] is False
        assert "did not pass" in res["message"]

    def test_registry_skill_skips_gate(self, monkeypatch, tmp_path):
        src = imp.SkillSource(
            repo="cecli-dev/community-resources",
            skill_id="files/docx",
            name="docx",
            source="registry",
        )
        monkeypatch.setattr(imp, "resolve_skill", lambda name, force=False: src)
        audit_called = {"v": False}

        def fake_audit(spath):
            audit_called["v"] = True
            return (False, "no")

        monkeypatch.setattr(imp, "skill_passes_security_audits", fake_audit)
        monkeypatch.setattr(imp, "download_skill_folder", lambda *a, **k: None)
        res = imp.install_skill("docx", root=str(tmp_path))
        assert res["ok"] is True
        assert audit_called["v"] is False
