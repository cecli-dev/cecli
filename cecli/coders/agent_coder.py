import asyncio
import base64
import json
import locale
import os
import platform
import random
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from cecli import utils
from cecli.change_tracker import ChangeTracker
from cecli.helpers import nested, responses
from cecli.helpers.background_commands import BackgroundCommandManager
from cecli.helpers.conversation import ConversationService, MessageTag
from cecli.helpers.similarity import (
    cosine_similarity,
    create_bigram_vector,
    normalize_vector,
)
from cecli.helpers.skills import SkillsManager
from cecli.hooks import HookIntegration
from cecli.llm import litellm
from cecli.mcp import LocalServer, McpServerManager
from cecli.tools.utils.registry import ToolRegistry
from cecli.utils import copy_tool_call, tool_call_to_dict

from .base_coder import Coder


class AgentCoder(Coder):
    """Mode where the LLM autonomously manages which files are in context."""

    edit_format = "agent"
    prompt_format = "agent"
    context_management_enabled = True
    hashlines = True
    stop_on_empty = False

    def __init__(self, *args, **kwargs):
        self.recently_removed = {}
        self.tool_usage_history = []
        self.loaded_custom_tools = []
        self.tool_usage_retries = 20
        self.last_round_tools = []
        self.tool_call_vectors = []
        self.tool_similarity_threshold = 0.95
        self.max_tool_vector_history = 20
        self.read_tools = {
            "command",
            "commandinteractive",
            "viewfilesatglob",
            "viewfilesmatching",
            "ls",
            "viewfileswithsymbol",
            "grep",
            "listchanges",
            "showcontext",
            "thinking",
            "updatetodolist",
        }
        self.write_tools = {
            "deletetext",
            "inserttext",
            "replacetext",
            "undochange",
        }
        self.edit_allowed = False
        self.max_tool_calls = 10000
        self.large_file_token_threshold = 8192
        self.skills_manager = None
        self.change_tracker = ChangeTracker()
        self.args = kwargs.get("args")
        self.files_added_in_exploration = set()
        self.tool_call_count = 0
        self.turn_count = 0
        self.max_reflections = 15
        self.use_enhanced_context = True
        self._last_edited_file = None
        self._cur_message_divider = None
        self.allowed_context_blocks = set()
        self.context_block_tokens = {}
        self.context_blocks_cache = {}
        self.hot_reload_enabled = False
        self.tokens_calculated = False
        self.skip_cli_confirmations = False
        self.agent_finished = False
        self.agent_config = self._get_agent_config()
        self._setup_agent()
        ToolRegistry.build_registry(agent_config=self.agent_config)
        self.loaded_custom_tools = ToolRegistry.loaded_custom_tools
        super().__init__(*args, **kwargs)

    def _setup_agent(self):
        os.makedirs(".cecli/workspace", exist_ok=True)

    def _get_agent_config(self):
        """
        Parse and return agent configuration from args.agent_config.

        Returns:
            dict: Agent configuration with defaults for missing values
        """
        config = {}
        if (
            hasattr(self, "args")
            and self.args
            and hasattr(self.args, "agent_config")
            and self.args.agent_config
        ):
            try:
                config = json.loads(self.args.agent_config)
            except (json.JSONDecodeError, TypeError) as e:
                self.io.tool_warning(f"Failed to parse agent-config JSON: {e}")
                return {}

        config["large_file_token_threshold"] = nested.getter(
            config, "large_file_token_threshold", 8192
        )
        config["skip_cli_confirmations"] = nested.getter(
            config, "skip_cli_confirmations", nested.getter(config, "yolo", [])
        )
        config["command_timeout"] = nested.getter(config, "command_timeout", 30)
        config["hot_reload"] = nested.getter(config, "hot_reload", False)

        config["tools_paths"] = nested.getter(config, ["tools_paths", "tool_paths"], [])
        config["tools_includelist"] = nested.getter(
            config, ["tools_includelist", "tools_whitelist"], []
        )
        config["tools_excludelist"] = nested.getter(
            config, ["tools_excludelist", "tools_blacklist"], []
        )

        config["include_context_blocks"] = set(
            nested.getter(
                config,
                "include_context_blocks",
                {
                    "context_summary",
                    # "directory_structure",
                    "environment_info",
                    "git_status",
                    # "symbol_outline",
                    "todo_list",
                    "skills",
                },
            )
        )
        config["exclude_context_blocks"] = set(nested.getter(config, "exclude_context_blocks", []))

        self.large_file_token_threshold = config["large_file_token_threshold"]
        self.skip_cli_confirmations = config["skip_cli_confirmations"]
        self.hot_reload_enabled = config["hot_reload"]
        self.allowed_context_blocks = config["include_context_blocks"]

        for context_block in config["exclude_context_blocks"]:
            try:
                self.allowed_context_blocks.remove(context_block)
            except KeyError:
                pass

        if "skills" in self.allowed_context_blocks:
            config["skills_paths"] = nested.getter(config, "skills_paths", [])
            config["skills_includelist"] = nested.getter(
                config, ["skills_includelist", "skills_whitelist"], []
            )
            config["skills_excludelist"] = nested.getter(
                config, ["skills_excludelist", "skills_blacklist"], []
            )

        if "skills" not in self.allowed_context_blocks or not nested.getter(
            config, "skills_paths", []
        ):
            config["tools_excludelist"].append("loadskill")
            config["tools_excludelist"].append("removeskill")

        self._initialize_skills_manager(config)
        return config

    def _initialize_skills_manager(self, config):
        """
        Initialize the skills manager with the configured directory paths and filters.
        """
        try:
            git_root = str(self.repo.root) if self.repo else None
            self.skills_manager = SkillsManager(
                directory_paths=config.get("skills_paths", []),
                include_list=config.get("skills_includelist", []),
                exclude_list=config.get("skills_excludelist", []),
                git_root=git_root,
                coder=self,
            )
        except Exception as e:
            self.io.tool_warning(f"Failed to initialize skills manager: {str(e)}")

    def show_announcements(self):
        super().show_announcements()
        if self.loaded_custom_tools:
            self.io.tool_output(f"Loaded custom tools: {', '.join(self.loaded_custom_tools)}")

        skills = self.skills_manager.find_skills()
        if skills:
            skills_list = []
            for skill in skills:
                skills_list.append(skill.name)
            joined_skills = ", ".join(skills_list)
            self.io.tool_output(f"Available Skills: {joined_skills}")

    def get_local_tool_schemas(self):
        """Returns the JSON schemas for all local tools using the tool registry."""
        schemas = []
        for tool_name in ToolRegistry.get_registered_tools():
            tool_module = ToolRegistry.get_tool(tool_name)
            if hasattr(tool_module, "SCHEMA"):
                schemas.append(tool_module.SCHEMA)
        return schemas

    async def initialize_mcp_tools(self):
        if not self.mcp_manager:
            self.mcp_manager = McpServerManager([], self.io, self.args.verbose)

        server_name = "Local"
        server = self.mcp_manager.get_server(server_name)

        # We have already initialized local server and its connected
        # then no need to duplicate work
        if server is not None and server.is_connected:
            return

        # If we dont have any tools for local server to use, no point in creating it then
        local_tools = self.get_local_tool_schemas()
        if not local_tools:
            return

        if server is None:
            local_server_config = {"name": server_name}
            local_server = LocalServer(local_server_config)

            await self.mcp_manager.add_server(local_server, connect=True)
        else:
            await self.mcp_manager.connect_server(server_name)

    async def _execute_local_tool_calls(self, tool_calls_list):
        tool_responses = []
        used_write_tool = False

        for tool_call in tool_calls_list:
            tool_name = tool_call.function.name
            result_message = ""
            try:
                if responses.unprefix_tool_name(tool_name)[1].lower() in self.write_tools:
                    used_write_tool = True

                args_string = tool_call.function.arguments.strip()
                parsed_args_list = []

                if not await HookIntegration.call_pre_tool_hooks(self, tool_name, args_string):
                    tool_responses.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": "Tool Request Aborted.",
                        }
                    )
                    continue

                if args_string:
                    json_chunks = utils.split_concatenated_json(args_string)
                    for chunk in json_chunks:
                        try:
                            parsed_args_list.append(json.loads(chunk))
                        except json.JSONDecodeError as e:
                            self.model_kwargs = {}
                            self.io.tool_warning(
                                f"Malformed JSON arguments in tool {tool_name}: {chunk}"
                            )
                            tool_responses.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": (
                                        f"Malformed JSON arguments in tool {tool_name}: {str(e)}"
                                    ),
                                }
                            )
                            continue
                if not parsed_args_list and not args_string:
                    parsed_args_list.append({})
                all_results_content = []
                norm_tool_name = tool_name.lower()
                tasks = []
                if norm_tool_name in ToolRegistry.get_registered_tools():
                    tool_module = ToolRegistry.get_tool(norm_tool_name)
                    for params in parsed_args_list:
                        result = tool_module.process_response(self, params)
                        if asyncio.iscoroutine(result):
                            tasks.append(result)
                        else:
                            tasks.append(asyncio.to_thread(lambda: result))
                else:
                    all_results_content.append(f"Error: Unknown tool name '{tool_name}'")
                if tasks:
                    task_results = await asyncio.gather(*tasks)
                    all_results_content.extend(str(res) for res in task_results)

                if not await HookIntegration.call_post_tool_hooks(
                    self, tool_name, args_string, "\n\n".join(all_results_content)
                ):
                    tool_responses.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": "Tool Response Redacted.",
                        }
                    )
                    continue

                result_message = "\n\n".join(all_results_content)
            except Exception as e:
                self.model_kwargs = {}
                result_message = f"Error executing {tool_name}: {e}"
                self.io.tool_error(f"""Error during {tool_name} execution: {e}
{traceback.format_exc()}""")
            tool_responses.append(
                {"role": "tool", "tool_call_id": tool_call.id, "content": result_message}
            )

        if self.auto_lint and used_write_tool and not self.edit_allowed:
            edited = list(self.files_edited_by_tools)
            lint_errors = self.lint_edited(edited, show_output=False)
            self.lint_outcome = not lint_errors

            if lint_errors:
                lint_errors = lint_errors.replace(
                    "# Fix any linting errors below, if possible.",
                    "# Fix any linting errors below, if possible and then continue with your task.",
                    1,
                )
                ConversationService.get_manager(self).add_message(
                    message_dict=dict(role="user", content=lint_errors),
                    tag=MessageTag.CUR,
                    hash_key=("lint_errors", "agent"),
                    promotion=ConversationService.get_manager(self).DEFAULT_TAG_PROMOTION_VALUE,
                    mark_for_demotion=1,
                    force=True,
                )
            else:
                ConversationService.get_manager(self).remove_message_by_hash_key(
                    ("lint_errors", "agent")
                )

        return tool_responses

    async def _execute_mcp_tool(self, server, tool_name, params):
        """Helper to execute a single MCP tool call, created from legacy format."""

        async def _exec_async():
            function_dict = {"name": tool_name, "arguments": json.dumps(params)}
            tool_call_dict = {
                "id": f"mcp-tool-call-{time.time()}",
                "function": function_dict,
                "type": "function",
            }
            try:
                session = await server.connect()
                call_result = await litellm.experimental_mcp_client.call_openai_tool(
                    session=session, openai_tool=tool_call_dict
                )
                content_parts = []
                if call_result.content:
                    for item in call_result.content:
                        if hasattr(item, "resource"):
                            resource = item.resource
                            if hasattr(resource, "text"):
                                content_parts.append(resource.text)
                            elif hasattr(resource, "blob"):
                                try:
                                    decoded_blob = base64.b64decode(resource.blob).decode("utf-8")
                                    content_parts.append(decoded_blob)
                                except (UnicodeDecodeError, TypeError):
                                    name = getattr(resource, "name", "unnamed")
                                    mime_type = getattr(resource, "mimeType", "unknown mime type")
                                    content_parts.append(
                                        f"[embedded binary resource: {name} ({mime_type})]"
                                    )
                        elif hasattr(item, "text"):
                            content_parts.append(item.text)
                return "".join(content_parts)
            except Exception as e:
                self.io.tool_warning(f"""Executing {tool_name} on {server.name} failed:
  Error: {e}
""")
                return f"Error executing tool call {tool_name}: {e}"

        return await _exec_async()

    def _calculate_context_block_tokens(self, force=False):
        """
        Calculate token counts for all enhanced context blocks.
        This is the central method for calculating token counts,
        ensuring they're consistent across all parts of the code.

        This method populates the cache for context blocks and calculates tokens.

        Args:
            force: If True, recalculate tokens even if already calculated
        """
        if hasattr(self, "tokens_calculated") and self.tokens_calculated and not force:
            return
        self.context_block_tokens = {}
        if not hasattr(self, "context_blocks_cache"):
            self.context_blocks_cache = {}
        if not self.use_enhanced_context:
            return
        try:
            self.context_blocks_cache = {}
            block_types = [
                "environment_info",
                "directory_structure",
                "git_status",
                "symbol_outline",
                "skills",
                "loaded_skills",
            ]
            for block_type in block_types:
                if block_type in self.allowed_context_blocks:
                    block_content = self._generate_context_block(block_type)
                    if block_content:
                        self.context_block_tokens[block_type] = self.get_active_model().token_count(
                            block_content
                        )
            self.tokens_calculated = True
        except Exception:
            pass

    def _generate_context_block(self, block_name):
        """
        Generate a specific context block and cache it.
        This is a helper method for get_cached_context_block.
        """
        content = None
        if block_name == "environment_info":
            content = self.get_environment_info()
        elif block_name == "directory_structure":
            content = self.get_directory_structure()
        elif block_name == "git_status":
            content = self.get_git_status()
        elif block_name == "symbol_outline":
            content = self.get_context_symbol_outline()
        elif block_name == "context_summary":
            content = self.get_context_summary()
        elif block_name == "todo_list":
            content = self.get_todo_list()
        elif block_name == "skills":
            content = self.get_skills_context()
        elif block_name == "loaded_skills":
            content = self.get_skills_content()
        if content is not None:
            self.context_blocks_cache[block_name] = content
        return content

    def get_cached_context_block(self, block_name):
        """
        Get a context block from the cache, or generate it if not available.
        This should be used by format_chat_chunks to avoid regenerating blocks.

        This will ensure tokens are calculated if they haven't been yet.
        """
        if not hasattr(self, "tokens_calculated") or not self.tokens_calculated:
            self._calculate_context_block_tokens()
        if hasattr(self, "context_blocks_cache") and block_name in self.context_blocks_cache:
            return self.context_blocks_cache[block_name]
        return self._generate_context_block(block_name)

    def get_context_symbol_outline(self):
        """
        Generate a symbol outline for files currently in context using Tree-sitter,
        bypassing the cache for freshness.
        """
        if not self.use_enhanced_context or not self.repo_map:
            return None
        try:
            result = '<context name="symbol_outline" from="agent">\n'
            result += "## Symbol Outline (Current Context)\n\n"
            result += """Code definitions (classes, functions, methods, etc.) found in files currently in chat context.

"""
            files_to_outline = list(self.abs_fnames) + list(self.abs_read_only_fnames)
            if not files_to_outline:
                result += "No files currently in context.\n"
                result += "</context>"
                return result
            all_tags_by_file = defaultdict(list)
            has_symbols = False
            if not self.repo_map:
                self.io.tool_warning("RepoMap not initialized, cannot generate symbol outline.")
                return None
            for abs_fname in sorted(files_to_outline):
                rel_fname = self.get_rel_fname(abs_fname)
                try:
                    tags = list(self.repo_map.get_tags_raw(abs_fname, rel_fname))
                    if tags:
                        all_tags_by_file[rel_fname].extend(tags)
                        has_symbols = True
                except Exception as e:
                    self.io.tool_warning(f"Could not get symbols for {rel_fname}: {e}")
            if not has_symbols:
                result += "No symbols found in the current context files.\n"
            else:
                for rel_fname in sorted(all_tags_by_file.keys()):
                    tags = sorted(all_tags_by_file[rel_fname], key=lambda t: (t.line, t.name))
                    definition_tags = []
                    for tag in tags:
                        kind_to_check = tag.specific_kind or tag.kind
                        if (
                            kind_to_check
                            and kind_to_check.lower() in self.repo_map.definition_kinds
                        ):
                            definition_tags.append(tag)
                    if definition_tags:
                        result += f"### {rel_fname}\n"
                        for tag in definition_tags:
                            line_info = (
                                f", lines {tag.start_line + 1} - {tag.end_line + 1}"
                                if tag.line >= 0
                                else ""
                            )
                            kind_to_check = tag.specific_kind or tag.kind
                            result += f"- {tag.name} ({kind_to_check}{line_info})\n"
                        result += "\n"
            result += "</context>"
            return result.strip()
        except Exception as e:
            self.io.tool_error(f"Error generating symbol outline: {str(e)}")
            return None

    def format_chat_chunks(self):
        """
        Override parent's format_chat_chunks to include enhanced context blocks with a
        cleaner, more hierarchical structure for better organization.

        Optimized for prompt caching by placing context blocks strategically:
        1. Relatively static blocks (directory structure, environment info) before done_messages
        2. Dynamic blocks (context summary, symbol outline, git status) after chat_files

        This approach preserves prefix caching while providing fresh context information.
        """
        if not self.use_enhanced_context:
            # Use parent's implementation which may use conversation system if flag is enabled
            return super().format_chat_chunks()

        # Choose appropriate fence based on file content
        self.choose_fence()

        ConversationService.get_chunks(self).initialize_conversation_system()

        # Clean up ConversationFiles and remove corresponding messages
        ConversationService.get_chunks(self).cleanup_files()

        # Add reminder message with list of readonly and editable files
        ConversationService.get_chunks(self).add_file_list_reminder()

        # Add system messages (including examples and reminder)
        ConversationService.get_chunks(self).add_system_messages()

        # Add static context blocks (priority 50 - between SYSTEM and EXAMPLES)
        ConversationService.get_chunks(self).add_static_context_blocks()

        # Add rules messages
        ConversationService.get_chunks(self).add_rules_messages()

        # Handle file messages using conversation module helper methods
        # These methods will add messages to ConversationManager
        ConversationService.get_chunks(self).add_repo_map_messages()

        # Add pre-message context blocks (priority 125 - between REPO and READONLY_FILES)
        ConversationService.get_chunks(self).add_pre_message_context_blocks()

        ConversationService.get_chunks(self).add_readonly_files_messages()
        ConversationService.get_chunks(self).add_chat_files_messages()

        # Add post-message context blocks (priority 250 - between CUR and REMINDER)
        ConversationService.get_chunks(self).add_post_message_context_blocks()

        return ConversationService.get_manager(self).get_messages_dict()

    def get_context_summary(self):
        """
        Generate a summary of the current context, including file content tokens and additional context blocks,
        with an accurate total token count.
        """
        if not self.use_enhanced_context:
            return None
        if hasattr(self, "context_blocks_cache") and "context_summary" in self.context_blocks_cache:
            return self.context_blocks_cache["context_summary"]
        try:
            if not hasattr(self, "context_block_tokens") or not self.context_block_tokens:
                self._calculate_context_block_tokens()
            result = '<context name="context_summary" from="agent">\n'
            result += "## Current Context Overview\n\n"
            max_input_tokens = self.get_active_model().info.get("max_input_tokens") or 0
            if max_input_tokens:
                result += f"Model context limit: {max_input_tokens:,} tokens\n\n"
            total_file_tokens = 0
            editable_tokens = 0
            readonly_tokens = 0
            editable_files = []
            readonly_files = []
            if self.abs_fnames:
                result += "### Editable Files\n\n"
                for fname in sorted(self.abs_fnames):
                    rel_fname = self.get_rel_fname(fname)
                    content = self.io.read_text(fname)
                    if content is not None:
                        tokens = self.get_active_model().token_count(content)
                        total_file_tokens += tokens
                        editable_tokens += tokens
                        size_indicator = (
                            "🔴 Large"
                            if tokens > 5000
                            else "🟡 Medium" if tokens > 1000 else "🟢 Small"
                        )
                        editable_files.append(
                            f"- {rel_fname}: {tokens:,} tokens ({size_indicator})"
                        )
                if editable_files:
                    result += "\n".join(editable_files) + "\n\n"
                    result += f"""**Total editable: {len(editable_files)} files, {editable_tokens:,} tokens**

"""
                else:
                    result += "No editable files in context\n\n"
            if self.abs_read_only_fnames:
                result += "### Read-Only Files\n\n"
                for fname in sorted(self.abs_read_only_fnames):
                    rel_fname = self.get_rel_fname(fname)
                    content = self.io.read_text(fname)
                    if content is not None:
                        tokens = self.get_active_model().token_count(content)
                        total_file_tokens += tokens
                        readonly_tokens += tokens
                        size_indicator = (
                            "🔴 Large"
                            if tokens > 5000
                            else "🟡 Medium" if tokens > 1000 else "🟢 Small"
                        )
                        readonly_files.append(
                            f"- {rel_fname}: {tokens:,} tokens ({size_indicator})"
                        )
                if readonly_files:
                    result += "\n".join(readonly_files) + "\n\n"
                    result += f"""**Total read-only: {len(readonly_files)} files, {readonly_tokens:,} tokens**

"""
                else:
                    result += "No read-only files in context\n\n"
            extra_tokens = sum(self.context_block_tokens.values())
            total_tokens = total_file_tokens + extra_tokens
            result += f"**Total files usage: {total_file_tokens:,} tokens**\n\n"
            result += f"**Additional context usage: {extra_tokens:,} tokens**\n\n"
            result += f"**Total context usage: {total_tokens:,} tokens**"
            if max_input_tokens:
                percentage = total_tokens / max_input_tokens * 100
                result += f" ({percentage:.1f}% of limit)"
                if percentage > 80:
                    result += "\n\n⚠️ **Context is getting full!**\n"
                    result += "- Remove non-essential files via the `ContextManager` tool.\n"
                    result += "- Keep only essential files in context for best performance"
            result += "\n</context>"
            if not hasattr(self, "context_blocks_cache"):
                self.context_blocks_cache = {}
            self.context_blocks_cache["context_summary"] = result
            return result
        except Exception as e:
            self.io.tool_error(f"Error generating context summary: {str(e)}")
            return None

    def get_environment_info(self):
        """
        Generate an environment information context block with key system details.
        Returns formatted string with working directory, platform, date, and other relevant environment details.
        """
        if not self.use_enhanced_context:
            return None
        try:
            current_date = datetime.now().strftime("%Y-%m-%d")
            platform_info = platform.platform()
            language = self.chat_language or locale.getlocale()[0] or "en-US"
            result = '<context name="environment_info" from="agent">\n'
            result += "## Environment Information\n\n"
            result += f"- Working directory: {self.root}\n"
            result += f"- Current date: {current_date}\n"
            result += f"- Platform: {platform_info}\n"
            result += f"- Language preference: {language}\n"
            if self.repo:
                try:
                    rel_repo_dir = self.repo.get_rel_repo_dir()
                    num_files = len(self.repo.get_tracked_files())
                    result += f"- Git repository: {rel_repo_dir} with {num_files:,} files\n"
                except Exception:
                    result += "- Git repository: active but details unavailable\n"
            else:
                result += "- Git repository: none\n"
            result += "</context>"
            return result
        except Exception as e:
            self.io.tool_error(f"Error generating environment info: {str(e)}")
            return None

    async def process_tool_calls(self, tool_call_response):
        """
        Track tool usage before calling the base implementation.
        """

        await self.auto_save_session()
        self.last_round_tools = []
        self.turn_count += 1

        if self.partial_response_tool_calls:
            for tool_call in self.partial_response_tool_calls:
                tool_name = getattr(tool_call.function, "name", None)
                tool_call_copy = tool_call_to_dict(copy_tool_call(tool_call))
                if "id" in tool_call_copy:
                    del tool_call_copy["id"]

                if tool_name:
                    self.last_round_tools.append(tool_name)
                    content = (
                        str(self.partial_response_content) if self.partial_response_content else ""
                    )
                    tool_call_str = str(tool_call_copy)
                    tool_vector = create_bigram_vector((tool_call_str, content))
                    tool_vector_norm = normalize_vector(tool_vector)
                    self.tool_call_vectors.append(tool_vector_norm)
        if self.last_round_tools:
            self.tool_usage_history += self.last_round_tools
            self.tool_usage_history = list(filter(None, self.tool_usage_history))
        if len(self.tool_usage_history) > self.tool_usage_retries:
            self.tool_usage_history.pop(0)
        if len(self.tool_call_vectors) > self.max_tool_vector_history:
            self.tool_call_vectors.pop(0)

        # Ensure we call base implementation to trigger execution of all tools (native + extracted)
        return await super().process_tool_calls(tool_call_response)

    async def _execute_local_tools(self, tool_calls):
        """Execute local tools via ToolRegistry."""
        return await self._execute_local_tool_calls(tool_calls)

    async def _execute_mcp_tools(self, server, tool_calls):
        """Execute MCP tools via LiteLLM."""
        responses = []
        for tool_call in tool_calls:
            # Use existing _execute_mcp_tool logic
            result = await self._execute_mcp_tool(
                server, tool_call.function.name, json.loads(tool_call.function.arguments)
            )
            responses.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )
        return responses

    def get_active_model(self):
        if self.main_model.agent_model:
            return self.main_model.agent_model

        return self.main_model

    async def reply_completed(self):
        """Process the completed response from the LLM.

        This handles:
        1. SEARCH/REPLACE blocks (Edit format)
        2. Tool execution follow-up (Reflections)

        Tool extraction and execution is now handled in BaseCoder.consolidate_chunks
        and BaseCoder.process_tool_calls respectively.
        """
        content = self.partial_response_content
        tool_calls_found = bool(self.partial_response_tool_calls)

        # 1. Handle Tool Execution Follow-up (Reflection)
        if self.agent_finished:
            self.tool_usage_history = []
            self.reflected_message = None
            if self.files_edited_by_tools:
                _ = await self.auto_commit(self.files_edited_by_tools)
            return False

        # 2. Check for unfinished and recently finished background commands
        background_commands = BackgroundCommandManager.list_background_commands()

        # Get command timeout from agent_config
        command_timeout = int(self.agent_config.get("command_timeout", 30))

        # Check for unfinished commands
        unfinished_commands = [
            cmd_key
            for cmd_key, cmd_info in background_commands.items()
            if cmd_info.get("running", False)
        ]

        # Check for recently finished commands (within last command_timeout seconds)
        current_time = time.time()
        recently_finished_commands = [
            cmd_key
            for cmd_key, cmd_info in background_commands.items()
            if not cmd_info.get("running", False)
            and cmd_info.get("end_time")
            and (current_time - cmd_info["end_time"]) < command_timeout * 4
        ]

        if unfinished_commands and not self.agent_finished:
            waiting_msg = (
                f"⏱️ Waiting for {len(unfinished_commands)} background command(s) to complete..."
            )
            self.reflected_message = (
                f"⏱️ Waiting for {len(unfinished_commands)} background command(s) to"
                " complete...\nPlease reply with 'waiting...' if you need the outputs of this"
                " command for your current task and it has not yet finished or stop the command if"
                " its outputs are no longer necessary"
            )
            self.io.tool_output(waiting_msg)
            await asyncio.sleep(command_timeout / 2)
            return True

        # Check for recently finished commands that need reflection
        if recently_finished_commands and not self.agent_finished:
            return True  # Retrigger reflection to process recently finished command outputs

        # 3. If no content and no tools, we might be done or just empty response
        if (not content or not content.strip()) and not tool_calls_found:
            if len(self.tool_usage_history) > self.tool_usage_retries:
                self.tool_usage_history = []
            return True

        if tool_calls_found and self.num_reflections < self.max_reflections:
            self.tool_call_count = 0
            self.files_added_in_exploration = set()
            cur_messages = ConversationService.get_manager(self).get_messages_dict(MessageTag.CUR)
            original_question = "Please continue your exploration and provide a final answer."
            if cur_messages:
                for msg in reversed(cur_messages):
                    if msg["role"] == "user":
                        original_question = msg["content"]
                        break

            # Construct reflection prompt
            next_prompt_parts = []
            next_prompt_parts.append(
                "I have processed the results of the previous tool calls. Let me analyze them"
                " and continue working towards your request."
            )
            next_prompt_parts.append("""
I will proceed based on the tool results and updated context.""")
            next_prompt_parts.append(f"\nYour original question was: {original_question}")
            self.reflected_message = "\n".join(next_prompt_parts)
            self.io.tool_output("Continuing exploration...")
            return False

        if self.files_edited_by_tools:
            saved_message = await self.auto_commit(self.files_edited_by_tools)
            if not saved_message and hasattr(self.gpt_prompts, "files_content_gpt_edits_no_repo"):
                saved_message = self.gpt_prompts.files_content_gpt_edits_no_repo

        self.tool_call_count = 0
        self.files_added_in_exploration = set()
        self.files_edited_by_tools = set()
        return False

    async def hot_reload(self):
        if self.hot_reload_enabled:
            self.skills_manager.hot_reload()

    def _get_repetitive_tools(self):
        """
        Identifies repetitive tool usage patterns from rounds of tool calls.
        """
        history_len = len(self.tool_usage_history)
        if history_len < 1:
            return set()

        similarity_repetitive_tools = self._get_repetitive_tools_by_similarity()

        if self.last_round_tools:
            last_round_has_write = any(
                responses.unprefix_tool_name(tool)[1].lower() in self.write_tools
                for tool in self.last_round_tools
            )
            if last_round_has_write:
                # Remove half of the history when a write tool is used
                half = len(self.tool_usage_history) // 2
                self.tool_usage_history = self.tool_usage_history[half:]
                self.tool_call_vectors = self.tool_call_vectors[half:]

        # Filter to only include tools in read_tools or write_tools
        return {
            tool
            for tool in similarity_repetitive_tools
            if responses.unprefix_tool_name(tool)[1].lower() in self.read_tools
            or responses.unprefix_tool_name(tool)[1].lower() in self.write_tools
        }

    def _get_repetitive_tools_by_similarity(self):
        """
        Identifies repetitive tool usage patterns using cosine similarity and windowed patterns.
        """
        if not self.tool_usage_history or len(self.tool_call_vectors) < 2:
            return set()

        repetitive_tools = set()
        latest_vector = self.tool_call_vectors[-1]
        similarity_triggered = False

        # Store similarity scores by index (similarity between latest vector and each historical vector)
        similarity_scores = []

        # 1. Similarity-based detection
        for i, historical_vector in enumerate(self.tool_call_vectors[:-1]):
            similarity = cosine_similarity(latest_vector, historical_vector)
            similarity_scores.append(similarity)

            # Flag immediately if similarity is very high (> 0.99)
            if similarity > 0.99:
                if i < len(self.tool_usage_history):
                    repetitive_tools.add(self.tool_usage_history[i])

            # Standard similarity threshold triggers windowed check
            elif similarity >= self.tool_similarity_threshold:
                similarity_triggered = True

        # 2. Windowed pattern detection (window size 3)
        # Only runs if similarity threshold was met or high similarity was found
        if similarity_triggered or repetitive_tools:
            window_size = 3
            if len(self.tool_usage_history) >= window_size * 2:
                latest_window = tuple(self.tool_usage_history[-window_size:])
                latest_window_vectors = self.tool_call_vectors[-window_size:]

                for i in range(len(self.tool_usage_history) - (window_size * 2) + 1):
                    historical_window = tuple(self.tool_usage_history[i : i + window_size])
                    historical_window_vectors = self.tool_call_vectors[i : i + window_size]

                    if latest_window == historical_window:
                        # Check if at least one tool in the window has similarity above threshold
                        # We compare each tool in the historical window with its counterpart in the latest window
                        window_has_high_similarity = False
                        for j in range(window_size):
                            # Compare historical tool at position i+j with latest tool at position -window_size+j
                            hist_idx = i + j
                            latest_idx = -window_size + j

                            if hist_idx < len(self.tool_call_vectors) and latest_idx < 0:
                                similarity = cosine_similarity(
                                    historical_window_vectors[j], latest_window_vectors[j]
                                )
                                if similarity >= self.tool_similarity_threshold:
                                    window_has_high_similarity = True
                                    break

                        if window_has_high_similarity:
                            repetitive_tools.update(latest_window)

        return repetitive_tools

    def _generate_tool_context(self, repetitive_tools):
        """
        Generate a context message for the LLM about recent tool usage.
        """
        if not self.tool_usage_history:
            return ""

        if not hasattr(self, "_last_repetitive_warning_turn"):
            self._last_repetitive_warning_turn = 0
            self._last_repetitive_warning_severity = 0

        context_parts = ['<context name="tool_usage_history" from="agent">']
        context_parts.append("## Turn and Tool Call Statistics")
        context_parts.append(f"- Current turn: {self.turn_count + 1}")
        context_parts.append(f"- Total tool calls this turn: {self.num_tool_calls}")
        context_parts.append("\n\n")
        context_parts.append("## Recent Tool Usage History")

        if len(self.tool_usage_history) > 10:
            recent_history = self.tool_usage_history[-20:]
            context_parts.append("(Showing last 20 tools)")
        else:
            recent_history = self.tool_usage_history
        for i, tool in enumerate(recent_history, 1):
            context_parts.append(f"{i}. {tool}")

        if not self.edit_allowed:
            context_parts.append("\n\n")
            context_parts.append("## File Editing Tools Disabled")
            context_parts.append(
                "File editing tools are currently disabled.Use `ShowContext` to determine the"
                " current hashline prefixes needed to perform an edit and activate them when you"
                " are ready to edit a file."
            )

        context_parts.append("\n\n")
        repetition_warning = None

        if repetitive_tools:
            if not self.model_kwargs:
                self.model_kwargs = {
                    "temperature": (
                        1
                        if isinstance(self.get_active_model().use_temperature, bool)
                        else float(self.get_active_model().use_temperature)
                    ) + 0.1,
                    "frequency_penalty": 0.2,
                    "presence_penalty": 0.1,
                }
            else:
                temperature = nested.getter(self.model_kwargs, "temperature")
                freq_penalty = nested.getter(self.model_kwargs, "frequency_penalty")
                if temperature and freq_penalty:
                    self.model_kwargs["temperature"] = min(temperature + 0.1, 2)
                    self.model_kwargs["frequency_penalty"] = min(freq_penalty + 0.1, 1)

                if random.random() < 0.2:
                    self.model_kwargs["temperature"] = min(
                        (
                            1
                            if isinstance(self.get_active_model().use_temperature, bool)
                            else float(self.get_active_model().use_temperature)
                        ),
                        max(temperature - 0.15, 1),
                    )
                    self.model_kwargs["frequency_penalty"] = min(0, max(freq_penalty - 0.15, 0))

            self.model_kwargs["temperature"] = max(
                0, min(nested.getter(self.model_kwargs, "temperature", 1), 1)
            )
            # One twentieth of the time, just straight reset the randomness
            if random.random() < 0.05:
                self.model_kwargs = {}

            if self.turn_count - self._last_repetitive_warning_turn > 1:
                self._last_repetitive_warning_turn = self.turn_count
                self._last_repetitive_warning_severity += 1

            repetition_warning = (
                "## Repetition Detected\nYou have used the following tools repetitively:"
                f" {', '.join([f'`{t}`' for t in repetitive_tools])}.\nDo not repeat the same"
                " parameters for these tools in your next turns. Prioritize editing.\n"
            )

            if self._last_repetitive_warning_severity > 5:
                self._last_repetitive_warning_severity = 0

                fruit = random.choice(
                    [
                        "an apple",
                        "a banana",
                        "a cantaloupe",
                        "a cherry",
                        "a honeydew",
                        "an orange",
                        "a mango",
                        "a pomegranate",
                        "a watermelon",
                    ]
                )
                animal = random.choice(
                    [
                        "a bird",
                        "a bear",
                        "a cat",
                        "a deer",
                        "a dog",
                        "an elephant",
                        "a fish",
                        "a fox",
                        "a monkey",
                        "a rabbit",
                    ]
                )
                verb = random.choice(
                    [
                        "absorbing",
                        "becoming",
                        "creating",
                        "dreaming of",
                        "eating",
                        "fighting with",
                        "playing with",
                        "painting",
                        "smashing",
                        "writing a song about",
                    ]
                )

                repetition_warning += (
                    "## CRITICAL: Execution Loop Detected\nYou may be stuck in a cycle. To break"
                    " the exploration loop and continue making progress, please do the"
                    " following:\n1. **Analyze**: Summarize your findings. Describe how you can"
                    " stop repeating yourself and make progress.2. **Reframe**: To help with"
                    f" creativity, include a 2-sentence story about {animal} {verb} {fruit} in your"
                    " thoughts.\n3. **Pivot**: Modify your current exploration strategy. Try"
                    " alternative methods. Prioritize editing.\n"
                )

            # context_parts.append(repetition_warning)
        else:
            self.model_kwargs = {}
            self._last_repetitive_warning_severity = min(
                self._last_repetitive_warning_severity - 1, 0
            )

        if repetition_warning:
            ConversationService.get_manager(self).add_message(
                message_dict=dict(role="user", content=repetition_warning),
                tag=MessageTag.CUR,
                hash_key=("repetition", "agent"),
                mark_for_delete=0,
                promotion=ConversationService.get_manager(self).DEFAULT_TAG_PROMOTION_VALUE + 2,
                mark_for_demotion=1,
                force=True,
            )

        context_parts.append("</context>")
        return "\n".join(context_parts)

    def _generate_write_context(self):
        if self.last_round_tools:
            last_round_has_write = any(
                responses.unprefix_tool_name(tool)[1].lower() in self.write_tools
                for tool in self.last_round_tools
            )
            if last_round_has_write:
                context_parts = [
                    '<context name="tool_usage_history" from="agent">',
                    "A file was just edited.",
                    "Review the diff to make sure that something of value was done.",
                    "Do not just leave placeholder content or partial implementations.",
                    "</context>",
                ]
                return "\n".join(context_parts)
        return ""

    def _add_file_to_context(self, file_path, explicit=False):
        """
        Helper method to add a file to context as read-only.

        Parameters:
        - file_path: Path to the file to add
        - explicit: Whether this was an explicit view command (vs. implicit through ViewFilesMatching)
        """
        abs_path = self.abs_root_path(file_path)
        rel_path = self.get_rel_fname(abs_path)
        if not os.path.isfile(abs_path):
            self.io.tool_output(f"⚠️ File '{file_path}' not found")
            return "File not found"
        if abs_path in self.abs_fnames:
            if explicit:
                self.io.tool_output(f"📎 File '{file_path}' already in context as editable")
                return "File already in context as editable"
            return "File already in context as editable"
        if abs_path in self.abs_read_only_fnames:
            if explicit:
                self.io.tool_output(f"📎 File '{file_path}' already in context as read-only")
                return "File already in context as read-only"
            return "File already in context as read-only"
        try:
            content = self.io.read_text(abs_path)
            if content is None:
                return f"Error reading file: {file_path}"
            if self.context_management_enabled:
                file_tokens = self.get_active_model().token_count(content)
                if file_tokens > self.large_file_token_threshold:
                    self.io.tool_output(
                        f"⚠️ '{file_path}' is very large ({file_tokens} tokens). Use"
                        " /context-management to toggle truncation off if needed."
                    )
            self.abs_read_only_fnames.add(abs_path)
            self.files_added_in_exploration.add(rel_path)
            if explicit:
                self.io.tool_output(f"📎 Viewed '{file_path}' (added to context as read-only)")
                return "Viewed file (added to context as read-only)"
            else:
                return "Added file to context as read-only"
        except Exception as e:
            self.io.tool_error(f"Error adding file '{file_path}' for viewing: {str(e)}")
            return f"Error adding file for viewing: {str(e)}"

    async def check_for_file_mentions(self, content):
        """
        Override parent's method to use our own file processing logic.

        Override parent's method to disable implicit file mention handling in agent mode.
        Files should only be added via explicit tool commands
        (`View`, `ViewFilesAtGlob`, `ViewFilesMatching`, `ViewFilesWithSymbol`).
        """
        pass

    async def preproc_user_input(self, inp):
        """
        Override parent's method to wrap user input in a context block.
        This clearly delineates user input from other sections in the context window.
        """
        inp = await super().preproc_user_input(inp)
        inp = self.wrap_user_input(inp)

        self.agent_finished = False
        self.turn_count = 0
        return inp

    def wrap_user_input(self, inp):
        if inp and not inp.startswith('<context name="user_input" from="agent">'):
            inp = f'<context name="user_input" from="agent">\n{inp}\n</context>'

        return inp

    def get_directory_structure(self):
        """
        Generate a structured directory listing of the project file structure.
        Returns a formatted string representation of the directory tree.
        """
        if not self.use_enhanced_context:
            return None
        try:
            result = '<context name="directoryStructure" from="agent">\n'
            result += "## Project File Structure\n\n"
            result += (
                "Below is a snapshot of this project's file structure at the current time. "
                "It skips over .gitignore patterns."
            )
            Path(self.root)
            if self.repo:
                tracked_files = self.repo.get_tracked_files()
                untracked_files = []
                try:
                    untracked_output = self.repo.repo.git.status("--porcelain")
                    for line in untracked_output.splitlines():
                        if line.startswith("??"):
                            untracked_file = line[3:]
                            if not self.repo.ignored_file(untracked_file):
                                untracked_files.append(untracked_file)
                except Exception as e:
                    self.io.tool_warning(f"Error getting untracked files: {str(e)}")
                all_files = tracked_files + untracked_files
            else:
                all_files = []
                for path in Path(self.root).rglob("*"):
                    if path.is_file():
                        all_files.append(str(path.relative_to(self.root)))
            all_files = sorted(all_files)
            all_files = [
                f for f in all_files if not any(part.startswith(".cecli") for part in f.split("/"))
            ]
            tree = {}
            for file in all_files:
                parts = file.split("/")
                current = tree
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        if "." not in current:
                            current["."] = []
                        current["."].append(part)
                    else:
                        if part not in current:
                            current[part] = {}
                        current = current[part]

            def print_tree(node, prefix="- ", indent="  ", current_path=""):
                lines = []
                dirs = sorted([k for k in node.keys() if k != "."])
                for i, dir_name in enumerate(dirs):
                    lines.append(f"{prefix}{dir_name}/")
                    sub_lines = print_tree(
                        node[dir_name], prefix=prefix, indent=indent, current_path=dir_name
                    )
                    for sub_line in sub_lines:
                        lines.append(f"{indent}{sub_line}")
                if "." in node:
                    for file_name in sorted(node["."]):
                        lines.append(f"{prefix}{file_name}")
                return lines

            tree_lines = print_tree(tree, prefix="- ")
            result += "\n".join(tree_lines)
            result += "\n</context>"
            return result
        except Exception as e:
            self.io.tool_error(f"Error generating directory structure: {str(e)}")
            return None

    def get_todo_list(self):
        """
        Generate a todo list context block from the todo.txt file.
        Returns formatted string with the current todo list or None if empty/not present.
        """
        try:
            todo_file_path = self.local_agent_folder("todo.txt")
            abs_path = self.abs_root_path(todo_file_path)
            import os

            if not os.path.isfile(abs_path):
                return """<context name="todo_list" from="agent">
Todo list does not exist. Please update it with the `UpdateTodoList` tool.</context>"""
            content = self.io.read_text(abs_path)
            if content is None or not content.strip():
                return None
            result = '<context name="todo_list" from="agent">\n'
            result += "## Current Todo List\n\n"
            result += "Below is the current todo list managed via the `UpdateTodoList` tool:\n\n"
            result += f"```\n{content}\n```\n"
            result += "</context>"
            return result
        except Exception as e:
            self.io.tool_error(f"Error generating todo list context: {str(e)}")
            return None

    def get_skills_context(self):
        """
        Generate a context block for available skills.

        Returns:
            Formatted context block string or None if no skills available
        """
        if not self.use_enhanced_context or not self.skills_manager:
            return None
        try:
            return self.skills_manager.get_skills_context()
        except Exception as e:
            self.io.tool_error(f"Error generating skills context: {str(e)}")
            return None

    def get_skills_content(self):
        """
        Generate a context block with the actual content of loaded skills.

        Returns:
            Formatted context block string with skill contents or None if no skills available
        """
        if not self.use_enhanced_context or not self.skills_manager:
            return None
        try:
            return self.skills_manager.get_skills_content()
        except Exception as e:
            self.io.tool_error(f"Error generating skills content context: {str(e)}")
            return None

    def get_background_command_output(self):
        """
        Get background command output to append after the main message.

        Returns:
            String containing formatted background command output, or empty string if none
        """
        # Get output from all running background commands
        bg_outputs = BackgroundCommandManager.get_all_command_outputs(clear=True)

        if not bg_outputs:
            return ""

        # Get command info to show actual command strings
        command_info = BackgroundCommandManager.list_background_commands()

        # Create formatted output for background commands
        output = "--- Background Commands Output ---\n"
        for command_key, cmd_output in bg_outputs.items():
            if cmd_output.strip():  # Only add if there's output
                # Get the actual command string if available
                command_str = command_info.get(command_key, {}).get("command", command_key)
                output += f"\n[bg: {command_str}]\n{cmd_output}\n"

        return output

    def get_git_status(self):
        """
        Generate a git status context block for repository information.
        Returns a formatted string with git branch, status, and recent commits.
        """
        if not self.use_enhanced_context or not self.repo:
            return None
        try:
            result = '<context name="gitStatus" from="agent">\n'
            result += "## Git Repository Status\n\n"
            result += "This is a snapshot of the git status at the current time.\n"
            try:
                current_branch = self.repo.repo.active_branch.name
                result += f"Current branch: {current_branch}\n\n"
            except Exception:
                result += "Current branch: (detached HEAD state)\n\n"
            main_branch = None
            try:
                for branch in self.repo.repo.branches:
                    if branch.name in ("main", "master"):
                        main_branch = branch.name
                        break
                if main_branch:
                    result += f"Main branch (you will usually use this for PRs): {main_branch}\n\n"
            except Exception:
                pass
            result += "Status:\n"
            try:
                status = self.repo.repo.git.status("--porcelain")
                if status:
                    status_lines = status.strip().split("\n")
                    staged_added = []
                    staged_modified = []
                    staged_deleted = []
                    unstaged_modified = []
                    unstaged_deleted = []
                    untracked = []
                    for line in status_lines:
                        if len(line) < 4:
                            continue
                        status_code = line[:2]
                        file_path = line[3:]
                        if any(part.startswith(".cecli") for part in file_path.split("/")):
                            continue
                        if status_code[0] == "A":
                            staged_added.append(file_path)
                        elif status_code[0] == "M":
                            staged_modified.append(file_path)
                        elif status_code[0] == "D":
                            staged_deleted.append(file_path)
                        if status_code[1] == "M":
                            unstaged_modified.append(file_path)
                        elif status_code[1] == "D":
                            unstaged_deleted.append(file_path)
                        if status_code == "??":
                            untracked.append(file_path)
                    if staged_added:
                        for file in staged_added:
                            result += f"A  {file}\n"
                    if staged_modified:
                        for file in staged_modified:
                            result += f"M  {file}\n"
                    if staged_deleted:
                        for file in staged_deleted:
                            result += f"D  {file}\n"
                    if unstaged_modified:
                        for file in unstaged_modified:
                            result += f" M {file}\n"
                    if unstaged_deleted:
                        for file in unstaged_deleted:
                            result += f" D {file}\n"
                    if untracked:
                        for file in untracked:
                            result += f"?? {file}\n"
                else:
                    result += "Working tree clean\n"
            except Exception as e:
                result += f"Unable to get modified files: {str(e)}\n"
            result += "\nRecent commits:\n"
            try:
                commits = list(self.repo.repo.iter_commits(max_count=5))
                for commit in commits:
                    short_hash = commit.hexsha[:8]
                    message = commit.message.strip().split("\n")[0]
                    result += f"{short_hash} {message}\n"
            except Exception:
                result += "Unable to get recent commits\n"
            result += "</context>"
            return result
        except Exception as e:
            self.io.tool_error(f"Error generating git status: {str(e)}")
            return None

    def cmd_context_blocks(self, args=""):
        """
        Toggle enhanced context blocks feature.
        """
        self.use_enhanced_context = not self.use_enhanced_context
        if self.use_enhanced_context:
            self.io.tool_output(
                "Enhanced context blocks are now ON - directory structure and git status will be"
                " included."
            )
            self.tokens_calculated = False
            self.context_blocks_cache = {}
        else:
            self.io.tool_output(
                "Enhanced context blocks are now OFF - directory structure and git status will not"
                " be included."
            )
            self.context_block_tokens = {}
            self.context_blocks_cache = {}
            self.tokens_calculated = False
        return True
