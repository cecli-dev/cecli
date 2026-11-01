"""Creator helpers for workflow entries."""

from pathlib import Path

import yaml

from cecli.helpers.creator import config_helpers


def build_workflow_fragment(coder, scope_dir, name, config, content) -> tuple:
    """Write a workflow document when needed and report discovery/enabled state."""
    file_path = Path(scope_dir) / "workflows" / f"{name}.yml"
    entry = None
    notes = []

    if content is not None:
        config_helpers.write_text(file_path, str(content))
        notes.append(f"Workflow written to {file_path}")
        parsed = config_helpers.parse_mapping(content)
        if isinstance(parsed, dict):
            entry = parsed
            if "name" not in entry:
                notes.append(
                    f"Warning: workflow '{name}' content has no name field; it will be skipped"
                )

    if entry is None and isinstance(config, dict):
        entry = dict(config)

    if entry is not None:
        entry.setdefault("name", name)
        if not file_path.exists():
            config_helpers.write_text(file_path, yaml.dump(entry, sort_keys=False))
            notes.append(f"Workflow written to {file_path}")
        if entry.get("enabled") is False:
            notes.append(
                f"Warning: workflow '{name}' has enabled: false; no wf: sub-agent registers"
            )
    elif not notes:
        notes.append(f"Workflow {file_path} is discovered from the workflows dir")

    return {}, notes


def remove_entry(data, name) -> bool:
    """Drop creator.yml workflow entries that refer to the named workflow."""
    items = data.get("workflows")
    if not isinstance(items, list):
        return False

    kept = [
        item
        for item in items
        if not (isinstance(item, dict) and item.get("name") == name)
        and not config_helpers.references(item, name)
    ]
    removed = len(kept) != len(items)
    data["workflows"] = kept

    return removed


def default_file(scope_dir, name):
    """Return the default on-disk file backing a workflow entry."""
    return Path(scope_dir) / "workflows" / f"{name}.yml"


build_fragment = build_workflow_fragment
