"""Workflow discovery, loading and validation.

Structural analogue of :mod:`cecli.helpers.workspaces.config`, but a workflow
source may define *many* workflows, so everything here resolves to a list of
:class:`~cecli.helpers.workflows.models.WorkflowConfig` (design §7).

Resolution order, highest precedence first:

1. ``config_arg`` — an inline JSON/YAML string, or a path to a workflows file.
   ``None``, ``''``, ``'{}'``, ``'[]'`` and ``'null'`` count as *absent* so that
   lower-precedence sources still load.
2. ``<git_root or cwd>/.cecli.workflows.yml`` / ``.cecli.workflows.yaml``.
3. ``<git_root or cwd>/.cecli/workflows/*.yml`` / ``*.yaml`` — globbed in stable sorted order.
4. ``<git_root or cwd>/.agents/workflows/*.yml`` / ``*.yaml`` — globbed in stable sorted order.
5. ``merged_config["workflows"]`` — the deep-merged ``.cecli.conf.yml`` value.
6. ``~/.cecli/workflows/*.yml`` / ``*.yaml`` — globbed in stable sorted order.
7. ``~/.agents/workflows/*.yml`` / ``*.yaml`` — globbed in stable sorted order.

Each source may hold a single workflow mapping or a ``workflows: [...]`` list.
On a duplicate ``name`` the higher-precedence definition wins and the loser is
skipped with a warning naming its file (mirroring skills' first-dir-wins). A
source that fails to parse is skipped with a warning so the rest still load: a
malformed workflows file must never crash startup.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from cecli.decoding import safe_open

from .models import ON_FAILURE_MODES, WORKFLOW_NAME_RE, TaskConfig, WorkflowConfig

logger = logging.getLogger(__name__)

WORKFLOW_FILENAMES = (".cecli.workflows.yml", ".cecli.workflows.yaml")

WORKFLOW_DIR = Path(".cecli") / "workflows"

AGENTS_WORKFLOW_DIR = Path(".agents") / "workflows"

# Values argparse/deep-merge normalization leaves behind when nothing was set.
_ABSENT_STRINGS = ("", "{}", "[]", "null", "~")

_INTERVAL_RE = re.compile(r"^@every\s+(\d+)([smhdw])\s*$", re.IGNORECASE)

_KNOWN_KEYS = frozenset(f.name for f in fields(WorkflowConfig))
_KNOWN_TASK_KEYS = frozenset(f.name for f in fields(TaskConfig))

# (raw mapping, file path or None, human-readable source label)
_Discovered = Tuple[Dict[str, Any], Optional[str], str]

_INLINE_LABEL = "inline --workflows value"
_CONFIG_LABEL = ".cecli.conf.yml 'workflows' key"


def load_workflows(
    config_arg: Optional[str] = None,
    merged_config: Optional[Dict[str, Any]] = None,
    git_root: Optional[Any] = None,
) -> List[WorkflowConfig]:
    """Load every workflow definition visible to this session.

    Never raises for a bad *file* or a bad *single definition*: those are
    skipped with a warning so the remaining workflows still load.
    """
    configs: List[WorkflowConfig] = []

    for raw, path, label in resolve_workflow_configs(config_arg, merged_config, git_root):
        wf = _build(raw, path, label)
        if wf is not None:
            configs.append(wf)

    logger.debug("loaded %d workflow(s): %s", len(configs), [wf.name for wf in configs])
    return configs


def resolve_workflow_configs(
    config_arg: Optional[str] = None,
    merged_config: Optional[Dict[str, Any]] = None,
    git_root: Optional[Any] = None,
) -> List[_Discovered]:
    """Return ``(raw mapping, source path, source label)`` in precedence order.

    Duplicates are already resolved: the first (highest-precedence) definition of
    a given ``name`` wins and every loser is logged and dropped here.
    """
    ordered: List[_Discovered] = []

    if config_arg and str(config_arg).strip() not in _ABSENT_STRINGS:
        ordered += _entries_from_arg(str(config_arg))

    ordered += _entries_from_local(git_root)
    ordered += _entries_from_local_dir(git_root)
    ordered += _entries_from_local_agents_dir(git_root)

    if isinstance(merged_config, dict):
        ordered += _entries(merged_config.get("workflows"), None, _CONFIG_LABEL)

    ordered += _entries_from_home()
    ordered += _entries_from_home_agents()

    return _dedupe(ordered)


def validate_workflow_config(wf: WorkflowConfig, raw: Optional[Dict[str, Any]] = None) -> List[str]:
    """Validate a workflow definition (design §1).

    Hard errors raise :class:`ValueError` carrying the source file and the
    offending key; soft issues come back as warning strings for the caller to
    log. ``raw`` is the pre-``from_dict`` mapping: without it two checks are
    impossible, because ``from_dict`` happily turns ``tasks: "oops"`` or
    ``skills: "gitlab"`` into a list of bogus entries.
    """
    from cecli.helpers.config_utils import _normalize_keys

    where = f"workflow '{wf.name or '?'}' ({_display(wf.source_path)})"
    norm = _normalize_keys(dict(raw)) if isinstance(raw, dict) else {}
    raw_tasks = norm.get("tasks")
    warnings: List[str] = []

    if not wf.name:
        raise ValueError(f"{where}: missing required 'name'")
    if ":" in wf.name or not WORKFLOW_NAME_RE.match(wf.name):
        raise ValueError(
            f"{where}: 'name' must match {WORKFLOW_NAME_RE.pattern} (no ':'), got {wf.name!r}"
        )

    if raw_tasks is not None and not isinstance(raw_tasks, (list, tuple)):
        raise ValueError(f"{where}: 'tasks' must be a list of task mappings")
    if not wf.tasks:
        raise ValueError(f"{where}: 'tasks' must contain at least one task")
    for index, task in enumerate(wf.tasks):
        warnings += _validate_task(task, index, where, norm_tasks=norm.get("tasks"))

    for key in ("skills", "servers"):
        value = getattr(wf, key)
        if norm.get(key) is not None and isinstance(norm[key], str):
            raise ValueError(f"{where}: '{key}' must be a list of strings")
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{where}: '{key}' must be a list of strings")
    if wf.servers != [s.lower() for s in wf.servers]:
        wf.servers = [s.lower() for s in wf.servers]

    if wf.on_failure not in ON_FAILURE_MODES:
        raise ValueError(
            f"{where}: 'on_failure' must be one of {ON_FAILURE_MODES}, got {wf.on_failure!r}"
        )

    if norm.get("hooks") is not None and not isinstance(norm["hooks"], dict):
        warnings.append("'hooks' is not a mapping and was ignored")

    wf.lease_timeout = _positive_number(wf.lease_timeout, "lease_timeout", where, default=30.0)
    _check_schedule(wf.schedule, where)

    if wf.timezone and wf.timezone != "local":
        from cecli.helpers.scheduler.cron import resolve_timezone

        try:
            resolve_timezone(wf.timezone)
        except ValueError:
            warnings.append(f"unknown 'timezone' {wf.timezone!r}; scheduling falls back to UTC")

    warnings += _unknown_key_warnings(norm, where)

    return warnings


def _build(raw: Dict[str, Any], path: Optional[str], label: str) -> Optional[WorkflowConfig]:
    """Turn one raw mapping into a validated config, or None with a warning."""
    try:
        wf = WorkflowConfig.from_dict(raw, path)
    except (TypeError, ValueError) as exc:
        logger.warning("skipping workflow in %s: %s", _display(path, label), exc)
        return None

    try:
        warnings = validate_workflow_config(wf, raw)
    except ValueError as exc:
        logger.warning("skipping workflow: %s", exc)
        return None

    for warning in warnings:
        logger.warning("%s: %s", _display(wf.source_path), warning)

    return wf


def _validate_task(task: TaskConfig, index: int, where: str, norm_tasks: Any = None) -> List[str]:
    """Validate one task entry; raise on hard errors, return warnings."""
    label = f"{where} tasks[{index}]"

    if not str(task.prompt or "").strip():
        raise ValueError(f"{label}: 'prompt' must be a non-empty string")
    task.timeout = _positive_number(task.timeout, "timeout", label)

    warnings: List[str] = []
    if isinstance(norm_tasks, (list, tuple)) and index < len(norm_tasks):
        entry = norm_tasks[index]
        if isinstance(entry, dict):
            unknown = sorted(set(entry) - _KNOWN_TASK_KEYS)
            if unknown:
                warnings.append(f"tasks[{index}] unknown key(s) ignored: {', '.join(unknown)}")
            if entry.get("name") is not None and not str(entry["name"]).strip():
                warnings.append(f"tasks[{index}] 'name' is empty and was ignored")

    if task.continue_on_error is not None and not isinstance(task.continue_on_error, bool):
        warnings.append(f"tasks[{index}] 'continue_on_error' is not a boolean")

    return warnings


def _positive_number(
    value: Any, key: str, where: str, default: Optional[float] = None
) -> Optional[float]:
    """Coerce an optional duration/timeout to a positive float."""
    if value is None or value == "":
        return default

    if isinstance(value, bool):
        raise ValueError(f"{where}: '{key}' must be a positive number, got {value!r}")

    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: '{key}' must be a positive number, got {value!r}")

    if number <= 0:
        raise ValueError(f"{where}: '{key}' must be a positive number, got {value!r}")

    return number


def _check_schedule(schedule: Any, where: str) -> None:
    """Shape-check a schedule string without importing the scheduler (no cycle)."""
    if schedule is None or str(schedule).strip() == "":
        return
    if not isinstance(schedule, str):
        raise ValueError(f"{where}: 'schedule' must be a string, got {schedule!r}")

    text = schedule.strip()

    # '@every 15m' style intervals are not expressible as 5-field cron, so
    # croniter rejects them — validate the shape here instead.
    interval = _INTERVAL_RE.match(text)
    if interval:
        if int(interval.group(1)) <= 0:
            raise ValueError(f"{where}: 'schedule' {schedule!r} must be a positive interval")
        return

    try:
        from croniter import croniter
    except ImportError:
        return

    if not croniter.is_valid(text):
        raise ValueError(
            f"{where}: 'schedule' {schedule!r} is not a valid cron expression, "
            f"@preset or '@every <N><smhdw>' interval"
        )


def _unknown_key_warnings(norm: Dict[str, Any], where: str) -> List[str]:
    """List top-level keys ``from_dict`` silently discarded."""
    unknown = sorted(set(norm) - _KNOWN_KEYS)
    if not unknown:
        return []

    return [f"unknown key(s) ignored: {', '.join(unknown)}"]


def _entries_from_arg(config_arg: str) -> List[_Discovered]:
    """Resolve an inline string (or a path to a workflows file)."""
    candidate = Path(config_arg).expanduser()
    if candidate.is_file():
        return _entries(_load_yaml_file(candidate), str(candidate), str(candidate))

    return _entries(_parse_workflow_string(config_arg), None, _INLINE_LABEL)


def _entries_from_local(git_root: Optional[Any]) -> List[_Discovered]:
    """Resolve a repo-local ``.cecli.workflows.yml`` if one exists."""
    base = Path(git_root).expanduser() if git_root else Path.cwd()

    for name in WORKFLOW_FILENAMES:
        path = base / name
        if path.is_file():
            return _entries(_load_yaml_file(path), str(path), str(path))

    return []


def _entries_from_local_dir(git_root: Optional[Any]) -> List[_Discovered]:
    """Resolve a repo-local ``.cecli/workflows/*.yml|*.yaml`` directory."""
    base = Path(git_root).expanduser() if git_root else Path.cwd()

    return _entries_from_dir(base / WORKFLOW_DIR)


def _entries_from_local_agents_dir(git_root: Optional[Any]) -> List[_Discovered]:
    """Resolve a repo-local ``.agents/workflows/*.yml|*.yaml`` directory."""
    base = Path(git_root).expanduser() if git_root else Path.cwd()

    return _entries_from_dir(base / AGENTS_WORKFLOW_DIR)


def _entries_from_home() -> List[_Discovered]:
    """Resolve ``~/.cecli/workflows/*.yml|*.yaml`` in stable sorted order."""

    return _entries_from_dir(Path.home() / WORKFLOW_DIR)


def _entries_from_home_agents() -> List[_Discovered]:
    """Resolve ``~/.agents/workflows/*.yml|*.yaml`` in stable sorted order."""

    return _entries_from_dir(Path.home() / AGENTS_WORKFLOW_DIR)


def _entries_from_dir(root: Path) -> List[_Discovered]:
    """Resolve ``*.yml`` / ``*.yaml`` files under *root* in stable sorted order."""
    if not root.is_dir():
        return []

    ordered: List[_Discovered] = []
    for path in sorted(p for p in root.iterdir() if p.suffix in (".yml", ".yaml") and p.is_file()):
        ordered += _entries(_load_yaml_file(path), str(path), str(path))

    return ordered


def _entries(loaded: Any, path: Optional[str], label: str) -> List[_Discovered]:
    """Flatten one parsed source into ``(mapping, path, label)`` tuples."""
    if loaded is None:
        return []

    if isinstance(loaded, dict):
        inner = loaded.get("workflows")
        if inner is not None:
            return _entries(inner, path, label)
        return [(loaded, path, label)]

    if isinstance(loaded, (list, tuple)):
        entries = []
        for item in loaded:
            if isinstance(item, dict):
                entries.append((item, path, label))
            else:
                logger.warning("ignoring non-mapping workflow entry %r in %s", item, label)
        return entries

    logger.warning("ignoring workflows source %s: expected a mapping or list", label)
    return []


def _dedupe(ordered: List[_Discovered]) -> List[_Discovered]:
    """Keep the first (highest-precedence) definition of each workflow name."""
    seen: Dict[str, _Discovered] = {}
    kept: List[_Discovered] = []

    for item in ordered:
        name = str(item[0].get("name") or "").strip()
        if not name:
            kept.append(item)
            continue

        if name in seen:
            winner = seen[name]
            logger.warning(
                "skipping duplicate workflow '%s' from %s: definition in %s takes precedence",
                name,
                _display(item[1], item[2]),
                _display(winner[1], winner[2]),
            )
            continue

        seen[name] = item
        kept.append(item)

    return kept


def _load_yaml_file(path: Path) -> Optional[Any]:
    """Parse a YAML/JSON workflows file, warning and returning None if unreadable."""
    try:
        with safe_open(path, "r") as f:
            return yaml.safe_load(f)
    except Exception as exc:
        logger.warning("skipping unreadable workflows file %s: %s", path, exc)
        return None


def _parse_workflow_string(config_arg: str) -> Optional[Any]:
    """Parse an inline workflows value as JSON first, then YAML."""
    try:
        return json.loads(config_arg)
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        return yaml.safe_load(config_arg)
    except yaml.YAMLError as exc:
        logger.warning("could not parse workflows value %r: %s", config_arg[:80], exc)
        return None


def _display(path: Optional[str], label: str = "") -> str:
    """Human-readable origin for messages: the file if we have one, else a label."""
    return path or label or "inline config"
