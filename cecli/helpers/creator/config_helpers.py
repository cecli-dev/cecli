"""Shared creator.yml read/write and agent-config helpers."""

import difflib
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

from cecli.decoding import safe_open
from cecli.helpers.creator import utils as creator_utils

RELOAD_FUNCS = {
    "mcp_server": "reload_mcp_servers",
    "hook": "reload_hooks",
    "skill": "reload_skills",
    "custom_tool": "reload_custom_tools",
    "custom_command": "reload_custom_commands",
    "workflow": "reload_workflows",
    "config": "reload_creator_extensions",
}


def creator_paths(coder) -> tuple:
    """Return (global, local) creator.yml paths via the shared contract helper."""
    from cecli.tools.utils.helpers import ToolError

    paths_fn = getattr(creator_utils, "creator_yml_paths", None)
    if paths_fn is None:
        raise ToolError(
            "creator_yml_paths is not available in cecli.helpers.creator.utils; "
            "cannot resolve creator.yml locations."
        )

    root = getattr(coder, "primary_root", None) or getattr(coder, "root", None)

    return paths_fn(root)


def read_yml(path) -> dict:
    """Parse a creator.yml file, returning {} when it does not exist."""
    if not path or not Path(path).exists():
        return {}

    with safe_open(str(path), "r") as fh:
        data = yaml.safe_load(fh)

    return data if isinstance(data, dict) else {}


def write_yml(path, data) -> None:
    """Dump a mapping back to a creator.yml file without reordering keys."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with safe_open(str(path), "w") as fh:
        yaml.dump(data, fh, sort_keys=False)


def merge_fragment(path, fragment) -> None:
    """Deep-merge a fragment into a creator.yml file (arrays concatenated)."""
    from cecli.helpers.config_utils import deep_merge

    write_yml(path, deep_merge(read_yml(path), fragment))


def write_text(path, text) -> None:
    """Write full file content, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with safe_open(str(path), "w") as fh:
        fh.write(text)


def parse_mapping(value):
    """Parse a YAML/JSON string into a mapping; non-strings pass through."""
    if isinstance(value, (dict, list)):
        return value

    if not isinstance(value, str):
        return None

    try:
        return yaml.safe_load(value)
    except yaml.YAMLError:
        return None


def as_mapping(config, content) -> dict:
    """Coerce add/update payloads into a mapping."""
    if isinstance(config, dict):
        return dict(config)

    parsed = parse_mapping(config)
    if isinstance(parsed, dict):
        return parsed

    if content is not None:
        parsed = parse_mapping(content)
        if isinstance(parsed, dict):
            return parsed

    return {}


def as_payload(config, content):
    """Return the payload for a dotted config path, falling back to parsed content."""
    if config is not None:
        return config

    if content is not None:
        parsed = parse_mapping(content)

        return parsed if parsed is not None else str(content)

    return {}


def nested(keys, value):
    """Wrap *value* in nested dicts along a dotted key path."""
    fragment = value

    for key in reversed([k for k in keys if k]):
        fragment = {key: fragment}

    return fragment


def pop_nested(data, keys) -> bool:
    """Pop the leaf at a dotted key path; returns True when something was removed."""
    keys = [k for k in keys if k]
    current = data

    for key in keys[:-1]:
        if not isinstance(current, dict) or key not in current:
            return False

        current = current[key]

    return isinstance(current, dict) and bool(keys) and current.pop(keys[-1], None) is not None


def references(item, name) -> bool:
    """Return True when a list entry's basename refers to *name*."""
    if not isinstance(item, str):
        return False

    base = Path(item).name

    return base in (name, f"{name}.py", f"{name}.yml", f"{name}.yaml")


def pop_list_value(sections, key, value) -> bool:
    """Drop *value* from a list at *key* across *sections*; True if anything went."""
    removed = False

    for section in sections:
        items = section.get(key)
        if isinstance(items, list) and value in items:
            items.remove(value)
            removed = True

    return removed


def has_agent_config_whitelist(coder, key) -> bool:
    """Return True when any live coder runs with a non-empty whitelist for *key*.

    Recording such a key in creator.yml's shared agent-config would turn an
    unfiltered setup into a whitelist of just the new entry, so it is only
    written when a whitelist is already in effect. Runtime state counts too:
    an include list restored this session (without a config value) still
    filters, so it must trigger the persistence record. For servers only the
    config-authored value counts: the runtime included set is auto-populated
    for unfiltered coders and therefore does not imply a whitelist.
    """
    for item in creator_utils._iter_coders(coder):
        config = getattr(item, "agent_config", None) or {}
        if config.get(key):
            return True

        if key == "skills_includelist":
            manager = getattr(item, "skills_manager", None)
            if manager is not None and getattr(manager, "include_list", None):
                return True

    return False


def normalize_apply_to(apply_to) -> list:
    """Normalise ``apply_to`` into a de-duplicated list of non-empty names."""
    if apply_to is None:
        return []

    if isinstance(apply_to, str):
        apply_to = [apply_to]

    targets = []
    for item in apply_to or []:
        name = str(item or "").strip()
        if name and name not in targets:
            targets.append(name)

    return targets


def validate_apply_to(apply_to, entry_type, name=None) -> list:
    """Validate and return the normalised ``apply_to`` targets for *entry_type*.

    Empty input means today's shared-config behavior and needs no validation.
    Unsupported types and malformed config paths raise ``ToolError`` with a
    hint; names are checked against the live agent registry (exact match or an
    fnmatch pattern matching at least one registered agent).
    """
    from cecli.tools.utils.helpers import ToolError

    targets = normalize_apply_to(apply_to)

    if not targets:
        return []

    if entry_type in ("custom_tool", "custom_command", "workflow"):
        raise ToolError(
            f"apply_to is not supported for type '{entry_type}': paths, commands and "
            "workflows are session-wide. Use type 'config' with an agent-config.* or "
            "hooks.* path to scope them."
        )

    if entry_type == "config":
        if len(targets) != 1:
            raise ToolError(
                "apply_to for type 'config' requires exactly one exact agent name; "
                f"got {targets}."
            )

        if is_pattern(targets[0]):
            raise ToolError(
                "apply_to for type 'config' requires an exact agent name, not a "
                f"pattern ('{targets[0]}')."
            )

        path = str(name or "")
        if not (path.startswith("agent-config.") or path.startswith("hooks.")):
            raise ToolError(
                "apply_to for type 'config' only supports 'agent-config.*' or "
                f"'hooks.*' paths; got '{path}'."
            )

    for target in targets:
        _validate_target_name(target)

    return targets


def resolve_target_names(target) -> list:
    """Return the registered agent names matched by *target* (exact or pattern)."""
    names = _registry_names()
    if target in names:
        return [target]

    return [name for name in names if fnmatchcase(name, target)]


def targets_with_whitelist(coder, targets, key) -> list:
    """Return the subset of *targets* whose effective config filters on *key*.

    For a pattern target every matched agent must already filter; otherwise
    writing an include entry for the pattern would turn unfiltered agents into
    a one-entry whitelist. ``key`` is ``skills_includelist`` (config truthiness
    or a live non-empty include list) or ``servers_includelist`` (config-
    authored value only: runtime ``registered_servers['included']`` is
    auto-populated and does not imply a whitelist).
    """
    safe = []
    for target in targets:
        matched = resolve_target_names(target) or [target]
        if all(_target_filters(coder, name, key) for name in matched):
            safe.append(target)

    return safe


def agents_fragment(entries) -> dict:
    """Build an ``agents:`` fragment from ``{target: node}`` entries."""
    nodes = {target: node for target, node in entries.items() if node}

    return {"agents": nodes} if nodes else {}


def prune_agent_references(data, patterns, keys, name, prune_paths=False, hooks=False) -> bool:
    """Prune *name* from per-agent override nodes matching *patterns*.

    Empty ``agents.<target>`` nodes are deleted so a removal does not leave
    dead scaffolding behind.
    """
    agents = data.get("agents")
    if not isinstance(agents, dict):
        return False

    removed = False
    for target in list(agents):
        if not matches_any_target(target, patterns):
            continue

        node = agents[target]
        if not isinstance(node, dict):
            continue

        config = node.get("agent-config")
        if isinstance(config, dict):
            for key in keys:
                removed = pop_list_value([config], key, name) or removed

            if prune_paths:
                items = config.get("skills_paths")
                if isinstance(items, list):
                    kept = [item for item in items if not references(item, name)]
                    removed = removed or len(kept) != len(items)
                    config["skills_paths"] = kept

        if hooks:
            section = node.get("hooks")
            if isinstance(section, dict) and name in section:
                section.pop(name)
                removed = True

        _prune_empty(node)
        if not node:
            del agents[target]

    if not agents:
        data.pop("agents", None)

    return removed


def pop_agent_path(data, target, keys) -> bool:
    """Pop a dotted path below ``agents.<target>`` and drop the node when empty."""
    agents = data.get("agents")
    if not isinstance(agents, dict):
        return False

    node = agents.get(target)
    if not isinstance(node, dict):
        return False

    removed = pop_nested(node, keys)
    _prune_empty(node)
    if not node:
        del agents[target]

    if not agents:
        data.pop("agents", None)

    return removed


def _prune_empty(mapping) -> None:
    """Drop empty dict/list values from *mapping* so nodes can disappear."""
    for key in list(mapping):
        value = mapping[key]
        if isinstance(value, dict):
            _prune_empty(value)
            if not value:
                mapping.pop(key)
        elif isinstance(value, list) and not value:
            mapping.pop(key)


def matches_any_target(target, patterns) -> bool:
    """Return True when *target* equals or matches any of *patterns*."""
    return any(target == pattern or fnmatchcase(target, pattern) for pattern in patterns)


def is_pattern(name) -> bool:
    """Return True when *name* contains fnmatch wildcard characters."""
    return any(char in str(name) for char in "*?[")


def tool_is_excluded(coder, name) -> bool:
    """Return True when a live coder's tools_excludelist names *name*."""
    for item in creator_utils._iter_coders(coder):
        config = getattr(item, "agent_config", None) or {}
        if name.lower() in (config.get("tools_excludelist") or []):
            return True

    return False


def list_creator_files(response, global_yml, local_yml) -> None:
    """Append the parsed contents of both creator.yml files to the response."""
    import json

    for label, path in (("global", global_yml), ("local", local_yml)):
        payload = json.dumps(read_yml(path), indent=2, default=str)
        response.append_result(f"{label} creator.yml ({path}):\n{payload}")


async def reload_for_type(coder, entry_type) -> list:
    """Run the reload helper matching *entry_type* and return its messages."""
    import inspect

    func_name = RELOAD_FUNCS[entry_type]
    func = getattr(creator_utils, func_name, None)
    if func is None:
        return [f"Reload helper {func_name} unavailable"]

    result = func(coder)
    if inspect.isawaitable(result):
        result = await result

    return list(result or [])


def _validate_target_name(target) -> None:
    """Raise ``ToolError`` when *target* is unregistered or ambiguous."""
    from cecli.tools.utils.helpers import ToolError

    if target in ("primary", "main"):
        raise ToolError(
            f"'{target}' cannot be targeted: the shared config already applies to the "
            "primary. Omit apply_to for shared config, or pass ['*'] for every agent."
        )

    names = _registry_names()
    if target in names:
        return

    if is_pattern(target):
        if any(fnmatchcase(name, target) for name in names):
            return

        raise ToolError(f"{_target_hint(target)}")

    nearby = difflib.get_close_matches(target, names, n=5)
    available = ", ".join(sorted(names)) or "none"
    hint = f" Did you mean: {', '.join(nearby)}?" if nearby else ""

    raise ToolError(f"Unknown agent '{target}'. Registered agents: {available}.{hint}")


def _target_hint(target) -> str:
    """Build a pattern-specific error message for *target*."""
    prefix, _, suffix = target.partition(":")

    if prefix == "wf" and suffix:
        return (
            f"No workflow named '{suffix}' is enabled/loaded (pattern '{target}' matched nothing)."
        )

    if prefix == "ws" and suffix:
        return (
            f"No workspace project named '{suffix}' is active (pattern '{target}' matched nothing)."
        )

    names = _registry_names()
    available = ", ".join(sorted(names)) or "none"

    return f"Pattern '{target}' matched no registered agent. Registered agents: {available}."


def _registry_names() -> list:
    """Return the registered sub-agent names, tolerating a missing service."""
    try:
        from cecli.helpers.agents.service import AgentService

        return list(AgentService.get_registry().keys())
    except Exception:
        return []


def _target_filters(coder, name, key) -> bool:
    """Return True when the named agent's effective config filters on *key*."""
    live = _live_coder(coder, name)
    config = dict(_registry_agent_config(name))
    live_config = getattr(live, "agent_config", None) if live is not None else None
    if isinstance(live_config, dict):
        config.update(live_config)

    if config.get(key):
        return True

    if key == "skills_includelist" and live is not None:
        manager = getattr(live, "skills_manager", None)
        return bool(getattr(manager, "include_list", None))

    return False


def _registry_agent_config(name) -> dict:
    """Return the registry entry's ``agent-config`` mapping for *name*."""
    try:
        from cecli.helpers.agents.service import AgentService

        entry = AgentService.get_registry().get(name)
    except Exception:
        return {}

    metadata = getattr(entry, "metadata", None)
    config = metadata.get("agent-config") if isinstance(metadata, dict) else None

    return config if isinstance(config, dict) else {}


def _live_coder(coder, name):
    """Return the live coder currently serving as *name*, if any."""
    try:
        from cecli.helpers.agents.service import AgentService

        for item in creator_utils._iter_coders(coder):
            try:
                if AgentService.get_instance(item).get_agent_name(item) == name:
                    return item
            except Exception:
                continue
    except Exception:
        pass

    return None
