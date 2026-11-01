"""``/workflows show`` — dump a workflow definition."""

from cecli.commands.workflow_helpers.common import require


def cmd_show(io, coder, name) -> None:
    """Dump the workflow definition as YAML."""
    import yaml

    wf = require(io, coder, name, "show")
    if wf is None:
        return

    io.tool_output(yaml.dump(wf.to_dict(), sort_keys=False, default_flow_style=False))
