"""Creator helpers for custom command entries."""

from pathlib import Path

from cecli.helpers.creator import config_helpers


def build_custom_command_fragment(coder, scope_dir, name, config, content) -> tuple:
    """Write an optional command source file and build its creator.yml fragment."""
    file_path = Path(scope_dir) / "commands" / f"{name}.py"
    notes = []

    if content is not None:
        config_helpers.write_text(file_path, str(content))
        notes.append(f"Custom command source written to {file_path}")
    elif not file_path.exists():
        notes.append(f"Command file {file_path} does not exist yet; provide 'content'")

    return {"custom": {"command-paths": [str(file_path)]}}, notes


def remove_entry(data, name) -> bool:
    """Drop creator.yml command-path entries that point at the named command."""
    removed = False
    custom = data.get("custom")

    if isinstance(custom, dict):
        for key in ("command-paths", "command_paths"):
            items = custom.get(key)
            if isinstance(items, list):
                kept = [item for item in items if not config_helpers.references(item, name)]
                removed = removed or len(kept) != len(items)
                custom[key] = kept

    return removed


def default_file(scope_dir, name):
    """Return the default on-disk file backing a custom command entry."""
    return Path(scope_dir) / "commands" / f"{name}.py"


build_fragment = build_custom_command_fragment
