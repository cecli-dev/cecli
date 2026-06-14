"""When spec-focus mode actually applies (active task + spec content)."""

from __future__ import annotations

import re
from pathlib import Path

from cecli.spec.implement import build_implement_workspace_block
from cecli.spec.steering import (
    IMPLEMENTATION_TOOL_HINTS,
    SCAFFOLD_MISSING_HINT,
    SPEC_FOCUS_INSTRUCTIONS,
    build_spec_focus_preamble,
    workspace_lib_missing,
)
from cecli.spec.todos import (
    TodoItem,
    TodoStore,
    format_todo_context,
    format_todo_context_implement,
    format_todo_context_light,
    migrate_todo_layers,
)

_SPEC_LAYER_PLACEHOLDERS = frozenset(
    {
        "(No requirements yet.)",
        "(No design yet.)",
        "(No implementation tasks yet.)",
    }
)

_IMPLEMENT_STEP_RE = re.compile(
    r"^implement only implementation task\s+\d+",
    re.IGNORECASE,
)


def todo_has_spec_content(item: TodoItem) -> bool:
    """True when the task has non-placeholder requirements, design, or legacy spec.

    Checklist / ``tasks_md`` alone do not count — those are normal tasks-without-specs.
    """
    item = migrate_todo_layers(item)
    for field in (item.requirements, item.design, item.spec):
        text = field.strip()
        if text and text not in _SPEC_LAYER_PLACEHOLDERS:
            return True
    return False


def _task_has_checklist(item: TodoItem) -> bool:
    return any(entry.text.strip() for entry in item.checklist)


def is_implement_turn_message(message: str) -> bool:
    """Start work / implement-step prompts from Tasks tab."""
    trimmed = message.strip()
    lower = trimmed.lower()
    if lower.startswith("/agent"):
        trimmed = trimmed[6:].lstrip()
        lower = trimmed.lower()
    if _IMPLEMENT_STEP_RE.match(trimmed):
        return True
    if lower.startswith("implement the active task per the injected"):
        return True
    if lower.startswith("work the active task checklist"):
        return True
    if lower.startswith("continue the active task"):
        return True
    return False


def spec_focus_requested(
    *,
    message_spec_focus: bool,
    session_spec_focus: bool,
    session_mode: str,
) -> bool:
    return bool(message_spec_focus or session_spec_focus or session_mode == "spec")


def should_inject_task_context(
    *,
    focus_requested: bool,
    item: TodoItem | None,
    inject_todo_spec: bool,
) -> bool:
    if item is None:
        return False
    if inject_todo_spec:
        return True
    if not focus_requested:
        return False
    # Spec layers stay in chat after the first inject — avoid re-sending ~12k every turn.
    if todo_has_spec_content(item):
        return False
    return _task_has_checklist(item)


def spec_focus_preamble_applies(
    *,
    focus_requested: bool,
    item: TodoItem | None,
) -> bool:
    """Generic spec-focus instructions only when an active task has real spec layers."""
    return bool(focus_requested and item is not None and todo_has_spec_content(item))


def _is_resume_implement_message(message: str) -> bool:
    trimmed = message.strip().lower()
    if trimmed.startswith("/agent"):
        trimmed = trimmed[6:].lstrip()
    return trimmed.startswith("continue the active task")


def build_user_message_with_spec_context(
    workspace: str | Path,
    message: str,
    *,
    item: TodoItem | None,
    store: TodoStore | None,
    focus_requested: bool,
    inject_todo_spec: bool,
    agent_continuation: bool = False,
) -> tuple[str, bool, str | None]:
    """
    Prepend task spec + optional spec-focus preamble.

    Returns ``(user_text, spec_focus_active, turn_todo_id)``.
    ``spec_focus_active`` is True when the spec-focus preamble was applied (for callers).
    """
    turn_todo_id: str | None = None
    user_text = message
    implement_turn = is_implement_turn_message(message)
    if should_inject_task_context(
        focus_requested=focus_requested,
        item=item,
        inject_todo_spec=inject_todo_spec,
    ):
        assert item is not None
        turn_todo_id = item.id
        if implement_turn and todo_has_spec_content(item):
            formatter = format_todo_context_implement
        elif todo_has_spec_content(item):
            formatter = format_todo_context
        else:
            formatter = format_todo_context_light
        user_text = formatter(item, store=store) + message
    preamble = spec_focus_preamble_applies(focus_requested=focus_requested, item=item)
    if preamble:
        blocks: list[str] = []
        if implement_turn:
            if not agent_continuation:
                blocks.append(build_spec_focus_preamble(workspace))
                blocks.append(IMPLEMENTATION_TOOL_HINTS.strip())
                if workspace_lib_missing(workspace):
                    blocks.append(SCAFFOLD_MISSING_HINT.strip())
            checklist = item.checklist if item is not None else []
            blocks.append(
                build_implement_workspace_block(
                    workspace,
                    checklist,
                    resume=_is_resume_implement_message(message),
                    message=message,
                    active_task_title=item.title if item is not None else None,
                    agent_continuation=agent_continuation,
                    todo_item=item,
                )
            )
        else:
            blocks.append(build_spec_focus_preamble(workspace))
        user_text = "\n\n".join(blocks) + "\n\n" + user_text
    return user_text, preamble, turn_todo_id


def spec_focus_effective_for_api(
    *,
    focus_requested: bool,
    item: TodoItem | None,
    inject_todo_spec: bool,
) -> bool:
    """Whether the UI/API should treat the turn as spec-focus (preamble or task inject)."""
    return spec_focus_preamble_applies(
        focus_requested=focus_requested, item=item
    ) or should_inject_task_context(
        focus_requested=focus_requested,
        item=item,
        inject_todo_spec=inject_todo_spec,
    )


def spec_focus_instructions_snippet() -> str:
    """First line marker used in tests."""
    return SPEC_FOCUS_INSTRUCTIONS.splitlines()[0]
