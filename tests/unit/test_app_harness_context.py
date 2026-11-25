"""Tests for the app-harness context block injected into the agent prompt."""

from __future__ import annotations

from types import SimpleNamespace

import cecli.helpers.app_harness as app_harness
from cecli.coders.agent_coder import AgentCoder


def test_app_automation_context_uses_bash_heredoc_on_posix(monkeypatch):
    coder = SimpleNamespace()
    monkeypatch.setattr(app_harness, "is_app_harness_available", lambda: True)
    monkeypatch.setattr("cecli.coders.agent_coder.platform.system", lambda: "Linux")

    context = AgentCoder.get_app_automation_context(coder)

    assert context.startswith('<context name="app_automation"')
    assert "app-harness --window" in context
    assert "<<'PY'" in context


def test_app_automation_context_uses_here_string_under_powershell(monkeypatch):
    coder = SimpleNamespace()
    monkeypatch.setattr(app_harness, "is_app_harness_available", lambda: True)
    monkeypatch.setattr("cecli.coders.agent_coder.platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "cecli.coders.agent_coder.get_windows_parent_process_name",
        lambda: "pwsh.exe",
    )

    context = AgentCoder.get_app_automation_context(coder)

    assert "'@ | app-harness" in context
    assert "```powershell" in context
    assert "<<" not in context


def test_app_automation_context_uses_pipeline_under_cmd(monkeypatch):
    coder = SimpleNamespace()
    monkeypatch.setattr(app_harness, "is_app_harness_available", lambda: True)
    monkeypatch.setattr("cecli.coders.agent_coder.platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "cecli.coders.agent_coder.get_windows_parent_process_name",
        lambda: "cmd.exe",
    )

    context = AgentCoder.get_app_automation_context(coder)

    assert "echo print(windows()) | app-harness" in context
    assert "```bat" in context
    assert "<<" not in context


def test_app_automation_context_requires_bridge(monkeypatch):
    coder = SimpleNamespace()
    monkeypatch.setattr(app_harness, "is_app_harness_available", lambda: False)

    assert AgentCoder.get_app_automation_context(coder) is None
