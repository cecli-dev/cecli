"""Spec job debug export (unit tests — HTTP routes stay in BrightVision tests/core)."""

from __future__ import annotations

import unittest

from cecli.spec.job_debug import build_spec_job_debug_export
from cecli.spec.jobs import SpecGenerationJob


class TestSpecJobDebug(unittest.TestCase):
    def test_build_spec_job_debug_export_shape(self):
        job = SpecGenerationJob(
            job_id="abc123",
            workspace="/tmp/ws",
            todo_id="todo-1",
            prompt="Build modules",
            mode="generate",
            section="requirements",
            model="gpt-4o",
            status="running",
            recent_io_events=[{"type": "progress", "label": "LLM", "message": "Waiting…"}],
        )
        payload = build_spec_job_debug_export(job)
        self.assertEqual(payload["format"], "brightvision-spec-job-debug-v1")
        self.assertEqual(payload["job_id"], "abc123")
        self.assertEqual(payload["job"]["status"], "running")
        self.assertEqual(payload["job"]["section"], "requirements")
        self.assertEqual(len(payload["recent_io_events"]), 1)


if __name__ == "__main__":
    unittest.main()
