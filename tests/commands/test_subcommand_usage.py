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
