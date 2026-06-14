"""Multi-turn, repo-grounded spec generation (Kiro-depth path)."""

from __future__ import annotations

import concurrent.futures
import os
import re
from typing import TYPE_CHECKING, Any

from cecli.spec.generate import (
    SpecSection,
    build_generate_message,
    compact_spec_gen_enabled,
    merge_generated_layers,
    parse_generated_layers,
)
from cecli.spec.layers import assess_spec_richness, normalize_spec_layer_traceability
from cecli.spec.runtime import SpecTurnRunner
from cecli.spec.steering import build_spec_focus_preamble

if TYPE_CHECKING:
    from cecli.spec.todos import TodoItem

_SECTION_LABELS = {
    "requirements": "Requirements (EARS)",
    "design": "Design",
    "tasks_md": "Implementation tasks",
    "all": "All spec layers",
}

# Pattern matches the Cecli reasoning tag used by thinking models (e.g. qwen3.6, deepseek-r1).
_THINKING_TAG_RE = re.compile(
    r"<thinking-content-[0-9a-f]+>.*?</thinking-content-[0-9a-f]+>",
    re.DOTALL,
)


def _strip_thinking_content(text: str) -> str:
    """Remove <thinking-content-...>...</thinking-content-...> blocks from raw LLM output.

    These blocks contain the model's chain-of-thought reasoning and should not be
    included in the parsed spec layers — they often duplicate REQ headings which
    triggers EARS_DUP_ID lint errors.
    """
    result = _THINKING_TAG_RE.sub("", text).strip()
    # Handle case where closing tag exists but opening tag was truncated/missing
    closing_pattern = re.compile(r"</thinking-content-[0-9a-f]+>")
    match = closing_pattern.search(result)
    if match:
        result = result[match.end() :].strip()
    return result


def spec_gen_agent_enabled() -> bool:
    """Repo-grounded multi-turn spec generation (default on; set ``BV_SPEC_GEN_AGENT=0`` to disable)."""
    if compact_spec_gen_enabled():
        return False
    return os.environ.get("BV_SPEC_GEN_AGENT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def spec_gen_richness_gate_enabled() -> bool:
    if compact_spec_gen_enabled():
        return False
    return os.environ.get("BV_SPEC_GEN_RICHNESS_GATE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def build_spec_explore_message(
    *,
    prompt: str,
    section: SpecSection,
    item: TodoItem | None,
) -> str:
    title = (item.title if item else "").strip() or "Active task"
    section_label = _SECTION_LABELS.get(section, section)
    return (
        "/agent READ-ONLY repository exploration for upcoming spec generation. "
        "Do NOT create, edit, or delete files.\n\n"
        f"Task title: {title}\n"
        f"Feature request: {prompt.strip()}\n"
        f"Target layer: {section_label}\n\n"
        "Use agent tools (read/list/grep) to inspect relevant source, architecture, "
        "and existing patterns in this repository.\n"
        "Reply with 8–15 bullets citing repo-relative paths and how they inform the spec.\n"
        "Do NOT write requirements, design, or implementation tasks yet — exploration only."
    )


def wrap_spec_generate_message(
    workspace: str,
    core_message: str,
    *,
    exploration: str = "",
) -> str:
    steering = build_spec_focus_preamble(workspace).strip()
    parts: list[str] = []
    if steering:
        parts.append(steering)
    parts.append(core_message.strip())
    notes = (exploration or "").strip()
    if notes:
        parts.append("## Repository exploration (ground your spec in these findings)\n" + notes)
    return "\n\n".join(parts) + "\n"


def _section_richness_suggestions(section: SpecSection, merged: dict[str, str]) -> list[str]:
    _, suggestions = assess_spec_richness(
        merged.get("requirements", ""),
        merged.get("design", ""),
        merged.get("tasks_md", ""),
    )
    if section == "all":
        return suggestions
    prefix = {
        "requirements": "requirements:",
        "design": "design:",
        "tasks_md": "tasks:",
    }.get(section, "")
    if not prefix:
        return suggestions
    return [s for s in suggestions if s.startswith(prefix)]


def build_deepen_message_for_workspace(
    *,
    workspace: str,
    prompt: str,
    item: TodoItem,
    section: SpecSection,
    suggestions: list[str],
    exploration: str = "",
) -> str:
    deepen_note = "Deepen the spec to Kiro-grade depth:\n" + "\n".join(
        f"- {s}" for s in suggestions
    )
    combined_prompt = f"{prompt.strip()}\n\n{deepen_note}"
    core = build_generate_message(combined_prompt, item=item, section=section, mode="generate")
    return wrap_spec_generate_message(workspace, core, exploration=exploration)


def _consume_run_message(runner: SpecTurnRunner, message: str, **kwargs: Any) -> str:
    parts: list[str] = []
    for event in runner.run_message(message, **kwargs):
        if event.get("type") == "token":
            parts.append(str(event.get("text") or ""))
        elif event.get("type") == "done":
            return str(event.get("assistant_text") or "".join(parts))
    return "".join(parts)


def run_timed_message(
    runner: SpecTurnRunner,
    message: str,
    *,
    timeout_s: float,
    **kwargs: Any,
) -> str:
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_consume_run_message, runner, message, **kwargs)
    try:
        return fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError as err:
        try:
            runner.interrupt_turn()
        except Exception:
            pass
        try:
            fut.result(timeout=15)
        except Exception:
            pass
        raise TimeoutError(f"Spec generation turn timed out after {int(timeout_s)}s") from err
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def spec_gen_explore_timeout_s(total_turn_timeout_s: float) -> float:
    return max(120.0, total_turn_timeout_s * 0.35)


def spec_gen_write_timeout_s(total_turn_timeout_s: float) -> float:
    """Budget for the main generate one-shot (after optional explore)."""
    if compact_spec_gen_enabled() or not spec_gen_agent_enabled():
        # Compact / single-pass lane: one write uses nearly the full turn cap.
        return max(180.0, total_turn_timeout_s - 60.0)
    return max(180.0, total_turn_timeout_s * 0.55)


def run_spec_layer_llm(
    runner: SpecTurnRunner,
    *,
    workspace: str,
    prompt: str,
    item: TodoItem,
    section: SpecSection,
    mode: str,
    todo_id: str,
    total_turn_timeout_s: float,
) -> str:
    """Repo-grounded generate: optional /agent explore, then one-shot write (+ optional deepen)."""
    core = build_generate_message(prompt, mode=mode, item=item, section=section)  # type: ignore[arg-type]
    exploration = ""
    runner.apply_spec_gen_route(core)

    if spec_gen_agent_enabled():
        explore_msg = build_spec_explore_message(prompt=prompt, section=section, item=item)
        try:
            exploration = run_timed_message(
                runner,
                explore_msg,
                timeout_s=spec_gen_explore_timeout_s(total_turn_timeout_s),
                preproc=True,
                skip_workspace_init=True,
                active_todo_id=todo_id,
                inject_todo_spec=False,
                spec_focus=True,
                force_tier="think",
            ).strip()
        except (TimeoutError, Exception):
            exploration = ""

    write_msg = wrap_spec_generate_message(workspace, core, exploration=exploration)
    runner.apply_spec_gen_route(write_msg)
    raw = runner.run_one_shot(
        write_msg,
        timeout_s=spec_gen_write_timeout_s(total_turn_timeout_s),
        skip_workspace_init=True,
    )
    raw = _strip_thinking_content(raw)

    if not spec_gen_richness_gate_enabled():
        return raw

    parsed = parse_generated_layers(raw, section=section)
    merged = normalize_spec_layer_traceability(
        merge_generated_layers(item, parsed, section=section)
    )
    suggestions = _section_richness_suggestions(section, merged)
    if not suggestions:
        return raw

    from dataclasses import replace

    temp = replace(
        item,
        requirements=merged.get("requirements", item.requirements),
        design=merged.get("design", item.design),
        tasks_md=merged.get("tasks_md", item.tasks_md),
    )
    deepen_msg = build_deepen_message_for_workspace(
        workspace=workspace,
        prompt=prompt,
        item=temp,
        section=section,
        suggestions=suggestions,
        exploration=exploration,
    )
    runner.apply_spec_gen_route(deepen_msg)
    raw2 = runner.run_one_shot(
        deepen_msg,
        timeout_s=max(120.0, total_turn_timeout_s * 0.35),
        skip_workspace_init=True,
    )
    raw2 = _strip_thinking_content(raw2)
    if raw2.strip():
        if section == "requirements" and "### REQ-" in raw2:
            return raw2.strip()
        return raw.rstrip() + "\n\n--- deepen pass ---\n\n" + raw2.strip()
    return raw
