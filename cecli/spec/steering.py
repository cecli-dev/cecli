# flake8: noqa: E501
"""Project steering markdown for spec-focus sessions (Kiro-style)."""

from __future__ import annotations

from pathlib import Path

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
