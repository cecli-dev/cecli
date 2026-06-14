"""EARS spec index (roadmap #22 / E3)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cecli.spec.ears import build_spec_index


class TestEarsSpecIndex(unittest.TestCase):
    def test_orphan_folder_and_global_dup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs = root / ".cecli" / "specs"
            for tid, req in (
                ("task-a", "### REQ-001\n**WHEN** a\n**THE** system **SHALL** do A.\n"),
                ("task-b", "### REQ-001\n**WHEN** b\n**THE** system **SHALL** do B.\n"),
                ("orphan", "### REQ-002\n**WHEN** c\n**THE** system **SHALL** do C.\n"),
            ):
                folder = specs / tid
                folder.mkdir(parents=True)
                (folder / "requirements.md").write_text(req, encoding="utf-8")

            result = build_spec_index(root, task_ids=["task-a", "task-b"])
            codes = {i.code for i in result.issues}
            self.assertIn("SPEC_ORPHAN_FOLDER", codes)
            self.assertIn("SPEC_REQ_ID_GLOBAL_DUP", codes)
            self.assertFalse(result.ok)

    def test_missing_folder_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = build_spec_index(root, task_ids=["only-json"])
            self.assertTrue(any(i.code == "SPEC_MISSING_FOLDER" for i in result.issues))

    def test_to_dict_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = build_spec_index(tmp, task_ids=[]).to_dict()
            self.assertIn("folders", d)
            self.assertIn("issues", d)


if __name__ == "__main__":
    unittest.main()
