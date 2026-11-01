"""Declarative workflows: optionally-scheduled prompt sequences on ``wf:`` agents.

A workflow run composes two existing mechanisms: workspace-style ``ws:``
sub-agent registration (generalized to a ``wf:`` prefix) and the CLI-33
per-coder prompt queue. Definitions live in YAML; see
:mod:`cecli.helpers.workflows.config`.

Exports are resolved lazily (PEP 562) so importing this package never drags in
the agents/hooks machinery at module-import time.
"""

from typing import Any

_EXPORTS = {
    "WorkflowConfig": "cecli.helpers.workflows.models",
    "TaskConfig": "cecli.helpers.workflows.models",
    "TaskResult": "cecli.helpers.workflows.models",
    "RunResult": "cecli.helpers.workflows.models",
    "load_workflows": "cecli.helpers.workflows.config",
    "validate_workflow_config": "cecli.helpers.workflows.config",
    "register_workflow_subagents": "cecli.helpers.workflows.subagents",
    "execute_workflow": "cecli.helpers.workflows.runner",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        import importlib

        return getattr(importlib.import_module(_EXPORTS[name]), name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
