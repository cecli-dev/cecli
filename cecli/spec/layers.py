"""Heuristics and normalization for three-layer generated specs."""

from __future__ import annotations

import re


def design_references_requirements(requirements: str, design: str) -> bool:
    req = (requirements or "").strip()
    des = (design or "").strip()
    if not des or not re.search(r"REQ-\d+", req, re.I):
        return True
    if re.search(r"REQ-\d+", des, re.I):
        return True
    nums = [m.group(1) for m in re.finditer(r"REQ-(\d+)", req, re.I)]
    if any(re.search(rf"\b{n}\b", des) for n in nums):
        return True
    if re.search(r"\brequirement\s*\d+", des, re.I):
        return True
    return False


def requirement_ids(requirements: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"REQ-\d+", requirements, re.I)))


def normalize_spec_layer_traceability(layers: dict[str, str]) -> dict[str, str]:
    """Ensure design cites REQ ids when requirements define them (small-model guard)."""
    req = (layers.get("requirements") or "").strip()
    design = (layers.get("design") or "").strip()
    ids = requirement_ids(req)
    if not ids:
        return layers
    if all(re.search(rf"\b{re.escape(rid)}\b", design, re.I) for rid in ids):
        return layers
    trace = "Covers " + ", ".join(ids) + "."
    out = dict(layers)
    if not design:
        out["design"] = f"## Traceability\n{trace}"
    else:
        out["design"] = f"{design.rstrip()}\n\n## Traceability\n{trace}"
    return out


_DESIGN_SUBSECTIONS = (
    ("architecture", "Architecture"),
    ("component", "Components and Interfaces"),
    ("data model", "Data Models"),
    ("error", "Error Handling"),
    ("testing", "Testing Strategy"),
)


def assess_spec_richness(
    requirements: str,
    design: str,
    tasks_md: str,
) -> tuple[bool, list[str]]:
    """Non-gating depth check — suggestions to make a spec Kiro-grade.

    Unlike :func:`assess_generated_spec_layers` (a hard usability gate), this only
    returns advisory suggestions so a thin-but-valid spec can be deepened.
    """
    suggestions: list[str] = []
    req = (requirements or "").strip()
    des = (design or "").strip()
    tasks = (tasks_md or "").strip()

    if req:
        if "user story" not in req.lower():
            suggestions.append("requirements: add a **User Story** line to each requirement")
        criteria = len(re.findall(r"(?m)^\s*\d+\.\s+", req))
        ids = len(requirement_ids(req))
        if ids < 2 or criteria < 4:
            suggestions.append(
                "requirements: add more requirements and acceptance criteria "
                "(happy path, edge cases, errors)"
            )

    if des:
        low = des.lower()
        missing = [label for key, label in _DESIGN_SUBSECTIONS if key not in low]
        if missing:
            suggestions.append("design: add subsections (" + ", ".join(missing) + ")")

    if tasks:
        steps = re.findall(r"(?m)^\s*(?:-\s*\[[ xX]\]\s*)?\d+\.", tasks)
        if len(steps) < 3:
            suggestions.append("tasks: break the work into more incremental, test-driven steps")

    return len(suggestions) == 0, suggestions


def assess_generated_spec_layers(
    requirements: str,
    design: str,
    tasks_md: str,
) -> tuple[bool, list[str]]:
    issues: list[str] = []
    req = (requirements or "").strip()
    des = (design or "").strip()
    tasks = (tasks_md or "").strip()

    if not req:
        issues.append("requirements empty")
    if not des:
        issues.append("design empty")
    if not tasks:
        issues.append("tasks_md empty")

    if req:
        if not re.search(r"REQ-\d+", req, re.I):
            issues.append("requirements missing REQ-### id")
        if not re.search(r"\bshall\b", req, re.I):
            issues.append("requirements missing SHALL")
        if not re.search(r"\bwhen\b", req, re.I):
            issues.append("requirements missing WHEN")

    if tasks and not re.search(r"(?:^|\n)\s*(?:-\s*\[[ xX]\]\s*)?\d+\.\s+", tasks):
        issues.append("tasks_md missing numbered implementation steps")

    if des and req and not design_references_requirements(req, des):
        if not (tasks and design_references_requirements(req, tasks)):
            issues.append("design does not reference any REQ id")

    return len(issues) == 0, issues
