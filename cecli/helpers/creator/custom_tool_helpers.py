"""Creator helpers for custom tool entries."""

from pathlib import Path

from cecli.helpers.creator import config_helpers


def build_custom_tool_fragment(coder, scope_dir, name, config, content) -> tuple:
    """Write an optional tool source file and build its creator.yml fragment."""
    tools_root = Path(scope_dir) / "tools"
    file_path = tools_root / f"{name}.py"
    notes = []

    if content is not None:
        config_helpers.write_text(file_path, str(content))
        notes.append(f"Custom tool source written to {file_path}")
    elif not file_path.exists():
        notes.append(f"Tool file {file_path} does not exist yet; provide 'content'")

    if coder is not None and config_helpers.tool_is_excluded(coder, name):
        notes.append(
            f"Note: a live coder's tools_excludelist names '{name}'; it will stay hidden there"
        )

    return {"agent-config": {"tools_paths": [str(tools_root)]}}, notes


def remove_entry(data, name) -> bool:
    """Drop creator.yml path and include/exclude references to the named tool."""
    removed = False
    sections = [data]

    if isinstance(data.get("agent-config"), dict):
        sections.append(data["agent-config"])

    for section in sections:
        items = section.get("tools_paths")
        if isinstance(items, list):
            kept = [item for item in items if not config_helpers.references(item, name)]
            removed = removed or len(kept) != len(items)
            section["tools_paths"] = kept

    removed = config_helpers.pop_list_value(sections, "tools_includelist", name) or removed
    removed = config_helpers.pop_list_value(sections, "tools_excludelist", name) or removed

    return removed

    return removed


def default_file(scope_dir, name):
    """Return the default on-disk file backing a custom tool entry."""
    return Path(scope_dir) / "tools" / f"{name}.py"


build_fragment = build_custom_tool_fragment
