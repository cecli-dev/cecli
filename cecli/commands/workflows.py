"""/workflows — inspect and run declarative workflows.

Subcommands: list, run <name>, show <name>, status [name], last <name>,
enable/disable <name>, reload. ``run`` starts a background task so the REPL
is never blocked by a workflow.
"""

from cecli.commands.utils.base_command import BaseCommand


class WorkflowCommand(BaseCommand):
    NORM_NAME = "workflows"
    DESCRIPTION = "List, run and manage declarative workflows"
    show_completion_notification = True

    SUBCOMMANDS = ("list", "run", "show", "status", "last", "enable", "disable", "reload")
    NAME_SUBCOMMANDS = ("run", "show", "status", "last", "enable", "disable")
    HELPER_MODULES = {
        "list": "cecli.commands.workflow_helpers.list",
        "run": "cecli.commands.workflow_helpers.run",
        "show": "cecli.commands.workflow_helpers.show",
        "status": "cecli.commands.workflow_helpers.status",
        "last": "cecli.commands.workflow_helpers.last",
        "toggle": "cecli.commands.workflow_helpers.toggle",
        "reload": "cecli.commands.workflow_helpers.reload",
    }
    ALIASES = {
        "list-workflows": "list",
        "run-workflow": "run",
        "show-workflow": "show",
        "status-workflow": "status",
        "last-workflow": "last",
        "enable-workflow": "enable",
        "disable-workflow": "disable",
        "reload-workflows": "reload",
    }
    SUBCOMMAND_USAGE = {
        "list": "/workflows list",
        "run": "/workflows run <name>",
        "show": "/workflows show <name>",
        "status": "/workflows status [name]",
        "last": "/workflows last <name>",
        "enable": "/workflows enable <name>",
        "disable": "/workflows disable <name>",
        "reload": "/workflows reload",
    }

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Dispatch a workflows subcommand.

        Syntax:
            /workflows list             — Show loaded workflows (default)
            /workflows run <name>       — Start a manual run in the background
            /workflows show <name>      — Dump the workflow definition (YAML)
            /workflows status [name]    — Scheduler job state (config view if absent)
            /workflows last <name>      — Summary of the most recent run
            /workflows enable <name>    — Enable a workflow (this session)
            /workflows disable <name>   — Disable a workflow (this session)
            /workflows reload           — Re-read workflow definitions
        """
        parts = (args or "").strip().split(maxsplit=1)
        sub = parts[0].lower() if parts else "list"
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub == "list":
            await cls.loader("list").cmd_list(io, coder)
        elif sub == "run":
            await cls.loader("run").cmd_run(io, coder, rest)
        elif sub == "show":
            cls.loader("show").cmd_show(io, coder, rest)
        elif sub == "status":
            await cls.loader("status").cmd_status(io, coder, rest)
        elif sub == "last":
            await cls.loader("last").cmd_last(io, coder, rest)
        elif sub in ("enable", "disable"):
            await cls.loader("toggle").cmd_toggle(io, coder, rest, enable=(sub == "enable"))
        elif sub == "reload":
            cls.loader("reload").cmd_reload(io, coder)
        else:
            io.tool_error(f"Unknown subcommand '{sub}'. Try one of: {', '.join(cls.SUBCOMMANDS)}")

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the workflows command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /workflows list              # Show loaded workflows\n"
        help_text += "  /workflows run <name>        # Start a manual run in the background\n"
        help_text += "  /workflows show <name>       # Dump the workflow definition (YAML)\n"
        help_text += "  /workflows status [name]     # Scheduler job state or config view\n"
        help_text += "  /workflows last <name>       # Summary of the most recent run\n"
        help_text += "  /workflows enable <name>     # Enable a workflow (this session)\n"
        help_text += "  /workflows disable <name>    # Disable a workflow (this session)\n"
        help_text += "  /workflows reload            # Re-read workflow definitions\n"
        return help_text

    @classmethod
    def get_completions(cls, io, coder, args) -> list:
        """Complete subcommands, then workflow names for the name-taking ones."""
        from cecli.commands.workflow_helpers.common import workflows

        raw = args or ""
        partial = raw.strip()

        if " " not in partial:
            # A trailing space means the subcommand is settled and the caller
            # is now completing its argument, so offer the workflow names
            # (when the subcommand takes one) instead of the subcommand list.
            if raw and raw[-1].isspace():
                if partial.lower() in cls.NAME_SUBCOMMANDS:
                    return sorted(wf.name for wf in workflows(coder))

                return []

            return [s for s in cls.SUBCOMMANDS if s.startswith(partial)] or list(cls.SUBCOMMANDS)

        sub, _, rest = partial.partition(" ")
        if sub.lower() in cls.NAME_SUBCOMMANDS:
            names = sorted(wf.name for wf in workflows(coder))
            return [n for n in names if n.startswith(rest)]

        return []
