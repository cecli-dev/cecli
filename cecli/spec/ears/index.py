"""Repo-wide ``.cecli/specs/**`` index vs ``todos.json`` (roadmap #22)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cecli.spec.ears.lint import analyze_requirements
from cecli.spec.ears.model import EarsIssue, Severity
from cecli.spec.ears.parse import parse_requirements_markdown


@dataclass
class SpecFolderRecord:
    todo_id: str
    has_requirements: bool = False
    has_design: bool = False
    has_tasks: bool = False
    req_ids: list[str] = field(default_factory=list)
    requirements_ok: bool | None = None
    requirements_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpecIndexResult:
    issues: list[EarsIssue] = field(default_factory=list)
    folders: list[SpecFolderRecord] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)

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
            "task_ids": list(self.task_ids),
            "folders": [f.to_dict() for f in self.folders],
            "issues": [i.to_dict() for i in self.issues],
        }


def _issue(
    code: str,
    message: str,
    severity: Severity,
    *,
    todo_id: str | None = None,
    req_id: str | None = None,
) -> EarsIssue:
    return EarsIssue(
        code=code,
        message=message,
        severity=severity,
        req_id=req_id,
        todo_id=todo_id,
        line=None,
    )


def _read_layer(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError:
        return ""


def _scan_spec_folder(folder: Path) -> SpecFolderRecord:
    todo_id = folder.name
    rec = SpecFolderRecord(todo_id=todo_id)
    req_path = folder / "requirements.md"
    if req_path.is_file():
        rec.has_requirements = True
        text = _read_layer(req_path)
        clauses = parse_requirements_markdown(text)
        seen: set[str] = set()
        for clause in clauses:
            if clause.req_id:
                rid = clause.req_id.upper()
                if rid not in seen:
                    seen.add(rid)
                    rec.req_ids.append(rid)
        lint = analyze_requirements(text, source_path=str(req_path))
        rec.requirements_ok = lint.ok
        rec.requirements_errors = lint.error_count
    rec.has_design = (folder / "design.md").is_file()
    rec.has_tasks = (folder / "tasks.md").is_file()
    return rec


def build_spec_index(
    workspace_root: str | Path,
    *,
    task_ids: list[str] | None = None,
    specs_root: Path | None = None,
) -> SpecIndexResult:
    """
    Compare ``.cecli/specs/{id}/`` on disk to workspace task ids.

    ``task_ids`` — from ``todos.json``; when omitted, only folder scan runs.
    """
    root = Path(workspace_root).resolve()
    specs = specs_root or root / ".cecli" / "specs"
    issues: list[EarsIssue] = []
    folders: list[SpecFolderRecord] = []

    known_tasks = {t.strip() for t in task_ids or [] if t.strip()}
    if specs.is_dir():
        for entry in sorted(specs.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            rec = _scan_spec_folder(entry)
            folders.append(rec)
            if known_tasks and rec.todo_id not in known_tasks:
                issues.append(
                    _issue(
                        "SPEC_ORPHAN_FOLDER",
                        f"Spec folder `.cecli/specs/{rec.todo_id}/` has no matching task in todos.json.",
                        "warning",
                        todo_id=rec.todo_id,
                    )
                )
            if rec.has_requirements and rec.requirements_ok is False:
                issues.append(
                    _issue(
                        "SPEC_REQ_LINT",
                        f"requirements.md has {rec.requirements_errors} EARS error(s).",
                        "error",
                        todo_id=rec.todo_id,
                    )
                )

    if known_tasks:
        folder_ids = {f.todo_id for f in folders}
        for tid in sorted(known_tasks):
            if tid not in folder_ids:
                issues.append(
                    _issue(
                        "SPEC_MISSING_FOLDER",
                        f"Task `{tid}` has no `.cecli/specs/{tid}/` folder (sync writes on save).",
                        "info",
                        todo_id=tid,
                    )
                )

    by_req: dict[str, list[str]] = defaultdict(list)
    for rec in folders:
        for rid in rec.req_ids:
            by_req[rid.upper()].append(rec.todo_id)
    for rid, tasks in sorted(by_req.items()):
        if len(tasks) > 1:
            issues.append(
                _issue(
                    "SPEC_REQ_ID_GLOBAL_DUP",
                    f"{rid} appears in multiple tasks: {', '.join(tasks)}.",
                    "error",
                    req_id=rid,
                )
            )

    return SpecIndexResult(
        issues=issues,
        folders=folders,
        task_ids=sorted(known_tasks),
    )
