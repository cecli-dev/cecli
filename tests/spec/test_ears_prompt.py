"""EARS + trace prompt context for generate/refine (E5)."""

from __future__ import annotations

import unittest

from cecli.spec.ears.prompt import (
    format_spec_quality_for_prompt,
    requirements_pass_ears,
)


class TestEarsPrompt(unittest.TestCase):
    def test_format_spec_quality_includes_lint_trace_and_depth(self):
        req = "### REQ-001\n**WHEN** x\n**THE** system **SHALL** y.\n"
        design = "## Overview\nShort."
        tasks = "- [ ] 1. Step (depends: none)"
        block = format_spec_quality_for_prompt(req, design, tasks)
        self.assertIn("Current spec quality", block)
        self.assertIn("EARS:", block)
        self.assertIn("Trace:", block)
        self.assertIn("Deepen the spec", block)
        self.assertIn("REQ-###", block)

    def test_format_spec_quality_requirements_only(self):
        req = "### REQ-001\n**WHEN** x\n**THE** system **SHALL** y.\n"
        block = format_spec_quality_for_prompt(req, "", "")
        self.assertIn("EARS:", block)
        self.assertNotIn("Trace: no REQ", block)

    def test_requirements_pass_ears_blocks_errors_only(self):
        ok, issues = requirements_pass_ears(
            "### REQ-001\n**WHEN** x\n**THE** system **SHALL** y.\n"
        )
        self.assertTrue(ok)
        self.assertEqual(issues, [])

        bad, issues = requirements_pass_ears("### REQ-001\n**WHEN** x\n**THE** system shows y.\n")
        self.assertFalse(bad)
        self.assertTrue(any(i["code"] == "EARS_NO_SHALL" for i in issues))
        self.assertTrue(all(i["severity"] == "error" for i in issues))

    def test_requirements_pass_ears_returns_errors_only(self):
        """Gate issues list contains severity=error entries only."""
        bad, issues = requirements_pass_ears("### REQ-001\n**WHEN** x\n**THE** system shows y.\n")
        self.assertFalse(bad)
        self.assertTrue(issues)
        self.assertTrue(all(i["severity"] == "error" for i in issues))


if __name__ == "__main__":
    unittest.main()
