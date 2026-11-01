"""Creator helpers for skill entries."""

from pathlib import Path

from cecli.helpers.creator import config_helpers
from cecli.helpers.creator import utils as creator_utils


def build_skill_fragment(coder, scope_dir, name, config, content, apply_to=None) -> tuple:
    """Write (or scaffold) a skill's SKILL.md and build its creator.yml fragment."""
    scope_dir = Path(scope_dir)
    skill_root = scope_dir / "skills"
    file_path = skill_root / name / "SKILL.md"
    notes = []

    if content is not None:
        config_helpers.write_text(file_path, str(content))
        notes.append(f"SKILL.md written to {file_path}")
    elif not file_path.exists():
        description = ""
        if isinstance(config, dict):
            description = str(config.get("description", ""))
        config_helpers.write_text(
            file_path, f"---\nname: {name}\ndescription: {description}\n---\n"
        )
        notes.append(f"Scaffolded {file_path}; fill in the skill body")

    if apply_to:
        fragment = _per_agent_fragment(coder, apply_to, name, skill_root)

        return fragment, notes

    agent_config = {"skills_paths": [str(skill_root)]}

    if coder is not None and config_helpers.has_agent_config_whitelist(coder, "skills_includelist"):
        agent_config["skills_includelist"] = [name]

    return {"agent-config": agent_config}, notes


def remove_entry(data, name, apply_to=None) -> bool:
    """Drop creator.yml path/include entries that point at the named skill."""
    keys = ("skills_includelist", "skills_init")

    if apply_to:
        return config_helpers.prune_agent_references(data, apply_to, keys, name, prune_paths=True)

    removed = _remove_shared_references(data, name)
    removed = (
        config_helpers.prune_agent_references(data, ["*"], keys, name, prune_paths=True) or removed
    )

    return removed


def activate_skill(coder, name, apply_to=None) -> list:
    """Make a newly created skill visible and loaded in the live session.

    A skills include list hides every skill not on it, so the fresh skill
    must be whitelisted before it can be found; coders without an include
    list already see it via the reloaded directories and only need loading.
    When *apply_to* is set, only coders matching those agents are touched.
    """
    messages = []
    seen = set()

    for item in creator_utils._iter_coders(coder):
        manager = getattr(item, "skills_manager", None)
        if manager is None or not _matches_target(item, apply_to):
            continue

        include_list = getattr(manager, "include_list", None)
        if include_list and name not in include_list:
            message = manager.include_skill(name)
            if message not in seen:
                seen.add(message)
                messages.append(message)

        if name not in getattr(manager, "_loaded_skills", set()):
            message = manager.load_skill(name)
            if message not in seen:
                seen.add(message)
                messages.append(message)

    return messages


def deactivate_skill(coder, name, blacklist=True, apply_to=None) -> list:
    """Unload a removed skill and optionally hide it from live coders.

    Unloading is always safe; blacklisting is only needed when the skill's
    backing directory remains on disk (config-only removal) so implicit skills
    directories do not rediscover it. The exclusion is added directly to avoid
    ``exclude_skill``'s include-list reset, which would expose every other
    skill when the removed one was the sole whitelisted entry. When *apply_to*
    is set, only coders matching those agents are touched.
    """
    messages = []
    seen = set()

    for item in creator_utils._iter_coders(coder):
        manager = getattr(item, "skills_manager", None)
        if manager is None or not _matches_target(item, apply_to):
            continue

        include_list = getattr(manager, "include_list", None)
        if include_list is not None and name in include_list:
            include_list.discard(name)

        if name in getattr(manager, "_loaded_skills", set()):
            message = manager.remove_skill(name)
            if message not in seen:
                seen.add(message)
                messages.append(message)

        if blacklist:
            manager.exclude_list.add(name)
            save_state = getattr(manager, "_save_state", None)
            if callable(save_state):
                save_state()

    return messages


def _matches_target(coder, apply_to) -> bool:
    """Return True when *coder* is targeted by *apply_to* (empty means all)."""
    if not apply_to:
        return True

    name = creator_utils._agent_name(coder)
    if not name:
        return False

    return config_helpers.matches_any_target(name, apply_to)


def default_file(scope_dir, name):
    """Return the default on-disk directory backing a skill entry."""
    return Path(scope_dir) / "skills" / name


def _per_agent_fragment(coder, apply_to, name, skill_root) -> dict:
    """Build one ``agents.<target>`` node per target for a skill entry."""
    whitelisted = set(config_helpers.targets_with_whitelist(coder, apply_to, "skills_includelist"))
    entries = {}
    for target in apply_to:
        agent_config = {"skills_paths": [str(skill_root)]}
        if target in whitelisted:
            agent_config["skills_includelist"] = [name]
        entries[target] = {"agent-config": agent_config}

    return config_helpers.agents_fragment(entries)


def _remove_shared_references(data, name) -> bool:
    """Drop path/include references to *name* from the shared config."""
    removed = False
    sections = [data]

    if isinstance(data.get("agent-config"), dict):
        sections.append(data["agent-config"])

    for section in sections:
        items = section.get("skills_paths")
        if isinstance(items, list):
            kept = [item for item in items if not config_helpers.references(item, name)]
            removed = removed or len(kept) != len(items)
            section["skills_paths"] = kept

    removed = config_helpers.pop_list_value(sections, "skills_includelist", name) or removed
    removed = config_helpers.pop_list_value(sections, "skills_init", name) or removed

    return removed


build_fragment = build_skill_fragment
