"""
Deterministic contract tests for the agent-family system prompts.

These tests do NOT call an LLM. They pin the *objective* properties that make the
agent/sub-agent prompts effective, so the improvements cannot silently regress the way
they have before:

- The agent prompt must state the edit contract (ContextManager -> ReadRange -> EditText,
  one file per call, empty-file markers) up front instead of relying on the harness to
  teach it after a failure.
- The prompt must render through ``str.format`` with the same placeholders that
  ``Coder.fmt_system_prompt`` supplies -- no stray ``{}`` and no missing keys.
- ``{final_reminders}`` must appear exactly once so ``overeager_prompt`` and the MCP
  ``tool_prompt`` actually reach the agent coder.
- The sub-agent prompt must inherit the agent identity + contract (it previously
  re-overrode ``main_system`` with stale text, dropping every improvement).
"""

import string

import pytest

from cecli.prompts.utils.registry import PromptRegistry

# Placeholders supplied by Coder.fmt_system_prompt() -> prompt.format(...).
FMT_KEYS = {
    "fence": ("```", "```"),
    "quad_backtick_reminder": "",
    "final_reminders": "[FINAL_REMINDERS]",
    "platform": "macOS",
    "shell_cmd_prompt": "[SHELL_PROMPT]",
    "rename_with_shell": "",
    "shell_cmd_reminder": "[SHELL_REMINDER]",
    "go_ahead_tip": "",
    "language": "English",
    "lazy_prompt": "[LAZY]",
    "overeager_prompt": "[OVEREAGER]",
}


def _render(template: str) -> str:
    """Render a prompt template the way fmt_system_prompt does, surfacing bad keys."""
    used = {name for _, name, _, _ in string.Formatter().parse(template) if name}
    missing = used - set(FMT_KEYS)
    assert not missing, f"prompt uses unknown format keys: {sorted(missing)}"
    return template.format(**FMT_KEYS)


def setup_function(_):
    PromptRegistry.reload_prompts()


@pytest.mark.parametrize("name", ["agent", "subagent"])
def test_prompt_renders_without_stray_braces(name):
    prompts = PromptRegistry.get_prompt(name)
    for key in ("main_system", "system_reminder"):
        rendered = _render(prompts.get(key) or "")
        assert "{" not in rendered and "}" not in rendered, f"{name}.{key} has stray braces"


@pytest.mark.parametrize("name", ["agent", "subagent"])
def test_final_reminders_reaches_prompt_exactly_once(name):
    """overeager_prompt + MCP tool_prompt ride in via {final_reminders}; it must appear once."""
    prompts = PromptRegistry.get_prompt(name)
    combined = (prompts.get("main_system") or "") + "\n" + (prompts.get("system_reminder") or "")
    rendered = _render(combined)
    assert (
        rendered.count("[FINAL_REMINDERS]") == 1
    ), f"{name}: expected exactly one {{final_reminders}} across main_system+system_reminder"


def test_agent_prompt_states_edit_contract():
    """The #1 cause of failed turns must be guidance, not a post-mortem warning."""
    text = _render(PromptRegistry.get_prompt("agent")["main_system"])
    for token in ("ReadRange", "EditText", "ContextManager"):
        assert token in text, f"agent main_system must mention {token}"
    lowered = text.lower()
    # ReadRange-before-EditText ordering and the empty-file markers.
    assert "readrange" in lowered and "before every" in lowered
    assert "@000" in text and "000@" in text
    assert "one file" in lowered  # one file per EditText call


def test_agent_prompt_discourages_loops_and_scope_creep():
    text = _render(PromptRegistry.get_prompt("agent")["main_system"]).lower()
    assert "scope" in text  # scope discipline
    assert "twice" in text  # failure-loop recognition (stop after two failures)


def test_subagent_inherits_agent_identity_and_contract():
    """SubAgentCoder must not fall back to stale directives; it inherits the agent prompt."""
    sub = PromptRegistry.get_prompt("subagent")
    agent = PromptRegistry.get_prompt("agent")
    # Inherits the agent's main_system verbatim (no local override).
    assert sub["main_system"] == agent["main_system"]
    # But keeps sub-agent-specific finishing guidance in its reminder.
    assert "summary" in (sub["system_reminder"] or "").lower()


def test_no_legacy_persistence_directive_remains():
    """The old 'no task takes too long' directive encouraged the loops the harness fights."""
    for name in ("agent", "subagent"):
        text = (PromptRegistry.get_prompt(name).get("main_system") or "").lower()
        assert "no task takes too long" not in text, f"{name} still has the loop-encouraging line"
