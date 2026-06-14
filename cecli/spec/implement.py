"""Ground spec-focus implement turns in on-disk workspace facts (avoid ls loops)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from cecli.spec.steering import workspace_lib_missing
from cecli.spec.todos import ChecklistItem

_PATH_IN_CHECKLIST = re.compile(
    r"(?:`((?:lib|test)/[\w./-]+)`|((?:lib|test)/[\w./-]+))",
    re.IGNORECASE,
)

_SNAPSHOT_DIRS = ("lib", "test")
_MAX_LIST_FILES = 24


def list_workspace_test_files(workspace: str | Path, *, limit: int = _MAX_LIST_FILES) -> list[str]:
    return _list_tree_files(Path(workspace).resolve(), "test", limit=limit)


def _list_tree_files(root: Path, subdir: str, *, limit: int = _MAX_LIST_FILES) -> list[str]:
    base = root / subdir
    if not base.is_dir():
        return []
    out: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        rel = path.relative_to(root).as_posix()
        out.append(rel)
        if len(out) >= limit:
            break
    return out


def paths_from_checklist_text(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _PATH_IN_CHECKLIST.finditer(text or ""):
        raw = (match.group(1) or match.group(2) or "").strip().rstrip("/")
        if not raw or raw in seen:
            continue
        seen.add(raw)
        found.append(raw)
    return found


def deliverable_paths_exist(workspace: str | Path, paths: list[str]) -> bool:
    """True when every path is an existing file or non-empty directory."""
    root = Path(workspace).resolve()
    if not paths:
        return False
    for rel in paths:
        target = root / rel
        if target.is_file():
            continue
        if target.is_dir() and any(target.iterdir()):
            continue
        return False
    return True


_IMPLEMENT_ONLY_TASK_RE = re.compile(
    r"^implement only implementation task\s+([\d.]+)\s*:",
    re.IGNORECASE,
)
_STEP_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)\b")


def checklist_step_prefix(text: str) -> str | None:
    m = _STEP_PREFIX_RE.match((text or "").strip())
    return m.group(1) if m else None


def implement_step_from_message(message: str) -> str | None:
    trimmed = (message or "").strip()
    if trimmed.lower().startswith("/agent"):
        trimmed = trimmed[6:].lstrip()
    m = _IMPLEMENT_ONLY_TASK_RE.match(trimmed)
    return m.group(1) if m else None


def step_sort_key(step: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in step.split("."))
    except ValueError:
        return (999,)


def is_step_after(candidate: str, focus: str) -> bool:
    return step_sort_key(candidate) > step_sort_key(focus)


def is_test_related_checklist_text(text: str) -> bool:
    lower = (text or "").lower()
    return "test" in lower or "verify" in lower


def first_open_checklist_item(checklist: list[ChecklistItem]) -> ChecklistItem | None:
    for entry in checklist:
        if not entry.done and entry.text.strip():
            return entry
    return None


def focus_checklist_item(
    checklist: list[ChecklistItem],
    *,
    message: str | None = None,
    active_task_title: str | None = None,
) -> ChecklistItem | None:
    """Pick the checklist row this turn should work — aligns with UI active task when possible."""
    if not checklist:
        return None

    step = implement_step_from_message(message or "")
    if step:
        for entry in checklist:
            if not entry.done and (
                entry.text.strip().startswith(step + " ")
                or entry.text.strip().startswith(step + ".")
            ):
                return entry
        for entry in checklist:
            if entry.text.strip().startswith(step + " ") or entry.text.strip().startswith(
                step + "."
            ):
                return entry

    title = (active_task_title or "").strip()
    if title:
        title_lower = title.lower()
        for entry in checklist:
            if not entry.done and title_lower in entry.text.lower():
                return entry
        step_from_title = checklist_step_prefix(title)
        if step_from_title:
            for entry in checklist:
                if not entry.done and entry.text.strip().startswith(step_from_title):
                    return entry
        # Active task may still name a row falsely marked done (agent UpdateTodoList).
        for entry in checklist:
            if title_lower in entry.text.lower():
                return entry
        if step_from_title:
            for entry in checklist:
                if entry.text.strip().startswith(step_from_title):
                    return entry

    return first_open_checklist_item(checklist)


def checklist_item_for_agent_row(
    checklist: list[ChecklistItem],
    row_text: str,
) -> ChecklistItem:
    """Synthetic checklist row for agent todo focus (always ``done=False``)."""
    import uuid

    text = (row_text or "").strip()
    for entry in checklist:
        if entry.text.strip() == text:
            return ChecklistItem(id=entry.id, text=entry.text, done=False)
    step = checklist_step_prefix(text)
    if step:
        for entry in checklist:
            prefix = entry.text.strip()
            if prefix.startswith(step + " ") or prefix.startswith(step + "."):
                return ChecklistItem(id=entry.id, text=entry.text, done=False)
    return ChecklistItem(id=uuid.uuid4().hex[:8], text=text, done=False)


def resolve_implement_focus(
    checklist: list[ChecklistItem],
    *,
    message: str | None = None,
    active_task_title: str | None = None,
    agent_todo_rows: list | None = None,
) -> tuple[ChecklistItem | None, bool]:
    """
    Pick focus for implement/resume turns.

    Returns ``(focus, from_agent_todo)``. When the workspace checklist is fully
    checked but agent ``todo.txt`` has ``→ current``, the agent row wins.
    """
    focus = focus_checklist_item(
        checklist,
        message=message,
        active_task_title=active_task_title,
    )
    if focus is not None:
        return focus, False

    if not agent_todo_rows:
        return None, False

    from cecli.spec.agent_todos import current_agent_todo_row

    row = current_agent_todo_row(agent_todo_rows)
    if row is None or row.done:
        return None, False
    return checklist_item_for_agent_row(checklist, row.text), True


def dart_test_paths_for_focus(workspace: str | Path, focus: ChecklistItem) -> list[str]:
    """Best-effort test file paths for a checklist item mentioning tests."""
    paths = paths_from_checklist_text(focus.text)
    test_paths = [p for p in paths if p.startswith("test/") and p.endswith(".dart")]
    if test_paths:
        return test_paths[:4]
    all_tests = list_workspace_test_files(workspace)
    lower = focus.text.lower()
    tokens = [
        t
        for t in re.split(r"[\W_]+", lower)
        if len(t) > 3 and t not in {"write", "unit", "tests", "test", "for"}
    ]
    scored: list[tuple[int, str]] = []
    for path in all_tests:
        path_lower = path.lower()
        score = sum(1 for tok in tokens if tok in path_lower)
        if score:
            scored.append((score, path))
    if scored:
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [p for _, p in scored[:4]]
    return [f for f in all_tests if f.endswith("_test.dart")][:4]


def resolve_flutter_executable() -> str | None:
    """Locate ``flutter`` when cecli's shell PATH omits it."""
    flutter_root = os.environ.get("FLUTTER_ROOT", "").strip()
    if flutter_root:
        candidate = Path(flutter_root).expanduser() / "bin" / "flutter"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("flutter")
    if found:
        return found
    home = Path.home()
    for candidate in (
        home / "flutter" / "bin" / "flutter",
        home / "development" / "flutter" / "bin" / "flutter",
        home / "fvm" / "default" / "bin" / "flutter",
        Path("/opt/homebrew/bin/flutter"),
        Path("/usr/local/bin/flutter"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def build_workspace_snapshot_lines(workspace: str | Path) -> list[str]:
    root = Path(workspace).resolve()
    lines = ["## Workspace snapshot (verified on disk — do **not** ls to rediscover)"]
    pubspec = root / "pubspec.yaml"
    if pubspec.is_file():
        lines.append("- `pubspec.yaml` — present")
    else:
        lines.append("- `pubspec.yaml` — **missing**")

    for sub in _SNAPSHOT_DIRS:
        files = _list_tree_files(root, sub)
        if not files:
            lines.append(f"- `{sub}/` — **empty or missing**")
            continue
        preview = ", ".join(f"`{f}`" for f in files[:8])
        extra = f" (+{len(files) - 8} more)" if len(files) > 8 else ""
        lines.append(f"- `{sub}/` — {len(files)} file(s): {preview}{extra}")
    return lines


def build_implement_next_action_lines(
    workspace: str | Path,
    checklist: list[ChecklistItem],
    *,
    resume: bool,
    focus: ChecklistItem | None = None,
    message: str | None = None,
    active_task_title: str | None = None,
    agent_todo_rows: list | None = None,
    from_agent_todo: bool = False,
) -> list[str]:
    lines = ["## Next action (this turn)"]
    if focus is None:
        focus, from_agent_todo = resolve_implement_focus(
            checklist,
            message=message,
            active_task_title=active_task_title,
            agent_todo_rows=agent_todo_rows,
        )
    if focus is None:
        lines.append(
            "All checklist items are marked done. Run project tests if applicable, "
            "then update the task status — **no ls/Grep exploration**."
        )
        return lines

    if from_agent_todo:
        lines.append(
            "**Agent todo** is the current step (workspace checklist is fully checked "
            "or out of sync with UpdateTodoList)."
        )
    paths = paths_from_checklist_text(focus.text)
    on_disk = deliverable_paths_exist(workspace, paths) if paths else False
    test_files = _list_tree_files(Path(workspace).resolve(), "test")

    if is_test_related_checklist_text(focus.text) and test_files:
        target = next((f for f in test_files if "test" in f), test_files[0])
        lines.append(f"Focus checklist: **{focus.text.strip()}** — test file(s) already on disk.")
        lines.append(
            f"1. **ReadRange** `{target}` with `@000` / `000@` once\n"
            f"2. **EditText** only if tests need fixes\n"
            f"3. BrightVision runs **`flutter test`** at end of this turn — **do not** run flutter via Command\n"
            f"4. Mark this checklist item done **only after** BrightVision reports tests passed\n"
            f"**Do not** call ls, Grep, GitStatus, or repeat ReadRange on the same file."
        )
    elif on_disk and is_test_related_checklist_text(focus.text):
        test_files = _list_tree_files(Path(workspace).resolve(), "test")
        target = next((f for f in test_files if "test" in f), test_files[0] if test_files else None)
        if target:
            lines.append(
                f"Focus checklist: **{focus.text.strip()}** — deliverable files already exist."
            )
            lines.append(
                f"1. **ReadRange** `{target}` with `@000` / `000@` once\n"
                f"2. **EditText** only if tests need fixes\n"
                f"3. BrightVision runs **`flutter test`** at end of this turn — **do not** run flutter via Command\n"
                f"4. Mark this checklist item done **only after** BrightVision reports tests passed\n"
                f"**Do not** call ls, Grep, GitStatus, or repeat ReadRange on the same file."
            )
        else:
            lines.append(
                f"Focus: **{focus.text.strip()}** — create tests with **ContextManager** + "
                "**ReadRange** + **EditText** (one file). **No ls.**"
            )
    elif on_disk:
        target = paths[0] if paths else "lib/"
        lines.append(
            f"Focus checklist: **{focus.text.strip()}** — paths exist on disk (`{target}`)."
        )
        lines.append(
            "**ReadRange** the target source file, then **EditText** to finish. **No ls.**"
        )
    elif workspace_lib_missing(workspace):
        lines.append(f"Focus checklist: **{focus.text.strip()}**")
        lines.append(
            "**ContextManager** to scaffold `lib/` (and `test/` if needed), then **ReadRange** + "
            "**EditText** on one file. **Do not ls** empty directories."
        )
    elif resume:
        lines.append(f"Focus checklist: **{focus.text.strip()}**")
        lines.append(
            "Use **ReadRange** + **EditText** on **one file** for this item. "
            "**Do not** ls, Grep, or GitStatus — use the workspace snapshot above."
        )
    else:
        lines.append(f"Focus checklist: **{focus.text.strip()}**")
        lines.append(
            "Work **this item only** — do not skip ahead to later numbered tasks. "
            "**ContextManager** / **ReadRange** / **EditText**. **No ls.**"
        )
    lines.append(
        "**Scope:** Mark **only** this checklist item done in UpdateTodoList — "
        "do not mark later steps (e.g. 2.x) until the user starts a new Implement turn."
    )
    return lines


_IMPLEMENT_CONTINUATION_HINT = """\
## Continue (trimmed — token limit / auto-continue)

Work **only** the **Next action** checklist item above. One **EditText** per file.
Do **not** ls, Grep, or GitStatus. Do **not** re-read the full spec.
Do **not** mark items done until edits succeed and BrightVision verifies tests (when applicable)."""


def build_implement_workspace_block(
    workspace: str | Path,
    checklist: list[ChecklistItem] | None,
    *,
    resume: bool,
    message: str | None = None,
    active_task_title: str | None = None,
    agent_continuation: bool = False,
    todo_item: object | None = None,
) -> str:
    """Markdown block injected on implement / resume turns."""
    from cecli.spec.agent_todos import load_agent_todo_rows

    agent_rows = load_agent_todo_rows(workspace, todo_item)  # type: ignore[arg-type]
    parts = build_workspace_snapshot_lines(workspace)
    checklist = checklist or []
    if checklist or agent_rows:
        parts.append("")
        parts.extend(
            build_implement_next_action_lines(
                workspace,
                checklist,
                resume=resume,
                message=message,
                active_task_title=active_task_title,
                agent_todo_rows=agent_rows,
            )
        )
    if agent_continuation:
        parts.append("")
        parts.append(_IMPLEMENT_CONTINUATION_HINT.strip())
    parts.append("")
    parts.append(
        "**Hard rule:** Do not batch UpdateTodoList JSON with other tool args. "
        "One tool per call. Do not call **ls** when this snapshot is present."
    )
    return "\n".join(parts)


def edited_dart_test_files(edited_files: list[str]) -> list[str]:
    out: list[str] = []
    for raw in edited_files:
        rel = raw.replace("\\", "/").lstrip("./")
        if rel.startswith("test/") and rel.endswith("_test.dart"):
            out.append(rel)
    return out


def run_flutter_tests(workspace: str | Path, test_paths: list[str]) -> tuple[bool, str]:
    """Run ``flutter test`` on specific files; return (passed, combined output)."""
    root = Path(workspace).resolve()
    if not (root / "pubspec.yaml").is_file():
        return False, "pubspec.yaml missing — cannot run flutter test"
    if not test_paths:
        return False, "no test paths"
    flutter = resolve_flutter_executable()
    if not flutter:
        return False, "flutter not found on PATH (install Flutter or set FLUTTER_ROOT)"
    cmd = [flutter, "test", *test_paths]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "PATH": os.pathsep.join(_flutter_path_entries(flutter))},
        )
    except subprocess.TimeoutExpired:
        return False, "flutter test timed out after 300s"
    except FileNotFoundError:
        return False, "flutter not found on PATH"
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = out.strip()[-4000:] if out.strip() else "(no output)"
    return proc.returncode == 0, tail


def _flutter_path_entries(flutter_bin: str) -> list[str]:
    entries: list[str] = []
    bin_dir = str(Path(flutter_bin).resolve().parent)
    if bin_dir:
        entries.append(bin_dir)
    entries.extend(os.environ.get("PATH", "").split(os.pathsep))
    seen: set[str] = set()
    out: list[str] = []
    for entry in entries:
        if entry and entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out
