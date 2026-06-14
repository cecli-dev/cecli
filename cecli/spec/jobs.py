"""Background spec-generation job types and timeout helpers (store lives in Vision HTTP)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["pending", "running", "completed", "error"]

_MAX_JOBS = 64
_JOB_TTL_S = 3600
_DEFAULT_WAIT_S = 1200.0


def spec_gen_timeout_s() -> float:
    """Wall-clock cap for background generate-spec jobs (pytest + HTTP sync wait)."""
    raw = os.environ.get("LLM_SPEC_GEN_TIMEOUT_S", str(int(_DEFAULT_WAIT_S)))
    try:
        return max(60.0, float(raw))
    except ValueError:
        return _DEFAULT_WAIT_S


def spec_gen_turn_timeout_s() -> float:
    """Wall-clock cap for one LLM one-shot inside generate-spec (run_one_shot)."""
    if os.environ.get("LLM_SPEC_GEN_TURN_TIMEOUT_S"):
        try:
            return max(60.0, float(os.environ["LLM_SPEC_GEN_TURN_TIMEOUT_S"]))
        except ValueError:
            pass
    job_cap = spec_gen_timeout_s()
    if os.environ.get("LLM_TEST_TURN_TIMEOUT_S"):
        try:
            chat_cap = float(os.environ["LLM_TEST_TURN_TIMEOUT_S"])
        except ValueError:
            chat_cap = 300.0
    else:
        chat_cap = 300.0
    scaled = min(job_cap - 60.0, max(chat_cap, job_cap * 0.6))
    return max(60.0, scaled)


def spec_gen_section_wait_s() -> float:
    """Poll cap for one phased section — slightly above one-shot turn cap."""
    return min(spec_gen_timeout_s(), spec_gen_turn_timeout_s() + 120.0)


def job_wall_timeout_s(job: SpecGenerationJob) -> float:
    if job.wall_timeout_s is not None and job.wall_timeout_s > 0:
        return float(job.wall_timeout_s)
    return spec_gen_timeout_s()


def job_turn_timeout_s(job: SpecGenerationJob) -> float:
    if job.turn_timeout_s is not None and job.turn_timeout_s > 0:
        return float(job.turn_timeout_s)
    return spec_gen_turn_timeout_s()


@dataclass
class SpecGenerationJob:
    job_id: str
    workspace: str
    todo_id: str
    prompt: str = ""
    mode: str = "generate"
    section: str = "all"
    model: str | None = None
    status: JobStatus = "pending"
    error: str | None = None
    requirements: str = ""
    design: str = ""
    tasks_md: str = ""
    raw: str = ""
    item: Any = None
    ears_blocked: bool = False
    ears_issues: list[dict] = field(default_factory=list)
    wall_timeout_s: float | None = None
    turn_timeout_s: float | None = None
    recent_io_events: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


__all__ = [
    "JobStatus",
    "SpecGenerationJob",
    "_JOB_TTL_S",
    "_MAX_JOBS",
    "job_turn_timeout_s",
    "job_wall_timeout_s",
    "spec_gen_section_wait_s",
    "spec_gen_timeout_s",
    "spec_gen_turn_timeout_s",
]
