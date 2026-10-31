"""Tests for the /hooks and /sessions dispatcher commands."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cecli.commands.hooks import HooksCommand
from cecli.commands.sessions import SessionsCommand
from cecli.commands.utils.registry import CommandRegistry


def _fake_loader(modules):
    return classmethod(lambda cls, sub: modules[sub])


def _recorder(calls, name):
    def record(io, coder, args):
        calls.append((name, args))
        return name

    return record


def _async_recorder(calls, name):
    async def record(io, coder, args):
        calls.append((name, args))
        return name

    return record


class TestHooksDispatch:
    @pytest.mark.asyncio
    async def test_flags_route_to_list(self, monkeypatch):
        calls = []
        modules = {"list": SimpleNamespace(cmd_list=_recorder(calls, "list"))}
        monkeypatch.setattr(HooksCommand, "loader", _fake_loader(modules))

        await HooksCommand.execute(None, None, "--type start")

        assert calls == [("list", "--type start")]

    @pytest.mark.asyncio
    async def test_load_and_remove_route_with_args(self, monkeypatch):
        calls = []
        modules = {
            "load": SimpleNamespace(cmd_load=_recorder(calls, "load")),
            "remove": SimpleNamespace(cmd_remove=_recorder(calls, "remove")),
        }
        monkeypatch.setattr(HooksCommand, "loader", _fake_loader(modules))

        await HooksCommand.execute(None, None, "load alpha beta")
        await HooksCommand.execute(None, None, "remove gamma")

        assert calls == [("load", "alpha beta"), ("remove", "gamma")]

    @pytest.mark.asyncio
    async def test_unknown_subcommand_reports_error(self):
        io = MagicMock()

        await HooksCommand.execute(io, None, "bogus")

        io.tool_error.assert_called_once()


class TestSessionsDispatch:
    @pytest.mark.asyncio
    async def test_empty_args_defaults_to_list(self, monkeypatch):
        calls = []
        modules = {"list": SimpleNamespace(cmd_list=_recorder(calls, "list"))}
        monkeypatch.setattr(SessionsCommand, "loader", _fake_loader(modules))

        await SessionsCommand.execute(None, None, "")

        assert calls == [("list", "")]

    @pytest.mark.asyncio
    async def test_load_and_save_route_with_args(self, monkeypatch):
        calls = []
        modules = {
            "load": SimpleNamespace(cmd_load=_async_recorder(calls, "load")),
            "save": SimpleNamespace(cmd_save=_recorder(calls, "save")),
        }
        monkeypatch.setattr(SessionsCommand, "loader", _fake_loader(modules))

        await SessionsCommand.execute(None, None, "load feature-x")
        await SessionsCommand.execute(None, None, "save feature-y")

        assert calls == [("load", "feature-x"), ("save", "feature-y")]

    @pytest.mark.asyncio
    async def test_unknown_subcommand_reports_error(self):
        io = MagicMock()

        await SessionsCommand.execute(io, None, "bogus")

        io.tool_error.assert_called_once()


class TestHooksCompletions:
    @pytest.mark.parametrize(
        "args,expected",
        [
            ("", ["list", "load", "remove"]),
            ("l", ["list", "load"]),
            ("load ", ["alpha", "beta"]),
            ("load a", ["alpha"]),
            ("remove be", ["beta"]),
            ("load alpha be", ["beta"]),
            ("bogus ", []),
        ],
    )
    def test_completions(self, monkeypatch, args, expected):
        from cecli.commands.hooks_helpers import common

        monkeypatch.setattr(common, "hook_names", lambda coder: ["alpha", "beta"])

        assert HooksCommand.get_completions(None, None, args) == expected


class TestSessionsCompletions:
    @pytest.mark.parametrize(
        "args,expected",
        [
            ("", ["list", "load", "save"]),
            ("s", ["save"]),
            ("load ", ["alpha", "beta"]),
            ("save al", ["alpha"]),
            ("list ", []),
            ("bogus ", []),
        ],
    )
    def test_completions(self, monkeypatch, args, expected):
        from cecli.commands.sessions_helpers import common

        monkeypatch.setattr(common, "session_names", lambda coder, io: ["alpha", "beta"])

        assert SessionsCommand.get_completions(None, None, args) == expected


class TestRegistration:
    def test_dispatchers_registered_and_legacy_names_removed(self):
        assert CommandRegistry.get_command("hooks") is HooksCommand
        assert CommandRegistry.get_command("sessions") is SessionsCommand

        for legacy in (
            "load-hook",
            "remove-hook",
            "list-sessions",
            "load-session",
            "save-session",
        ):
            assert CommandRegistry.get_command(legacy) is None


class TestFullArgsRegistration:
    def test_dispatchers_register_for_full_args_completion(self):
        from cecli.commands.core import Commands

        assert "/sessions" in Commands.FULL_ARGS_COMPLETION_COMMANDS
        assert "/hooks" in Commands.FULL_ARGS_COMPLETION_COMMANDS
        assert "/queue" in Commands.FULL_ARGS_COMPLETION_COMMANDS
        assert "/insert-queue" not in Commands.FULL_ARGS_COMPLETION_COMMANDS
        assert "/list-queue" not in Commands.FULL_ARGS_COMPLETION_COMMANDS
