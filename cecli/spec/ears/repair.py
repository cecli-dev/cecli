"""Deterministic repairs for small-model requirement drafts before EARS gate."""

from __future__ import annotations

from cecli.spec.ears.parse import parse_requirements_markdown
from cecli.spec.ears.patterns import has_shall

_SHALL_SUFFIX = " **THE** system **SHALL** satisfy this acceptance criterion."


def repair_requirements_missing_shall(requirements: str) -> str:
    """Add normative SHALL to parsed EARS clauses missing SHALL (common small-model slip)."""
    if not (requirements or "").strip():
        return requirements
    lines = requirements.replace("\r\n", "\n").split("\n")
    fixed_line_nums: set[int] = set()
    for clause in parse_requirements_markdown(requirements):
        if has_shall(clause.text):
            continue
        idx = clause.line - 1
        if idx < 0 or idx >= len(lines) or idx in fixed_line_nums:
            continue
        lines[idx] = lines[idx].rstrip() + _SHALL_SUFFIX
        fixed_line_nums.add(idx)
    return "\n".join(lines)
