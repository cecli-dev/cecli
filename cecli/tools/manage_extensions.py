"""ManageExtensions tool - persists cecli extensions into the session's creator.yml files."""

import json
import shutil
from pathlib import Path

from cecli.helpers.creator import (
    config_helpers,
    custom_command_helpers,
    custom_tool_helpers,
    hook_helpers,
    mcp_helpers,
    skills_helpers,
    workflow_helpers,
)
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError, is_creator_coder
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations

ACTIONS = ("add", "update", "remove", "list")
TYPES = ("mcp_server", "hook", "skill", "custom_tool", "custom_command", "workflow", "config")
SCOPES = ("global", "local")

_EXTENSION_MODULES = {
    "mcp_server": mcp_helpers,
    "hook": hook_helpers,
    "skill": skills_helpers,
    "custom_tool": custom_tool_helpers,
    "custom_command": custom_command_helpers,
    "workflow": workflow_helpers,
}


class Tool(BaseTool):
    NORM_NAME = "manageextensions"
    RESULT_TYPE = "list"
    TRACK_INVOCATIONS = False
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ManageExtensions",
            "description": (
                "Manage persisted cecli extensions and config in creator.yml so they "
                "survive sessions. One action per call: add/update entries of a given "
                "type into the global (~/.cecli/creator.yml) or local "
                "(<root>/.cecli/creator.yml) file, remove entries, or list current "
                "contents. Scoped to the creator sub-agent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(ACTIONS),
                        "description": "Operation to perform.",
                    },
                    "type": {
                        "type": "string",
                        "enum": list(TYPES),
                        "description": "Kind of entry to create, update, remove, or list.",
                    },
                    "scope": {
                        "type": "string",
                        "enum": list(SCOPES),
                        "default": "local",
                        "description": (
                            "Which creator.yml to write. Prefer 'local' unless the user "
                            "asks for a global extension."
                        ),
                    },
                    "name": {
                        "type": "string",
                        "description": (
                            "Entry name: the file/dir name for skill, custom_tool, "
                            "custom_command and workflow entries; the dict key (or dotted "
                            "config key path for type 'config') for mcp_server, hook and "
                            "config entries."
                        ),
                    },
                    "config": {
                        "description": (
                            "Payload stored or deep-merged for the entry (mapping for "
                            "mcp_server/hook, arbitrary value for dotted config paths)."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "Full file content for file-backed entries, e.g. a SKILL.md "
                            "body, a custom tool .py source, or a workflow yml document."
                        ),
                    },
                    "apply_to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": (
                            "Agent names or patterns to scope this entry to, e.g. "
                            "['reviewer'], ['wf:*'], ['ws:newsletter'], ['*']. Omit to "
                            "write the shared config exactly as today (primary and "
                            "inheriting agents)."
                        ),
                    },
                },
                "required": ["action", "type"],
            },
        },
    }

    @classmethod
    async def execute(
        cls,
        coder,
        action=None,
        type=None,
        scope="local",
        name=None,
        config=None,
        content=None,
        apply_to=None,
        **kwargs,
    ):
        """Persist an extension or config change into the session's creator.yml.

        Parameters
        ----------
        coder: Coder instance
            The active coder; must be a creator-mode agent.
        action: str
            One of add, update, remove, list.
        type: str
            One of mcp_server, hook, skill, custom_tool, custom_command, workflow, config.
        scope: str
            'global' writes ~/.cecli/creator.yml, 'local' writes <root>/.cecli/creator.yml.
        name: str
            Entry name; a dotted key path when type is 'config'.
        config: any
            Payload to deep-merge for the entry.
        content: str
            Optional full file content for file-backed entries.
        apply_to: list
            Agent names or fnmatch patterns to scope the change to. Empty means
            the shared config; unsupported for custom_tool/custom_command/workflow.

        Returns
        -------
        ToolResponse with a summary line plus the reload helper's messages.
        """
        if not is_creator_coder(coder):
            raise ToolError(
                "The ManageExtensions tool is scoped to the creator sub-agent. Delegate the "
                "request to the creator agent instead."
            )

        action = str(action or "").strip().lower()
        entry_type = str(type or "").strip().lower()
        scope = str(scope or "local").strip().lower()

        if action not in ACTIONS:
            raise ToolError(f"Unknown action '{action}'. Expected one of: {', '.join(ACTIONS)}.")

        if entry_type not in TYPES:
            raise ToolError(f"Unknown type '{entry_type}'. Expected one of: {', '.join(TYPES)}.")

        if scope not in SCOPES:
            raise ToolError(f"Unknown scope '{scope}'. Expected 'global' or 'local'.")

        global_yml, local_yml = config_helpers.creator_paths(coder)
        target = global_yml if scope == "global" else local_yml

        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)

        if action == "list":
            config_helpers.list_creator_files(response, global_yml, local_yml)
            return response

        name = str(name or "").strip()
        if not name:
            raise ToolError(f"'name' is required for action '{action}'.")

        apply_to = config_helpers.validate_apply_to(apply_to, entry_type, name)

        coder.io.tool_output(
            f"✚ Creator extension update: {action} {entry_type} '{name}' ({scope})",
            type="tool-result",
        )

        if action == "remove":
            notes = cls._remove_entry(target, entry_type, name, config, apply_to)
        else:
            notes = cls._add_entry(coder, target, entry_type, name, config, content, apply_to)

        notes.extend(cls._refresh_agent_overrides(coder))

        for note in notes:
            response.append_result(note)

        if apply_to:
            response.append_result(f"Targeted agents: {', '.join(apply_to)}")
        else:
            response.append_result(
                "Shared config (applies to the primary and inheriting agents); "
                "pass apply_to to scope this change."
            )

        for message in await config_helpers.reload_for_type(coder, entry_type):
            response.append_result(message)

        if entry_type == "skill":
            if action == "remove":
                scope_dir = Path(target).parent
                skill_dir = skills_helpers.default_file(scope_dir, name)
                messages = skills_helpers.deactivate_skill(
                    coder, name, blacklist=skill_dir.exists(), apply_to=apply_to
                )
            else:
                messages = skills_helpers.activate_skill(coder, name, apply_to=apply_to)

            for message in messages:
                response.append_result(message)

        return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for ManageExtensions tool - preview the requested change."""
        color_start, color_end = color_markers(coder)

        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        try:
            params = ToolValidations.validate_params(
                tool_response.function.arguments, cls.VALIDATIONS, cls.SCHEMA
            )
        except ToolError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        if not isinstance(params, dict):
            coder.io.tool_error("Invalid Tool JSON")
            return

        action = params.get("action", "")
        entry_type = params.get("type", "")
        scope = params.get("scope", "local")

        summary = (
            f"{color_start}action:{color_end} {action} • "
            f"{color_start}type:{color_end} {entry_type} • "
            f"{color_start}scope:{color_end} {scope}"
        )

        name = params.get("name")
        if name:
            summary += f" • {color_start}name:{color_end} {name}"

        coder.io.tool_output(summary)

        apply_to = params.get("apply_to") or []
        if apply_to:
            coder.io.tool_output(
                f"{color_start}apply_to:{color_end} {', '.join(str(item) for item in apply_to)}"
            )

        config = params.get("config")
        if config is not None:
            if isinstance(config, str):
                rendered_config = config
            else:
                rendered_config = json.dumps(config, ensure_ascii=False, default=str)

            coder.io.tool_output(f"{color_start}config:{color_end} {rendered_config}")

        content = params.get("content")
        if content:
            coder.io.tool_output("")
            coder.io.tool_output(f"{color_start}content:{color_end}")
            for line in str(content).splitlines():
                coder.io.tool_output(f"  {line}")

        tool_footer(coder=coder, tool_response=tool_response, params=params)

    @classmethod
    def _add_entry(cls, coder, path, entry_type, name, config, content, apply_to=None) -> list:
        """Build the fragment for an add/update, write any backing files, merge it in."""
        scope_dir = Path(path).parent
        notes = []

        if entry_type == "config":
            keys = name.split(".")
            if apply_to:
                keys = ["agents", apply_to[0]] + keys
            fragment = config_helpers.nested(keys, config_helpers.as_payload(config, content))
        elif entry_type in ("skill", "mcp_server", "hook"):
            fragment, notes = _EXTENSION_MODULES[entry_type].build_fragment(
                coder, scope_dir, name, config, content, apply_to
            )
        else:
            fragment, notes = _EXTENSION_MODULES[entry_type].build_fragment(
                coder, scope_dir, name, config, content
            )

        if fragment:
            config_helpers.merge_fragment(path, fragment)
            notes.append(f"Merged into {path} ({scope_dir.name} scope)")

        return notes

    @classmethod
    def _remove_entry(cls, path, entry_type, name, config, apply_to=None) -> list:
        """Pop an entry from creator.yml; backing files are only removed on request.

        For file-backed types the backing file is itself the entry, so its
        presence is enough to consider the removal successful even when
        creator.yml no longer has a reference to it.
        """
        data = config_helpers.read_yml(path)
        file_path = None

        if entry_type == "config":
            if apply_to:
                entry_removed = config_helpers.pop_agent_path(data, apply_to[0], name.split("."))
            else:
                entry_removed = config_helpers.pop_nested(data, name.split("."))
        else:
            module = _EXTENSION_MODULES[entry_type]
            if apply_to and entry_type in ("skill", "mcp_server", "hook"):
                entry_removed = module.remove_entry(data, name, apply_to)
            else:
                entry_removed = module.remove_entry(data, name)
            file_path = module.default_file(Path(path).parent, name)

        file_exists = file_path is not None and file_path.exists()
        if not entry_removed and not file_exists:
            return [f"No {entry_type} entry referencing '{name}' found in {path}."]

        if entry_removed:
            notes = [f"Removed {entry_type} entry '{name}' from {path}"]
        else:
            notes = [f"Removed {entry_type} '{name}' (file-backed) from {path}"]

        delete_files = isinstance(config, dict) and bool(config.get("delete_files"))
        if file_exists:
            if delete_files:
                still_used = cls._remaining_references(data, entry_type, name) if apply_to else []

                if still_used:
                    notes.append(f"Kept {file_path}; still referenced by: {', '.join(still_used)}")
                else:
                    if file_path.is_dir():
                        shutil.rmtree(file_path)
                    else:
                        file_path.unlink()
                    notes.append(f"Deleted {file_path}")
            else:
                notes.append(f"File {file_path} left on disk (config-only removal)")

        if entry_removed:
            config_helpers.write_yml(path, data)

        return notes

    @classmethod
    def _refresh_agent_overrides(cls, coder) -> list:
        """Re-read creator.yml so later spawns see per-agent overrides immediately."""
        try:
            from cecli.helpers.agents.overrides import refresh_agent_overrides
        except Exception as exc:
            return [f"Agent overrides take effect on restart (refresh unavailable: {exc})"]

        root = getattr(coder, "primary_root", None) or getattr(coder, "root", None)

        try:
            refresh_agent_overrides(root)
        except Exception as exc:
            return [
                "creator.yml updated; agent overrides take effect on restart "
                f"(refresh failed: {exc})"
            ]

        return []

    @classmethod
    def _remaining_references(cls, data, entry_type, name) -> list:
        """Return labels of config sections that still reference *name*."""
        if not isinstance(data, dict):
            return []

        references = []

        def collect(section, label):
            if not isinstance(section, dict):
                return

            if entry_type == "skill":
                for key in ("skills_includelist", "skills_init"):
                    items = section.get(key)
                    if isinstance(items, list) and name in items:
                        references.append(label)
                        break

                items = section.get("skills_paths")
                if isinstance(items, list) and any(
                    config_helpers.references(item, name) for item in items
                ):
                    references.append(label)

            elif entry_type == "hook":
                hooks = section.get("hooks")
                if isinstance(hooks, dict) and name in hooks:
                    references.append(label)

        collect(data, "shared config")
        collect(data.get("agent-config"), "shared config")

        agents = data.get("agents")
        if isinstance(agents, dict):
            for target, node in agents.items():
                if not isinstance(node, dict):
                    continue

                if entry_type == "skill":
                    collect(node.get("agent-config"), target)
                elif entry_type == "hook":
                    collect(node, target)

        return list(dict.fromkeys(references))
