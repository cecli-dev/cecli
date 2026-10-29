"""Tests for the creator-scoped ManageExtensions tool."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from cecli.helpers.creator import utils as creator_utils
from cecli.tools import manage_extensions
from cecli.tools.manage_extensions import Tool
from cecli.tools.utils.helpers import ToolError


@pytest.fixture
def coder(tmp_path):
    return SimpleNamespace(
        agent_config={"creator_mode": True},
        root=str(tmp_path / "repo"),
        primary_root=str(tmp_path / "repo"),
        io=Mock(),
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
    """Patch every creator reload helper; return the mocks by name."""
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

    return mocks


def _result_text(response):
    return "\n".join(item["content"] for item in response.to_dict()["result"])


@pytest.mark.asyncio
async def test_add_config_writes_local_creator_yml(coder, creator_paths, reloads):
    global_yml, local_yml = creator_paths

    response = await Tool.execute(
        coder,
        action="add",
        type="config",
        scope="local",
        name="models.default",
        config="gpt-test",
    )

    data = yaml.safe_load(local_yml.read_text())
    assert data == {"models": {"default": "gpt-test"}}
    assert not global_yml.exists()
    assert "reload_creator_extensions: ok" in _result_text(response)


@pytest.mark.asyncio
async def test_add_mcp_server_records_entry_and_reloads(coder, creator_paths, reloads):
    _, local_yml = creator_paths
    reloads["reload_mcp_servers"].return_value = ["MCP servers added: demo"]

    response = await Tool.execute(
        coder,
        action="add",
        type="mcp_server",
        scope="local",
        name="demo",
        config={"command": "run-demo", "args": ["--stdio"]},
    )

    data = yaml.safe_load(local_yml.read_text())
    assert data["mcp-servers"]["demo"]["command"] == "run-demo"

    text = _result_text(response)
    assert "MCP servers added: demo" in text
    reloads["reload_mcp_servers"].assert_awaited_once()


@pytest.mark.asyncio
async def test_add_skill_writes_file_and_path(coder, creator_paths, reloads):
    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="demo-skill",
        content="# Demo\nbody\n",
    )

    skill_file = local_yml.parent / "skills" / "demo-skill" / "SKILL.md"
    assert skill_file.read_text() == "# Demo\nbody\n"

    data = yaml.safe_load(local_yml.read_text())
    assert str(local_yml.parent / "skills") in data["agent-config"]["skills_paths"]
    reloads["reload_skills"].assert_awaited_once()


@pytest.mark.asyncio
async def test_non_creator_coder_rejected(coder, creator_paths, reloads, monkeypatch):
    monkeypatch.setattr(manage_extensions, "is_creator_coder", lambda coder: False)

    with pytest.raises(ToolError):
        await Tool.execute(coder, action="add", type="config", name="x", config=1)


@pytest.mark.asyncio
async def test_remove_pops_entry(coder, creator_paths, reloads):
    _, local_yml = creator_paths
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump({"mcp-servers": {"keep": {}, "drop": {"command": "x"}}}, sort_keys=False)
    )

    response = await Tool.execute(coder, action="remove", type="mcp_server", name="drop")

    data = yaml.safe_load(local_yml.read_text())
    assert list(data["mcp-servers"]) == ["keep"]
    assert "Removed mcp_server entry 'drop'" in _result_text(response)
    reloads["reload_mcp_servers"].assert_awaited_once()


@pytest.mark.asyncio
async def test_list_returns_both_files(coder, creator_paths, reloads):
    global_yml, local_yml = creator_paths
    global_yml.parent.mkdir(parents=True)
    local_yml.parent.mkdir(parents=True)
    global_yml.write_text(yaml.dump({"hooks": {"global_hook": {}}}))
    local_yml.write_text(yaml.dump({"mcp-servers": {"local_server": {}}}))

    response = await Tool.execute(coder, action="list", type="config")

    text = _result_text(response)
    assert "global_hook" in text
    assert "local_server" in text
    assert "global creator.yml" in text
    assert "local creator.yml" in text


@pytest.fixture
def live_coders(monkeypatch):
    """Route _iter_coders to a fixed list instead of the agent service."""

    def patch(coders):
        monkeypatch.setattr(creator_utils, "_iter_coders", lambda coder: coders)
        return coders

    return patch


@pytest.mark.asyncio
async def test_add_skill_records_includelist_when_whitelist_active(
    coder, creator_paths, reloads, live_coders
):
    _, local_yml = creator_paths
    coder.agent_config["skills_includelist"] = ["existing-skill"]
    live_coders([coder])

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="demo-skill",
        content="# Demo\n",
    )

    data = yaml.safe_load(local_yml.read_text())
    assert "demo-skill" in data["agent-config"]["skills_includelist"]
    assert "agent-config" in data


@pytest.mark.asyncio
async def test_add_skill_without_whitelist_keeps_unfiltered(
    coder, creator_paths, reloads, live_coders
):
    _, local_yml = creator_paths
    live_coders([coder])

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="demo-skill",
        content="# Demo\n",
    )

    data = yaml.safe_load(local_yml.read_text())
    assert "skills_includelist" not in data.get("agent-config", {})


@pytest.mark.asyncio
async def test_skill_activation_includes_then_loads(coder, creator_paths, reloads, live_coders):
    manager = Mock()
    manager.include_list = {"existing-skill"}
    manager._loaded_skills = set()
    manager.include_skill.return_value = "Skill 'demo-skill' has been included (whitelisted)."
    manager.load_skill.return_value = "Skill 'demo-skill' loaded successfully."
    coder.skills_manager = manager
    live_coders([coder])

    response = await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="demo-skill",
        content="# Demo\n",
    )

    manager.include_skill.assert_called_once_with("demo-skill")
    manager.load_skill.assert_called_once_with("demo-skill")
    text = _result_text(response)
    assert "loaded successfully" in text


@pytest.mark.asyncio
async def test_skill_activation_without_whitelist_only_loads(
    coder, creator_paths, reloads, live_coders
):
    manager = Mock()
    manager.include_list = None
    manager._loaded_skills = set()
    manager.load_skill.return_value = "Skill 'demo-skill' loaded successfully."
    coder.skills_manager = manager
    live_coders([coder])

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="demo-skill",
        content="# Demo\n",
    )

    manager.include_skill.assert_not_called()
    manager.load_skill.assert_called_once_with("demo-skill")


@pytest.mark.asyncio
async def test_add_skill_ignores_empty_include_list(coder, creator_paths, reloads, live_coders):
    """An empty restored include set means no filtering, not a whitelist."""
    _, local_yml = creator_paths
    manager = Mock()
    manager.include_list = set()
    manager._loaded_skills = set()
    manager.load_skill.return_value = "Skill 'demo-skill' loaded successfully."
    coder.skills_manager = manager
    coder.registered_servers = {"included": {"already-connected"}}
    live_coders([coder])

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        scope="local",
        name="demo-skill",
        content="# Demo\n",
    )

    data = yaml.safe_load(local_yml.read_text())
    assert "skills_includelist" not in data.get("agent-config", {})
    manager.include_skill.assert_not_called()


@pytest.mark.asyncio
async def test_add_mcp_server_ignores_runtime_included_set(
    coder, creator_paths, reloads, live_coders
):
    """A runtime populated servers include set does not imply a configured whitelist."""
    _, local_yml = creator_paths
    coder.registered_servers = {"included": {"already-connected"}}
    live_coders([coder])

    await Tool.execute(
        coder,
        action="add",
        type="mcp_server",
        scope="local",
        name="demo",
        config={"command": "run-demo"},
    )

    data = yaml.safe_load(local_yml.read_text())
    assert "servers_includelist" not in data.get("agent-config", {})


@pytest.mark.asyncio
async def test_add_workflow_from_config_includes_name_and_loads(coder, creator_paths, reloads):
    """Config-derived workflows are written with the entry name and are discoverable."""
    from cecli.helpers.workflows.config import load_workflows

    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="workflow",
        scope="local",
        name="nightly",
        config={"enabled": False, "tasks": [{"prompt": "say hi"}]},
    )

    workflow_file = local_yml.parent / "workflows" / "nightly.yml"
    data = yaml.safe_load(workflow_file.read_text())
    assert data["name"] == "nightly"
    assert data["enabled"] is False

    names = [workflow.name for workflow in load_workflows(git_root=coder.root)]
    assert "nightly" in names


@pytest.mark.asyncio
async def test_remove_workflow_delete_files_removes_backing_file(coder, creator_paths, reloads):
    """A workflow file is itself the entry, so delete_files removes it."""
    _, local_yml = creator_paths
    workflow_file = local_yml.parent / "workflows" / "nightly.yml"
    workflow_file.parent.mkdir(parents=True)
    workflow_file.write_text("name: nightly\ntasks:\n  - prompt: hi\n")

    response = await Tool.execute(coder, action="remove", type="workflow", name="nightly")
    assert workflow_file.exists()
    assert "left on disk" in _result_text(response)

    response = await Tool.execute(
        coder,
        action="remove",
        type="workflow",
        name="nightly",
        config={"delete_files": True},
    )
    assert not workflow_file.exists()
    assert "Deleted" in _result_text(response)


@pytest.mark.asyncio
async def test_remove_skill_delete_files_removes_default_dir(coder, creator_paths, reloads):
    """Default skills directories are removable even without a creator.yml entry."""
    _, local_yml = creator_paths
    skill_dir = local_yml.parent / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Demo\n")

    response = await Tool.execute(coder, action="remove", type="skill", name="demo-skill")
    assert skill_dir.exists()
    assert "left on disk" in _result_text(response)

    response = await Tool.execute(
        coder,
        action="remove",
        type="skill",
        name="demo-skill",
        config={"delete_files": True},
    )
    assert not skill_dir.exists()
    assert "Deleted" in _result_text(response)


@pytest.fixture
def registry(monkeypatch):
    """Install a fixed agent registry (unfiltered unless configured below)."""
    from cecli.helpers.agents.service import AgentService

    mapping = {
        "reviewer": SimpleNamespace(
            metadata={"agent-config": {"skills_includelist": ["existing-skill"]}}
        ),
        "worker": SimpleNamespace(metadata={}),
        "wf:nightly": SimpleNamespace(metadata={}),
        "wf:weekly": SimpleNamespace(metadata={}),
    }
    monkeypatch.setattr(AgentService, "_global_registry", mapping)

    return mapping


@pytest.fixture(autouse=True)
def stub_override_refresh(monkeypatch):
    """Keep ManageExtensions' post-write override refresh out of the real config files."""
    from cecli.helpers.agents import overrides

    monkeypatch.setattr(overrides, "refresh_agent_overrides", Mock(return_value={}))


@pytest.mark.asyncio
async def test_apply_to_rejects_primary(coder, creator_paths, reloads, registry):
    with pytest.raises(ToolError, match="cannot be targeted"):
        await Tool.execute(coder, action="add", type="skill", name="demo", apply_to=["primary"])


@pytest.mark.asyncio
async def test_apply_to_unknown_name_lists_registered(coder, creator_paths, reloads, registry):
    with pytest.raises(ToolError, match="Registered agents"):
        await Tool.execute(coder, action="add", type="skill", name="demo", apply_to=["reviewe"])


@pytest.mark.asyncio
async def test_apply_to_rejected_for_workflow_and_custom_tool(
    coder, creator_paths, reloads, registry
):
    for entry_type in ("workflow", "custom_tool", "custom_command"):
        with pytest.raises(ToolError, match="not supported"):
            await Tool.execute(
                coder,
                action="add",
                type=entry_type,
                name="demo",
                apply_to=["reviewer"],
            )


@pytest.mark.asyncio
async def test_config_apply_to_requires_exact_agent_and_scoped_path(
    coder, creator_paths, reloads, registry
):
    with pytest.raises(ToolError, match="exactly one exact agent"):
        await Tool.execute(
            coder,
            action="add",
            type="config",
            name="agent-config.skills_includelist",
            config=["a"],
            apply_to=["reviewer", "worker"],
        )

    with pytest.raises(ToolError, match="exact agent name"):
        await Tool.execute(
            coder,
            action="add",
            type="config",
            name="agent-config.skills_includelist",
            config=["a"],
            apply_to=["wf:*"],
        )

    with pytest.raises(ToolError, match="only supports"):
        await Tool.execute(
            coder,
            action="add",
            type="config",
            name="models.default",
            config="gpt-test",
            apply_to=["reviewer"],
        )


@pytest.mark.asyncio
async def test_config_apply_to_writes_agent_node(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="config",
        name="agent-config.skills_includelist",
        config=["pdf"],
        apply_to=["reviewer"],
    )

    data = yaml.safe_load(local_yml.read_text())
    assert data["agents"]["reviewer"]["agent-config"]["skills_includelist"] == ["pdf"]
    assert "agent-config" not in data


@pytest.mark.asyncio
async def test_skill_apply_to_scopes_path_and_conditional_includelist(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        name="pdf",
        content="# PDF\n",
        apply_to=["reviewer", "worker"],
    )

    data = yaml.safe_load(local_yml.read_text())
    skill_path = str(local_yml.parent / "skills")
    assert data["agents"]["reviewer"]["agent-config"]["skills_paths"] == [skill_path]
    assert data["agents"]["reviewer"]["agent-config"]["skills_includelist"] == ["pdf"]
    assert data["agents"]["worker"]["agent-config"]["skills_paths"] == [skill_path]
    assert "skills_includelist" not in data["agents"]["worker"]["agent-config"]
    assert "agent-config" not in data


@pytest.mark.asyncio
async def test_skill_apply_to_wildcard_writes_single_pattern_node(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        name="pdf",
        content="# PDF\n",
        apply_to=["wf:*"],
    )

    data = yaml.safe_load(local_yml.read_text())
    assert list(data["agents"]) == ["wf:*"]
    assert "skills_includelist" not in data["agents"]["wf:*"]["agent-config"]


@pytest.mark.asyncio
async def test_mcp_apply_to_includelist_only_for_filtering_targets(
    coder, creator_paths, reloads, registry
):
    registry["worker"] = SimpleNamespace(
        metadata={"agent-config": {"servers_includelist": ["github"]}}
    )
    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="mcp_server",
        name="demo",
        config={"command": "run-demo"},
        apply_to=["reviewer", "worker"],
    )

    data = yaml.safe_load(local_yml.read_text())
    assert data["mcp-servers"]["demo"]["command"] == "run-demo"
    assert data["agents"]["worker"]["agent-config"]["servers_includelist"] == ["demo"]
    assert "agents" not in data or "reviewer" not in data["agents"]


@pytest.mark.asyncio
async def test_mcp_apply_to_ignores_runtime_included_set(
    coder, creator_paths, reloads, registry, live_coders
):
    coder.registered_servers = {"included": {"already-connected"}}
    live_coders([coder])
    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="mcp_server",
        name="demo",
        config={"command": "run-demo"},
        apply_to=["worker"],
    )

    data = yaml.safe_load(local_yml.read_text())
    assert "agents" not in data


@pytest.mark.asyncio
async def test_hook_apply_to_keeps_shared_definition_and_adds_agent_entry(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="hook",
        name="audit",
        config={"pre_tool_call": [{"file": "audit.py"}]},
        apply_to=["reviewer"],
    )

    data = yaml.safe_load(local_yml.read_text())
    assert data["hooks"]["audit"]["pre_tool_call"] == [{"file": "audit.py"}]
    assert data["agents"]["reviewer"]["hooks"]["audit"]["pre_tool_call"] == [{"file": "audit.py"}]


@pytest.mark.asyncio
async def test_remove_apply_to_prunes_only_named_targets(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump(
            {
                "agents": {
                    "reviewer": {
                        "agent-config": {
                            "skills_paths": ["/skills"],
                            "skills_includelist": ["pdf"],
                        }
                    },
                    "worker": {
                        "agent-config": {
                            "skills_paths": ["/skills"],
                            "skills_includelist": ["pdf"],
                        }
                    },
                }
            }
        )
    )

    await Tool.execute(coder, action="remove", type="skill", name="pdf", apply_to=["reviewer"])

    data = yaml.safe_load(local_yml.read_text())
    assert "skills_includelist" not in data["agents"]["reviewer"]["agent-config"]
    assert data["agents"]["reviewer"]["agent-config"]["skills_paths"] == ["/skills"]
    assert data["agents"]["worker"]["agent-config"]["skills_includelist"] == ["pdf"]


@pytest.mark.asyncio
async def test_remove_apply_to_wildcard_prunes_all_per_agent_entries(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump(
            {
                "agents": {
                    "reviewer": {"agent-config": {"skills_includelist": ["pdf"]}},
                    "wf:*": {"agent-config": {"skills_includelist": ["pdf"]}},
                    "worker": {"agent-config": {"skills_paths": ["/skills"]}},
                }
            }
        )
    )

    await Tool.execute(coder, action="remove", type="skill", name="pdf", apply_to=["*"])

    data = yaml.safe_load(local_yml.read_text())
    assert "reviewer" not in data["agents"]
    assert "wf:*" not in data["agents"]
    assert data["agents"]["worker"]["agent-config"]["skills_paths"] == ["/skills"]


@pytest.mark.asyncio
async def test_remove_without_apply_to_prunes_shared_and_per_agent(
    coder, creator_paths, reloads, registry
):
    _, local_yml = creator_paths
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump(
            {
                "agent-config": {
                    "skills_paths": ["/skills"],
                    "skills_includelist": ["pdf", "keep"],
                },
                "agents": {"reviewer": {"agent-config": {"skills_includelist": ["pdf", "keep"]}}},
            }
        )
    )

    await Tool.execute(coder, action="remove", type="skill", name="pdf")

    data = yaml.safe_load(local_yml.read_text())
    assert data["agent-config"]["skills_includelist"] == ["keep"]
    assert data["agents"]["reviewer"]["agent-config"]["skills_includelist"] == ["keep"]


@pytest.mark.asyncio
async def test_update_merges_mcp_config_and_keeps_agent_entry(
    coder, creator_paths, reloads, registry
):
    registry["worker"] = SimpleNamespace(
        metadata={"agent-config": {"servers_includelist": ["github"]}}
    )
    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="mcp_server",
        name="demo",
        config={"command": "run-demo"},
        apply_to=["worker"],
    )
    await Tool.execute(
        coder,
        action="update",
        type="mcp_server",
        name="demo",
        config={"args": ["--stdio"]},
        apply_to=["worker"],
    )

    data = yaml.safe_load(local_yml.read_text())
    assert data["mcp-servers"]["demo"] == {
        "command": "run-demo",
        "args": ["--stdio"],
    }
    assert "demo" in data["agents"]["worker"]["agent-config"]["servers_includelist"]


@pytest.mark.asyncio
async def test_shared_path_unchanged_without_apply_to(coder, creator_paths, reloads, registry):
    _, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="skill",
        name="pdf",
        content="# PDF\n",
    )

    data = yaml.safe_load(local_yml.read_text())
    assert "agents" not in data
    assert str(local_yml.parent / "skills") in data["agent-config"]["skills_paths"]


@pytest.mark.asyncio
async def test_add_custom_tool_writes_file_and_records_tools_path(
    coder, creator_paths, reloads, live_coders
):
    _, local_yml = creator_paths
    live_coders([coder])
    source = "class Tool:\n    pass\n"

    await Tool.execute(
        coder,
        action="add",
        type="custom_tool",
        scope="local",
        name="log_summary",
        content=source,
    )

    tool_file = local_yml.parent / "tools" / "log_summary.py"
    assert tool_file.read_text() == source

    data = yaml.safe_load(local_yml.read_text())
    assert data["agent-config"]["tools_paths"] == [str(local_yml.parent / "tools")]
    reloads["reload_custom_tools"].assert_awaited_once()


@pytest.mark.asyncio
async def test_add_custom_command_writes_file_and_records_command_path(
    coder, creator_paths, reloads, live_coders
):
    _, local_yml = creator_paths
    live_coders([coder])
    source = "from cecli.commands.utils.base_command import BaseCommand\n"

    await Tool.execute(
        coder,
        action="add",
        type="custom_command",
        scope="local",
        name="deploy",
        content=source,
    )

    command_file = local_yml.parent / "commands" / "deploy.py"
    assert command_file.read_text() == source

    data = yaml.safe_load(local_yml.read_text())
    assert data["custom"]["command-paths"] == [str(command_file)]
    reloads["reload_custom_commands"].assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_custom_tool_delete_files_removes_source(
    coder, creator_paths, reloads, live_coders
):
    _, local_yml = creator_paths
    live_coders([coder])
    tool_file = local_yml.parent / "tools" / "log_summary.py"
    tool_file.parent.mkdir(parents=True)
    tool_file.write_text("class Tool:\n    pass\n")

    response = await Tool.execute(
        coder,
        action="remove",
        type="custom_tool",
        name="log_summary",
        config={"delete_files": True},
    )

    assert not tool_file.exists()
    assert "Deleted" in _result_text(response)


@pytest.mark.asyncio
async def test_remove_custom_command_delete_files_removes_source(
    coder, creator_paths, reloads, live_coders
):
    _, local_yml = creator_paths
    live_coders([coder])
    command_file = local_yml.parent / "commands" / "deploy.py"
    command_file.parent.mkdir(parents=True)
    command_file.write_text("class Command:\n    pass\n")

    response = await Tool.execute(
        coder,
        action="remove",
        type="custom_command",
        name="deploy",
        config={"delete_files": True},
    )

    assert not command_file.exists()
    assert "Deleted" in _result_text(response)


@pytest.mark.asyncio
async def test_add_config_writes_global_creator_yml(coder, creator_paths, reloads):
    global_yml, local_yml = creator_paths

    await Tool.execute(
        coder,
        action="add",
        type="config",
        scope="global",
        name="models.default",
        config="gpt-global",
    )

    data = yaml.safe_load(global_yml.read_text())
    assert data == {"models": {"default": "gpt-global"}}
    assert not local_yml.exists()


@pytest.mark.asyncio
async def test_add_preserves_unrelated_creator_yml_content(coder, creator_paths, reloads):
    _, local_yml = creator_paths
    local_yml.parent.mkdir(parents=True)
    local_yml.write_text(
        yaml.dump(
            {
                "model": "keep-me",
                "mcp-servers": {"keep": {"command": "keep-cmd"}},
            },
            sort_keys=False,
        )
    )

    await Tool.execute(
        coder,
        action="add",
        type="mcp_server",
        scope="local",
        name="demo",
        config={"command": "run-demo"},
    )

    data = yaml.safe_load(local_yml.read_text())
    assert data["model"] == "keep-me"
    assert data["mcp-servers"]["keep"]["command"] == "keep-cmd"
    assert data["mcp-servers"]["demo"]["command"] == "run-demo"


@pytest.mark.asyncio
async def test_add_disabled_workflow_warns_no_subagent(coder, creator_paths, reloads):
    response = await Tool.execute(
        coder,
        action="add",
        type="workflow",
        scope="local",
        name="nightly",
        config={"enabled": False, "tasks": [{"prompt": "say hi"}]},
    )

    assert "enabled: false; no wf: sub-agent registers" in _result_text(response)
