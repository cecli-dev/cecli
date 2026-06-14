"""Parse requirements markdown into EARS clauses."""

from __future__ import annotations

import re

from cecli.spec.ears.model import EarsClause
from cecli.spec.ears.patterns import classify_clause

# Allow an optional title after the id (Kiro-style: "### REQ-001: Health check").
_REQ_HEADING = re.compile(r"^###\s+(REQ-\d+)\b.*$", re.I)
_BULLET = re.compile(r"^(\s*[-*]|\s*\d+\.)\s+")
# Kiro-style labels — not normative EARS clauses (may contain "if"/"while" in prose).
_SKIP_LABEL = re.compile(r"^\*\*(User Story:|Acceptance Criteria)\*\*", re.I)
# Lines that read like normative EARS prose (vs. descriptive User Story text).
_EARS_KEYWORD = re.compile(r"\b(SHALL|WHEN|WHILE|WHERE)\b|\bIF\b", re.I)


def parse_requirements_markdown(text: str) -> list[EarsClause]:
    """Extract requirement clauses with line numbers and optional REQ ids."""
    lines = text.replace("\r\n", "\n").split("\n")
    clauses: list[EarsClause] = []
    current_req_id: str | None = None
    buf: list[str] = []
    buf_line = 0

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        body = " ".join(s.strip() for s in buf if s.strip())
        if body:
            clauses.append(
                EarsClause(
                    req_id=current_req_id,
                    line=buf_line,
                    text=body,
                    pattern=classify_clause(body),
                )
            )
        buf = []

    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        m = _REQ_HEADING.match(line.strip())
        if m:
            flush()
            current_req_id = m.group(1).upper()
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if _SKIP_LABEL.match(stripped):
            flush()
            continue
        if _BULLET.match(line) or (current_req_id and "**WHEN**" in stripped.upper() and not buf):
            flush()
            buf_line = i
            buf = [stripped.lstrip("-* ").strip()]
            continue
        if buf:
            buf.append(stripped)
            continue
        if current_req_id and stripped and _EARS_KEYWORD.search(stripped):
            # Only start a clause for normative prose; descriptive lines such as
            # "**User Story:** As a …" or an "**Acceptance Criteria**" label are skipped.
            buf_line = i
            buf = [stripped]

    flush()
    return clauses
