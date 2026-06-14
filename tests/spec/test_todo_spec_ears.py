"""E5: EARS context in spec generate and apply gate."""

from __future__ import annotations

import unittest

from cecli.spec.ears.prompt import (
    format_spec_quality_for_prompt,
    requirements_pass_ears,
)
from cecli.spec.generate import build_generate_message
from cecli.spec.todos import TodoItem


class TestTodoSpecEars(unittest.TestCase):
    def test_refine_prompt_includes_ears_section(self):
        item = TodoItem(
            id="t1",
            title="Auth",
            requirements="### REQ-001\n**WHEN** x\n**THE** system shows y.\n",
            design="",
            tasks_md="",
        )
        msg = build_generate_message("fix", mode="refine", item=item)
        self.assertIn("Current spec quality", msg)
        self.assertIn("EARS_NO_SHALL", msg)

    def test_requirements_pass_ears(self):
        ok, issues = requirements_pass_ears(
            "### REQ-001\n**WHEN** a\n**THE** system **SHALL** b.\n"
        )
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_format_spec_quality_empty(self):
        self.assertEqual(format_spec_quality_for_prompt("", "", ""), "")


if __name__ == "__main__":
    unittest.main()
