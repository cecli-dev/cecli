import pytest

from cecli.helpers.agents.service import AgentService


@pytest.fixture(autouse=True)
def reset_agent_registry():
    """Clear the global sub-agent registry before/after each test."""
    AgentService._global_registry.clear()
    yield
    AgentService._global_registry.clear()
