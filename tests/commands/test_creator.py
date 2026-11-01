"""Tests for the /creator command."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cecli.commands.creator import CreatorCommand
from cecli.helpers.agents.service import AgentService


def _service(new_coder):
    service = SimpleNamespace(foreground_uuid=None)
    info = SimpleNamespace(coder=new_coder)
    service.spawn = AsyncMock(return_value=(new_coder, info))

    return service


def _coder(tui=None):
    return SimpleNamespace(uuid="primary-uuid", tui=tui)


def _patch_service(monkeypatch, service):
    monkeypatch.setattr(AgentService, "get_instance", classmethod(lambda cls, coder: service))


@pytest.mark.asyncio
async def test_creator_command_spawns_with_prompt(monkeypatch):
    new_coder = SimpleNamespace(uuid="creator-uuid")
    service = _service(new_coder)
    _patch_service(monkeypatch, service)
    coder = _coder()
    io = MagicMock()

    await CreatorCommand.execute(io, coder, "  build a review skill  ")

    service.spawn.assert_awaited_once_with(
        "creator",
        "build a review skill",
        parent=coder,
        auto_reap=False,
        independent=True,
    )
    assert service.foreground_uuid == "creator-uuid"


@pytest.mark.asyncio
async def test_creator_command_spawns_without_prompt(monkeypatch):
    new_coder = SimpleNamespace(uuid="creator-uuid")
    service = _service(new_coder)
    _patch_service(monkeypatch, service)

    await CreatorCommand.execute(MagicMock(), _coder(), "   ")

    assert service.spawn.await_args.args == ("creator", None)
    assert service.foreground_uuid == "creator-uuid"


@pytest.mark.asyncio
async def test_creator_command_switches_tui_to_new_agent(monkeypatch):
    new_coder = SimpleNamespace(uuid="creator-uuid")
    service = _service(new_coder)
    _patch_service(monkeypatch, service)
    tui = MagicMock()
    tui.get_keys_for.return_value = "ctrl+x"
    coder = _coder(tui=MagicMock(return_value=tui))
    io = MagicMock()

    await CreatorCommand.execute(io, coder, "add a hook")

    tui.call_from_thread.assert_called_once_with(tui._switch_to_container, "creator-uuid")
    messages = "\n".join(str(call) for call in io.tool_output.call_args_list)
    assert "ctrl+x" in messages


@pytest.mark.asyncio
async def test_creator_command_reports_spawn_errors(monkeypatch):
    service = _service(SimpleNamespace(uuid="creator-uuid"))
    service.spawn.side_effect = ValueError("no such agent")
    _patch_service(monkeypatch, service)
    io = MagicMock()

    await CreatorCommand.execute(io, _coder(), "add a hook")

    io.tool_error.assert_called_once_with("Error: no such agent")
