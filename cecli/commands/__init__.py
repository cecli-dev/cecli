"""
Command system for cecli.

This package contains individual command implementations that follow the
BaseCommand pattern for modular, testable command execution.
"""

from cecli.signals import ReloadProgramSignal, SwitchCoderSignal

from .add import AddCommand
from .agent import AgentCommand
from .agent_model import AgentModelCommand
from .agent_tree import AgentTreeCommand
from .architect import ArchitectCommand
from .ask import AskCommand
from .auto_memory import AutoMemoryCommand
from .clear import ClearCommand
from .code import CodeCommand
from .command_prefix import CommandPrefixCommand
from .commit import CommitCommand
from .compact import CompactCommand
from .context import ContextCommand
from .context_blocks import ContextBlocksCommand
from .context_management import ContextManagementCommand
from .copy import CopyCommand
from .copy_context import CopyContextCommand
from .core import Commands
from .creator import CreatorCommand
from .diff import DiffCommand
from .drop import DropCommand
from .editor import EditCommand, EditorCommand
from .editor_model import EditorModelCommand
from .exit import ExitCommand
from .git import GitCommand
from .hashline import HashlineCommand
from .help import HelpCommand
from .history_search import HistorySearchCommand
from .hooks import HooksCommand
from .hot_reload import HotReloadCommand
from .lint import LintCommand
from .load import LoadCommand
from .ls import LsCommand
from .map import MapCommand
from .map_refresh import MapRefreshCommand
from .mcp import McpCommand
from .merge import MergeCommand
from .model import ModelCommand
from .models import ModelsCommand
from .multiline_mode import MultilineModeCommand
from .paste import PasteCommand
from .queue import QueueCommand
from .quit import QuitCommand
from .read_only import ReadOnlyCommand
from .read_only_stub import ReadOnlyStubCommand
from .reap_agent import ReapAgentCommand
from .reasoning_effort import ReasoningEffortCommand
from .remove_memory import RemoveMemoryCommand
from .report import ReportCommand
from .reset import ResetCommand
from .rules import RulesCommand
from .run import RunCommand
from .save import SaveCommand
from .search_memory import SearchMemoryCommand
from .sessions import SessionsCommand
from .settings import SettingsCommand
from .skills import SkillsCommand
from .spawn_agent import SpawnAgentCommand
from .switch_agent import SwitchAgentCommand
from .terminal_setup import TerminalSetupCommand
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
from .workflows import WorkflowCommand
from .workspace import WorkspaceCommand

# Register commands
CommandRegistry.register(AddCommand)
CommandRegistry.register(AgentCommand)
CommandRegistry.register(AgentModelCommand)
CommandRegistry.register(AgentTreeCommand)
CommandRegistry.register(ArchitectCommand)
CommandRegistry.register(AskCommand)
CommandRegistry.register(AutoMemoryCommand)
CommandRegistry.register(ClearCommand)
CommandRegistry.register(CodeCommand)
CommandRegistry.register(CommandPrefixCommand)
CommandRegistry.register(CommitCommand)
CommandRegistry.register(CompactCommand)
CommandRegistry.register(ContextBlocksCommand)
CommandRegistry.register(ContextCommand)
CommandRegistry.register(ContextManagementCommand)
CommandRegistry.register(CopyCommand)
CommandRegistry.register(CopyContextCommand)
CommandRegistry.register(CreatorCommand)
CommandRegistry.register(DiffCommand)
CommandRegistry.register(DropCommand)
CommandRegistry.register(EditCommand)
CommandRegistry.register(EditorCommand)
CommandRegistry.register(EditorModelCommand)
CommandRegistry.register(ExitCommand)
CommandRegistry.register(GitCommand)
CommandRegistry.register(HashlineCommand)
CommandRegistry.register(HelpCommand)
CommandRegistry.register(HistorySearchCommand)
CommandRegistry.register(HooksCommand)
CommandRegistry.register(HotReloadCommand)
CommandRegistry.register(LintCommand)
CommandRegistry.register(LoadCommand)
CommandRegistry.register(LsCommand)
CommandRegistry.register(MapCommand)
CommandRegistry.register(MapRefreshCommand)
CommandRegistry.register(McpCommand)
CommandRegistry.register(MergeCommand)
CommandRegistry.register(ModelCommand)
CommandRegistry.register(ModelsCommand)
CommandRegistry.register(MultilineModeCommand)
CommandRegistry.register(PasteCommand)
CommandRegistry.register(QueueCommand)
CommandRegistry.register(QuitCommand)
CommandRegistry.register(ReadOnlyCommand)
CommandRegistry.register(ReadOnlyStubCommand)
CommandRegistry.register(ReapAgentCommand)
CommandRegistry.register(ReasoningEffortCommand)
CommandRegistry.register(RemoveMemoryCommand)
CommandRegistry.register(ReportCommand)
CommandRegistry.register(ResetCommand)
CommandRegistry.register(RulesCommand)
CommandRegistry.register(RunCommand)
CommandRegistry.register(SaveCommand)
CommandRegistry.register(SearchMemoryCommand)
CommandRegistry.register(SessionsCommand)
CommandRegistry.register(SettingsCommand)
CommandRegistry.register(SkillsCommand)
CommandRegistry.register(SpawnAgentCommand)
CommandRegistry.register(SwitchAgentCommand)
CommandRegistry.register(TerminalSetupCommand)
CommandRegistry.register(TestCommand)
CommandRegistry.register(ThinkTokensCommand)
CommandRegistry.register(TokensCommand)
CommandRegistry.register(UndoCommand)
CommandRegistry.register(VoiceCommand)
CommandRegistry.register(WeakModelCommand)
CommandRegistry.register(WebCommand)
CommandRegistry.register(WorkflowCommand)
CommandRegistry.register(WorkspaceCommand)


__all__ = [
    "AddCommand",
    "AgentCommand",
    "AgentModelCommand",
    "AgentTreeCommand",
    "ArchitectCommand",
    "AskCommand",
    "AutoMemoryCommand",
    "BaseCommand",
    "ClearCommand",
    "CodeCommand",
    "CommandError",
    "CommandPrefixCommand",
    "CommandRegistry",
    "Commands",
    "CommitCommand",
    "CompactCommand",
    "ContextBlocksCommand",
    "ContextCommand",
    "ContextManagementCommand",
    "CopyCommand",
    "CopyContextCommand",
    "CreatorCommand",
    "DiffCommand",
    "DropCommand",
    "EditCommand",
    "EditorCommand",
    "EditorModelCommand",
    "ExitCommand",
    "expand_subdir",
    "format_command_result",
    "get_available_files",
    "GitCommand",
    "glob_filtered_to_repo",
    "HashlineCommand",
    "HelpCommand",
    "HistorySearchCommand",
    "HooksCommand",
    "HotReloadCommand",
    "LintCommand",
    "LoadCommand",
    "LsCommand",
    "MapCommand",
    "MapRefreshCommand",
    "McpCommand",
    "MergeCommand",
    "ModelCommand",
    "ModelsCommand",
    "MultilineModeCommand",
    "parse_quoted_filenames",
    "PasteCommand",
    "QueueCommand",
    "QuitCommand",
    "quote_filename",
    "ReadOnlyCommand",
    "ReadOnlyStubCommand",
    "ReapAgentCommand",
    "ReasoningEffortCommand",
    "ReloadProgramSignal",
    "RemoveMemoryCommand",
    "ReportCommand",
    "ResetCommand",
    "RulesCommand",
    "RunCommand",
    "SaveCommand",
    "SearchMemoryCommand",
    "SessionsCommand",
    "SettingsCommand",
    "SkillsCommand",
    "SpawnAgentCommand",
    "SwitchAgentCommand",
    "SwitchCoderSignal",
    "TerminalSetupCommand",
    "TestCommand",
    "ThinkTokensCommand",
    "TokensCommand",
    "UndoCommand",
    "validate_file_access",
    "VoiceCommand",
    "WeakModelCommand",
    "WebCommand",
    "WorkflowCommand",
    "WorkspaceCommand",
]
