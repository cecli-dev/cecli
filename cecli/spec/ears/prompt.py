"""EARS / trace context for LLM spec generate and refine (E5)."""

from __future__ import annotations

from cecli.spec.ears.lint import analyze_requirements
from cecli.spec.ears.report import format_lint_summary, format_trace_summary
from cecli.spec.ears.trace import analyze_traceability
from cecli.spec.layers import assess_spec_richness


def format_spec_quality_for_prompt(
    requirements: str,
    design: str,
    tasks_md: str,
) -> str:
    """Deterministic lint + trace summary appended to generate/refine prompts."""
    req = (requirements or "").strip()
    des = (design or "").strip()
    tsk = (tasks_md or "").strip()
    if not req and not des and not tsk:
        return ""
    lint = analyze_requirements(req) if req else None
    trace = analyze_traceability(req, des, tsk) if req else None
    parts: list[str] = ["", "## Current spec quality (fix in your output)"]
    if lint:
        parts.append(format_lint_summary(lint))
    if trace:
        parts.append(format_trace_summary(trace))
        for issue in trace.issues[:8]:
            parts.append(f"- [{issue.severity}] {issue.code}: {issue.message}")
    _, depth = assess_spec_richness(req, des, tsk)
    if depth:
        parts.append("Deepen the spec (Kiro-grade):")
        for hint in depth:
            parts.append(f"- {hint}")
    parts.append(
        "Use ### REQ-### headings with a **User Story** and numbered EARS acceptance criteria "
        "(**WHEN** … **THE** system **SHALL** …). Align design and implementation tasks with every REQ id."
    )
    return "\n".join(parts)


def requirements_pass_ears(requirements: str) -> tuple[bool, list[dict]]:
    """Return (ok, issue dicts) for apply gate."""
    result = analyze_requirements(requirements or "")
    return result.ok, [i.to_dict() for i in result.issues if i.severity == "error"]
