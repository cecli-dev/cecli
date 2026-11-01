"""Tests for creator.yml per-agent overrides and their spawn-time merge."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from cecli.helpers.agents import overrides as agent_overrides
from cecli.helpers.agents.config import SubAgentConfig
from cecli.helpers.agents.overrides import (
    apply_agent_override,
    apply_hooks_override,
    load_agent_overrides,
    refresh_agent_overrides,
    register_creator_agents,
    resolve_agent_overrides,
)
from cecli.helpers.agents.service import AgentService


@pytest.fixture
def service():
    """Clean AgentService with isolated class-level state."""
    AgentService._instances = {}
    AgentService._global_registry = {}
    AgentService._uuid_coder_map = {}
    AgentService._primary_agent_uuid = None
    AgentService._agent_overrides = {}
    agent_overrides._registered_creator_agents.clear()

    coder = MagicMock()
    coder.uuid = "parent-uuid"
    coder.parent_uuid = ""
    coder.max_sub_agents = 30
    coder.io = MagicMock()
    coder.agent_config = {}

    return AgentService(coder)


def _write_yml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data))


async def _spawn(service, name):
    """Spawn *name* with fake coder construction; return (kwargs, info)."""
    mock_new_coder = MagicMock()
    mock_new_coder.tui = None

    with patch("cecli.coders.Coder") as MockCoder:
        MockCoder.create = AsyncMock(return_value=mock_new_coder)
        with patch("cecli.helpers.conversation.service.ConversationService") as MockConv:
            MockConv.get_chunks.return_value = MagicMock()
            _, info = await service.spawn(name, parent=service.coder)

    return MockCoder.create.call_args[1], info


def _register(name, agent_config=None, root=None, hooks=None, auto_reap=None, model=None):
    metadata = {"agent-config": agent_config or {}}
    if root is not None:
        metadata["root"] = root

    AgentService.register_subagent(
        name,
        SubAgentConfig(
            name=name,
            prompt="base prompt",
            model=model,
            hooks=hooks or {},
            auto_reap=auto_reap,
            metadata=metadata,
        ),
    )


# ------------------------------------------------------------------ #
# Pattern resolution
# ------------------------------------------------------------------ #


def test_exact_name_beats_family_and_broad_patterns():
    overrides = {
        "*": {"model": "broad"},
        "wf:*": {"model": "family"},
        "wf:nightly": {"model": "exact"},
    }

    assert resolve_agent_overrides("wf:nightly", overrides)["model"] == "exact"
    assert resolve_agent_overrides("wf:other", overrides)["model"] == "family"
    assert resolve_agent_overrides("reviewer", overrides)["model"] == "broad"


def test_family_pattern_beats_bare_wildcard():
    overrides = {
        "*": {"agent-config": {"skills_includelist": ["everyone"]}},
        "ws:*": {"agent-config": {"skills_includelist": ["workspace"]}},
    }

    resolved = resolve_agent_overrides("ws:app", overrides)

    assert resolved["agent-config"]["skills_includelist"] == ["everyone", "workspace"]


def test_specific_pattern_beats_generic_wildcard_within_tier():
    overrides = {
        "w*": {"model": "generic"},
        "wf:night*": {"model": "specific"},
    }

    assert resolve_agent_overrides("wf:nightly", overrides)["model"] == "specific"


def test_unmatched_name_resolves_to_empty():
    assert resolve_agent_overrides("reviewer", {"wf:*": {"model": "x"}}) == {}
    assert resolve_agent_overrides("reviewer", None) == {}


# ------------------------------------------------------------------ #
# Loading global/local files
# ------------------------------------------------------------------ #


def test_global_is_merged_under_local(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setenv("HOME", str(home))
    # Windows ignores HOME for ~ expansion (ntpath uses USERPROFILE)
    monkeypatch.setenv("USERPROFILE", str(home))

    _write_yml(
        home / ".cecli" / "creator.yml",
        {
            "agents": {
                "reviewer": {
                    "model": "global-model",
                    "agent-config": {"skills_includelist": ["global"]},
                }
            }
        },
    )
    _write_yml(
        project / ".cecli" / "creator.yml",
        {
            "agents": {
                "reviewer": {
                    "model": "local-model",
                    "agent-config": {"skills_includelist": ["local"]},
                }
            }
        },
    )

    loaded = load_agent_overrides(str(project))

    assert loaded["reviewer"]["model"] == "local-model"
    assert loaded["reviewer"]["agent-config"]["skills_includelist"] == ["global", "local"]


def test_missing_files_yield_empty_map(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Windows ignores HOME for ~ expansion (ntpath uses USERPROFILE)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))

    assert load_agent_overrides(str(tmp_path / "project")) == {}


def test_prompt_file_is_resolved_against_declaring_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    # Windows ignores HOME for ~ expansion (ntpath uses USERPROFILE)
    monkeypatch.setenv("USERPROFILE", str(home))
    _write_yml(
        home / ".cecli" / "creator.yml",
        {"agents": {"writer": {"prompt_file": "prompts/writer.md"}}},
    )
    (home / ".cecli" / "prompts").mkdir(parents=True)
    (home / ".cecli" / "prompts" / "writer.md").write_text("Write things.")

    loaded = load_agent_overrides(str(tmp_path / "project"))

    prompt_file = Path(loaded["writer"]["prompt_file"])
    assert prompt_file.is_absolute()
    assert prompt_file.read_text() == "Write things."


# ------------------------------------------------------------------ #
# Merge helpers
# ------------------------------------------------------------------ #


def test_agent_config_arrays_concatenate_and_dedupe():
    merged = apply_agent_override(
        {"skills_includelist": ["a"], "x": "front"},
        {"skills_includelist": ["b", "a"], "x": "override"},
    )

    assert merged["skills_includelist"] == ["a", "b"]
    assert merged["x"] == "override"


def test_agent_override_is_noop_without_fragment():
    config = {"skills_includelist": ["a"]}

    assert apply_agent_override(config, None) == config
    assert apply_agent_override(config, {}) == config
    assert apply_agent_override(None, {"x": 1}) == {"x": 1}


def test_hooks_merge_accepts_entry_or_fragment():
    hooks = {"pre_tool_call": [{"name": "base"}]}

    from_entry = apply_hooks_override(hooks, {"hooks": {"post_tool_call": [{"name": "ov"}]}})
    from_fragment = apply_hooks_override(hooks, {"post_tool_call": [{"name": "ov"}]})

    assert from_entry == from_fragment
    assert from_entry["pre_tool_call"] == [{"name": "base"}]
    assert from_entry["post_tool_call"] == [{"name": "ov"}]


# ------------------------------------------------------------------ #
# Spawn-time merge in _create_sub_agent_coder
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_override_merges_on_top_of_front_matter(service):
    _register(
        "reviewer",
        agent_config={"skills_includelist": ["front"], "x": "front"},
    )
    AgentService.set_agent_overrides(
        {"reviewer": {"agent-config": {"skills_includelist": ["override"], "x": "override"}}}
    )

    kwargs, _ = await _spawn(service, "reviewer")
    merged = kwargs["init_metadata"]["agent_config"]

    assert merged["skills_includelist"] == ["front", "override"]
    assert merged["x"] == "override"


@pytest.mark.asyncio
async def test_wf_local_invariant_is_reapplied_after_override(service):
    _register("wf:demo", agent_config={"servers_includelist": ["GitLab"]})
    AgentService.set_agent_overrides(
        {"wf:*": {"agent-config": {"servers_includelist": ["github"]}}}
    )

    kwargs, _ = await _spawn(service, "wf:demo")

    assert kwargs["init_metadata"]["agent_config"]["servers_includelist"] == [
        "gitlab",
        "github",
        "local",
    ]


@pytest.mark.asyncio
async def test_root_and_auto_reap_overrides(service):
    _register("reviewer", root="/from-md", auto_reap=True)
    AgentService.set_agent_overrides(
        {"reviewer": {"root": "/from-override", "auto_reap": False, "detached": True}}
    )

    kwargs, info = await _spawn(service, "reviewer")

    assert kwargs["root"] == "/from-override"
    assert info.auto_reap is False
    assert info.detached is True

    kwargs, info = await _spawn(service, "reviewer")

    assert kwargs["root"] == "/from-override"
    assert info.auto_reap is False


@pytest.mark.asyncio
async def test_hooks_from_config_and_override_are_merged(service, monkeypatch):
    _register("reviewer", hooks={"pre_tool_call": [{"name": "base"}]})
    AgentService.set_agent_overrides(
        {"reviewer": {"hooks": {"pre_tool_call": [{"name": "override"}]}}}
    )

    captured = {}
    registry = MagicMock()

    def fake_load(path):
        captured.update(yaml.safe_load(Path(path).read_text()))
        return []

    registry.load_hooks_from_config.side_effect = fake_load
    monkeypatch.setattr("cecli.hooks.HookService.get_registry", lambda coder: registry)

    await _spawn(service, "reviewer")

    assert captured["hooks"]["pre_tool_call"] == [{"name": "base"}, {"name": "override"}]


@pytest.mark.asyncio
async def test_agent_config_only_override_leaves_hooks_untouched(service, monkeypatch):
    """A non-hook override must not be mistaken for a hooks fragment."""
    _register("reviewer", hooks={"pre_tool_call": [{"name": "base"}]})
    AgentService.set_agent_overrides(
        {"reviewer": {"agent-config": {"skills_includelist": ["pdf"]}}}
    )

    captured = {}
    registry = MagicMock()

    def fake_load(path):
        captured.update(yaml.safe_load(Path(path).read_text()))
        return []

    registry.load_hooks_from_config.side_effect = fake_load
    monkeypatch.setattr("cecli.hooks.HookService.get_registry", lambda coder: registry)

    await _spawn(service, "reviewer")

    assert captured["hooks"] == {"pre_tool_call": [{"name": "base"}]}


@pytest.mark.asyncio
async def test_no_overrides_is_a_noop(service):
    AgentService.set_agent_overrides({})
    _register("reviewer", agent_config={"skills_includelist": ["front"]})

    kwargs, _ = await _spawn(service, "reviewer")

    assert kwargs["init_metadata"]["agent_config"] == {"skills_includelist": ["front"]}


# ------------------------------------------------------------------ #
# Dynamic creator:<name> agents + refresh
# ------------------------------------------------------------------ #


def test_definition_entries_register_namespaced_agents(service):
    overrides = {
        "writer": {
            "description": "Release notes",
            "prompt": "You write release notes.",
            "model": "gpt-test",
            "auto_reap": False,
            "agent-config": {"skills_includelist": ["release"]},
        },
        "wf:*": {"prompt": "patterns cannot define an agent"},
    }

    registered = register_creator_agents(overrides)

    assert registered == ["creator:writer"]
    assert "creator:wf:*" not in AgentService.get_registry()

    config = AgentService.get_registry()["creator:writer"]
    assert config.prompt == "You write release notes."
    assert config.model == "gpt-test"
    assert config.auto_reap is False
    assert config.metadata["description"] == "Release notes"
    assert config.metadata["agent-config"] == {"skills_includelist": ["release"]}


def test_refresh_installs_map_and_tracks_definitions(service, tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setenv("HOME", str(home))
    # Windows ignores HOME for ~ expansion (ntpath uses USERPROFILE)
    monkeypatch.setenv("USERPROFILE", str(home))
    _write_yml(
        project / ".cecli" / "creator.yml",
        {
            "agents": {
                "reviewer": {"agent-config": {"skills_includelist": ["pdf"]}},
                "writer": {"prompt": "Write."},
            }
        },
    )

    loaded = refresh_agent_overrides(str(project))

    assert AgentService.get_agent_overrides() == loaded
    assert "creator:writer" in AgentService.get_registry()

    _write_yml(project / ".cecli" / "creator.yml", {"agents": {}})
    refresh_agent_overrides(str(project))

    assert AgentService.get_agent_overrides() == {}
    assert "creator:writer" not in AgentService.get_registry()
