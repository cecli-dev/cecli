from cecli.commands.utils.base_command import BaseCommand


class WorkspaceCommand(BaseCommand):
    NORM_NAME = "workspace"
    DESCRIPTION = "List, open or register workspace sub-agents"
    show_completion_notification = True

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """List active workspace sub-agents, or open / register one.

        Syntax:
            /workspace                 — List active workspace sub-agents
            /workspace <ws:name>       — Open an already-registered ``ws:name`` sub-agent (like /spawn-agent)
            /workspace <name> <path>   — Register and open a ``ws:{name}`` sub-agent rooted at ``<path>``
        """
        parts = args.strip().split(maxsplit=1)

        if not parts:
            cls._list_workspace_subagents(io)
            return

        name = parts[0]
        path_arg = parts[1].strip() if len(parts) > 1 else None

        if path_arg is None:
            await cls._open_existing(io, coder, name)
            return

        await cls._register_and_open(io, coder, name, path_arg)

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the workspace command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /workspace              # List active workspace sub-agents\n"
        help_text += "  /workspace <ws:name>    # Open an already-registered ws: sub-agent (like /spawn-agent)\n"
        help_text += "  /workspace <name> <path>  # Register and open a ws:{name} sub-agent rooted at <path>\n"
        return help_text

    @classmethod
    def get_completions(cls, io, coder, args) -> list[str]:
        """Return tab-completions for the workspace command.

        - The first argument (the ``ws:{name}`` sub-agent name) is completed from
          the active workspace sub-agent names, including the ``ws:`` prefix.
        - The second argument (the project path) is completed by browsing the
          folders at the typed path, independent of the coder's file completion
          index. The folder list is ranked with rapidfuzz + ngram so prefix
          matches surface first.
        """
        from cecli.helpers.agents.service import AgentService

        partial = (args or "").strip()

        if not partial or partial.startswith("ws:"):
            return [name for name in AgentService.get_registry() if name.startswith("ws:")]

        return cls._get_path_completions(partial)

    @classmethod
    def _list_workspace_subagents(cls, io) -> None:
        """Print the registered ``ws:{name}`` workspace sub-agents and their roots."""
        from cecli.helpers.agents.service import AgentService

        registry = AgentService.get_registry()
        ws_agents = sorted((name, cfg) for name, cfg in registry.items() if name.startswith("ws:"))

        if not ws_agents:
            io.tool_output("No workspace sub-agents are active.")
            return

        io.print("Workspace Sub-Agents:")
        for name, cfg in ws_agents:
            metadata = getattr(cfg, "metadata", {}) or {}
            io.print(f"  - {name}")
            io.print(f"    Root:   {metadata.get('root')}")
            io.print(f"    Layout: {metadata.get('layout')}")
            io.print("")

    @classmethod
    async def _open_existing(cls, io, coder, name) -> None:
        """Open an already-registered workspace sub-agent, mirroring /spawn-agent."""
        from cecli.helpers.agents.service import AgentService

        if not name.startswith("ws:"):
            io.tool_error(f"Error: '{name}' is not a registered workspace sub-agent.")
            return

        if name not in AgentService.get_registry():
            io.tool_error(f"Error: workspace sub-agent '{name}' is not registered.")
            return

        try:
            agent_service = AgentService.get_instance(coder)
            new_coder, info = await agent_service.spawn(
                name, prompt=None, parent=coder, auto_reap=False, independent=True
            )

            agent_service.foreground_uuid = info.coder.uuid

            if coder.tui and coder.tui():
                tui = coder.tui()
                switch_key = tui.get_keys_for("next_agent")
                io.tool_output(f"Sub-agent '{name}' spawned and active. Switch with {switch_key}")

                try:
                    tui.call_from_thread(tui._switch_to_container, info.coder.uuid)
                except Exception:
                    pass
            else:
                io.tool_output(f"Opened workspace sub-agent '{name}'.")
        except ValueError as e:
            io.tool_error(f"Error: {e}")
        except RuntimeError as e:
            io.tool_error(f"Error: {e}")
        except Exception as e:
            io.tool_error(f"Error spawning sub-agent '{name}': {e}")

    @classmethod
    async def _register_and_open(cls, io, coder, name, path_arg) -> None:
        """Register a ``ws:{name}`` sub-agent rooted at ``<path>`` and open it."""
        from pathlib import Path

        from cecli.helpers.agents.service import AgentService
        from cecli.helpers.workspaces.subagents import register_workspace_subagents

        project_name = name[3:] if name.startswith("ws:") else name
        agent_name = f"ws:{project_name}"
        path = Path(path_arg).expanduser()

        config = {
            "name": project_name,
            "projects": [{"name": project_name, "path": str(path)}],
        }
        registered = register_workspace_subagents(config)
        if agent_name not in registered:
            io.tool_error(f"Error: '{path}' is not a valid git repository or does not exist.")
            return

        root = AgentService.get_registry()[agent_name].metadata.get("root")

        try:
            agent_service = AgentService.get_instance(coder)
            new_coder, info = await agent_service.spawn(
                agent_name, prompt=None, parent=coder, auto_reap=False, independent=True
            )

            agent_service.foreground_uuid = info.coder.uuid

            if coder.tui and coder.tui():
                tui = coder.tui()
                switch_key = tui.get_keys_for("next_agent")
                io.tool_output(
                    f"Opened workspace sub-agent '{agent_name}' rooted at {root}. Switch with {switch_key}"
                )

                try:
                    tui.call_from_thread(tui._switch_to_container, info.coder.uuid)
                except Exception:
                    pass
            else:
                io.tool_output(f"Opened workspace sub-agent '{agent_name}' rooted at {root}.")
        except Exception as e:
            io.tool_error(f"Error opening workspace sub-agent '{agent_name}': {e}")

    @classmethod
    def _get_path_completions(cls, partial: str) -> list[str]:
        """Browse the filesystem for folders matching the typed path prefix."""
        from pathlib import Path

        path = Path(partial)
        if partial.endswith("/"):
            search_dir = path
            name_prefix = ""
        else:
            search_dir = path.parent
            name_prefix = path.name

        if not search_dir.is_dir():
            return []

        if search_dir == Path("."):
            path_prefix = ""
        else:
            path_prefix = str(search_dir).rstrip("/") + "/"

        folders: list[str] = []
        try:
            for entry in search_dir.iterdir():
                if entry.is_dir():
                    folders.append(path_prefix + entry.name + "/")
        except (PermissionError, OSError):
            return []

        if name_prefix:
            prefix_lower = name_prefix.lower()
            folders = [f for f in folders if Path(f).name.lower().startswith(prefix_lower)]

        return cls._rank_paths(partial, folders)

    @staticmethod
    def _rank_paths(query: str, candidates: list[str]) -> list[str]:
        """Order path candidates with rapidfuzz + ngram so prefix matches surface first."""
        if not candidates:
            return []

        query_lower = query.lower()

        try:
            from ngram import NGram
            from rapidfuzz import fuzz, process
        except ImportError:
            return sorted(
                candidates,
                key=lambda c: (not c.lower().startswith(query_lower), c.lower()),
            )

        lower_candidates = [c.lower() for c in candidates]
        results = process.extract(
            query_lower,
            lower_candidates,
            scorer=fuzz.partial_ratio,
            limit=min(len(candidates), 20),
            score_cutoff=0,
        )

        matched = [candidates[idx] for _, _, idx in results]

        if len(matched) < 100:
            ng = NGram([c.lower() for c in matched], N=3)
            reranked = ng.search(query_lower, threshold=0.0)
            original_by_lower = {c.lower(): c for c in matched}
            matched = [original_by_lower.get(item.lower(), item) for item, _ in reranked]

        return matched
