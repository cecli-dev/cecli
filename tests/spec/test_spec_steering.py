"""Spec-focus steering loader."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cecli.spec.steering import (
    STEERING_MAIN_RELPATH,
    build_spec_focus_preamble,
    load_steering_markdown,
    scaffold_steering_files,
    scan_steering_files,
)


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

    def test_scan_steering_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".cecli").mkdir()
            (root / ".cecli" / "STEERING.md").write_text("Rules here.", encoding="utf-8")
            steering = root / ".cecli" / "steering"
            steering.mkdir()
            (steering / "security.md").write_text("", encoding="utf-8")
            (steering / "style.md").write_text("Tabs not spaces.", encoding="utf-8")
            snapshot = scan_steering_files(root)
            self.assertTrue(snapshot.has_content)
            self.assertEqual(snapshot.file_count, 2)
            self.assertIsNotNone(snapshot.main)
            self.assertTrue(snapshot.main.nonempty)
            self.assertEqual(len(snapshot.fragments), 2)
            self.assertFalse(snapshot.fragments[0].nonempty)

    def test_scaffold_steering_creates_main_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = scaffold_steering_files(root)
            self.assertEqual(created, [STEERING_MAIN_RELPATH])
            self.assertTrue((root / ".cecli" / "STEERING.md").is_file())
            again = scaffold_steering_files(root)
            self.assertEqual(again, [])


if __name__ == "__main__":
    unittest.main()
