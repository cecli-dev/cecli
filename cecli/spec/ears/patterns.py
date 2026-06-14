"""Classify EARS clause shapes (deterministic)."""

from __future__ import annotations

import re

from cecli.spec.ears.model import PatternKind

_RE_WHEN = re.compile(r"\bWHEN\b", re.I)
_RE_WHILE = re.compile(r"\bWHILE\b", re.I)
_RE_IF_THEN = re.compile(r"\bIF\b.+\bTHEN\b", re.I | re.S)
_RE_WHERE = re.compile(r"\bWHERE\b", re.I)
_RE_SHALL = re.compile(r"\bSHALL\b", re.I)
_RE_THE_SYSTEM_SHALL = re.compile(
    r"\bTHE\b.+\bSHALL\b",
    re.I | re.S,
)


def classify_clause(text: str) -> PatternKind:
    t = text.strip()
    if not t:
        return "unknown"
    if _RE_IF_THEN.search(t):
        return "unwanted"
    if _RE_WHERE.search(t) and _RE_SHALL.search(t):
        return "optional"
    if _RE_WHILE.search(t) and _RE_SHALL.search(t):
        return "state_driven"
    if _RE_WHEN.search(t) and _RE_SHALL.search(t):
        return "event_driven"
    if _RE_THE_SYSTEM_SHALL.search(t):
        return "ubiquitous"
    if _RE_SHALL.search(t):
        return "complex"
    return "unknown"


def has_shall(text: str) -> bool:
    return bool(_RE_SHALL.search(text))


def has_the_system_shall(text: str) -> bool:
    return bool(_RE_THE_SYSTEM_SHALL.search(text))
