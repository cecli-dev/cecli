"""EARS report formatters for UI, logs, and LLM prompt context."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cecli.spec.ears import analyze_requirements, analyze_traceability, build_spec_index
from cecli.spec.ears.report import (
    format_lint_summary,
    format_spec_index_summary,
    format_trace_summary,
)


class TestEarsReport(unittest.TestCase):
    def test_format_lint_summary_ok(self):
        result = analyze_requirements("### REQ-001\n**WHEN** x\n**THE** system **SHALL** y.\n")
        summary = format_lint_summary(result)
        self.assertIn("no issues", summary.lower())

    def test_format_lint_summary_errors(self):
        result = analyze_requirements("### REQ-001\n**WHEN** x\n**THE** system shows y.\n")
        summary = format_lint_summary(result)
        self.assertIn("error", summary.lower())
        self.assertIn("EARS_NO_SHALL", summary)

    def test_format_trace_summary_counts_coverage(self):
        req = "### REQ-001\n**WHEN** x\n**THE** system **SHALL** y.\n"
        design = "## Overview\nImplements REQ-001.\n"
        tasks = "- [ ] 1. Step (depends: none) — REQ-001\n"
        trace = analyze_traceability(req, design, tasks)
        summary = format_trace_summary(trace)
        self.assertIn("Trace:", summary)
        self.assertIn("1/1", summary)

    def test_format_trace_summary_no_req_ids(self):
        trace = analyze_traceability("", "design", "tasks")
        summary = format_trace_summary(trace)
        self.assertIn("no REQ", summary)

    def test_format_spec_index_summary_empty_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_spec_index(tmp, task_ids=[])
            summary = format_spec_index_summary(result)
            self.assertIn("Spec index:", summary)
            self.assertIn("OK", summary)

    def test_format_spec_index_summary_orphan_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            orphan = Path(tmp) / ".cecli" / "specs" / "orphan-task"
            orphan.mkdir(parents=True)
            (orphan / "requirements.md").write_text(
                "### REQ-001\n**WHEN** x\n**THE** system **SHALL** y.\n",
                encoding="utf-8",
            )
            result = build_spec_index(tmp, task_ids=["known-task"])
            summary = format_spec_index_summary(result)
            self.assertIn("warning", summary.lower())


if __name__ == "__main__":
    unittest.main()
