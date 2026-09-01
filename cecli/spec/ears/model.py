"""Data types for EARS lint and traceability (JSON-serializable)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]
PatternKind = Literal[
    "ubiquitous",
    "event_driven",
    "state_driven",
    "unwanted",
    "optional",
    "complex",
    "unknown",
]


@dataclass
class EarsClause:
    """One requirement bullet or paragraph under a REQ heading."""

    req_id: str | None
    line: int
    text: str
    pattern: PatternKind


@dataclass
class EarsIssue:
    code: str
    message: str
    severity: Severity
    line: int | None = None
    req_id: str | None = None
    todo_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EarsLintResult:
    issues: list[EarsIssue] = field(default_factory=list)
    clauses: list[EarsClause] = field(default_factory=list)
    source_path: str | None = None

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
            "source_path": self.source_path,
            "issues": [i.to_dict() for i in self.issues],
            "clauses": [asdict(c) for c in self.clauses],
        }


def merge_results(*results: EarsLintResult) -> EarsLintResult:
    issues: list[EarsIssue] = []
    clauses: list[EarsClause] = []
    for r in results:
        issues.extend(r.issues)
        clauses.extend(r.clauses)
    return EarsLintResult(issues=issues, clauses=clauses)
