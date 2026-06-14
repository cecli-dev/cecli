"""Parse + sanity checks for generate/refine spec output (no LLM)."""

from __future__ import annotations

import unittest

from helpers.spec_layer_assertions import (
    SAMPLE_GENERATED_MARKDOWN,
    assess_generated_spec_layers,
)

from cecli.spec.generate import parse_generated_layers
from cecli.spec.layers import (
    assess_spec_richness,
    normalize_spec_layer_traceability,
)


class TestGenerateSpecParse(unittest.TestCase):
    def test_parse_three_sections(self):
        layers = parse_generated_layers(SAMPLE_GENERATED_MARKDOWN)
        self.assertIn("REQ-001", layers.get("requirements", ""))
        self.assertIn("Overview", layers.get("design", ""))
        self.assertRegex(layers.get("tasks_md", ""), r"1\.\s+Add route")

    def test_sample_passes_sanity(self):
        layers = parse_generated_layers(SAMPLE_GENERATED_MARKDOWN)
        ok, issues = assess_generated_spec_layers(
            layers.get("requirements", ""),
            layers.get("design", ""),
            layers.get("tasks_md", ""),
        )
        self.assertTrue(ok, issues)

    def test_normalize_adds_design_traceability(self):
        layers = {
            "requirements": "### REQ-001\n**WHEN** x\n**THE** system **SHALL** a.\n",
            "design": "## Overview\nHTTP API only.",
            "tasks_md": "- [ ] 1. Step (depends: none)",
        }
        out = normalize_spec_layer_traceability(layers)
        self.assertIn("REQ-001", out["design"])
        ok, issues = assess_generated_spec_layers(
            out["requirements"],
            out["design"],
            out["tasks_md"],
        )
        self.assertTrue(ok, issues)

    def test_sample_is_kiro_rich(self):
        """The shared fixture should now read as a rich, Kiro-grade spec."""
        layers = parse_generated_layers(SAMPLE_GENERATED_MARKDOWN)
        rich, suggestions = assess_spec_richness(
            layers.get("requirements", ""),
            layers.get("design", ""),
            layers.get("tasks_md", ""),
        )
        self.assertTrue(rich, suggestions)

    def test_richness_flags_thin_spec(self):
        rich, suggestions = assess_spec_richness(
            requirements="### REQ-001\n**WHEN** x\n**THE** system **SHALL** y.\n",
            design="## Overview\nshort",
            tasks_md="- [ ] 1. Do it (depends: none)",
        )
        self.assertFalse(rich)
        joined = " ".join(suggestions)
        self.assertIn("User Story", joined)
        self.assertIn("design:", joined)
        self.assertIn("tasks:", joined)

    def test_normalize_after_merge_for_phased_design(self):
        """Phased design parse omits requirements; merge must precede normalize."""
        parsed_only = {
            "requirements": "",
            "design": "## Overview\nHTTP API only.",
            "tasks_md": "",
        }
        self.assertNotIn("REQ-001", normalize_spec_layer_traceability(parsed_only)["design"])
        merged = {
            "requirements": "### REQ-001\n**WHEN** x\n**THE** system **SHALL** a.\n",
            "design": "## Overview\nHTTP API only.",
            "tasks_md": "",
        }
        out = normalize_spec_layer_traceability(merged)
        self.assertIn("REQ-001", out["design"])


if __name__ == "__main__":
    unittest.main()
