"""Background spec-generation job types and timeout helpers."""

from __future__ import annotations

import os
import unittest

from cecli.spec.jobs import (
    SpecGenerationJob,
    job_turn_timeout_s,
    job_wall_timeout_s,
    spec_gen_section_wait_s,
    spec_gen_timeout_s,
    spec_gen_turn_timeout_s,
)


class TestSpecJobs(unittest.TestCase):
    def test_spec_gen_timeout_s_env_override(self):
        prev = os.environ.get("LLM_SPEC_GEN_TIMEOUT_S")
        os.environ["LLM_SPEC_GEN_TIMEOUT_S"] = "900"
        try:
            self.assertEqual(spec_gen_timeout_s(), 900.0)
        finally:
            if prev is None:
                os.environ.pop("LLM_SPEC_GEN_TIMEOUT_S", None)
            else:
                os.environ["LLM_SPEC_GEN_TIMEOUT_S"] = prev

    def test_spec_gen_timeout_s_invalid_env_falls_back(self):
        prev = os.environ.get("LLM_SPEC_GEN_TIMEOUT_S")
        os.environ["LLM_SPEC_GEN_TIMEOUT_S"] = "not-a-number"
        try:
            self.assertGreaterEqual(spec_gen_timeout_s(), 60.0)
        finally:
            if prev is None:
                os.environ.pop("LLM_SPEC_GEN_TIMEOUT_S", None)
            else:
                os.environ["LLM_SPEC_GEN_TIMEOUT_S"] = prev

    def test_job_wall_timeout_prefers_job_override(self):
        job = SpecGenerationJob(
            job_id="j",
            workspace="/tmp",
            todo_id="t",
            wall_timeout_s=180.0,
        )
        self.assertEqual(job_wall_timeout_s(job), 180.0)

    def test_job_turn_timeout_prefers_job_override(self):
        job = SpecGenerationJob(
            job_id="j",
            workspace="/tmp",
            todo_id="t",
            turn_timeout_s=90.0,
        )
        self.assertEqual(job_turn_timeout_s(job), 90.0)

    def test_section_wait_bounded_by_job_cap(self):
        prev_job = os.environ.get("LLM_SPEC_GEN_TIMEOUT_S")
        prev_turn = os.environ.get("LLM_SPEC_GEN_TURN_TIMEOUT_S")
        os.environ["LLM_SPEC_GEN_TIMEOUT_S"] = "300"
        os.environ["LLM_SPEC_GEN_TURN_TIMEOUT_S"] = "200"
        try:
            wait = spec_gen_section_wait_s()
            self.assertLessEqual(wait, spec_gen_timeout_s())
            self.assertGreaterEqual(wait, spec_gen_turn_timeout_s())
        finally:
            for key, prev in (
                ("LLM_SPEC_GEN_TIMEOUT_S", prev_job),
                ("LLM_SPEC_GEN_TURN_TIMEOUT_S", prev_turn),
            ):
                if prev is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prev


if __name__ == "__main__":
    unittest.main()
