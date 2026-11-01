"""Tests for the /agent-tree command."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cecli.commands.agent_tree import AgentTreeCommand
from cecli.helpers.agents.service import AgentService, SubAgentStatus
from cecli.helpers.agents.tree import AgentTree


@pytest.fixture(autouse=True)
def clean_tree():
    """Start and end every test with an empty shared tree."""
    AgentTree.clear()
    yield
    AgentTree.clear()


def _info(name, coder, parent_uuid):
    return SimpleNamespace(
        name=name,
        coder=coder,
        parent_uuid=parent_uuid,
        status=SubAgentStatus.RUNNING,
        error=None,
    )


@pytest.mark.asyncio
async def test_agent_tree_reads_shared_tree_and_scopes_to_primary_subtree():
    """The command renders the primary's AgentTree subtree and nothing else."""
    primary = SimpleNamespace(uuid="primary", parent_uuid="")
    worker = SimpleNamespace(uuid="worker", parent_uuid="primary")
    other_worker = SimpleNamespace(uuid="other-worker", parent_uuid="other-primary")

    service = SimpleNamespace(
        coder=primary,
        sub_agents={
            "worker": _info("worker", worker, "primary"),
            "other-worker": _info("other-worker", other_worker, "other-primary"),
        },
    )

    AgentTree.register("primary", name="primary")
    AgentTree.register("worker", parent_uuid="primary", name="worker")
    AgentTree.register("other-primary", name="primary")
    AgentTree.register("other-worker", parent_uuid="other-primary", name="worker")

    io = MagicMock()
    with patch.object(AgentService, "get_instance", return_value=service):
        await AgentTreeCommand.execute(io, primary, "")

    output = "\n".join(call.args[0] for call in io.tool_output.call_args_list)

    assert "primary" in output
    assert "worker" in output
    assert "other-worker" not in output


@pytest.mark.asyncio
async def test_agent_tree_uses_tree_structure_not_coder_parent_uuid():
    """The rendered hierarchy follows AgentTree parent links."""
    primary = SimpleNamespace(uuid="primary", parent_uuid="")
    worker = SimpleNamespace(uuid="worker", parent_uuid="")

    service = SimpleNamespace(
        coder=primary,
        sub_agents={"worker": _info("worker", worker, "")},
    )

    AgentTree.register("primary", name="primary")
    AgentTree.register("worker", parent_uuid="primary", name="worker")

    io = MagicMock()
    with patch.object(AgentService, "get_instance", return_value=service):
        await AgentTreeCommand.execute(io, primary, "")

    output = "\n".join(call.args[0] for call in io.tool_output.call_args_list)

    assert "└── primary" in output
    assert "└── worker" in output
