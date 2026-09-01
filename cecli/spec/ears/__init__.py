"""
EARS (Easy Approach to Requirements Syntax) — spec grammar, lint, and index.

Standalone package: no imports from Session, http_api, or workspace_todos.
Designed for eventual lift into cecli (see docs/EARS_MODULE.md).
"""

from cecli.spec.ears.index import build_spec_index
from cecli.spec.ears.lint import analyze_requirements
from cecli.spec.ears.model import (
    EarsClause,
    EarsIssue,
    EarsLintResult,
    PatternKind,
    Severity,
)
from cecli.spec.ears.trace import analyze_traceability

__all__ = [
    "EarsClause",
    "EarsIssue",
    "EarsLintResult",
    "PatternKind",
    "Severity",
    "analyze_requirements",
    "analyze_traceability",
    "build_spec_index",
]
