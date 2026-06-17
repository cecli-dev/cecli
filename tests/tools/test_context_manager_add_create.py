"""ContextManager add on missing paths upgrades to create."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from cecli.tools.context_manager import Tool


class _CoderStub:
    def __init__(self, root: Path):
        self.root = str(root)
        self.repo = SimpleNamespace(root=str(root))
        self.io = SimpleNamespace(
            tool_output=Mock(),
            tool_error=Mock(),
            tool_warning=Mock(),
        )
        self.abs_fnames: set[str] = set()
        self.abs_read_only_fnames: set[str] = set()
        self.tui = lambda: False

    def abs_root_path(self, file_path: str) -> str:
        path = Path(file_path)
        if path.is_absolute():
            return str(path)
        return str((Path(self.root) / path).resolve())


class TestContextManagerAddCreate(unittest.TestCase):
    def test_add_missing_file_creates_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coder = _CoderStub(root)
            rel = "src/new_module.py"

            result = Tool.execute(coder, add=[rel])

            abs_path = coder.abs_root_path(rel)
            self.assertTrue(Path(abs_path).is_file())
            self.assertIn(abs_path, coder.abs_fnames)
            self.assertIn("create", result.lower())
            coder.io.tool_output.assert_any_call(
                "ℹ️ `src/new_module.py` missing on disk — using **create** instead of add"
            )

    def test_create_root_level_file_without_makedirs_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coder = _CoderStub(root)

            result = Tool.execute(coder, create=["README.md"])

            self.assertTrue((root / "README.md").is_file())
            self.assertIn("Created", result)


if __name__ == "__main__":
    unittest.main()
