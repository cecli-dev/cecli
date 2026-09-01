"""Workspace configuration loading and validation (local, path-based).

Workspaces are defined by a local ``.cecli.workspaces.yml`` file listing
existing git roots via ``path:`` entries. There is no ``repo:``/clone mode:
every project must point at an on-disk git root.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from cecli.decoding import safe_open

WORKSPACE_FILENAMES = (".cecli.workspaces.yml", ".cecli.workspaces.yaml")


def resolve_workspace_config(config_arg: Optional[str] = None) -> Optional[Any]:
    """Resolve the raw workspace config from the same hierarchy as before:

    1. ``config_arg`` (JSON/YAML string or path to a file)
    2. Local ``.cecli.workspaces.yml`` / ``.cecli.workspaces.yaml``
    3. Global ``~/.cecli/workspaces.yml`` / ``.cecli/workspaces.yaml``
    """
    workspace_conf = None

    if config_arg:
        candidate = Path(config_arg).expanduser()
        if candidate.is_file():
            workspace_conf = _load_yaml_file(candidate)
        else:
            workspace_conf = _parse_workspace_string(config_arg)

    if not workspace_conf:
        for name in WORKSPACE_FILENAMES:
            local_path = Path(name)
            if local_path.is_file():
                workspace_conf = _load_yaml_file(local_path)
                if workspace_conf:
                    break

    if not workspace_conf:
        for name in ("workspaces.yml", "workspaces.yaml"):
            global_path = Path.home() / ".cecli" / name
            if global_path.is_file():
                workspace_conf = _load_yaml_file(global_path)
                if workspace_conf:
                    break

    return workspace_conf


def _load_yaml_file(path: Path) -> Optional[Any]:
    try:
        with safe_open(path, "r") as f:
            loaded = yaml.safe_load(f)
    except Exception:
        return None
    if not loaded:
        return None
    if isinstance(loaded, dict):
        return loaded.get("workspaces") or loaded.get("workspace") or loaded
    return loaded


def _parse_workspace_string(config_arg: str) -> Optional[Any]:
    try:
        loaded = json.loads(config_arg)
    except (json.JSONDecodeError, TypeError):
        try:
            loaded = yaml.safe_load(config_arg)
        except yaml.YAMLError:
            return None
    if isinstance(loaded, dict):
        return loaded.get("workspaces") or loaded.get("workspace") or loaded
    return loaded


def load_workspace_config_file(path: Path) -> Dict[str, Any]:
    """Load and validate a repo-local ``.cecli.workspaces.yml`` file."""
    from .paths import load_workspace_file

    config = load_workspace_file(path)
    validate_config(config)
    return config


def load_workspace_config(
    config_arg: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Load workspace config from the hierarchy, optionally selecting by name."""
    workspace_conf = resolve_workspace_config(config_arg)

    config: Dict[str, Any] = {}
    if isinstance(workspace_conf, list):
        if name:
            selected = next((ws for ws in workspace_conf if ws.get("name") == name), None)
            if not selected:
                raise ValueError(f"Workspace '{name}' not found in configuration")
            config = selected
        else:
            active = [ws for ws in workspace_conf if ws.get("active")]
            if len(active) > 1:
                names = [ws.get("name", "unknown") for ws in active]
                raise ValueError(f"Multiple workspaces marked as active: {', '.join(names)}")
            active_ws = active[0] if active else None
            if not active_ws and len(workspace_conf) == 1:
                active_ws = workspace_conf[0]
            config = active_ws if active_ws else {}
    elif isinstance(workspace_conf, dict):
        config = workspace_conf

    validate_config(config)
    return config


def validate_config(config: Dict[str, Any]) -> None:
    """Validate a workspace config.

    Each project must have a ``name`` and **exactly one** of ``path`` (local
    git root) or ``repo`` (clone URL). At most one project may set
    ``primary: true``.
    """
    if not config:
        return

    if "name" not in config:
        raise ValueError("Workspace configuration must include a 'name'")

    if "projects" not in config:
        config["projects"] = []

    project_names = set()
    primary_count = 0
    for project in config["projects"]:
        if "name" not in project:
            raise ValueError("Each project must have a 'name'")
        has_path = bool(project.get("path"))
        has_repo = bool(project.get("repo"))
        if not (has_path or has_repo):
            raise ValueError(
                f"Project '{project['name']}' must have exactly one of 'path' or 'repo'"
            )
        if has_path and has_repo:
            raise ValueError(
                f"Project '{project['name']}' must have exactly one of 'path' or 'repo'"
            )
        if project.get("primary"):
            primary_count += 1
        if project["name"] in project_names:
            raise ValueError(f"Duplicate project name: {project['name']}")
        project_names.add(project["name"])

    if primary_count > 1:
        raise ValueError("Only one project may be marked primary: true")


def workspace_layout(config: Dict[str, Any]) -> str:
    """Return the workspace layout: ``clone`` if any project uses ``repo``, else ``local``.

    An explicit ``layout`` field on the workspace overrides the inference.
    """
    explicit = config.get("layout")
    if explicit in ("clone", "local"):
        return explicit
    for proj in config.get("projects") or []:
        if proj.get("repo"):
            return "clone"
    return "local"


def find_active_workspace_name(config_arg: Optional[str] = None) -> Optional[str]:
    """Return the active workspace name without fully resolving it."""
    workspace_conf = resolve_workspace_config(config_arg)

    if isinstance(workspace_conf, list):
        active = next((ws for ws in workspace_conf if ws.get("active")), None)
        if active:
            return active.get("name")
        if len(workspace_conf) == 1:
            return workspace_conf[0].get("name")
    elif isinstance(workspace_conf, dict):
        return workspace_conf.get("name")

    return None
