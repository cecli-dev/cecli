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

    assert context.startswith('<harness type="app_automation"')
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


def test_static_context_blocks_include_app_automation(monkeypatch):
    from cecli.helpers.conversation import ConversationService
    from cecli.helpers.conversation.integration import ConversationChunks

    added = []

    class Manager:
        def add_message(self, message_dict=None, **kwargs):
            added.append((message_dict, kwargs))

    class Coder:
        def __init__(self):
            self.uuid = "app-automation-test"
            self.allowed_context_blocks = {"app_automation", "browser_automation"}

        def get_cached_context_block(self, block_name):
            return f'<harness type="{block_name}"></harness>'

    manager = Manager()
    monkeypatch.setattr(ConversationService, "get_manager", lambda _coder: manager)

    coder = Coder()
    chunks = ConversationChunks(coder)
    chunks.add_static_context_blocks()

    hash_keys = [kwargs["hash_key"] for _, kwargs in added]
    assert ("static", "app_automation") in hash_keys
    assert ("static", "browser_automation") in hash_keys
