"""
Orchestration module for programmatic tool calling in agent mode.

Public API:
- AgentExecutionEnv: sandboxed execution environment
- AgentProxy / ToolProxy: proxies for calling tools from generated code
- build_orchestration_context_block: context block builder
- SecurityError / SecurityFilter / LoopYieldInjector: security components
"""

from cecli.helpers.orchestration.environment import (
    AgentExecutionEnv,
    AgentProxy,
    ToolProxy,
    build_orchestration_context_block,
)
from cecli.helpers.orchestration.security import (
    LoopYieldInjector,
    SecurityError,
    SecurityFilter,
    _cooperative_yield,
)
from cecli.helpers.orchestration.service import OrchestrationService

__all__ = [
    "AgentExecutionEnv",
    "AgentProxy",
    "ToolProxy",
    "build_orchestration_context_block",
    "SecurityError",
    "SecurityFilter",
    "LoopYieldInjector",
    "_cooperative_yield",
    "OrchestrationService",
]
