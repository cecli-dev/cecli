"""
Command system for cecli.

This package contains individual command implementations that follow the
BaseCommand pattern for modular, testable command execution.
"""

from .add import AddCommand
from .agent import AgentCommand
from .architect import ArchitectCommand
from .ask import AskCommand
from .clear import ClearCommand
from .code import CodeCommand
from .command_prefix import CommandPrefixCommand
from .commit import CommitCommand
from .context import ContextCommand
from .context_blocks import ContextBlocksCommand
from .context_management import ContextManagementCommand
from .copy import CopyCommand
from .copy_context import CopyContextCommand
from .core import Commands, SwitchCoderSignal
from .diff import DiffCommand

# Import and register commands
from .drop import DropCommand
from .editor import EditCommand, EditorCommand
from .exit import ExitCommand
from .git import GitCommand
from .help import HelpCommand
from .history_search import HistorySearchCommand
from .lint import LintCommand
from .list_sessions import ListSessionsCommand
from .load import LoadCommand
from .load_session import LoadSessionCommand
from .load_skill import LoadSkillCommand
from .ls import LsCommand
from .map import MapCommand
from .map_refresh import MapRefreshCommand
from .model import ModelCommand
from .models import ModelsCommand
from .multiline_mode import MultilineModeCommand
from .paste import PasteCommand
from .quit import QuitCommand
from .read_only import ReadOnlyCommand
from .read_only_stub import ReadOnlyStubCommand
from .reasoning_effort import ReasoningEffortCommand
from .remove_skill import RemoveSkillCommand
from .report import ReportCommand
from .reset import ResetCommand
from .run import RunCommand
from .save import SaveCommand
from .save_session import SaveSessionCommand
from .settings import SettingsCommand
from .test import TestCommand
from .think_tokens import ThinkTokensCommand
from .tokens import TokensCommand
from .undo import UndoCommand
from .utils.base_command import BaseCommand
from .utils.helpers import (
    CommandError,
    expand_subdir,
    format_command_result,
    get_available_files,
    glob_filtered_to_repo,
    parse_quoted_filenames,
    quote_filename,
    validate_file_access,
)
from .utils.registry import CommandRegistry
from .voice import VoiceCommand
from .weak_model import WeakModelCommand
from .web import WebCommand

# Register commands
CommandRegistry.register(DropCommand)
CommandRegistry.register(ClearCommand)
CommandRegistry.register(LsCommand)
CommandRegistry.register(DiffCommand)
CommandRegistry.register(ResetCommand)
CommandRegistry.register(CopyCommand)
CommandRegistry.register(PasteCommand)
CommandRegistry.register(SettingsCommand)
CommandRegistry.register(ReportCommand)
CommandRegistry.register(TokensCommand)
CommandRegistry.register(UndoCommand)
CommandRegistry.register(GitCommand)
CommandRegistry.register(RunCommand)
CommandRegistry.register(HelpCommand)
CommandRegistry.register(CommitCommand)
CommandRegistry.register(ModelsCommand)
CommandRegistry.register(ExitCommand)
CommandRegistry.register(QuitCommand)
CommandRegistry.register(VoiceCommand)
CommandRegistry.register(MapCommand)
CommandRegistry.register(MapRefreshCommand)
CommandRegistry.register(MultilineModeCommand)
CommandRegistry.register(EditorCommand)
CommandRegistry.register(EditCommand)
CommandRegistry.register(HistorySearchCommand)
CommandRegistry.register(ThinkTokensCommand)
CommandRegistry.register(LoadCommand)
CommandRegistry.register(SaveCommand)
CommandRegistry.register(ReasoningEffortCommand)
CommandRegistry.register(SaveSessionCommand)
CommandRegistry.register(ListSessionsCommand)
CommandRegistry.register(LoadSessionCommand)
CommandRegistry.register(ReadOnlyCommand)
CommandRegistry.register(ReadOnlyStubCommand)
CommandRegistry.register(AddCommand)
CommandRegistry.register(ModelCommand)
CommandRegistry.register(WeakModelCommand)
CommandRegistry.register(WebCommand)
CommandRegistry.register(LintCommand)
CommandRegistry.register(TestCommand)
CommandRegistry.register(ContextManagementCommand)
CommandRegistry.register(ContextBlocksCommand)
CommandRegistry.register(AskCommand)
CommandRegistry.register(CodeCommand)
CommandRegistry.register(ArchitectCommand)
CommandRegistry.register(ContextCommand)
CommandRegistry.register(AgentCommand)
CommandRegistry.register(CopyContextCommand)
CommandRegistry.register(CommandPrefixCommand)
CommandRegistry.register(LoadSkillCommand)
CommandRegistry.register(RemoveSkillCommand)


__all__ = [
    "BaseCommand",
    "CommandRegistry",
    "CommandError",
    "quote_filename",
    "parse_quoted_filenames",
    "glob_filtered_to_repo",
    "validate_file_access",
    "format_command_result",
    "get_available_files",
    "expand_subdir",
    "DropCommand",
    "ClearCommand",
    "LsCommand",
    "DiffCommand",
    "ResetCommand",
    "CopyCommand",
    "PasteCommand",
    "SettingsCommand",
    "ReportCommand",
    "TokensCommand",
    "UndoCommand",
    "GitCommand",
    "RunCommand",
    "HelpCommand",
    "CommitCommand",
    "ModelsCommand",
    "ExitCommand",
    "QuitCommand",
    "VoiceCommand",
    "MapCommand",
    "MapRefreshCommand",
    "MultilineModeCommand",
    "EditorCommand",
    "EditCommand",
    "HistorySearchCommand",
    "ThinkTokensCommand",
    "LoadCommand",
    "SaveCommand",
    "ReasoningEffortCommand",
    "SaveSessionCommand",
    "ListSessionsCommand",
    "LoadSessionCommand",
    "ReadOnlyCommand",
    "ReadOnlyStubCommand",
    "AddCommand",
    "ModelCommand",
    "WeakModelCommand",
    "WebCommand",
    "LintCommand",
    "TestCommand",
    "ContextManagementCommand",
    "ContextBlocksCommand",
    "AskCommand",
    "CodeCommand",
    "ArchitectCommand",
    "ContextCommand",
    "AgentCommand",
    "CopyContextCommand",
    "CommandPrefixCommand",
    "LoadSkillCommand",
    "RemoveSkillCommand",
    "SwitchCoderSignal",
    "Commands",
]
