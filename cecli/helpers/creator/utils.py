"""Helpers for reloading extensions changed by the creator sub-agent."""

import json
import os
from pathlib import Path


def is_creator(coder) -> bool:
    """Return True when *coder* is the creator sub-agent."""
    if not coder:
        return False

    agent_config = getattr(coder, "agent_config", {}) or {}
    if agent_config.get("creator_mode") or agent_config.get("allow_external_paths"):
        return True

    try:
        from cecli.helpers.agents.service import AgentService

        return AgentService.get_instance(coder).get_agent_name(coder) == "creator"
    except Exception:
        return False


def resolve_config_paths(coder):
    """Return the config paths used by the current session.

    The result mirrors ``main.main_async``: global ``conf.yml`` files are
    shallow-merged, ``.cecli.conf.yml`` files are deep-merged, and
    ``creator.yml`` files are deep-merged last (highest config precedence).
    """
    home = Path.home()
    cwd = Path.cwd()
    root = getattr(coder, "root", None) or cwd

    paths = [
        str(home / ".cecli" / "conf.yml"),
        str(home / ".cecli" / ".cecli.conf.yml"),
        str(home / ".cecli.conf.yml"),
        str(cwd / ".cecli.conf.yml"),
        str(Path(root) / ".cecli.conf.yml"),
    ]

    env_path = os.environ.get("CECLI_CONFIG_FILE")
    if env_path:
        paths.append(env_path)

    creator_paths = list(creator_yml_paths(root))
    paths = list(dict.fromkeys(paths + creator_paths))
    conf_yml_paths = [
        p for p in paths if p.endswith("conf.yml") and not p.endswith(".cecli.conf.yml")
    ]
    cecli_conf_paths = [p for p in paths if p.endswith(".cecli.conf.yml")]

    return paths, conf_yml_paths, cecli_conf_paths, creator_paths


def creator_yml_paths(root=None) -> tuple:
    """Return (global_path, local_path) for creator.yml config files.

    global: ~/.cecli/creator.yml ; local: <root or cwd>/.cecli/creator.yml
    """
    base = Path(root) if root else Path.cwd()

    return (
        str(Path.home() / ".cecli" / "creator.yml"),
        str(base / ".cecli" / "creator.yml"),
    )


def read_merged_config(coder) -> dict:
    """Read and merge the session's config files into a single dict."""
    try:
        from cecli.helpers import config_utils

        paths, conf_yml_paths, cecli_conf_paths, creator_paths = resolve_config_paths(coder)
        return config_utils.read_and_merge_all_configs(
            paths, conf_yml_paths, cecli_conf_paths, creator_paths
        )
    except Exception:
        return {}


def reload_skills(coder, config=None) -> list:
    """Rebuild skills managers so new files and config filters are visible."""
    config = config if config is not None else read_merged_config(coder)
    agent_config = _extract_agent_config(config)
    skill_keys = (
        "skills_paths",
        "skills_includelist",
        "skills_excludelist",
        "skills_init",
    )
    coders = _iter_coders(coder)
    overrides = _extract_agent_overrides(config)
    _apply_agent_config(coder, coders, agent_config, skill_keys, overrides)

    try:
        from cecli.helpers.skills import _skill_state_store
    except Exception:
        _skill_state_store = None

    if _skill_state_store is not None and any(key in agent_config for key in skill_keys[1:]):
        for item in coders:
            _skill_state_store.pop(getattr(item, "uuid", None), None)

    messages = []
    for item in coders:
        try:
            if hasattr(item, "_initialize_skills_manager"):
                item._initialize_skills_manager(
                    getattr(item, "agent_config", {}) or {}, root=getattr(item, "root", None)
                )
            elif getattr(item, "skills_manager", None):
                item.skills_manager.hot_reload()
        except Exception as exc:
            messages.append(f"Skills reload failed: {exc}")
            continue

    if not messages:
        messages.append("Skills reloaded")

    return messages


def reload_hooks(coder, config=None) -> list:
    """Reload hooks from disk and re-apply config-supplied hook definitions."""
    config = config if config is not None else read_merged_config(coder)
    hooks_config = config.get("hooks")

    messages = []
    for item in _iter_coders(coder):
        try:
            from cecli.hooks import HookService

            registry = HookService.get_registry(item)
            registry.reload_hooks()

            payload = hooks_config
            if payload is None:
                args = getattr(item, "args", None)
                payload = getattr(args, "hooks", None)

            if isinstance(payload, dict):
                payload = json.dumps(payload)

            if isinstance(payload, str) and payload.strip():
                registry.load_hooks_from_json(payload)
        except Exception as exc:
            messages.append(f"Hooks reload failed: {exc}")

    if not messages:
        messages.append("Hooks reloaded")

    return messages


def reload_workflows(coder, config=None) -> list:
    """Re-read workflow definitions and refresh ``wf:`` sub-agent registrations."""
    config = config if config is not None else read_merged_config(coder)

    try:
        from cecli.helpers.workflows import load_workflows
        from cecli.helpers.workflows.subagents import (
            get_workflow_configs,
            register_workflow_subagents,
            unregister_workflow_subagents,
        )

        workflows = load_workflows(
            config_arg=getattr(coder, "workflows_config_arg", None),
            merged_config=config or getattr(coder, "workflows_merged_config", None),
            git_root=getattr(coder, "root", None),
        )

        previous = get_workflow_configs()
        by_name = {workflow.name: workflow for workflow in previous}
        by_name.update({workflow.name: workflow for workflow in workflows})
        merged = sorted(by_name.values(), key=lambda workflow: workflow.name)

        unregister_workflow_subagents(previous)
        registered = register_workflow_subagents(merged)

        scheduler = getattr(coder, "scheduler", None)
        if scheduler is not None and getattr(scheduler, "db", None) is not None:
            import asyncio

            try:
                asyncio.get_running_loop().create_task(
                    scheduler.db.sync_definitions(
                        {workflow.name: workflow for workflow in merged if workflow.enabled}
                    )
                )
            except Exception:
                pass

        return [f"Workflows reloaded ({len(registered)} active)"]
    except Exception as exc:
        return [f"Workflows reload failed: {exc}"]


async def reload_custom_tools(coder, config=None) -> list:
    """Invalidate custom-tool modules and rebuild the tool registry."""
    config = config if config is not None else read_merged_config(coder)
    agent_config = _extract_agent_config(config)
    tool_keys = ("tools_paths", "tools_includelist", "tools_excludelist")
    coders = _iter_coders(coder)
    overrides = _extract_agent_overrides(config)
    _apply_agent_config(coder, coders, agent_config, tool_keys, overrides)

    try:
        from cecli.tools.utils.registry import ToolRegistry

        tool_paths = set()
        for item in coders:
            tool_paths.update(_tool_paths(item))

        for path in tool_paths:
            _invalidate_module_cache(path)

        ToolRegistry.build_registry(
            getattr(coder, "agent_config", {}) or {}, root=getattr(coder, "root", None)
        )

        for item in coders:
            item.loaded_custom_tools = list(ToolRegistry.loaded_custom_tools)
            manager = getattr(item, "mcp_manager", None)
            if manager is None:
                continue

            local = manager.get_server("Local")
            if local is not None and local.is_connected:
                await manager.disconnect_server(local.name)
                await manager.connect_server(local.name)

        return [f"Custom tools reloaded ({len(ToolRegistry.loaded_custom_tools)} loaded)"]
    except Exception as exc:
        return [f"Custom tools reload failed: {exc}"]


def reload_custom_commands(coder, config=None) -> list:
    """Invalidate custom-command modules and re-run the command loader."""
    config = config if config is not None else read_merged_config(coder)
    custom = config.get("custom")

    if isinstance(custom, str):
        try:
            custom = json.loads(custom)
        except Exception:
            custom = {}

    command_paths = None
    if isinstance(custom, dict):
        command_paths = custom.get("command-paths", custom.get("command_paths"))

    messages = []
    for item in _iter_coders(coder):
        commands = getattr(item, "commands", None)
        if commands is None:
            continue

        paths = command_paths
        if paths is None:
            paths = getattr(commands, "custom_commands", [])

        if isinstance(paths, str):
            paths = [paths]

        for path in paths or []:
            _invalidate_module_cache(path)

        try:
            commands.custom_commands = list(paths or [])
            commands._load_custom_commands(commands.custom_commands)
        except Exception as exc:
            messages.append(f"Custom commands reload failed: {exc}")

    if not messages:
        messages.append("Custom commands reloaded")

    return messages


async def reload_mcp_servers(coder, config=None) -> list:
    """Connect newly configured MCP servers without disturbing live ones."""
    config = config if config is not None else read_merged_config(coder)
    raw_servers = config.get("mcp-servers", config.get("mcp_servers"))
    server_files = config.get(
        "mcp-servers-files", config.get("mcp_servers_files", config.get("mcp-servers-file"))
    )

    if not raw_servers and not server_files:
        return ["MCP servers unchanged"]

    if isinstance(raw_servers, (dict, list)):
        raw_servers = json.dumps(raw_servers)

    if isinstance(server_files, str):
        server_files = [server_files]

    try:
        from cecli.mcp import load_mcp_servers

        args = getattr(coder, "args", None)
        servers = load_mcp_servers(
            raw_servers,
            server_files or [],
            coder.io,
            verbose=getattr(args, "verbose", False),
            mcp_transport=getattr(args, "mcp_transport", "stdio"),
        )
    except Exception as exc:
        return [f"MCP config reload failed: {exc}"]

    added = []
    messages = []
    for item in _iter_coders(coder):
        manager = getattr(item, "mcp_manager", None)
        if manager is None:
            continue

        existing = {server.name for server in manager.servers}
        for server in servers:
            if server.name in existing:
                continue

            clone = _clone_server(server, io=getattr(item, "io", None), verbose=False)
            try:
                connected = await manager.add_server(clone, connect=True)
            except Exception as exc:
                messages.append(f"MCP server '{server.name}' failed: {exc}")
                continue

            if connected:
                added.append(server.name)
                included = getattr(item, "registered_servers", {}).get("included")
                if included is not None:
                    included.add(server.name)

    if added:
        names = ", ".join(sorted(set(added)))
        messages.append(f"MCP servers added: {names}")
    elif not messages:
        messages.append("MCP servers unchanged")

    return messages


async def reload_creator_extensions(coder) -> list:
    """Reload every extension type a creator agent may have changed."""
    config = read_merged_config(coder)
    messages = []

    messages.extend(reload_skills(coder, config))
    messages.extend(reload_hooks(coder, config))
    messages.extend(reload_workflows(coder, config))
    messages.extend(await reload_custom_tools(coder, config))
    messages.extend(reload_custom_commands(coder, config))
    messages.extend(await reload_mcp_servers(coder, config))

    return messages


def _iter_coders(coder) -> list:
    """Return all live coders, including *coder* when it is not tracked."""
    coders = []
    try:
        from cecli.helpers.agents.service import AgentService

        coders = AgentService.get_all_agents()
    except Exception:
        coders = []

    if coder is not None and coder not in coders:
        coders.append(coder)

    return coders


def _extract_agent_config(config) -> dict:
    """Return the ``agent-config`` mapping from a merged config dict."""
    if not isinstance(config, dict):
        return {}

    raw = config.get("agent-config", config.get("agent_config"))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}

    return raw if isinstance(raw, dict) else {}


def _extract_agent_overrides(config) -> dict:
    """Return the per-agent ``agents:`` map from a merged config dict."""
    raw = config.get("agents") if isinstance(config, dict) else None

    return raw if isinstance(raw, dict) else {}


def _override_agent_config_for(name, overrides) -> dict:
    """Return the merged ``agent-config`` a coder named *name* overrides."""
    if not name or not isinstance(overrides, dict):
        return {}

    try:
        from cecli.helpers.agents.overrides import resolve_agent_overrides

        resolved = resolve_agent_overrides(name, overrides)
    except Exception:
        return {}

    config = resolved.get("agent-config") if isinstance(resolved, dict) else None

    return config if isinstance(config, dict) else {}


def _agent_name(coder) -> str:
    """Return *coder*'s sub-agent name, or '' for the primary."""
    try:
        from cecli.helpers.agents.service import AgentService

        return AgentService.get_instance(coder).get_agent_name(coder) or ""
    except Exception:
        return ""


def _apply_agent_config(coder, coders, agent_config, keys, overrides=None) -> None:
    """Copy selected shared ``agent-config`` keys onto each coder.

    Per-agent overrides win: a key declared under ``agents.<name>`` is left
    untouched so the reload does not stamp the shared value back over it. When
    no ``agents:`` map exists every key is applied, matching the old behavior.
    """
    if not agent_config:
        return

    for item in coders:
        config = getattr(item, "agent_config", None)
        if not isinstance(config, dict):
            continue

        override_config = _override_agent_config_for(_agent_name(item), overrides)
        for key in keys:
            if key in agent_config and key not in override_config:
                config[key] = agent_config[key]


def _tool_paths(coder) -> set:
    """Return every directory/file that may contain custom tools."""
    paths = {Path.home() / ".cecli" / "tools"}
    root = getattr(coder, "primary_root", None) or getattr(coder, "root", None)
    if root:
        paths.add(Path(root) / ".cecli" / "tools")

    agent_config = getattr(coder, "agent_config", {}) or {}
    configured = agent_config.get("tools_paths", agent_config.get("tool_paths", []))
    if isinstance(configured, str):
        configured = [configured]

    for path in configured or []:
        raw = Path(os.path.expanduser(str(path)))
        paths.add(raw if raw.is_absolute() else Path(root or Path.cwd()) / raw)

    return paths


def _invalidate_module_cache(target) -> None:
    """Drop cached plugin modules for *target* so edits are re-imported."""
    try:
        from cecli.helpers import plugin_manager
    except Exception:
        return

    path = Path(os.path.expanduser(str(target)))
    candidates = []
    if path.is_dir():
        candidates = list(path.rglob("*.py"))
    elif path.suffix == ".py":
        candidates = [path]

    for candidate in candidates:
        try:
            plugin_manager.module_cache.pop(str(candidate.resolve()), None)
        except OSError:
            continue


def _clone_server(server, io=None, verbose=False):
    """Build an independent ``McpServer`` with the same configuration."""
    import copy

    return type(server)(copy.deepcopy(server.config), io=io, verbose=verbose)
