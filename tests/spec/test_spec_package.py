"""Package boundary: cecli.spec is self-contained and importable without BrightVision."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import cecli.spec
import cecli.spec.ears as ears_pkg
from cecli.spec import (
    SpecGenerationJob,
    analyze_requirements,
    analyze_traceability,
    build_spec_index,
)
from cecli.spec.ears.model import EarsLintResult
from cecli.spec.jobs import spec_gen_timeout_s
from cecli.spec.runtime import AgentTodoSession, SpecTurnRunner

_FORBIDDEN_PREFIXES = (
    "bright_vision_core",
    "fastapi",
    "bright_vision",
)


def _spec_root() -> Path:
    return Path(cecli.spec.__file__).resolve().parent


class TestSpecPackage(unittest.TestCase):
    def test_public_api_imports(self):
        self.assertTrue(callable(analyze_requirements))
        self.assertTrue(callable(analyze_traceability))
        self.assertTrue(callable(build_spec_index))
        self.assertTrue(callable(spec_gen_timeout_s))
        job = SpecGenerationJob(job_id="j1", workspace="/tmp", todo_id="t1")
        self.assertEqual(job.status, "pending")

    def test_ears_subpackage_exports(self):
        self.assertTrue(hasattr(ears_pkg, "analyze_requirements"))
        self.assertTrue(hasattr(ears_pkg, "build_spec_index"))

    def test_runtime_protocols_are_importable(self):
        # Structural typing — no runtime isinstance checks required.
        self.assertTrue(hasattr(SpecTurnRunner, "apply_spec_gen_route"))
        self.assertTrue(hasattr(AgentTodoSession, "coder"))

    def test_no_forbidden_imports_in_spec_tree(self):
        violations: list[str] = []
        for path in sorted(_spec_root().rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name.startswith(p) for p in _FORBIDDEN_PREFIXES):
                            violations.append(f"{path.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and any(node.module.startswith(p) for p in _FORBIDDEN_PREFIXES):
                        violations.append(f"{path.name}: from {node.module}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_ears_lint_result_serializes(self):
        result = analyze_requirements("### REQ-001\n**WHEN** x\n**THE** system **SHALL** y.\n")
        self.assertIsInstance(result, EarsLintResult)
        payload = result.to_dict()
        self.assertIn("ok", payload)
        self.assertIn("issues", payload)


if __name__ == "__main__":
    unittest.main()
