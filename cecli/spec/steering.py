# flake8: noqa: E501
"""Project steering markdown for spec-focus sessions (Kiro-style)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

STEERING_MAIN_RELPATH = ".cecli/STEERING.md"
STEERING_FRAGMENTS_DIR_RELPATH = ".cecli/steering"

DEFAULT_STEERING_TEMPLATE = """\
# Project steering

Rules the spec agent and implementation turns should follow across **all** tasks in this repo.

## Stack & conventions

- Language / framework:
- Test command:
- Avoid:

## Spec discipline

- EARS: ### REQ-NNN with **WHEN** … **THE** system **SHALL** …
- Keep design and tasks_md aligned with every REQ id.
- Do not mark implementation done until requirements pass EARS lint.
"""

SPEC_FOCUS_INSTRUCTIONS = """\
## Spec-focus mode (BrightVision)

You are in **spec-focus**: work on the active task's requirements, design, and implementation tasks only.

- Prefer editing `.cecli/specs/<task-id>/` layers and related docs; avoid drive-by refactors.
- Use EARS notation: ### REQ-### headings, **WHEN** … **THE** system **SHALL** …
- Keep design and tasks_md aligned with every REQ id; call out gaps explicitly.
- Do not mark implementation done until requirements pass EARS lint (WHEN/SHALL, no duplicate REQ ids).
"""

SCAFFOLD_MISSING_HINT = """\
## Workspace state (read before exploring)

`lib/` does **not** exist yet — scaffolding tasks (e.g. **1.1**, **1.2**) are incomplete.
Do **not** repeat `ls` on `lib/` or `test/`. Use **ContextManager** to create directories/files,
then **ReadRange** + **EditText**. If the active task is **1.3+**, complete **1.1** first.
"""


def workspace_lib_missing(workspace: str | Path) -> bool:
    return not (Path(workspace).resolve() / "lib").is_dir()


IMPLEMENTATION_TOOL_HINTS = """\
## Implementation turn (tools)

- **Empty files:** `ReadRange` once with `@000`/`000@`, then **`EditText`** (replace `@000`–`@000`) or **`ContextManager`** create — do not re-read the same empty file.
- **Before EditText:** always **`ReadRange`** the target file in the same turn (required for new files and after ContextManager create).
- **Scaffolding:** prefer `ContextManager` + `EditText` over repeated `ls` / `Grep` on known paths.
- After a successful read, edit — do not loop on exploration.
- **UpdateTodoList:** mark **only the current** checklist item `done: true` after **EditText** succeeded (and BrightVision **flutter test** passed when applicable) — never on failed edits or skipped verification.
- **Do not** run `flutter test` via Command — BrightVision runs it at end of implement turns.
- When EditText errors, read the error, **ReadRange**, retry one file; do not assume success from assistant prose alone.
"""


@dataclass(frozen=True)
class SteeringFileRecord:
    relpath: str
    size_bytes: int
    nonempty: bool


@dataclass(frozen=True)
class SteeringFilesSnapshot:
    main: SteeringFileRecord | None
    fragments: tuple[SteeringFileRecord, ...]

    @property
    def has_content(self) -> bool:
        if self.main and self.main.nonempty:
            return True
        return any(fragment.nonempty for fragment in self.fragments)

    @property
    def file_count(self) -> int:
        count = 0
        if self.main and self.main.nonempty:
            count += 1
        count += sum(1 for fragment in self.fragments if fragment.nonempty)
        return count


def _steering_file_record(root: Path, relpath: str) -> SteeringFileRecord | None:
    path = root / relpath
    if not path.is_file():
        return None
    try:
        size_bytes = path.stat().st_size
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return SteeringFileRecord(
        relpath=relpath.replace("\\", "/"),
        size_bytes=size_bytes,
        nonempty=bool(text),
    )


def scan_steering_files(workspace: str | Path) -> SteeringFilesSnapshot:
    """List ``.cecli/STEERING.md`` and ``.cecli/steering/*.md`` with sizes."""
    root = Path(workspace).resolve()
    main = _steering_file_record(root, STEERING_MAIN_RELPATH)
    fragments: list[SteeringFileRecord] = []
    frag_dir = root / ".cecli" / "steering"
    if frag_dir.is_dir():
        for path in sorted(frag_dir.glob("*.md")):
            rel = str(path.relative_to(root)).replace("\\", "/")
            record = _steering_file_record(root, rel)
            if record is not None:
                fragments.append(record)
    return SteeringFilesSnapshot(main=main, fragments=tuple(fragments))


def scaffold_steering_files(workspace: str | Path) -> list[str]:
    """Create ``.cecli/STEERING.md`` from template when missing. Returns new relpaths."""
    root = Path(workspace).resolve()
    created: list[str] = []
    main_path = root / ".cecli" / "STEERING.md"
    if not main_path.is_file():
        main_path.parent.mkdir(parents=True, exist_ok=True)
        main_path.write_text(DEFAULT_STEERING_TEMPLATE, encoding="utf-8")
        created.append(STEERING_MAIN_RELPATH)
    return created


def load_steering_markdown(workspace: str | Path) -> str:
    """Load ``.cecli/STEERING.md`` and ``.cecli/steering/*.md`` if present."""
    root = Path(workspace).resolve()
    parts: list[str] = []
    single = root / ".cecli" / "STEERING.md"
    if single.is_file():
        try:
            text = single.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
        except OSError:
            pass
    steering_dir = root / ".cecli" / "steering"
    if steering_dir.is_dir():
        for path in sorted(steering_dir.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(f"### {path.name}\n{text}")
            except OSError:
                continue
    return "\n\n".join(parts).strip()


def build_spec_focus_preamble(workspace: str | Path) -> str:
    """Steering files + spec-focus instructions for chat prepend."""
    steering = load_steering_markdown(workspace)
    blocks = [SPEC_FOCUS_INSTRUCTIONS.strip()]
    if steering:
        blocks.append("## Project steering\n" + steering)
    return "\n\n".join(blocks) + "\n\n"
