"""Tests for subcommand usage hints shown by the TUI."""

import pytest

from cecli.commands import (
    CommandRegistry,
    HooksCommand,
    McpCommand,
    QueueCommand,
    SessionsCommand,
    SkillsCommand,
    WorkflowCommand,
)

DISPATCHERS = (
    HooksCommand,
    McpCommand,
    QueueCommand,
    SessionsCommand,
    SkillsCommand,
    WorkflowCommand,
)


@pytest.mark.parametrize("command_class", DISPATCHERS)
def test_every_subcommand_has_a_usage_hint(command_class):
    assert set(command_class.SUBCOMMANDS) == set(command_class.SUBCOMMAND_USAGE)


@pytest.mark.parametrize("command_class", DISPATCHERS)
def test_get_command_description_returns_subcommand_usage(command_class):
    for subcommand in command_class.SUBCOMMANDS:
        description = CommandRegistry.get_command_description(command_class.NORM_NAME, subcommand)

        assert description == command_class.SUBCOMMAND_USAGE[subcommand]


def test_unknown_subcommand_falls_back_to_command_description():
    assert CommandRegistry.get_command_description("mcp", "bogus") == McpCommand.DESCRIPTION
    assert CommandRegistry.get_command_description("mcp") == McpCommand.DESCRIPTION


@pytest.mark.parametrize("command_class", DISPATCHERS)
def test_aliases_route_to_registered_subcommands(command_class):
    aliases = getattr(command_class, "ALIASES", {})
    assert aliases

    for alias, subcommand in aliases.items():
        assert subcommand in command_class.SUBCOMMANDS
        assert CommandRegistry.resolve_alias(alias) == (command_class.NORM_NAME, subcommand)
        assert CommandRegistry.get_command(alias) is command_class


def test_command_listing_includes_aliases_on_request():
    plain = CommandRegistry.list_commands()
    aliases = CommandRegistry.list_commands(include_aliases=True)

    assert "load-mcp" not in plain
    assert "load-mcp" in aliases
    assert set(aliases) - set(plain) == {
        alias for command_class in DISPATCHERS for alias in command_class.ALIASES
    }


def test_alias_description_uses_target_subcommand_usage():
    assert (
        CommandRegistry.get_command_description("load-mcp") == McpCommand.SUBCOMMAND_USAGE["load"]
    )
    assert CommandRegistry.get_command_description("load-mcp", "ignored") == (
        McpCommand.SUBCOMMAND_USAGE["load"]
    )


@pytest.mark.asyncio
async def test_alias_execution_prefixes_the_subcommand():
    from unittest.mock import AsyncMock, MagicMock, patch

    io = MagicMock()
    coder = MagicMock()

    with patch("cecli.commands.mcp_helpers.load.cmd_load", new_callable=AsyncMock) as cmd_load:
        await CommandRegistry.execute("load-mcp", io, coder, "github")

    cmd_load.assert_awaited_once_with(io, coder, "github")
