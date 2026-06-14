"""Debug export bundle for background todo spec generation jobs."""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from typing import Any

from cecli.spec.jobs import SpecGenerationJob, job_wall_timeout_s, spec_gen_timeout_s

_MAX_RAW_PREVIEW = 12_000


def _truncate_text(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _duplicate_call_hints(invocations: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, int] = {}
    hints: list[str] = []
    for inv in invocations:
        key = f"{inv.get('tool', '')}:{inv.get('args_preview', '')}"
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 2:
            hints.append(f"Duplicate tool call: {key[:120]}")
    return hints


def _tool_invocations(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        for inv in msg.get("tool_invocations") or []:
            if isinstance(inv, dict):
                out.append(inv)
    return out


def build_spec_job_debug_export(job: SpecGenerationJob) -> dict[str, Any]:
    """JSON-serializable debug bundle for a spec generation job (live or finished)."""
    messages = list(job.messages or [])
    invocations = _tool_invocations(messages)

    return {
        "format": "brightvision-spec-job-debug-v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "job_id": job.job_id,
        "job": {
            "status": job.status,
            "workspace": job.workspace,
            "todo_id": job.todo_id,
            "model": job.model,
            "mode": job.mode,
            "section": job.section,
            "prompt_preview": _truncate_text(job.prompt, 500),
            "error": job.error,
            "ears_blocked": bool(job.ears_blocked),
            "ears_issues": list(getattr(job, "ears_issues", None) or []),
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "wall_timeout_s": job_wall_timeout_s(job),
            "turn_timeout_s": getattr(job, "turn_timeout_s", None),
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "spec_gen_timeout_s": spec_gen_timeout_s(),
        },
        "result_preview": {
            "requirements_chars": len(job.requirements or ""),
            "design_chars": len(job.design or ""),
            "tasks_md_chars": len(job.tasks_md or ""),
            "raw_preview": _truncate_text(job.raw or "", 4000),
        },
        "messages": messages,
        "tool_invocations": invocations,
        "duplicate_tool_call_hints": _duplicate_call_hints(invocations),
        "recent_io_events": list(job.recent_io_events or []),
        "notes": (
            "Spec jobs run in a short-lived headless session separate from chat. "
            "Export while running or after error/timeout to diagnose stalled generation. "
            "Redact secrets before posting publicly."
        ),
    }
