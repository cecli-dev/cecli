"""Completion behavior for the consolidated /mcp and /skills commands."""

import pytest

import cecli.helpers.extensions.skills_importer as skills_importer
from cecli.commands.mcp import McpCommand
from cecli.commands.skills import SkillsCommand


class _Server:
    def __init__(self, name, connected):
        self.name = name
        self.is_connected = connected


class _McpManager:
    def __init__(self):
        self.servers = [
            _Server("github", True),
            _Server("context7", False),
            _Server("unnamed-server", False),
        ]
        self.connected_servers = [server for server in self.servers if server.is_connected]

    def __iter__(self):
        return iter(self.servers)


class _Skill:
    def __init__(self, name):
        self.name = name


class _SkillsManager:
    def find_skills(self):
        return [_Skill("pdf"), _Skill("docx")]


class _Coder:
    pass


@pytest.fixture
def mcp_coder():
    coder = _Coder()
    coder.mcp_manager = _McpManager()
    return coder


@pytest.fixture
def skills_coder(monkeypatch):
    coder = _Coder()
    coder.skills_manager = _SkillsManager()
    monkeypatch.setattr(
        skills_importer, "get_registry_skills", lambda: ["pdf", "docx", "files/slides"]
    )
    return coder


@pytest.mark.parametrize(
    "args, expected",
    [
        ("", ["list", "load", "remove"]),
        ("l", ["list", "load"]),
        ("load ", ["context7"]),
        ("load c", ["context7"]),
        ("load context7 ", ["context7"]),
        ("remove ", ["github"]),
        ("remove github ", ["github"]),
        ("list ", []),
    ],
)
def test_mcp_completions(mcp_coder, args, expected):
    assert McpCommand.get_completions(None, mcp_coder, args) == expected


@pytest.mark.parametrize(
    "args, expected",
    [
        ("", ["list", "load", "include", "exclude", "remove", "import"]),
        ("l", ["list", "load"]),
        ("load ", ["pdf", "docx"]),
        ("include ", ["pdf", "docx"]),
        ("include pdf ", ["pdf", "docx"]),
        ("include d", ["docx"]),
        ("import ", ["--global", "pdf", "docx", "files/slides"]),
        ("import --", ["--global"]),
        ("import --global ", ["pdf", "docx", "files/slides"]),
        ("import --global d", ["docx"]),
        ("import -g ", ["pdf", "docx", "files/slides"]),
        ("list ", []),
    ],
)
def test_skills_completions(skills_coder, args, expected):
    assert SkillsCommand.get_completions(None, skills_coder, args) == expected


def test_mcp_and_skills_receive_full_args_for_completion():
    from cecli.commands.core import Commands

    assert "/mcp" in Commands.FULL_ARGS_COMPLETION_COMMANDS
    assert "/skills" in Commands.FULL_ARGS_COMPLETION_COMMANDS


def _io_completer(coder):
    from cecli.commands.core import Commands
    from cecli.io import AutoCompleter

    completer = AutoCompleter.__new__(AutoCompleter)
    completer.commands = Commands(None, coder)
    completer.command_names = completer.commands.get_commands()
    return completer


def test_io_completes_skills_subcommands_and_names(skills_coder):
    completer = _io_completer(skills_coder)

    command = list(completer.get_command_completions(None, None, "/skill", ["/skill"]))
    assert any(c.text == "/skills " for c in command)

    subcommands = list(completer.get_command_completions(None, None, "/skills ", ["/skills"]))
    assert {c.text for c in subcommands} == {
        "list",
        "load",
        "include",
        "exclude",
        "remove",
        "import",
    }
    assert not any(c.text.endswith(" ") for c in subcommands)

    load = list(completer.get_command_completions(None, None, "/skills l", ["/skills", "l"]))
    assert {c.text for c in load} == {"list", "load"}

    names = list(
        completer.get_command_completions(None, None, "/skills load ", ["/skills", "load"])
    )
    assert {c.text for c in names} == {"pdf", "docx"}


def test_io_completes_mcp_names(mcp_coder):
    completer = _io_completer(mcp_coder)

    command = list(completer.get_command_completions(None, None, "/mc", ["/mc"]))
    assert any(c.text == "/mcp " for c in command)

    no_subcommands = list(completer.get_command_completions(None, None, "/ad", ["/ad"]))
    assert no_subcommands
    assert not any(c.text.endswith(" ") for c in no_subcommands)

    subcommands = list(completer.get_command_completions(None, None, "/mcp ", ["/mcp"]))
    assert {c.text for c in subcommands} == {"list", "load", "remove"}
    assert not any(c.text.endswith(" ") for c in subcommands)

    names = list(completer.get_command_completions(None, None, "/mcp load ", ["/mcp", "load"]))
    assert {c.text for c in names} == {"context7"}


def test_at_subcommand_boundary_blocks_duplicate_spaces():
    from cecli.commands.core import Commands

    commands = Commands(None, None)

    assert commands.at_subcommand_boundary("/skills ")
    assert commands.at_subcommand_boundary("/skills l ")
    assert commands.at_subcommand_boundary("/skills load ")
    assert commands.at_subcommand_boundary("/mcp load ")
    assert commands.at_subcommand_boundary("/workflows run ")

    assert not commands.at_subcommand_boundary("/skills")
    assert not commands.at_subcommand_boundary("/skills load")
    assert not commands.at_subcommand_boundary("/skills load pdf ")
    assert not commands.at_subcommand_boundary("/add ")
    assert not commands.at_subcommand_boundary("/skillsx ")


def _tui_app(coder):
    from unittest.mock import MagicMock

    from cecli.commands.core import Commands
    from cecli.tui.app import TUI

    app = TUI.__new__(TUI)
    app.worker = MagicMock()
    app.worker.coder.commands = Commands(None, coder)
    return app


def test_tui_subcommand_completion_preserves_host(skills_coder):
    app = _tui_app(skills_coder)

    assert app._get_completed_text("/skills ", "load") == "/skills load"
    assert app._get_completed_text("/skills load ", "pdf") == "/skills load pdf"


def test_tui_completion_request_syncs_prefix():
    from unittest.mock import MagicMock

    from cecli.tui.app import TUI

    app = TUI.__new__(TUI)
    input_area = MagicMock()
    input_area.text = "/skills "
    app.query_one = lambda *args, **kwargs: input_area
    app._get_suggestions = lambda text: []

    app.on_input_area_completion_requested(MagicMock(text="/skil"))

    assert input_area._completion_prefix == "/skills "
