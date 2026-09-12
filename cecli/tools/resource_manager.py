import os
import re
import time

from cecli.commands.utils.helpers import (
    is_server_globally_excluded,
    iter_all_coders,
    update_server_registration,
)
from cecli.decoding import safe_open
from cecli.helpers.background_commands import BackgroundCommandManager
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError, parse_arg_as_list
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "resourcemanager"
    RESULT_TYPE = "list"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ResourceManager",
            "description": (
                "Manage files, long running commands, skills, and MCP servers"
                " in the chat context: add, read_only, create, remove files;"
                " view up to 3 pages of command output with paging;"
                " stop background commands; load/remove skills and load/remove MCP servers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "add": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of file paths to add to context. Limit to at most 2 at a time. "
                            "Command output aliases (command_key::) are rejected; use paging instead."
                        ),
                    },
                    "read_only": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of file paths to add as read-only. Limit to at most 2 at a time. "
                            "Command output aliases (command_key::) are rejected; use paging instead."
                        ),
                    },
                    "create": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to create.",
                    },
                    "remove": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of file paths to remove from context.",
                    },
                    "stop": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of command keys to stop background commands for.",
                    },
                    "load_skill": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of skill names to load.",
                    },
                    "remove_skill": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of skill names to remove.",
                    },
                    "load_mcp": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of MCP server names to load. Use '*' to load all enabled servers."
                        ),
                    },
                    "remove_mcp": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of MCP server names to remove. Use '*' to remove all connected servers."
                        ),
                    },
                    "actions": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["list_mcp_servers"]},
                        "description": (
                            "List of action operations to perform. "
                            'Possible values: "list_mcp_servers" to list MCP servers.'
                        ),
                    },
                    "paging": {
                        "type": "array",
                        "description": (
                            "View 1-3 saved command output pages without adding files to context. "
                            'Format: [{"target": "<command key>", "page": 1}]. '
                            "Pages are numbered from 1."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "target": {
                                    "type": "string",
                                    "description": (
                                        "Command key returned by Command (e.g., bg_1_1234), "
                                        "matching ^bg_[0-9]+_[0-9]+$."
                                    ),
                                },
                                "page": {"type": "integer", "minimum": 1},
                            },
                            "required": ["target", "page"],
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
                "required": [],
            },
        },
    }

    @classmethod
    async def execute(
        cls,
        coder,
        remove=None,
        add=None,
        read_only=None,
        create=None,
        stop=None,
        load_skill=None,
        remove_skill=None,
        load_mcp=None,
        remove_mcp=None,
        actions=None,
        paging=None,
        **kwargs,
    ):
        """Perform batch operations on the coder's context.

        Parameters
        ----------
        coder: Coder instance
            The active coder handling file context.
        remove: list[str] | None
            Files to remove from the context.
        add: list[str] | None
            Files to promote to editable status (not command output aliases).
        read_only: list[str] | None
            Files to add as read-only (not command output aliases).
        create: list[str] | None
            Files to create and make editable.
        stop: list[str] | None
            Command keys to stop background commands for.
        load_skill: list[str] | None
            Skill names to load.
        remove_skill: list[str] | None
            Skill names to remove.
        load_mcp: list[str] | None
            MCP server names to load.
        remove_mcp: list[str] | None
            MCP server names to remove.
        actions: list[str] | None
            Action operations to perform (e.g., "list_mcp_servers").
        paging: list[dict] | None
            One to three saved output pages: [{"target": command_key, "page": positive_int}].
            Returns contents directly without adding the pages to file context.
        """
        remove_files = sorted(parse_arg_as_list(remove), key=cls._natural_sort_key)
        editable_files = sorted(parse_arg_as_list(add), key=cls._natural_sort_key)
        view_files = sorted(parse_arg_as_list(read_only), key=cls._natural_sort_key)
        create_files = sorted(parse_arg_as_list(create), key=cls._natural_sort_key)
        stop_keys = sorted(parse_arg_as_list(stop), key=cls._natural_sort_key)
        load_skill_names = sorted(parse_arg_as_list(load_skill), key=cls._natural_sort_key)
        remove_skill_names = sorted(parse_arg_as_list(remove_skill), key=cls._natural_sort_key)
        load_mcp_servers = sorted(parse_arg_as_list(load_mcp), key=cls._natural_sort_key)
        remove_mcp_servers = sorted(parse_arg_as_list(remove_mcp), key=cls._natural_sort_key)
        action_operations = sorted(parse_arg_as_list(actions), key=cls._natural_sort_key)

        for file_path in editable_files + view_files:
            if file_path.startswith("command_key::"):
                raise ToolError(
                    "Command output files cannot be viewed with add or read_only. "
                    'Use paging=[{"target": "<command key>", "page": 1}] instead.'
                )

        if paging is not None:
            cls._validate_paging(paging)

        if (
            not remove_files
            and not editable_files
            and not view_files
            and not create_files
            and not stop_keys
            and not load_skill_names
            and not remove_skill_names
            and not load_mcp_servers
            and not remove_mcp_servers
            and not action_operations
            and paging is None
        ):
            raise ToolError(
                "You must specify at least one of: remove, add, read_only, create, stop, "
                "load_skill, remove_skill, load_mcp, remove_mcp, actions, or paging"
            )

        coder.io.tool_output("⛭ Modifying Context", type="tool-result")
        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)

        for page_request in paging or []:
            try:
                response.append_result(cls._read_command_page(coder, page_request))
            except OSError as e:
                response.append_error(
                    f"Unable to read command output page {page_request['page']} "
                    f"for {page_request['target']}: {e}"
                )

        # Expand wildcards for MCP operations
        if "*" in load_mcp_servers and coder.mcp_manager:
            servers = coder.mcp_manager.servers or []
            if isinstance(coder.mcp_manager.connected_servers, dict):
                connected_names = set(coder.mcp_manager.connected_servers.keys())
            else:
                connected_names = {
                    getattr(s, "name", s) for s in coder.mcp_manager.connected_servers
                }
            load_mcp_servers = [
                s.name
                for s in servers
                if s.name not in connected_names and s.config.get("enabled", True)
            ]
        if "*" in remove_mcp_servers and coder.mcp_manager:
            if isinstance(coder.mcp_manager.connected_servers, dict):
                remove_mcp_servers = list(coder.mcp_manager.connected_servers.keys())
            else:
                remove_mcp_servers = [
                    getattr(s, "name", s) for s in coder.mcp_manager.connected_servers
                ]

        # Before connecting any new MCP server, convert coders with empty
        # included sets to explicit include lists.
        if load_mcp_servers and coder.mcp_manager:
            if isinstance(coder.mcp_manager.connected_servers, dict):
                connected_names = {k.lower() for k in coder.mcp_manager.connected_servers.keys()}
            else:
                connected_names = {s.name.lower() for s in coder.mcp_manager.connected_servers}
            if connected_names:
                for c in iter_all_coders(coder):
                    if not c.registered_servers["included"]:
                        included = set(connected_names) - c.registered_servers["excluded"]
                        if c.edit_format in ("agent", "subagent"):
                            included.add("local")
                        c.registered_servers["included"] = included

        for f in create_files:
            response.append_result(cls._create(coder, f))
        for f in remove_files:
            response.append_result(cls._remove(coder, f))
        for f in view_files:
            response.append_result(cls._view(coder, f))
        for f in editable_files:
            try:
                abs_path = coder.abs_root_path(f)
            except Exception:
                abs_path = None
            if abs_path is not None and not os.path.isfile(abs_path):
                coder.io.tool_output(f"ℹ️ `{f}` missing on disk — using **create** instead of add")
                response.append_result(cls._create(coder, f))
            else:
                response.append_result(cls._editable(coder, f))
        for key in stop_keys:
            response.append_result(cls._stop_command(coder, key))
        for skill_name in load_skill_names:
            response.append_result(cls._load_skill(coder, skill_name))
        for skill_name in remove_skill_names:
            response.append_result(cls._remove_skill(coder, skill_name))
        for server_name in load_mcp_servers:
            result = await cls._load_mcp(coder, server_name)
            response.append_result(result)
        for server_name in remove_mcp_servers:
            result = await cls._remove_mcp(coder, server_name)
            response.append_result(result)

        for action_name in action_operations:
            result = await cls._list_mcp_servers(coder)
            response.append_result(result)

        tui = getattr(coder, "tui", None)
        if tui and tui():
            tui().refresh()

        coder.context_blocks_cache = {}
        coder.edit_allowed = True

        return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for ResourceManager tool."""
        color_start, color_end = color_markers(coder)

        # Output header
        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        try:
            params = ToolValidations.validate_params(
                tool_response.function.arguments, cls.VALIDATIONS, cls.SCHEMA
            )
        except ToolError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        # Define action display names
        action_names = {
            "create": "create",
            "remove": "remove",
            "view": "view",
            "editable": "editable",
            "stop": "stop",
            "load_skill": "load_skill",
            "remove_skill": "remove_skill",
            "load_mcp": "load_mcp",
            "remove_mcp": "remove_mcp",
            "actions": "actions",
        }

        # Output each action with comma-separated file list
        for action_key, display_name in action_names.items():
            files = sorted(parse_arg_as_list(params.get(action_key)), key=cls._natural_sort_key)
            if files:
                file_list = ", ".join(files)
                coder.io.tool_output(f"{color_start}{display_name}:{color_end} {file_list}")

        if params.get("paging") is not None:
            coder.io.tool_output(f"{color_start}paging:{color_end} {params['paging']}")

        tool_footer(coder=coder, tool_response=tool_response, params=params)

    @classmethod
    def _remove(cls, coder, file_path):
        """Remove a file from the coder's context."""
        from cecli.helpers.conversation import ConversationService

        try:
            abs_path = cls._resolve_file_path(coder, file_path)
            rel_path = coder.get_rel_fname(abs_path)
            removed = False

            if abs_path in coder.abs_fnames:
                coder.abs_fnames.remove(abs_path)
                removed = True

            if abs_path in coder.abs_read_only_fnames:
                coder.abs_read_only_fnames.remove(abs_path)
                removed = True

            if not removed:
                coder.io.tool_output(f"⚠ File '{file_path}' not in context", type="tool-result")
                return f"File not in context: {file_path}"

            coder.recently_removed[rel_path] = {"removed_at": time.time()}

            if not file_path.startswith("command_key::"):
                ConversationService.get_chunks(coder).defer_removal(abs_path)
                ConversationService.get_chunks(coder).defer_removal(rel_path)

            coder.io.tool_output(f"✗ Removed '{file_path}' from context", type="tool-result")
            return (
                f"Removed: {file_path}\n"
                "Old file contents may remain visible. This is an acceptable system behavior."
            )
        except Exception as e:
            coder.io.tool_error(f"Error removing file '{file_path}': {str(e)}")
            return f"Error removing {file_path}: {e}"

    @classmethod
    def _stop_command(cls, coder, command_key):
        """Stop a background command by its command key."""
        try:
            success, output, exit_code = BackgroundCommandManager.stop_background_command(
                command_key
            )
            if success:
                coder.io.tool_output(
                    f"✗ Stopped background command '{command_key}'", type="tool-result"
                )
                return (
                    f"Background command stopped: {command_key}\n"
                    f"Exit code: {exit_code}\n"
                    f"Final output:\n{output}"
                )
            else:
                coder.io.tool_output(
                    f"⚠ Background command '{command_key}' not found or not running",
                    type="tool-result",
                )
                return f"Command not found or not running: {command_key}"
        except Exception as e:
            coder.io.tool_error(f"Error stopping command '{command_key}': {str(e)}")
            return f"Error stopping {command_key}: {e}"

    @classmethod
    def _editable(cls, coder, file_path):
        """Make a file editable in the coder's context."""
        try:
            abs_path = cls._resolve_file_path(coder, file_path)
            if abs_path in coder.abs_fnames:
                coder.io.tool_output(
                    f"🗀 File '{file_path}' is already editable", type="tool-result"
                )
                return f"Already editable: {file_path}"
            if not os.path.isfile(abs_path):
                coder.io.tool_output(f"⚠ File '{file_path}' not found on disk", type="tool-result")
                return f"File not found: {file_path}"
            was_read_only = False
            if abs_path in coder.abs_read_only_fnames:
                coder.abs_read_only_fnames.remove(abs_path)
                was_read_only = True
            coder.abs_fnames.add(abs_path)
            if was_read_only:
                coder.io.tool_output(
                    f"🗀 Moved '{file_path}' from read-only to editable", type="tool-result"
                )
                return f"Made editable (moved): {file_path}"
            else:
                coder.io.tool_output(
                    f"🗀 Added '{file_path}' directly to editable context", type="tool-result"
                )
                return f"Made editable (added): {file_path}"
        except Exception as e:
            coder.io.tool_error(f"Error making editable '{file_path}': {str(e)}")
            return f"Error making editable {file_path}: {e}"

    @classmethod
    def _view(cls, coder, file_path):
        """View a file (add as read‑only) in the coder's context."""
        try:
            resolved_path = cls._resolve_file_path(coder, file_path)
            return coder._add_file_to_context(resolved_path, explicit=True)
        except Exception as e:
            coder.io.tool_error(f"Error viewing file '{file_path}': {str(e)}")
            return f"Error viewing {file_path}: {e}"

    @classmethod
    def _create(cls, coder, file_path):
        """Create a new file on the file system and make it editable in the coder's context."""
        try:
            abs_path = coder.abs_root_path(file_path)

            # Check if file already exists
            if os.path.exists(abs_path):
                coder.io.tool_output(f"⚠ File '{file_path}' already exists", type="tool-result")
                return f"File already exists: {file_path}"

            # Create parent directories if they don't exist
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            # Create an empty file
            with safe_open(abs_path, "w"):
                pass

            # Add the file to editable context
            coder.abs_fnames.add(abs_path)

            coder.io.tool_output(
                f"🗀 Created '{file_path}' and made it editable", type="tool-result"
            )
            return f"Created and made editable: {file_path}"

        except Exception as e:
            coder.io.tool_error(f"Error creating file '{file_path}': {str(e)}")
            return f"Error creating {file_path}: {e}"

    @classmethod
    def _resolve_file_path(cls, coder, file_path):
        """Resolve a file path, handling command_key:: aliases.

        command_key::{command_key}/{filename} resolves to the actual
        file path under the agent's local agent folder.
        """
        if file_path.startswith("command_key::"):
            alias_path = file_path[len("command_key::") :]
            parts = alias_path.split("/", 1)
            if len(parts) == 2:
                command_key = parts[0]
                filename = parts[1]
                rel_path = coder.local_agent_folder(f"{command_key}/{filename}")
                return coder.abs_root_path(rel_path)
        return coder.abs_root_path(file_path)

    @classmethod
    def _load_skill(cls, coder, skill_name):
        """Load a skill by name."""
        if not cls._is_context_block_active(coder, "skills"):
            coder.io.tool_output(
                f"⚠ Skills context block is not enabled. Skill '{skill_name}' cannot be loaded.",
                type="tool-result",
            )
            return f"Skills context block not enabled: {skill_name}"

        try:
            if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
                coder.io.tool_output(
                    f"⚠ Skills manager not initialized. Skill '{skill_name}' not loaded.",
                    type="tool-result",
                )
                return f"Skills manager not initialized: {skill_name}"
            return coder.skills_manager.load_skill(skill_name)
        except Exception as e:
            coder.io.tool_error(f"Error loading skill '{skill_name}': {str(e)}")
            return f"Error loading skill {skill_name}: {e}"

    @classmethod
    def _remove_skill(cls, coder, skill_name):
        """Remove a skill by name."""
        if not cls._is_context_block_active(coder, "skills"):
            coder.io.tool_output(
                f"⚠ Skills context block is not enabled. Skill '{skill_name}' cannot be removed.",
                type="tool-result",
            )
            return f"Skills context block not enabled: {skill_name}"

        try:
            if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
                coder.io.tool_output(
                    f"⚠ Skills manager not initialized. Skill '{skill_name}' not removed.",
                    type="tool-result",
                )
                return f"Skills manager not initialized: {skill_name}"
            return coder.skills_manager.remove_skill(skill_name)
        except Exception as e:
            coder.io.tool_error(f"Error removing skill '{skill_name}': {str(e)}")
            return f"Error removing skill {skill_name}: {e}"

    @classmethod
    async def _load_mcp(cls, coder, server_name):
        """Load an MCP server by name."""
        if not cls._is_context_block_active(coder, "servers"):
            coder.io.tool_output(
                f"⚠ Servers context block is not enabled. Server '{server_name}' cannot be loaded.",
                type="tool-result",
            )
            return f"Servers context block not enabled: {server_name}"

        try:
            if not coder.mcp_manager or not coder.mcp_manager.servers:
                return "No MCP servers found, nothing to load."

            server = coder.mcp_manager.get_server(server_name)
            if server is None:
                return f"MCP server {server_name} does not exist."

            if isinstance(coder.mcp_manager.connected_servers, dict):
                connected_names = set(coder.mcp_manager.connected_servers.keys())
            else:
                connected_names = {s.name for s in coder.mcp_manager.connected_servers}
            if server.name in connected_names:
                return f"Server already loaded: {server_name}"
            coder.interrupt_event.clear()
            did_connect, interrupted = await coder.coroutines.interruptible(
                coder.mcp_manager.connect_server(server_name),
                coder.interrupt_event,
            )

            if interrupted:
                return f"Interrupted: {server_name}"
            if did_connect:
                update_server_registration(coder, server_name, "include", force=True)
                for other_coder in iter_all_coders(coder):
                    if other_coder is coder:
                        continue
                    update_server_registration(other_coder, server_name, "exclude", force=False)
                return f"Loaded server: {server_name}"
            else:
                return f"Unable to load server: {server_name}"
        except Exception as e:
            coder.io.tool_error(f"Error loading MCP server '{server_name}': {str(e)}")
            return f"Error loading MCP server {server_name}: {e}"

    @classmethod
    async def _remove_mcp(cls, coder, server_name):
        """Remove an MCP server by name."""
        if not cls._is_context_block_active(coder, "servers"):
            coder.io.tool_output(
                f"⚠ Servers context block is not enabled. Server '{server_name}' cannot be removed.",
                type="tool-result",
            )
            return f"Servers context block not enabled: {server_name}"

        try:
            if not coder.mcp_manager or not coder.mcp_manager.servers:
                return "No MCP servers are configured."

            if server_name.lower() == "local":
                return "Cannot remove 'Local' server"

            server = coder.mcp_manager.get_server(server_name)
            if not server:
                return f"MCP server {server_name} does not exist."
            if isinstance(coder.mcp_manager.connected_servers, dict):
                connected_names = set(coder.mcp_manager.connected_servers.keys())
            else:
                connected_names = {s.name for s in coder.mcp_manager.connected_servers}
            if server.name not in connected_names:
                return f"Server {server_name} is not currently connected."

            update_server_registration(coder, server_name, "exclude", force=True)

            all_excluded = is_server_globally_excluded(coder, server_name)

            if all_excluded:
                coder.interrupt_event.clear()
                did_disconnect, interrupted = await coder.coroutines.interruptible(
                    coder.mcp_manager.disconnect_server(server_name),
                    coder.interrupt_event,
                )
                if interrupted:
                    return f"Interrupted: {server_name}"
                if did_disconnect:
                    return f"Removed server: {server_name}"
                else:
                    return f"Unable to remove server: {server_name}"
            else:
                return f"Removed from active coder, still active for others: {server_name}"
        except Exception as e:
            coder.io.tool_error(f"Error removing MCP server '{server_name}': {str(e)}")
            return f"Error removing MCP server {server_name}: {e}"

    @classmethod
    async def _list_mcp_servers(cls, coder):
        """List all loaded and configured MCP servers."""
        if not coder.mcp_manager:
            return "MCP manager is not configured."

        all_servers = coder.mcp_manager.servers
        connected_servers = coder.mcp_manager.connected_servers

        loaded_server_names = {server.name for server in connected_servers}
        configured_servers = [
            server for server in all_servers if server.name not in loaded_server_names
        ]

        result = []
        if loaded_server_names:
            result.append("Loaded MCP Servers:")
            for name in sorted(list(loaded_server_names)):
                result.append(f"- {name}")
        else:
            result.append("No MCP servers are currently loaded.")

        result.append("")

        if configured_servers:
            result.append("Configured MCP Servers:")
            for server in sorted(configured_servers, key=lambda s: s.name):
                result.append(f"- {server.name}")
        else:
            result.append("No other MCP servers are configured.")

        return "\n".join(result)

    @classmethod
    def _is_context_block_active(cls, coder, block_name):
        """Check if a context block is active in the coder's agent configuration."""
        agent_config = getattr(coder, "agent_config", {})
        include_blocks = agent_config.get("include_context_blocks", set())
        exclude_blocks = agent_config.get("exclude_context_blocks", set())
        return block_name in include_blocks and block_name not in exclude_blocks

    @classmethod
    def _natural_sort_key(cls, s: str) -> list:
        """Natural sort key that splits "a10b2" into ["a", 10, "b", 2]."""
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]

    @staticmethod
    def _validate_paging(paging):
        """Require one to three command keys with positive, one-based page numbers.

        Restrict targets to generated command keys so paging cannot read arbitrary
        files or traverse outside the command's saved output folder. Validate the
        entire request before reading any pages or performing context operations.
        """
        if not isinstance(paging, list) or not 1 <= len(paging) <= 3:
            raise ToolError(
                'paging must be an array of 1-3 objects: [{"target": "<command key>", "page": 1}].'
            )

        for page_request in paging:
            if not isinstance(page_request, dict) or set(page_request) != {"target", "page"}:
                raise ToolError('Each paging entry must be {"target": "<command key>", "page": 1}.')

            target = page_request["target"]
            page = page_request["page"]
            if not isinstance(target, str) or not re.fullmatch(r"bg_[0-9]+_[0-9]+", target):
                raise ToolError("paging.target must be a command key (e.g., bg_1_1234).")

            if type(page) is not int or page < 1:
                raise ToolError("paging.page must be a positive integer starting at 1.")

    @classmethod
    def _read_command_page(cls, coder, paging):
        """Return one saved output page without registering it as a context file."""
        target = paging["target"]
        page = paging["page"]
        rel_path = coder.local_agent_folder(f"{target}/{page}.txt")
        abs_path = coder.abs_root_path(rel_path)
        with safe_open(abs_path, "r") as page_file:
            output = page_file.read()

        return f"Command output: {target}, page {page}\n{output}"
