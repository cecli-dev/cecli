"""Spec-focus steering loader."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cecli.spec.steering import build_spec_focus_preamble, load_steering_markdown


class TestSpecSteering(unittest.TestCase):
    def test_load_steering_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".cecli").mkdir()
            (root / ".cecli" / "STEERING.md").write_text(
                "Use TypeScript strict mode.", encoding="utf-8"
            )
            steering = root / ".cecli" / "steering"
            steering.mkdir()
            (steering / "security.md").write_text("No secrets in repo.", encoding="utf-8")
            text = load_steering_markdown(root)
            self.assertIn("strict mode", text)
            self.assertIn("security.md", text)

    def test_preamble_includes_spec_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            pre = build_spec_focus_preamble(tmp)
            self.assertIn("Spec-focus mode", pre)


if __name__ == "__main__":
    unittest.main()
