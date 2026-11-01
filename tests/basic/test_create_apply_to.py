"""Tests for per-agent targeting (``ManageExtensions --apply_to``)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from cecli.helpers.agents import overrides as agent_overrides
from cecli.helpers.agents.config import SubAgentConfig
from cecli.helpers.agents.service import AgentService
from cecli.helpers.creator import utils as creator_utils
from cecli.tools.manage_extensions import Tool
from cecli.tools.utils.helpers import ToolError


@pytest.fixture
def coder(tmp_path):
    return SimpleNamespace(
        agent_config={"creator_mode": True},
        root=str(tmp_path / "repo"),
        primary_root=str(tmp_path / "repo"),
        io=Mock(),
        registered_servers={},
    )


@pytest.fixture
def creator_paths(tmp_path, monkeypatch):
    """Redirect creator.yml resolution into a temporary global/local pair."""
    global_yml = tmp_path / "home" / ".cecli" / "creator.yml"
    local_yml = tmp_path / "repo" / ".cecli" / "creator.yml"

    def fake_paths(root=None):
        return global_yml, local_yml

    monkeypatch.setattr(creator_utils, "creator_yml_paths", fake_paths)

    return global_yml, local_yml


@pytest.fixture
def reloads(monkeypatch):
    """Patch creator reload helpers so tool calls stay offline."""
    mocks = {}
    for name in (
        "reload_mcp_servers",
        "reload_hooks",
        "reload_skills",
        "reload_custom_tools",
        "reload_custom_commands",
        "reload_workflows",
        "reload_creator_extensions",
    ):
        mock = AsyncMock(return_value=[f"{name}: ok"])
        monkeypatch.setattr(creator_utils, name, mock)
        mocks[name] = mock

    monkeypatch.setattr(agent_overrides, "refresh_agent_overrides", lambda root=None: {})

    return mocks


@pytest.fixture
def registry():
    """Isolate AgentService's registry/override index and expose a registrar."""
    saved_registry = dict(AgentService.get_registry())
    saved_overrides = dict(AgentService.get_agent_overrides())
    AgentService._global_registry.clear()
    AgentService.set_agent_overrides({})

    def register(name, agent_config=None):
        AgentService.register_subagent(
            name,
            SubAgentConfig(name=name, metadata={"agent-config": dict(agent_config or {})}),
        )

        return name

    yield register

    AgentService._global_registry.clear()
    AgentService._global_registry.update(saved_registry)
    AgentService.set_agent_overrides(saved_overrides)


def _read(path):
    return yaml.safe_load(path.read_text())


def _skill_dir(local_yml):
    return str(local_yml.parent / "skills")


def _result_text(response):
    return "\n".join(item["content"] for item in response.to_dict()["result"])


@pytest.mark.asyncio
async def test_add_skill_apply_to_exact_target(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths
    registry("reviewer", {"skills_includelist": ["existing"]})

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="pdf",
        content="# PDF\n",
        apply_to=["reviewer"],
    )

    data = _read(local_yml)
    assert "agent-config" not in data
    node = data["agents"]["reviewer"]["agent-config"]
    assert node["skills_paths"] == [_skill_dir(local_yml)]
    assert node["skills_includelist"] == ["pdf"]
    assert (local_yml.parent / "skills" / "pdf" / "SKILL.md").read_text() == "# PDF\n"


@pytest.mark.asyncio
async def test_add_skill_apply_to_unfiltered_target_omits_includelist(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("writer")

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="pdf",
        content="# PDF\n",
        apply_to=["writer"],
    )

    node = _read(local_yml)["agents"]["writer"]["agent-config"]
    assert node["skills_paths"] == [_skill_dir(local_yml)]
    assert "skills_includelist" not in node


@pytest.mark.asyncio
async def test_add_skill_apply_to_wildcard_writes_one_entry(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("wf:one", {"skills_includelist": ["a"]})
    registry("wf:two", {"skills_includelist": ["b"]})

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="pdf",
        content="# PDF\n",
        apply_to=["wf:*"],
    )

    data = _read(local_yml)
    assert set(data["agents"]) == {"wf:*"}
    node = data["agents"]["wf:*"]["agent-config"]
    assert node["skills_paths"] == [_skill_dir(local_yml)]
    assert node["skills_includelist"] == ["pdf"]


@pytest.mark.asyncio
async def test_apply_to_unknown_name_raises(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths
    registry("reviewer")

    with pytest.raises(ToolError, match="Unknown agent"):
        await Tool.execute(
            coder,
            action="add",
            type="skill",
            scope="local",
            name="pdf",
            content="# PDF\n",
            apply_to=["reviewe"],
        )

    assert not local_yml.exists()


@pytest.mark.asyncio
async def test_add_mcp_server_apply_to_only_records_filtering_targets(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("reviewer", {"servers_includelist": ["existing"]})
    registry("writer")
    coder.registered_servers = {"included": {"runtime-only"}}

    await Tool.execute(
        coder,
        action="add",
        type="mcp_server",
        scope="local",
        name="demo",
        config={"command": "run-demo"},
        apply_to=["reviewer", "writer"],
    )

    data = _read(local_yml)
    assert data["mcp-servers"]["demo"]["command"] == "run-demo"
    assert "agent-config" not in data
    assert data["agents"]["reviewer"]["agent-config"]["servers_includelist"] == ["demo"]
    assert "writer" not in data["agents"]


@pytest.mark.asyncio
async def test_add_hook_apply_to_records_shared_and_per_agent(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("reviewer")

    await Tool.execute(
        coder,
        action="add",
        type="hook",
        scope="local",
        name="audit",
        content="def audit(**kwargs):\n    return None\n",
        apply_to=["reviewer"],
    )

    data = _read(local_yml)
    hook_path = local_yml.parent / "hooks" / "audit.py"
    assert data["hooks"]["audit"]["path"] == str(hook_path)
    assert "audit" in data["agents"]["reviewer"]["hooks"]


@pytest.mark.asyncio
async def test_remove_skill_apply_to_prunes_only_named_target(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("reviewer")
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump(
            {
                "agent-config": {"skills_paths": [_skill_dir(local_yml)]},
                "agents": {
                    "reviewer": {
                        "agent-config": {
                            "skills_paths": [_skill_dir(local_yml)],
                            "skills_includelist": ["pdf", "keep"],
                        }
                    },
                    "wf:*": {"agent-config": {"skills_includelist": ["pdf"]}},
                },
            },
            sort_keys=False,
        )
    )

    await Tool.execute(
        coder,
        action="remove",
        type="skill",
        scope="local",
        name="pdf",
        apply_to=["reviewer"],
    )

    data = _read(local_yml)
    assert data["agents"]["reviewer"]["agent-config"]["skills_includelist"] == ["keep"]
    assert data["agents"]["wf:*"]["agent-config"]["skills_includelist"] == ["pdf"]
    assert data["agent-config"]["skills_paths"] == [_skill_dir(local_yml)]


@pytest.mark.asyncio
async def test_remove_skill_apply_to_wildcard_deletes_target_node(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("wf:one")
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump({"agents": {"wf:*": {"agent-config": {"skills_includelist": ["pdf"]}}}})
    )

    await Tool.execute(
        coder,
        action="remove",
        type="skill",
        scope="local",
        name="pdf",
        apply_to=["wf:*"],
    )

    assert "agents" not in _read(local_yml)


@pytest.mark.asyncio
async def test_remove_without_apply_to_prunes_every_override(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("reviewer")
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump(
            {
                "agent-config": {"skills_includelist": ["pdf"]},
                "agents": {
                    "reviewer": {"agent-config": {"skills_includelist": ["pdf"]}},
                    "wf:*": {"agent-config": {"skills_includelist": ["pdf"]}},
                },
            }
        )
    )

    await Tool.execute(coder, action="remove", type="skill", scope="local", name="pdf")

    data = _read(local_yml)
    assert data["agent-config"]["skills_includelist"] == []
    for node in data.get("agents", {}).values():
        assert node["agent-config"]["skills_includelist"] == []


@pytest.mark.asyncio
async def test_update_skill_apply_to_merges_target_entries(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths
    registry("reviewer", {"skills_includelist": ["existing"]})

    for name in ("pdf", "notes"):
        await Tool.execute(
            coder,
            action="update",
            type="skill",
            scope="local",
            name=name,
            content=f"# {name}\n",
            apply_to=["reviewer"],
        )

    node = _read(local_yml)["agents"]["reviewer"]["agent-config"]
    assert node["skills_includelist"] == ["pdf", "notes"]
    assert node["skills_paths"] == [_skill_dir(local_yml)]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_type", ["custom_tool", "custom_command", "workflow"])
async def test_apply_to_rejected_for_session_wide_types(
    coder, creator_paths, reloads, registry, entry_type
):
    registry("reviewer")

    with pytest.raises(ToolError, match="not supported"):
        await Tool.execute(
            coder,
            action="add",
            type=entry_type,
            scope="local",
            name="thing",
            content="x",
            apply_to=["reviewer"],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["primary", "main"])
async def test_apply_to_rejects_primary(coder, creator_paths, reloads, registry, target):
    registry("reviewer")

    with pytest.raises(ToolError, match="cannot be targeted"):
        await Tool.execute(
            coder,
            action="add",
            type="skill",
            scope="local",
            name="pdf",
            content="# PDF\n",
            apply_to=[target],
        )


@pytest.mark.asyncio
async def test_apply_to_config_writes_nested_agent_path(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths
    registry("reviewer")

    await Tool.execute(
        coder,
        action="add",
        type="config",
        scope="local",
        name="agent-config.skills_includelist",
        config=["pdf"],
        apply_to=["reviewer"],
    )

    data = _read(local_yml)
    assert "agent-config" not in data
    assert data["agents"]["reviewer"]["agent-config"]["skills_includelist"] == ["pdf"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,apply_to",
    [
        ("agent-config.skills_includelist", ["*"]),
        ("agent-config.skills_includelist", ["reviewer", "writer"]),
        ("models.default", ["reviewer"]),
    ],
)
async def test_apply_to_config_validation(coder, creator_paths, reloads, registry, name, apply_to):
    registry("reviewer")
    registry("writer")

    with pytest.raises(ToolError, match="apply_to for type 'config'"):
        await Tool.execute(
            coder,
            action="add",
            type="config",
            scope="local",
            name=name,
            config="x",
            apply_to=apply_to,
        )


@pytest.mark.asyncio
async def test_without_apply_to_keeps_shared_recording(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths
    registry("reviewer", {"skills_includelist": ["existing"]})
    coder.agent_config["skills_includelist"] = ["existing"]

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="pdf",
        content="# PDF\n",
    )
    registry("reviewer", {"skills_includelist": ["existing"]})

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="pdf",
        content="# PDF\n",
    )

    data = _read(local_yml)
    assert "agents" not in data
    assert data["agent-config"]["skills_paths"] == [_skill_dir(local_yml)]
    assert data["agent-config"]["skills_includelist"] == ["pdf"]


@pytest.mark.asyncio
async def test_apply_to_resolves_through_spawn_override_merge(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("reviewer", {"skills_includelist": ["base"]})

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="pdf",
        content="# PDF\n",
        apply_to=["reviewer"],
    )

    mapping = agent_overrides.load_agent_overrides(str(coder.primary_root))
    AgentService.set_agent_overrides(mapping)
    override = AgentService._resolve_agent_overrides("reviewer")
    resolved = agent_overrides.apply_agent_override(
        {"skills_includelist": ["base"]}, override.get("agent-config")
    )

    assert resolved["skills_includelist"] == ["base", "pdf"]
    assert resolved["skills_paths"] == [_skill_dir(local_yml)]


@pytest.mark.asyncio
async def test_remove_mcp_server_apply_to_keeps_shared_definition(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("reviewer", {"servers_includelist": ["demo", "other"]})
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump(
            {
                "mcp-servers": {"demo": {"command": "run-demo"}},
                "agents": {
                    "reviewer": {"agent-config": {"servers_includelist": ["demo", "other"]}}
                },
            }
        )
    )

    await Tool.execute(
        coder,
        action="remove",
        type="mcp_server",
        scope="local",
        name="demo",
        apply_to=["reviewer"],
    )

    data = _read(local_yml)
    assert "demo" in data["mcp-servers"]
    assert data["agents"]["reviewer"]["agent-config"]["servers_includelist"] == ["other"]


@pytest.mark.asyncio
async def test_remove_hook_apply_to_keeps_shared_definition(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("reviewer")
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump(
            {
                "hooks": {"audit": {"path": "/tmp/audit.py"}},
                "agents": {"reviewer": {"hooks": {"audit": {"path": "/tmp/audit.py"}}}},
            }
        )
    )

    await Tool.execute(
        coder,
        action="remove",
        type="hook",
        scope="local",
        name="audit",
        apply_to=["reviewer"],
    )

    data = _read(local_yml)
    assert "audit" in data["hooks"]
    assert "agents" not in data


@pytest.mark.asyncio
async def test_creator_yml_definition_registers_namespaced_agent(coder, creator_paths, reloads):
    _, local_yml = creator_paths
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump(
            {"agents": {"writer": {"description": "Release note writer", "prompt": "Write notes."}}}
        )
    )

    mapping = agent_overrides.load_agent_overrides(str(coder.primary_root))
    registered = agent_overrides.register_creator_agents(mapping, base_dir=str(local_yml.parent))

    try:
        assert registered == ["creator:writer"]
        assert "creator:writer" in AgentService.get_registry()
        assert "writer" not in AgentService.get_registry()
    finally:
        agent_overrides.register_creator_agents({})


@pytest.mark.asyncio
async def test_scoped_remove_delete_files_keeps_file_used_by_other_target(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("reviewer")
    registry("worker")
    skill_file = local_yml.parent / "skills" / "pdf" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("# PDF\n")
    local_yml.parent.mkdir(parents=True, exist_ok=True)
    local_yml.write_text(
        yaml.dump(
            {
                "agents": {
                    "reviewer": {"agent-config": {"skills_includelist": ["pdf"]}},
                    "worker": {"agent-config": {"skills_includelist": ["pdf"]}},
                }
            }
        )
    )

    response = await Tool.execute(
        coder,
        action="remove",
        type="skill",
        scope="local",
        name="pdf",
        apply_to=["reviewer"],
        config={"delete_files": True},
    )

    assert skill_file.exists()
    data = _read(local_yml)
    assert "reviewer" not in data.get("agents", {})
    assert data["agents"]["worker"]["agent-config"]["skills_includelist"] == ["pdf"]
    assert "Kept" in _result_text(response)
    assert "worker" in _result_text(response)


@pytest.mark.asyncio
async def test_scoped_remove_delete_files_deletes_unreferenced_file(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    registry("reviewer")
    skill_file = local_yml.parent / "skills" / "pdf" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("# PDF\n")
    local_yml.parent.mkdir(parents=True, exist_ok=True)
    local_yml.write_text(
        yaml.dump({"agents": {"reviewer": {"agent-config": {"skills_includelist": ["pdf"]}}}})
    )

    response = await Tool.execute(
        coder,
        action="remove",
        type="skill",
        scope="local",
        name="pdf",
        apply_to=["reviewer"],
        config={"delete_files": True},
    )

    assert not skill_file.exists()
    assert "Deleted" in _result_text(response)


@pytest.mark.asyncio
async def test_scoped_hook_remove_keeps_shared_file(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths
    registry("reviewer")
    hook_file = local_yml.parent / "hooks" / "audit.py"
    hook_file.parent.mkdir(parents=True)
    hook_file.write_text("x = 1\n")
    local_yml.parent.mkdir(parents=True, exist_ok=True)
    local_yml.write_text(
        yaml.dump(
            {
                "hooks": {"audit": {"path": str(hook_file)}},
                "agents": {"reviewer": {"hooks": {"audit": {"path": str(hook_file)}}}},
            }
        )
    )

    response = await Tool.execute(
        coder,
        action="remove",
        type="hook",
        scope="local",
        name="audit",
        apply_to=["reviewer"],
        config={"delete_files": True},
    )

    assert hook_file.exists()
    assert "audit" in _read(local_yml)["hooks"]
    assert "Kept" in _result_text(response)


@pytest.mark.asyncio
async def test_unscoped_remove_delete_files_still_deletes(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths
    registry("reviewer")
    registry("worker")
    skill_file = local_yml.parent / "skills" / "pdf" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("# PDF\n")
    local_yml.parent.mkdir(parents=True, exist_ok=True)
    local_yml.write_text(
        yaml.dump(
            {
                "agents": {
                    "reviewer": {"agent-config": {"skills_includelist": ["pdf"]}},
                    "worker": {"agent-config": {"skills_includelist": ["pdf"]}},
                }
            }
        )
    )

    await Tool.execute(
        coder,
        action="remove",
        type="skill",
        scope="local",
        name="pdf",
        config={"delete_files": True},
    )

    assert not skill_file.exists()


@pytest.mark.asyncio
async def test_scoped_skill_add_activates_only_target(
    coder, creator_paths, reloads, registry, monkeypatch
):
    _, local_yml = creator_paths
    registry("reviewer")
    primary_manager = Mock(include_list=None, _loaded_skills=set())
    target_manager = Mock(include_list=None, _loaded_skills=set())
    target_manager.load_skill.return_value = "Skill 'pdf' loaded successfully."
    coders = [
        SimpleNamespace(name="", skills_manager=primary_manager),
        SimpleNamespace(name="reviewer", skills_manager=target_manager),
    ]
    monkeypatch.setattr(creator_utils, "_iter_coders", lambda c: coders)
    monkeypatch.setattr(creator_utils, "_agent_name", lambda c: c.name)

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="pdf",
        content="# PDF\n",
        apply_to=["reviewer"],
    )

    primary_manager.load_skill.assert_not_called()
    target_manager.load_skill.assert_called_once_with("pdf")


@pytest.mark.asyncio
async def test_scoped_skill_remove_deactivates_only_target(
    coder, creator_paths, reloads, registry, monkeypatch
):
    _, local_yml = creator_paths
    registry("reviewer")
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump({"agents": {"reviewer": {"agent-config": {"skills_includelist": ["pdf"]}}}})
    )
    primary_manager = Mock(include_list=None, _loaded_skills={"pdf"})
    target_manager = Mock(include_list=None, _loaded_skills={"pdf"})
    target_manager.remove_skill.return_value = "Skill 'pdf' removed."
    coders = [
        SimpleNamespace(name="", skills_manager=primary_manager),
        SimpleNamespace(name="reviewer", skills_manager=target_manager),
    ]
    monkeypatch.setattr(creator_utils, "_iter_coders", lambda c: coders)
    monkeypatch.setattr(creator_utils, "_agent_name", lambda c: c.name)

    await Tool.execute(
        coder,
        action="remove",
        type="skill",
        scope="local",
        name="pdf",
        apply_to=["reviewer"],
    )

    primary_manager.remove_skill.assert_not_called()
    target_manager.remove_skill.assert_called_once_with("pdf")


@pytest.mark.asyncio
async def test_scoped_skill_wildcard_affects_only_matching_coders(
    coder, creator_paths, reloads, registry, monkeypatch
):
    _, local_yml = creator_paths
    registry("wf:one")
    registry("writer")
    primary_manager = Mock(include_list=None, _loaded_skills=set())
    workflow_manager = Mock(include_list=None, _loaded_skills=set())
    writer_manager = Mock(include_list=None, _loaded_skills=set())
    workflow_manager.load_skill.return_value = "Skill 'pdf' loaded successfully."
    coders = [
        SimpleNamespace(name="", skills_manager=primary_manager),
        SimpleNamespace(name="wf:one", skills_manager=workflow_manager),
        SimpleNamespace(name="writer", skills_manager=writer_manager),
    ]
    monkeypatch.setattr(creator_utils, "_iter_coders", lambda c: coders)
    monkeypatch.setattr(creator_utils, "_agent_name", lambda c: c.name)

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="pdf",
        content="# PDF\n",
        apply_to=["wf:*"],
    )

    primary_manager.load_skill.assert_not_called()
    writer_manager.load_skill.assert_not_called()
    workflow_manager.load_skill.assert_called_once_with("pdf")
