"""REQ ↔ design ↔ implementation task traceability (roadmap E4)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from cecli.spec.ears.model import EarsIssue, Severity
from cecli.spec.ears.parse import parse_requirements_markdown

_REQ_REF = re.compile(r"\b(REQ-\d+)\b", re.I)
_IMPL_STEP = re.compile(
    r"^\s*(?:-\s*\[([ xX])\]\s*)?(\d+)\.\s*(.+?)(?:\s*\(depends:\s*[^)]+\))?\s*$",
    re.I,
)
_DESIGN_HEADING = re.compile(r"^#{2,}\s+(.+)$")


@dataclass
class TraceStep:
    number: int
    text: str
    done: bool
    req_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TraceLink:
    req_id: str
    in_design: bool = False
    task_steps: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TraceabilityResult:
    issues: list[EarsIssue] = field(default_factory=list)
    req_ids: list[str] = field(default_factory=list)
    links: list[TraceLink] = field(default_factory=list)
    steps: list[TraceStep] = field(default_factory=list)
    design_headings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "req_ids": list(self.req_ids),
            "links": [link.to_dict() for link in self.links],
            "steps": [s.to_dict() for s in self.steps],
            "design_headings": list(self.design_headings),
            "issues": [i.to_dict() for i in self.issues],
        }


def _issue(
    code: str,
    message: str,
    severity: Severity,
    *,
    req_id: str | None = None,
) -> EarsIssue:
    return EarsIssue(code=code, message=message, severity=severity, req_id=req_id)


def _extract_req_refs(text: str) -> set[str]:
    return {m.group(1).upper() for m in _REQ_REF.finditer(text)}


def _parse_steps(tasks_md: str) -> list[TraceStep]:
    steps: list[TraceStep] = []
    for line in tasks_md.replace("\r\n", "\n").split("\n"):
        m = _IMPL_STEP.match(line.strip())
        if not m:
            continue
        body = m.group(3).strip()
        steps.append(
            TraceStep(
                number=int(m.group(2)),
                text=body,
                done=m.group(1) is not None and m.group(1).lower() == "x",
                req_refs=sorted(_extract_req_refs(body)),
            )
        )
    return sorted(steps, key=lambda s: s.number)


def _parse_design_headings(design: str) -> list[str]:
    headings: list[str] = []
    for line in design.replace("\r\n", "\n").split("\n"):
        m = _DESIGN_HEADING.match(line.strip())
        if m:
            headings.append(m.group(1).strip())
    return headings


def analyze_traceability(
    requirements: str,
    design: str,
    tasks_md: str,
) -> TraceabilityResult:
    """Map REQ ids across the three spec layers for one task."""
    issues: list[EarsIssue] = []
    clauses = parse_requirements_markdown(requirements)
    req_ids: list[str] = []
    seen: set[str] = set()
    for clause in clauses:
        if clause.req_id:
            rid = clause.req_id.upper()
            if rid not in seen:
                seen.add(rid)
                req_ids.append(rid)

    design_refs = _extract_req_refs(design)
    design_headings = _parse_design_headings(design)
    steps = _parse_steps(tasks_md)
    task_refs: set[str] = set()
    for step in steps:
        task_refs.update(step.req_refs)

    links: list[TraceLink] = []
    for rid in req_ids:
        in_design = rid in design_refs
        task_steps = [s.number for s in steps if rid in s.req_refs]
        links.append(TraceLink(req_id=rid, in_design=in_design, task_steps=task_steps))
        if not in_design and not task_steps:
            issues.append(
                _issue(
                    "TRACE_REQ_UNCOVERED",
                    f"{rid} is not referenced in design.md or tasks.md.",
                    "warning",
                    req_id=rid,
                )
            )

    known = set(req_ids)
    for ref in sorted(design_refs | task_refs):
        if ref not in known:
            issues.append(
                _issue(
                    "TRACE_REQ_UNKNOWN",
                    f"{ref} is referenced in design/tasks but not declared under Requirements.",
                    "error",
                    req_id=ref,
                )
            )

    if req_ids and not design.strip() and not tasks_md.strip():
        issues.append(
            _issue(
                "TRACE_LAYER_EMPTY",
                "Requirements exist but design and implementation tasks are empty.",
                "warning",
            )
        )

    return TraceabilityResult(
        issues=issues,
        req_ids=req_ids,
        links=links,
        steps=steps,
        design_headings=design_headings,
    )
