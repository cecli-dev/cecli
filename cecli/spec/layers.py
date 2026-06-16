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


_TASK_NUMBERED_RE = re.compile(r"(?:^|\n)\s*(?:-\s*\[[ xX]\]\s*)?\d+\.\s+")


def tasks_have_numbered_steps(tasks_md: str) -> bool:
    return bool(_TASK_NUMBERED_RE.search(tasks_md or ""))


def normalize_tasks_md_numbering(tasks_md: str) -> str:
    """Coerce plain bullets into numbered checklist lines (small-model guard)."""
    tasks = (tasks_md or "").strip()
    if not tasks or tasks_have_numbered_steps(tasks):
        return tasks_md or ""

    lines = tasks.splitlines()
    out: list[str] = []
    n = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        if re.match(r"^\d+\.\s+", stripped):
            n = max(n, int(stripped.split(".", 1)[0]))
            out.append(f"- [ ] {stripped}")
            continue
        m = re.match(r"^[-*]\s*(?:\[[ xX]\]\s*)?(\d+)[.)]\s+(.+)$", stripped)
        if m:
            n = max(n, int(m.group(1)))
            out.append(f"- [ ] {m.group(1)}. {m.group(2)}")
            continue
        m = re.match(r"^[-*]\s*\[[ xX]\]\s*(.+)$", stripped)
        if m:
            body = m.group(1).strip()
            if re.match(r"^\d+\.\s+", body):
                out.append(line)
                continue
            n += 1
            out.append(f"- [ ] {n}. {body}")
            continue
        m = re.match(r"^[-*]\s+(.+)$", stripped)
        if m:
            body = m.group(1).strip()
            m2 = re.match(r"^(\d+)\.\s+", body)
            if m2:
                n = max(n, int(m2.group(1)))
                out.append(f"- [ ] {body}")
                continue
            n += 1
            out.append(f"- [ ] {n}. {body}")
            continue
        m = re.match(r"^(?:task\s*)?(\d+)\s*[:.)]\s*(.+)$", stripped, re.I)
        if m:
            n = max(n, int(m.group(1)))
            out.append(f"- [ ] {m.group(1)}. {m.group(2).strip()}")
            continue
        out.append(line)

    result = "\n".join(out).strip()
    if tasks_have_numbered_steps(result):
        return result
    return tasks_md


def normalize_spec_layer_traceability(layers: dict[str, str]) -> dict[str, str]:
    """Ensure design cites REQ ids and tasks use numbered steps (small-model guard)."""
    out = dict(layers)
    req = (out.get("requirements") or "").strip()
    design = (out.get("design") or "").strip()
    ids = requirement_ids(req)
    if ids and not all(re.search(rf"\b{re.escape(rid)}\b", design, re.I) for rid in ids):
        trace = "Covers " + ", ".join(ids) + "."
        if not design:
            out["design"] = f"## Traceability\n{trace}"
        else:
            out["design"] = f"{design.rstrip()}\n\n## Traceability\n{trace}"
    tasks = normalize_tasks_md_numbering(out.get("tasks_md", ""))
    if tasks.strip():
        out["tasks_md"] = tasks
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
