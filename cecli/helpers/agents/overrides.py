"""Per-agent overrides loaded from the ``agents:`` map in ``creator.yml``.

A ``creator.yml`` may declare an ``agents:`` mapping whose keys are agent names
(``reviewer``), wildcard patterns (``*``, ``wf:*``) or dynamic agent definitions
(``writer`` with a ``prompt``). The map is honored **only** in ``creator.yml``
(global ``~/.cecli/creator.yml`` and the project-local
``<root>/.cecli/creator.yml``); an ``agents:`` key in ``conf.yml`` or
``.cecli.conf.yml`` has no consumer. Global and project-local files are merged
global-first (local wins), then :func:`resolve_agent_overrides` collapses the
patterns that match a spawned agent into one override dictionary.

The map is deliberately kept out of ``agent-config`` so it cannot reach the
primary coder through ``args.agent_config``; only
``AgentService._create_sub_agent_coder`` applies it at spawn time.
"""

import logging
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import yaml

from cecli.decoding import safe_open

logger = logging.getLogger(__name__)


# Names registered from definition entries on the last load, so a reload can
# remove dynamic agents that disappeared from the config.
_registered_creator_agents: set = set()


# Keys that only appear on a whole ``agents:`` entry, never in a bare hooks
# fragment. Used to tell an entry from a fragment when no ``hooks`` key exists.
ENTRY_ONLY_KEYS = frozenset(
    {
        "agent-config",
        "root",
        "model",
        "auto_reap",
        "detached",
        "prompt",
        "prompt_file",
        "description",
    }
)


def load_agent_overrides(primary_root: Optional[str] = None) -> Dict[str, Any]:
    """Return the global + local ``creator.yml`` ``agents:`` map.

    Global (``~/.cecli/creator.yml``) is read first and the project-local
    ``<primary_root>/.cecli/creator.yml`` is deep-merged on top, so local
    entries win and array keys concatenate/dedupe.

    Only the two ``creator.yml`` files are read; ``agents:`` entries in other
    config files are intentionally ignored.

    Args:
        primary_root: Project root used to locate the local file. Defaults to
            the current working directory (see ``creator_yml_paths``).

    Returns:
        Mapping of agent name or pattern to its override/definition entry.
        Relative ``prompt_file`` values are resolved against the file that
        declared them.
    """
    from cecli.helpers.config_utils import deep_merge
    from cecli.helpers.creator.utils import creator_yml_paths

    merged: Dict[str, Any] = {}

    for path in creator_yml_paths(primary_root):
        merged = deep_merge(merged, _read_agents_map(path))

    return merged


def refresh_agent_overrides(primary_root: Optional[str] = None) -> Dict[str, Any]:
    """Re-read the ``creator.yml`` files and refresh the spawn-time index.

    Both startup (``main_async``) and the ManageExtensions tool use this single reader
    path: it re-reads the global and local ``creator.yml`` files, updates
    ``AgentService``'s override index, and re-registers/removes dynamic
    ``creator:<name>`` definitions. Call it after any mutation of a
    ``creator.yml`` ``agents:`` map so sub-agents spawned later in the same
    session see the change without a restart. ``agents:`` is honored only in
    ``creator.yml`` — never in the other config files.

    Args:
        primary_root: Project root used to locate the local file. Defaults to
            the current working directory.

    Returns:
        The merged ``agents:`` map that was installed on ``AgentService``.
    """
    overrides = load_agent_overrides(primary_root)

    from cecli.helpers.agents.service import AgentService

    AgentService.set_agent_overrides(overrides)
    register_creator_agents(overrides)

    return overrides


def resolve_agent_overrides(name: str, overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Collapse every ``agents:`` entry matching *name* into one override.

    Precedence, lowest to highest: a bare ``*``, then family patterns
    (``wf:*`` / ``ws:*``), then any other wildcard, then an exact name.
    Longer patterns win within a tier, and each merge uses
    ``config_utils.deep_merge`` (agent-config arrays concatenate/dedupe).

    Args:
        name: Registry name of the agent being spawned.
        overrides: The ``agents:`` map returned by :func:`load_agent_overrides`.

    Returns:
        The merged override for *name*, or ``{}`` when nothing matches.
    """
    if not name or not isinstance(overrides, dict):
        return {}

    matched: List[Tuple[str, Dict[str, Any]]] = [
        (pattern, entry)
        for pattern, entry in overrides.items()
        if isinstance(entry, dict) and fnmatchcase(name, pattern)
    ]
    matched.sort(key=lambda item: _pattern_specificity(item[0]))

    from cecli.helpers.config_utils import deep_merge

    resolved: Dict[str, Any] = {}

    for _, entry in matched:
        resolved = deep_merge(resolved, entry)

    return resolved


def apply_agent_override(agent_config: Any, override: Any) -> Dict[str, Any]:
    """Deep-merge an ``agent-config`` override onto a resolved agent config.

    Args:
        agent_config: The agent's current config (parent inheritance plus its
            own front matter / registration metadata).
        override: The ``agent-config`` fragment from the matching ``agents:``
            entry (``resolved_entry.get("agent-config")``), not the whole
            entry. Non-mappings and empty values leave the config untouched.

    Returns:
        A new mapping; list-valued keys are concatenated and de-duplicated by
        ``config_utils.deep_merge``.
    """
    from cecli.helpers.config_utils import deep_merge

    base = dict(agent_config) if isinstance(agent_config, dict) else {}

    if not isinstance(override, dict) or not override:
        return base

    return deep_merge(base, override)


def apply_hooks_override(hooks: Any, override: Any) -> Dict[str, Any]:
    """Deep-merge override hook definitions onto a sub-agent's hooks config.

    Hook configs are mappings of hook type (``pre_tool_call``) to a list of
    hook definitions, so the generic deep merge concatenates and de-duplicates
    lists while later entries win on scalar keys.

    Args:
        hooks: The hooks mapping from ``SubAgentConfig.hooks`` (may be empty).
        override: Either the full ``agents:`` entry (its ``hooks`` key is used)
            or a bare hooks fragment.

    Returns:
        A new merged hooks mapping.
    """
    from cecli.helpers.config_utils import deep_merge

    base = dict(hooks) if isinstance(hooks, dict) else {}

    if not isinstance(override, dict):
        return base
    if "hooks" in override:
        fragment = override.get("hooks")
    elif set(override) & ENTRY_ONLY_KEYS:
        fragment = None
    else:
        fragment = override

    if not isinstance(fragment, dict) or not fragment:
        return base

    return deep_merge(base, fragment)


def iter_agent_definitions(
    overrides: Optional[Dict[str, Any]],
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield ``(name, entry)`` pairs that define a new agent.

    Definition entries provide ``prompt`` or ``prompt_file``; wildcard pattern
    keys are skipped because they cannot name a single registered agent.
    """
    if not isinstance(overrides, dict):
        return

    for name, entry in overrides.items():
        if _has_wildcard(name) or not isinstance(entry, dict):
            continue

        if entry.get("prompt") or entry.get("prompt_file"):
            yield name, entry


def register_creator_agents(
    overrides: Optional[Dict[str, Any]], base_dir: Optional[Any] = None
) -> List[str]:
    """Register dynamic ``creator:<name>`` agents for definition entries.

    Idempotent: a re-run replaces existing entries and unregisters names that
    were registered previously but are no longer defined.

    Args:
        overrides: The ``agents:`` map.
        base_dir: Directory used to resolve relative ``prompt_file`` values
            when the map did not come from :func:`load_agent_overrides`.
            Defaults to the current working directory.

    Returns:
        The registered ``creator:<name>`` agent names.
    """
    from cecli.helpers.agents.config import SubAgentConfig
    from cecli.helpers.agents.service import AgentService

    registered: List[str] = []

    for name, entry in iter_agent_definitions(overrides):
        prompt = entry.get("prompt") or _read_prompt_file(entry.get("prompt_file"), base_dir)

        metadata: Dict[str, Any] = {}
        for key in ("description", "root"):
            if entry.get(key) is not None:
                metadata[key] = entry[key]
        if isinstance(entry.get("agent-config"), dict):
            metadata["agent-config"] = dict(entry["agent-config"])

        agent_name = f"creator:{name}"
        hooks = entry.get("hooks")

        AgentService.register_subagent(
            agent_name,
            SubAgentConfig(
                name=agent_name,
                prompt=prompt or "",
                model=entry.get("model"),
                hooks=dict(hooks) if isinstance(hooks, dict) else {},
                auto_reap=entry.get("auto_reap"),
                metadata=metadata,
            ),
        )
        registered.append(agent_name)
        logger.info("Registered creator sub-agent '%s'", agent_name)

    stale = _registered_creator_agents - set(registered)
    for agent_name in stale:
        AgentService.unregister_subagent(agent_name)

    _registered_creator_agents.clear()
    _registered_creator_agents.update(registered)

    return registered


def _pattern_specificity(pattern: str) -> Tuple[int, int]:
    """Sort key for override precedence: broad patterns first, exact last."""
    if not _has_wildcard(pattern):
        return (2, len(pattern))

    if pattern.startswith(("wf:", "ws:")):
        return (1, len(pattern))

    return (0, len(pattern))


def _has_wildcard(pattern: str) -> bool:
    """Whether *pattern* contains any fnmatch wildcard character."""
    return any(char in pattern for char in "*?[")


def _read_agents_map(path: Any) -> Dict[str, Any]:
    """Read the ``agents:`` mapping from one creator.yml file."""
    data = _read_yml(path)
    agents = data.get("agents")

    if not isinstance(agents, dict):
        return {}

    base_dir = Path(str(path)).expanduser().resolve().parent
    normalized: Dict[str, Any] = {}

    for name, entry in agents.items():
        if not isinstance(entry, dict):
            continue

        entry = dict(entry)
        prompt_file = entry.get("prompt_file")

        if prompt_file and not Path(str(prompt_file)).is_absolute():
            entry["prompt_file"] = str(base_dir / str(prompt_file))

        normalized[str(name)] = entry

    return normalized


def _read_yml(path: Any) -> Dict[str, Any]:
    """Parse a YAML mapping, returning ``{}`` for missing/invalid files."""
    if not path or not Path(str(path)).exists():
        return {}

    try:
        with safe_open(str(path), "r") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not read creator agents from %s: %s", path, exc)
        return {}

    return data if isinstance(data, dict) else {}


def _read_prompt_file(prompt_file: Any, base_dir: Optional[Any] = None) -> str:
    """Read a definition's prompt file, resolving relative paths."""
    if not prompt_file:
        return ""

    path = Path(str(prompt_file)).expanduser()

    if not path.is_absolute():
        path = Path(str(base_dir or Path.cwd())).expanduser() / path

    if not path.exists():
        logger.warning("Prompt file for creator agent not found: %s", path)
        return ""

    with safe_open(str(path), "r") as handle:
        return handle.read().strip()
