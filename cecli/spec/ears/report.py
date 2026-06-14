"""Human-readable summaries for UI and logs."""

from __future__ import annotations

from cecli.spec.ears.index import SpecIndexResult
from cecli.spec.ears.model import EarsLintResult
from cecli.spec.ears.trace import TraceabilityResult


def format_lint_summary(result: EarsLintResult) -> str:
    if result.ok and not result.issues:
        return "EARS: no issues."
    parts = [f"EARS: {result.error_count} error(s), {result.warning_count} warning(s)."]
    for issue in result.issues[:12]:
        loc = ""
        if issue.line:
            loc = f" line {issue.line}"
        if issue.req_id:
            loc += f" ({issue.req_id})"
        parts.append(f"- [{issue.severity}] {issue.code}{loc}: {issue.message}")
    if len(result.issues) > 12:
        parts.append(f"- … and {len(result.issues) - 12} more")
    return "\n".join(parts)


def format_spec_index_summary(result: SpecIndexResult) -> str:
    if result.ok and not result.issues:
        return f"Spec index: {len(result.folders)} folder(s), {len(result.task_ids)} task(s) — OK."
    return (
        f"Spec index: {result.error_count} error(s), {result.warning_count} warning(s) "
        f"({len(result.folders)} folders, {len(result.task_ids)} tasks)."
    )


def format_trace_summary(result: TraceabilityResult) -> str:
    if not result.req_ids:
        return "Trace: no REQ-### ids in requirements."
    covered = sum(1 for link in result.links if link.in_design or link.task_steps)
    return (
        f"Trace: {covered}/{len(result.req_ids)} REQ ids referenced in design or tasks. "
        f"{result.error_count} error(s), {result.warning_count} warning(s)."
    )
