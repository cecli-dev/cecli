"""EARS module — deterministic requirements lint."""

from __future__ import annotations

import unittest

from cecli.spec.ears import analyze_requirements

GOOD = """\
### REQ-001
**WHEN** the user opens Tasks
**THE** system **SHALL** show the active task chip.

### REQ-002
**WHEN** the user saves a requirement
**THE** system **SHALL** sync to `.cecli/specs/{id}/requirements.md`.
"""

BAD_NO_SHALL = """\
### REQ-001
**WHEN** the user opens Tasks
**THE** system shows the active task chip.
"""

DUP_ID = """\
### REQ-001
**WHEN** a
**THE** system **SHALL** do A.

### REQ-001
**WHEN** b
**THE** system **SHALL** do B.
"""

# Kiro-style: one titled requirement with a User Story and several acceptance criteria.
KIRO_MULTI_AC = """\
### Introduction
The feature exposes a health endpoint.

### REQ-001: Health check
**User Story:** As a client, I want a health endpoint, so that I can confirm the API is up.

**Acceptance Criteria**
1. **WHEN** a client sends `GET /health` **THE** system **SHALL** respond with HTTP 200.
2. **IF** the core is starting **THEN THE** system **SHALL** respond with HTTP 503.
3. **WHILE** running **THE** system **SHALL** report uptime.
"""


class TestEarsLint(unittest.TestCase):
    def test_good_requirements_ok(self):
        r = analyze_requirements(GOOD)
        self.assertTrue(r.ok)
        self.assertGreaterEqual(len(r.clauses), 2)
        self.assertFalse(any(i.code == "EARS_NO_SHALL" for i in r.issues))

    def test_missing_shall_errors(self):
        r = analyze_requirements(BAD_NO_SHALL)
        self.assertFalse(r.ok)
        self.assertTrue(any(i.code == "EARS_NO_SHALL" for i in r.issues))

    def test_duplicate_req_id(self):
        r = analyze_requirements(DUP_ID)
        self.assertFalse(r.ok)
        self.assertTrue(any(i.code == "EARS_DUP_ID" for i in r.issues))

    def test_kiro_multi_acceptance_criteria_ok(self):
        """One titled requirement with several ACs must not trip EARS_DUP_ID."""
        r = analyze_requirements(KIRO_MULTI_AC)
        self.assertTrue(r.ok, [i.to_dict() for i in r.issues])
        self.assertFalse(any(i.code == "EARS_DUP_ID" for i in r.issues))
        # Three acceptance criteria → three clauses, all under REQ-001.
        self.assertEqual(len([c for c in r.clauses if c.req_id == "REQ-001"]), 3)
        # The descriptive User Story line is not linted as a normative clause.
        self.assertFalse(any("User Story" in c.text for c in r.clauses))

    def test_titled_heading_carries_req_id(self):
        r = analyze_requirements(KIRO_MULTI_AC)
        self.assertTrue(all(c.req_id == "REQ-001" for c in r.clauses))

    def test_kiro_user_story_with_if_while_not_clauses(self):
        """User Story prose must not lint as EARS (common words if/while)."""
        text = """\
### REQ-002: Cloud sync
**User Story:** As a user, I want sync while traveling, so that I can access logs if I lose signal.

**Acceptance Criteria**
1. **WHERE** sync is enabled **THEN THE** system **SHALL** encrypt data.
"""
        r = analyze_requirements(text)
        self.assertTrue(r.ok, [i.to_dict() for i in r.issues])
        self.assertFalse(any("User Story" in c.text for c in r.clauses))


if __name__ == "__main__":
    unittest.main()
