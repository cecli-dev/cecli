"""Creator helpers for hook entries."""

from pathlib import Path

from cecli.helpers.creator import config_helpers


def build_hook_fragment(coder, scope_dir, name, config, content, apply_to=None) -> tuple:
    """Write an optional hook source file and build its creator.yml fragment.

    The hook definition stays in the shared ``hooks:`` section; ``apply_to``
    adds a per-agent copy so the spawn-time merge loads it for those agents.
    """
    payload = config_helpers.as_mapping(config, content)
    notes = []

    if content is not None:
        file_path = Path(scope_dir) / "hooks" / f"{name}.py"
        config_helpers.write_text(file_path, str(content))
        payload.setdefault("path", str(file_path))
        notes.append(f"Hook source written to {file_path}")

    fragment = {"hooks": {name: payload}}

    if apply_to:
        entries = {target: {"hooks": {name: payload}} for target in apply_to}
        fragment.update(config_helpers.agents_fragment(entries))

    return fragment, notes


def remove_entry(data, name, apply_to=None) -> bool:
    """Pop the named hook from the hooks section or per-agent overrides."""
    if apply_to:
        return config_helpers.prune_agent_references(data, apply_to, (), name, hooks=True)

    section = data.get("hooks")
    removed = False

    if isinstance(section, dict) and name in section:
        section.pop(name)
        removed = True

    return config_helpers.prune_agent_references(data, ["*"], (), name, hooks=True) or removed


def default_file(scope_dir, name):
    """Return the default on-disk file backing a hook entry."""
    return Path(scope_dir) / "hooks" / f"{name}.py"


build_fragment = build_hook_fragment
