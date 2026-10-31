"""Data models for declarative workflows.

A workflow is a named, optionally-scheduled sequence of prompts executed
unattended on a dedicated ``wf:{name}`` worker sub-agent. Definitions live in
YAML; these dataclasses are the in-memory form produced by
:mod:`cecli.helpers.workflows.config`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

ON_FAILURE_MODES = ("continue", "stop")


@dataclass
class TaskConfig:
    """One prompt in a workflow's ordered task list."""

    prompt: str
    name: Optional[str] = None
    timeout: Optional[float] = None  # minutes
    continue_on_error: Optional[bool] = None
    save_to: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"prompt": self.prompt}
        if self.name is not None:
            data["name"] = self.name
        if self.timeout is not None:
            data["timeout"] = self.timeout
        if self.continue_on_error is not None:
            data["continue_on_error"] = self.continue_on_error
        if self.save_to is not None:
            data["save_to"] = self.save_to
        return data


@dataclass
class WorkflowConfig:
    """Resolved definition of a single workflow."""

    name: str
    tasks: List[TaskConfig]
    description: str = ""
    schedule: Optional[str] = None
    enabled: bool = True
    timezone: str = "local"
    lease_timeout: float = 30.0  # minutes
    model: Optional[str] = None
    root: Optional[str] = None
    hooks: Dict[str, Any] = field(default_factory=dict)
    skills: List[str] = field(default_factory=list)
    servers: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    persist: bool = False
    on_failure: str = "stop"
    catch_up: Optional[bool] = None  # None: use the scheduler default
    source_path: Optional[str] = None

    @property
    def agent_name(self) -> str:
        return f"wf:{self.name}"

    def to_dict(self) -> Dict[str, Any]:
        """Canonical dict form used for hashing and ``/workflows show``."""
        return {
            "name": self.name,
            "description": self.description,
            "schedule": self.schedule,
            "enabled": self.enabled,
            "timezone": self.timezone,
            "lease_timeout": self.lease_timeout,
            "model": self.model,
            "root": self.root,
            "hooks": self.hooks,
            "skills": list(self.skills),
            "servers": list(self.servers),
            "metadata": self.metadata,
            "persist": self.persist,
            "on_failure": self.on_failure,
            "catch_up": self.catch_up,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    def definition_hash(self) -> str:
        """sha256 of the normalized definition (key-order independent)."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], source_path: Optional[str] = None) -> "WorkflowConfig":
        """Build a config from a (hyphen- or snake-case) mapping.

        Keys are normalized (``lease-timeout`` -> ``lease_timeout``) and every
        string is passed through ``interpolate_env_vars`` (``${VAR}`` / ``$VAR``
        expansion). Unknown top-level keys are ignored (validated with a warning
        elsewhere).
        """
        from cecli.helpers.config_utils import _normalize_keys
        from cecli.main import interpolate_env_vars

        data = _normalize_keys(dict(raw or {}))

        tasks: List[TaskConfig] = []
        for entry in data.get("tasks") or []:
            if isinstance(entry, str):
                tasks.append(TaskConfig(prompt=_interp(interpolate_env_vars, entry)))
                continue
            task_data = _normalize_keys(dict(entry))
            prompt = task_data.get("prompt")
            if prompt is None:
                raise ValueError(f"workflow task requires a 'prompt' key: {task_data!r}")
            tasks.append(
                TaskConfig(
                    prompt=_interp(interpolate_env_vars, prompt),
                    name=(
                        _interp(interpolate_env_vars, task_data["name"])
                        if task_data.get("name") is not None
                        else None
                    ),
                    timeout=task_data.get("timeout"),
                    continue_on_error=task_data.get("continue_on_error"),
                    save_to=(
                        _interp(interpolate_env_vars, task_data["save_to"])
                        if task_data.get("save_to") is not None
                        else None
                    ),
                )
            )

        hooks = data.get("hooks") or {}
        return cls(
            name=str(data.get("name") or ""),
            tasks=tasks,
            description=_interp(interpolate_env_vars, data.get("description") or ""),
            schedule=(
                _interp(interpolate_env_vars, data["schedule"]) if data.get("schedule") else None
            ),
            enabled=bool(data.get("enabled", True)),
            timezone=_interp(interpolate_env_vars, data.get("timezone") or "local"),
            lease_timeout=float(data.get("lease_timeout", 30.0)),
            model=(
                _interp(interpolate_env_vars, data["model"])
                if data.get("model") is not None
                else None
            ),
            root=(
                _interp(interpolate_env_vars, data["root"])
                if data.get("root") is not None
                else None
            ),
            hooks=hooks if isinstance(hooks, dict) else {},
            skills=[_interp(interpolate_env_vars, s) for s in data.get("skills") or []],
            servers=[_interp(interpolate_env_vars, s) for s in data.get("servers") or []],
            metadata=(dict(data["metadata"]) if isinstance(data.get("metadata"), dict) else {}),
            persist=_as_bool(data.get("persist")),
            on_failure=str(data.get("on_failure") or "stop"),
            catch_up=None if data.get("catch_up") is None else bool(data.get("catch_up")),
            source_path=str(source_path) if source_path else None,
        )


@dataclass
class TaskResult:
    """Outcome of one workflow task within a run."""

    index: int
    label: str = ""
    status: str = "ok"  # ok | error | skipped | aborted
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idx": self.index,
            "label": self.label,
            "status": self.status,
            "message": self.message,
        }


@dataclass
class RunResult:
    """Outcome of one workflow run, consumed by the scheduler and the runner."""

    name: str = ""
    status: str = "ok"  # ok | error | aborted | skipped
    source: str = "manual"  # manual | scheduler | scheduler_daemon
    summary: str = ""
    error_message: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    tasks: List[TaskResult] = field(default_factory=list)
    run_id: Optional[int] = None
    log_path: Optional[str] = None

    @classmethod
    def error(cls, exc: BaseException, name: str = "", source: str = "scheduler") -> "RunResult":
        return cls(
            name=name, status="error", source=source, error_message=str(exc), summary=str(exc)
        )


def _as_bool(value: Any, default: bool = False) -> bool:
    """Coerce a config value to a boolean without treating "false" as truthy."""

    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")

    return bool(value)


def _interp(interpolate_env_vars, value: Any) -> Any:
    """Interpolate a single string value; pass anything else through unchanged."""

    if isinstance(value, str):
        return interpolate_env_vars(value)

    return value
