import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def resolve_workspace_config(config_arg: Optional[str] = None) -> Optional[Any]:
    """
    Common logic to resolve workspace configuration from hierarchy:
    1. config_arg (JSON string)
    2. Local .cecli.workspaces.yml/yaml
    3. Global ~/.cecli/workspaces.yml/yaml
    4. Fallback to .cecli.conf.yml
    """
    workspace_conf = None

    # 1. Try config_arg (JSON string from main.py)
    if config_arg:
        try:
            loaded = json.loads(config_arg)
            if isinstance(loaded, dict):
                workspace_conf = loaded.get("workspaces") or loaded.get("workspace") or loaded
            elif isinstance(loaded, list):
                workspace_conf = loaded
        except json.JSONDecodeError:
            try:
                loaded = yaml.safe_load(config_arg)
                if isinstance(loaded, dict):
                    workspace_conf = loaded.get("workspaces") or loaded.get("workspace") or loaded
                elif isinstance(loaded, list):
                    workspace_conf = loaded
            except yaml.YAMLError:
                pass

    # 2. Look for local .cecli.workspaces.yml/yaml
    if not workspace_conf:
        for local_name in [".cecli.workspaces.yml", ".cecli.workspaces.yaml"]:
            local_path = Path(local_name)
            if local_path.exists():
                try:
                    with open(local_path, "r") as f:
                        loaded = yaml.safe_load(f)
                        if loaded:
                            workspace_conf = (
                                loaded.get("workspaces") or loaded.get("workspace") or loaded
                            )
                            if workspace_conf:
                                break
                except Exception:
                    pass

    # 3. Look for global ~/.cecli/workspaces.yml/yaml
    if not workspace_conf:
        for global_name in ["workspaces.yml", "workspaces.yaml"]:
            global_path = Path.home() / ".cecli" / global_name
            if global_path.exists():
                try:
                    with open(global_path, "r") as f:
                        loaded = yaml.safe_load(f)
                        if loaded:
                            workspace_conf = (
                                loaded.get("workspaces") or loaded.get("workspace") or loaded
                            )
                            if workspace_conf:
                                break
                except Exception:
                    pass

    return workspace_conf


def load_workspace_config(
    config_arg: Optional[str] = None, name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Load workspace configuration from hierarchy.
    If name is provided, select that specific workspace from a list.
    """
    workspace_conf = resolve_workspace_config(config_arg)

    config = {}
    # Handle list of workspaces or single dict
    if isinstance(workspace_conf, list):
        if name:
            selected_ws = next((ws for ws in workspace_conf if ws.get("name") == name), None)
            if not selected_ws:
                raise ValueError(f"Workspace '{name}' not found in configuration")
            config = selected_ws
        else:
            active_workspaces = [ws for ws in workspace_conf if ws.get("active")]
            if len(active_workspaces) > 1:
                active_names = [ws.get("name", "unknown") for ws in active_workspaces]
                raise ValueError(f"Multiple workspaces marked as active: {', '.join(active_names)}")

            active_ws = active_workspaces[0] if active_workspaces else None

            # If no workspace is explicitly marked active, but there is only one, use it
            if not active_ws and len(workspace_conf) == 1:
                active_ws = workspace_conf[0]
            config = active_ws if active_ws else {}
    elif isinstance(workspace_conf, dict):
        config = workspace_conf

    validate_config(config)
    return config


def validate_config(config: Dict[str, Any]) -> None:
    """
    Minimal validation of required fields.
    """
    if not config:
        return

    if "name" not in config:
        raise ValueError("Workspace configuration must include a 'name'")

    if "projects" not in config:
        config["projects"] = []

    project_names = set()
    for project in config["projects"]:
        if "name" not in project or "repo" not in project:
            raise ValueError("Each project must have a 'name' and 'repo' URL")
        if project["name"] in project_names:
            raise ValueError(f"Duplicate project name: {project['name']}")
        project_names.add(project["name"])


def find_active_workspace_name(config_arg: Optional[str] = None) -> Optional[str]:
    """
    Find the name of the active workspace from the config without resolving it fully.
    Used in main.py to automatically activate a workspace.
    """
    workspace_conf = resolve_workspace_config(config_arg)

    if isinstance(workspace_conf, list):
        active_ws = next((ws for ws in workspace_conf if ws.get("active")), None)
        if active_ws:
            return active_ws.get("name")
        # If there's only one workspace, it's considered active
        if len(workspace_conf) == 1:
            return workspace_conf[0].get("name")
    elif isinstance(workspace_conf, dict):
        # If it's a single dict, it's considered active by default
        return workspace_conf.get("name")

    return None
