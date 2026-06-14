"""EARS repair helper for compact LLM spec generation."""

from __future__ import annotations

import unittest

from cecli.spec.ears.lint import analyze_requirements
from cecli.spec.ears.repair import repair_requirements_missing_shall


class TestEarsRepair(unittest.TestCase):
    def test_repairs_when_only_clauses(self):
        raw = """\
### REQ-001: A
**Acceptance Criteria**
1. **WHEN** a client calls the API
2. **WHEN** the core is idle
"""
        fixed = repair_requirements_missing_shall(raw)
        result = analyze_requirements(fixed)
        self.assertTrue(result.ok, result.issues)

    def test_repairs_numbered_bullet_without_shall(self):
        raw = """\
### REQ-001: Health
1. **WHEN** a client calls GET /health
### REQ-002: Payload
2. Response body includes a status field
"""
        fixed = repair_requirements_missing_shall(raw)
        result = analyze_requirements(fixed)
        self.assertTrue(result.ok, result.issues)
        self.assertIn("SHALL", fixed)

    def test_repairs_if_then_prose_without_shall(self):
        raw = """\
### REQ-001: Health
1. **WHEN** a client calls GET /health **THE** system **SHALL** respond with HTTP 200.
### REQ-002: Payload
**IF** the status is ok **THEN** include the literal value `ok` in the JSON body.
"""
        fixed = repair_requirements_missing_shall(raw)
        result = analyze_requirements(fixed)
        self.assertTrue(result.ok, result.issues)
        self.assertIn("SHALL", fixed.split("REQ-002")[1])

    def test_repairs_where_prose_without_shall(self):
        raw = """\
### REQ-002: Auth
**WHERE** the client is unauthenticated the API returns HTTP 401.
"""
        fixed = repair_requirements_missing_shall(raw)
        result = analyze_requirements(fixed)
        self.assertTrue(result.ok, result.issues)


if __name__ == "__main__":
    unittest.main()
