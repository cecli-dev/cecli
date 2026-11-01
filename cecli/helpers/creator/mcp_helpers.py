"""Creator helpers for MCP server entries."""

from cecli.helpers.creator import config_helpers


def build_mcp_fragment(coder, scope_dir, name, config, content, apply_to=None) -> tuple:
    """Build the creator.yml fragment for an MCP server entry."""
    fragment = {"mcp-servers": {name: config_helpers.as_mapping(config, content)}}

    if apply_to:
        fragment.update(_per_agent_fragment(coder, apply_to, name))

        return fragment, []

    if coder is not None and config_helpers.has_agent_config_whitelist(
        coder, "servers_includelist"
    ):
        fragment["agent-config"] = {"servers_includelist": [name]}

    return fragment, []


def remove_entry(data, name, apply_to=None) -> bool:
    """Pop the named server and any servers_includelist reference."""
    if apply_to:
        return config_helpers.prune_agent_references(data, apply_to, ("servers_includelist",), name)

    removed = _remove_shared_references(data, name)
    removed = (
        config_helpers.prune_agent_references(data, ["*"], ("servers_includelist",), name)
        or removed
    )

    return removed


def default_file(scope_dir, name):
    """MCP servers have no backing file on disk."""
    return None


def _per_agent_fragment(coder, apply_to, name) -> dict:
    """Build one ``agents.<target>`` node per filtering target."""
    whitelisted = set(config_helpers.targets_with_whitelist(coder, apply_to, "servers_includelist"))
    entries = {
        target: {"agent-config": {"servers_includelist": [name]}}
        for target in apply_to
        if target in whitelisted
    }

    return config_helpers.agents_fragment(entries)


def _remove_shared_references(data, name) -> bool:
    """Pop the server definition and its shared include reference."""
    section = data.get("mcp-servers")
    removed = False

    if isinstance(section, dict) and name in section:
        section.pop(name)
        removed = True

    sections = [data]
    if isinstance(data.get("agent-config"), dict):
        sections.append(data["agent-config"])

    return config_helpers.pop_list_value(sections, "servers_includelist", name) or removed


build_fragment = build_mcp_fragment
