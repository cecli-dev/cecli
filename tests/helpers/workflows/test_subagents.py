"""Tests for ``wf:`` workflow sub-agent registration (tests.md cases 9-14)."""

import pytest

from cecli.helpers.agents.service import AgentService
from cecli.helpers.workflows import subagents as wf_subagents
from cecli.helpers.workflows.models import TaskConfig, WorkflowConfig
from cecli.helpers.workflows.subagents import (
    ensure_wf_agent_registered,
    register_workflow_subagents,
    unregister_workflow_subagents,
)


@pytest.fixture(autouse=True)
def isolate_registry():
    """Swap out the global registry + wf config cache so tests don't leak."""
    saved_registry = AgentService._global_registry
    saved_cache = dict(wf_subagents._workflow_configs_by_agent)
    AgentService._global_registry = {}
    wf_subagents._workflow_configs_by_agent.clear()
    yield
    AgentService._global_registry = saved_registry
    wf_subagents._workflow_configs_by_agent.clear()
    wf_subagents._workflow_configs_by_agent.update(saved_cache)


def _wf(name="check-pipeline", **kwargs):
    kwargs.setdefault("tasks", [TaskConfig(prompt="do the thing")])
    return WorkflowConfig(name=name, **kwargs)


def worker_config():
    return AgentService.get_registry()["worker"]


# ---------------------------------------------------------------- case 9 --


def test_register_workflow_subagents_registers_and_is_idempotent():
    wf = _wf()
    registered = register_workflow_subagents([wf])

    assert registered == ["wf:check-pipeline"]
    assert "wf:check-pipeline" in AgentService.get_registry()

    # re-registering replaces the entry; no duplicates/errors
    registered_again = register_workflow_subagents([wf])
    assert registered_again == ["wf:check-pipeline"]
    assert list(AgentService.get_registry()).count("wf:check-pipeline") == 1

    # unregister removes it, ensure_* re-registers from the module cache
    assert unregister_workflow_subagents([wf]) == ["wf:check-pipeline"]
    assert "wf:check-pipeline" not in AgentService.get_registry()

    assert ensure_wf_agent_registered("wf:check-pipeline") == "wf:check-pipeline"
    assert "wf:check-pipeline" in AgentService.get_registry()

    # unknown / uncached names resolve to None and never raise
    assert ensure_wf_agent_registered("wf:ghost") is None


# ---------------------------------------------------------------- case 10 --


def test_metadata_mapping(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Windows ignores HOME for ~ expansion (ntpath uses USERPROFILE)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir()

    wf = _wf(
        skills=["gitlab-ci"],
        servers=["GitLab", "MyServer"],
        root="~/repo",
    )
    register_workflow_subagents([wf])
    cfg = AgentService.get_registry()["wf:check-pipeline"]

    agent_config = cfg.metadata["agent-config"]
    assert agent_config["skills_init"] == ["gitlab-ci"]
    assert agent_config["skills_includelist"] == []
    # servers are normalized to lowercase (MCP server names are lowercase)
    assert agent_config["servers_includelist"] == ["gitlab", "myserver"]
    # unattended runs must never block on an interactive confirm
    assert agent_config["skip_cli_confirmations"] is True
    # ...and stay out of the parent's context: workflow runs are detached
    assert agent_config["detached"] is True
    assert agent_config["skip_cli_confirmations"] is True

    assert cfg.metadata["root"] == str(root.expanduser().resolve())
    assert cfg.metadata["description"] == "Workflow sub-agent for 'check-pipeline'"


def test_skip_cli_confirmations_forced_even_without_skills_or_servers():
    register_workflow_subagents([_wf()])
    cfg = AgentService.get_registry()["wf:check-pipeline"]
    assert cfg.metadata["agent-config"]["skip_cli_confirmations"] is True
    assert cfg.metadata["agent-config"]["detached"] is True


# ---------------------------------------------------------------- case 11 --


def test_model_sentinel_passthrough_and_override():
    sentinel = _wf(model="<agent_model>")
    explicit = _wf(name="explicit", model="claude-sonnet-4")
    unset = _wf(name="unset")
    register_workflow_subagents([sentinel, explicit, unset])
    registry = AgentService.get_registry()

    assert registry["wf:check-pipeline"].model == "<agent_model>"
    assert registry["wf:explicit"].model == "claude-sonnet-4"
    # unset falls back to the worker default
    assert registry["wf:unset"].model == worker_config().model


# ---------------------------------------------------------------- case 12 --


def test_hooks_fall_back_to_worker():
    hooks = {"start": [{"name": "wf-start", "command": "echo hi"}]}
    with_hooks = _wf(name="withhooks", hooks=hooks)
    without = _wf(name="withouthooks")
    register_workflow_subagents([with_hooks, without])
    registry = AgentService.get_registry()

    assert registry["wf:withhooks"].hooks == hooks
    assert registry["wf:withouthooks"].hooks == dict(worker_config().hooks)


# ---------------------------------------------------------------- case 13 --


def test_disabled_workflows_are_not_registered():
    wf = _wf(enabled=False)
    registered = register_workflow_subagents([wf])

    assert registered == []
    assert "wf:check-pipeline" not in AgentService.get_registry()
    # but the config is still cached (for /workflows list + enable)
    assert wf_subagents._workflow_configs_by_agent["wf:check-pipeline"] is wf


# ---------------------------------------------------------------- case 14 --


def test_worker_prompt_inherited():
    register_workflow_subagents([_wf()])
    cfg = AgentService.get_registry()["wf:check-pipeline"]

    worker = worker_config()
    assert cfg.prompt == worker.prompt
    # (the built-in worker default may legitimately have an empty body)
    assert cfg.auto_reap is False


# ---------------------------------------------------------------- case 15 --


def test_workflow_metadata_overrides_subagent_config():
    wf = _wf(
        servers=["GitLab"],
        persist=True,
        metadata={
            "model": "meta-model",
            "auto_reap": True,
            "custom": "value",
            "agent-config": {"skills_init": ["meta-skill"]},
        },
    )
    register_workflow_subagents([wf])
    cfg = AgentService.get_registry()["wf:check-pipeline"]

    assert cfg.model == "meta-model"
    # persist workers must never be auto-reaped
    assert cfg.auto_reap is False
    assert cfg.metadata["custom"] == "value"

    agent_config = cfg.metadata["agent-config"]
    assert agent_config["skills_init"] == ["meta-skill"]
    assert agent_config["servers_includelist"] == ["gitlab"]
    assert agent_config["skip_cli_confirmations"] is True
    assert agent_config["detached"] is True
