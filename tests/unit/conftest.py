"""pytest conftest for unit tests - cleans shared state between tests."""

import pytest

from cecli.helpers.agents.service import AgentService


@pytest.fixture(autouse=True)
def clean_agent_service_state():
    """Clean AgentService class-level state between tests to prevent stale entries."""
    AgentService._uuid_coder_map.clear()
    AgentService._primary_agent_uuid = None
    AgentService._instances = {}
