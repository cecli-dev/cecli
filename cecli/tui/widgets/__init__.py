"""Widgets for the cecli TUI."""

from .background_commands_panel import BackgroundCommandsPanel
from .completion_bar import CompletionBar
from .file_list import FileList
from .floating_panels import FloatingPanels
from .footer import MainFooter
from .input_area import InputArea
from .input_container import InputContainer
from .key_hints import KeyHints
from .output import OutputContainer
from .status_bar import StatusBar
from .subagent_pills import SubAgentPills

__all__ = [
    "BackgroundCommandsPanel",
    "MainFooter",
    "CompletionBar",
    "InputArea",
    "InputContainer",
    "KeyHints",
    "OutputContainer",
    "StatusBar",
    "FileList",
    "FloatingPanels",
    "SubAgentPills",
]
