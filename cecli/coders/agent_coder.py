import ast
import asyncio
import base64
import json
import locale
import os
import platform
import re
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from litellm import experimental_mcp_client

from cecli import urls, utils
from cecli.change_tracker import ChangeTracker
from cecli.helpers.similarity import (
    cosine_similarity,
    create_bigram_vector,
    normalize_vector,
)
from cecli.helpers.skills import SkillsManager
from cecli.mcp.server import LocalServer
from cecli.repo import ANY_GIT_ERROR
from cecli.tools import TOOL_MODULES

from .base_coder import ChatChunks, Coder
from .editblock_coder import do_replace, find_original_update_blocks, find_similar_lines


class AgentCoder(Coder):
    """Mode where the LLM autonomously manages which files are in context."""

    edit_format = "agent"
    prompt_format = "agent"

    def __init__(self, *args, **kwargs):
        self.recently_removed = {}
        self.tool_usage_history = []
        self.tool_usage_retries = 10
        self.last_round_tools = []
        self.tool_call_vectors = []
        self.tool_similarity_threshold = 0.99
        self.max_tool_vector_history = 10
        self.read_tools = {
            "viewfilesatglob",
            "viewfilesmatching",
            "ls",
            "viewfileswithsymbol",
            "grep",
            "listchanges",
            "extractlines",
            "shownumberedcontext",
        }
        self.write_tools = {
            "command",
            "commandinteractive",
            "insertblock",
            "replaceblock",
            "replaceall",
            "replacetext",
            "undochange",
        }
        self.max_tool_calls = 10000
        self.large_file_token_threshold = 25000
        self.context_management_enabled = True
        self.skills_manager = None
        self.change_tracker = ChangeTracker()
        self.args = kwargs.get("args")
        self.tool_registry = self._build_tool_registry()
        self.files_added_in_exploration = set()
        self.tool_call_count = 0
        self.max_reflections = 15
        self.use_enhanced_context = True
        self._last_edited_file = None
        self._cur_message_divider = None
        self.allowed_context_blocks = set()
        self.context_block_tokens = {}
        self.context_blocks_cache = {}
        self.tokens_calculated = False
        self.skip_cli_confirmations = False
        self.agent_finished = False
        self._get_agent_config()
        super().__init__(*args, **kwargs)

    def _build_tool_registry(self):
        """
        Build a registry of available tools with their normalized names and process_response functions.
        Handles agent configuration with includelist/excludelist functionality.

        Returns:
            dict: Mapping of normalized tool names to tool modules
        """
        registry = {}
        tool_modules = TOOL_MODULES
        agent_config = self._get_agent_config()
        tools_includelist = agent_config.get(
            "tools_includelist", agent_config.get("tools_whitelist", [])
        )
        tools_excludelist = agent_config.get(
            "tools_excludelist", agent_config.get("tools_blacklist", [])
        )
        if "skills" not in self.allowed_context_blocks or not agent_config.get("skills_paths"):
            tools_excludelist.append("loadskill")
            tools_excludelist.append("removeskill")
        essential_tools = {"contextmanager", "replacetext", "finished"}
        for module in tool_modules:
            if hasattr(module, "Tool"):
                tool_class = module.Tool
                tool_name = tool_class.NORM_NAME
                should_include = True
                if tools_includelist:
                    should_include = tool_name in tools_includelist
                if tool_name in essential_tools:
                    should_include = True
                if tool_name in tools_excludelist and tool_name not in essential_tools:
                    should_include = False
                if should_include:
                    registry[tool_name] = tool_class
        return registry

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
        if "large_file_token_threshold" not in config:
            config["large_file_token_threshold"] = 25000
        if "tools_includelist" not in config:
            config["tools_includelist"] = []
        if "tools_excludelist" not in config:
            config["tools_excludelist"] = []
        if "include_context_blocks" in config:
            self.allowed_context_blocks = set(config["include_context_blocks"])
        else:
            self.allowed_context_blocks = {
                "context_summary",
                "directory_structure",
                "environment_info",
                "git_status",
                "symbol_outline",
                "todo_list",
                "skills",
            }
        if "exclude_context_blocks" in config:
            for context_block in config["exclude_context_blocks"]:
                try:
                    self.allowed_context_blocks.remove(context_block)
                except KeyError:
                    pass
        self.large_file_token_threshold = config["large_file_token_threshold"]
        self.skip_cli_confirmations = config.get(
            "skip_cli_confirmations", config.get("yolo", False)
        )
        if "skills" in self.allowed_context_blocks:
            if "skills_paths" not in config:
                config["skills_paths"] = []
            if "skills_includelist" not in config:
                config["skills_includelist"] = []
            if "skills_excludelist" not in config:
                config["skills_excludelist"] = []
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
        for tool_module in self.tool_registry.values():
            if hasattr(tool_module, "SCHEMA"):
                schemas.append(tool_module.SCHEMA)
        return schemas

    async def initialize_mcp_tools(self):
        await super().initialize_mcp_tools()
        server_name = "Local"
        if server_name not in [name for name, _ in self.mcp_tools]:
            local_tools = self.get_local_tool_schemas()
            if not local_tools:
                return
            local_server_config = {"name": server_name}
            local_server = LocalServer(local_server_config)
            if not self.mcp_servers:
                self.mcp_servers = []
            if not any(isinstance(s, LocalServer) for s in self.mcp_servers):
                self.mcp_servers.append(local_server)
            if not self.mcp_tools:
                self.mcp_tools = []
            if server_name not in [name for name, _ in self.mcp_tools]:
                self.mcp_tools.append((local_server.name, local_tools))

    async def _execute_local_tool_calls(self, tool_calls_list):
        tool_responses = []
        for tool_call in tool_calls_list:
            tool_name = tool_call.function.name
            result_message = ""
            try:
                args_string = tool_call.function.arguments.strip()
                parsed_args_list = []
                if args_string:
                    json_chunks = utils.split_concatenated_json(args_string)
                    for chunk in json_chunks:
                        try:
                            parsed_args_list.append(json.loads(chunk))
                        except json.JSONDecodeError:
                            self.io.tool_warning(
                                f"Could not parse JSON chunk for tool {tool_name}: {chunk}"
                            )
                            continue
                if not parsed_args_list and not args_string:
                    parsed_args_list.append({})
                all_results_content = []
                norm_tool_name = tool_name.lower()
                tasks = []
                if norm_tool_name in self.tool_registry:
                    tool_module = self.tool_registry[norm_tool_name]
                    for params in parsed_args_list:
                        result = tool_module.process_response(self, params)
                        if asyncio.iscoroutine(result):
                            tasks.append(result)
                        else:
                            tasks.append(asyncio.to_thread(lambda: result))
                elif self.mcp_tools:
                    for server_name, server_tools in self.mcp_tools:
                        if any(
                            t.get("function", {}).get("name") == norm_tool_name
                            for t in server_tools
                        ):
                            server = next(
                                (s for s in self.mcp_servers if s.name == server_name), None
                            )
                            if server:
                                for params in parsed_args_list:
                                    tasks.append(
                                        self._execute_mcp_tool(server, norm_tool_name, params)
                                    )
                                break
                    else:
                        all_results_content.append(f"Error: Unknown tool name '{tool_name}'")
                else:
                    all_results_content.append(f"Error: Unknown tool name '{tool_name}'")
                if tasks:
                    task_results = await asyncio.gather(*tasks)
                    all_results_content.extend(str(res) for res in task_results)
                result_message = "\n\n".join(all_results_content)
            except Exception as e:
                result_message = f"Error executing {tool_name}: {e}"
                self.io.tool_error(f"""Error during {tool_name} execution: {e}
{traceback.format_exc()}""")
            tool_responses.append(
                {"role": "tool", "tool_call_id": tool_call.id, "content": result_message}
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
                call_result = await experimental_mcp_client.call_openai_tool(
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
                        self.context_block_tokens[block_type] = self.main_model.token_count(
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
            result = '<context name="symbol_outline">\n'
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
                            line_info = f", line {tag.line + 1}" if tag.line >= 0 else ""
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
            return super().format_chat_chunks()
        self.choose_fence()
        main_sys = self.fmt_system_prompt(self.gpt_prompts.main_system)
        example_messages = []
        if self.main_model.examples_as_sys_msg:
            if self.gpt_prompts.example_messages:
                main_sys += "\n# Example conversations:\n\n"
            for msg in self.gpt_prompts.example_messages:
                role = msg["role"]
                content = self.fmt_system_prompt(msg["content"])
                main_sys += f"## {role.upper()}: {content}\n\n"
            main_sys = main_sys.strip()
        else:
            for msg in self.gpt_prompts.example_messages:
                example_messages.append(
                    dict(role=msg["role"], content=self.fmt_system_prompt(msg["content"]))
                )
            if self.gpt_prompts.example_messages:
                example_messages += [
                    dict(
                        role="user",
                        content=(
                            "I switched to a new code base. Please don't consider the above files"
                            " or try to edit them any longer."
                        ),
                    ),
                    dict(role="assistant", content="Ok."),
                ]
        if self.gpt_prompts.system_reminder:
            main_sys += "\n" + self.fmt_system_prompt(self.gpt_prompts.system_reminder)
        chunks = ChatChunks(
            chunk_ordering=[
                "system",
                "static",
                "examples",
                "readonly_files",
                "repo",
                "chat_files",
                "pre_message",
                "done",
                "edit_files",
                "cur",
                "post_message",
                "reminder",
            ]
        )
        if self.main_model.use_system_prompt:
            chunks.system = [dict(role="system", content=main_sys)]
        else:
            chunks.system = [
                dict(role="user", content=main_sys),
                dict(role="assistant", content="Ok."),
            ]
        chunks.examples = example_messages
        self.summarize_end()
        cur_messages_list = list(self.cur_messages)
        cur_messages_pre = []
        cur_messages_post = cur_messages_list
        chunks.readonly_files = self.get_readonly_files_messages()
        chat_files_result = self.get_chat_files_messages()
        chunks.chat_files = chat_files_result.get("chat_files", [])
        chunks.edit_files = chat_files_result.get("edit_files", [])
        edit_file_names = chat_files_result.get("edit_file_names", set())
        divider = self._update_edit_file_tracking(edit_file_names)
        if divider is not None:
            if divider > 0 and divider < len(cur_messages_list):
                cur_messages_pre = cur_messages_list[:divider]
                cur_messages_post = cur_messages_list[divider:]
        chunks.repo = self.get_repo_messages()
        chunks.done = list(self.done_messages) + cur_messages_pre
        if self.gpt_prompts.system_reminder:
            reminder_message = [
                dict(
                    role="system", content=self.fmt_system_prompt(self.gpt_prompts.system_reminder)
                )
            ]
        else:
            reminder_message = []
        chunks.cur = cur_messages_post
        chunks.reminder = []
        self._calculate_context_block_tokens()
        chunks.static = []
        chunks.pre_message = []
        chunks.post_message = []
        static_blocks = []
        pre_message_blocks = []
        post_message_blocks = []
        if "environment_info" in self.allowed_context_blocks:
            block = self.get_cached_context_block("environment_info")
            static_blocks.append(block)
        if "directory_structure" in self.allowed_context_blocks:
            block = self.get_cached_context_block("directory_structure")
            static_blocks.append(block)
        if "skills" in self.allowed_context_blocks:
            block = self._generate_context_block("skills")
            static_blocks.append(block)
        if "symbol_outline" in self.allowed_context_blocks:
            block = self.get_cached_context_block("symbol_outline")
            pre_message_blocks.append(block)
        if "git_status" in self.allowed_context_blocks:
            block = self.get_cached_context_block("git_status")
            pre_message_blocks.append(block)
        if "todo_list" in self.allowed_context_blocks:
            block = self.get_cached_context_block("todo_list")
            pre_message_blocks.append(block)
        if "skills" in self.allowed_context_blocks:
            block = self._generate_context_block("loaded_skills")
            pre_message_blocks.append(block)
        if "context_summary" in self.allowed_context_blocks:
            block = self.get_context_summary()
            pre_message_blocks.insert(0, block)
        if hasattr(self, "tool_usage_history") and self.tool_usage_history:
            repetitive_tools = self._get_repetitive_tools()
            if repetitive_tools:
                tool_context = self._generate_tool_context(repetitive_tools)
                if tool_context:
                    post_message_blocks.append(tool_context)
            else:
                write_context = self._generate_write_context()
                if write_context:
                    post_message_blocks.append(write_context)
        if static_blocks:
            for block in static_blocks:
                if block:
                    chunks.static.append(dict(role="system", content=block))
        if pre_message_blocks:
            for block in pre_message_blocks:
                if block:
                    chunks.pre_message.append(dict(role="system", content=block))
        if post_message_blocks:
            for block in post_message_blocks:
                if block:
                    chunks.post_message.append(dict(role="system", content=block))
        base_messages = chunks.all_messages()
        messages_tokens = self.main_model.token_count(base_messages)
        reminder_tokens = self.main_model.token_count(reminder_message)
        cur_tokens = self.main_model.token_count(chunks.cur)
        if None not in (messages_tokens, reminder_tokens, cur_tokens):
            total_tokens = messages_tokens
            if not chunks.reminder:
                total_tokens += reminder_tokens
            if not chunks.cur:
                total_tokens += cur_tokens
        else:
            total_tokens = 0
        if chunks.cur:
            final = chunks.cur[-1]
        else:
            final = None
        max_input_tokens = self.main_model.info.get("max_input_tokens") or 0
        if (
            not max_input_tokens
            or total_tokens < max_input_tokens
            and self.gpt_prompts.system_reminder
        ):
            if self.main_model.reminder == "sys":
                chunks.reminder = reminder_message
            elif self.main_model.reminder == "user" and final and final["role"] == "user":
                new_content = (
                    final["content"]
                    + "\n\n"
                    + self.fmt_system_prompt(self.gpt_prompts.system_reminder)
                )
                chunks.cur[-1] = dict(role=final["role"], content=new_content)
        if self.verbose:
            self._log_chunks(chunks)
        return chunks

    def _update_edit_file_tracking(self, edit_file_names):
        """
        Update tracking for last edited file and message divider for caching efficiency.

        When the last edited file changes, we store the current message index minus 4
        as a divider to split cur_messages, moving older messages to done_messages
        for better caching.
        """
        kept_messages = 8
        if not edit_file_names:
            self._cur_message_divider = 0
        sorted_edit_files = sorted(edit_file_names)
        current_edited_file = sorted_edit_files[0] if sorted_edit_files else None
        if current_edited_file != self._last_edited_file:
            self._last_edited_file = current_edited_file
            cur_messages_list = list(self.cur_messages)
            if len(cur_messages_list) > kept_messages:
                self._cur_message_divider = len(cur_messages_list) - kept_messages
            else:
                self._cur_message_divider = 0
        return self._cur_message_divider

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
            result = '<context name="context_summary">\n'
            result += "## Current Context Overview\n\n"
            max_input_tokens = self.main_model.info.get("max_input_tokens") or 0
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
                        tokens = self.main_model.token_count(content)
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
                        tokens = self.main_model.token_count(content)
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
            result = '<context name="environment_info">\n'
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
            features = []
            if self.context_management_enabled:
                features.append("context management")
            if self.use_enhanced_context:
                features.append("enhanced context blocks")
            if features:
                result += f"- Enabled features: {', '.join(features)}\n"
            result += "</context>"
            return result
        except Exception as e:
            self.io.tool_error(f"Error generating environment info: {str(e)}")
            return None

    async def process_tool_calls(self, tool_call_response):
        """
        Track tool usage before calling the base implementation.
        """
        self.agent_finished = False
        await self.auto_save_session()
        self.last_round_tools = []
        if self.partial_response_tool_calls:
            for tool_call in self.partial_response_tool_calls:
                tool_name = tool_call.get("function", {}).get("name")
                if tool_name:
                    self.last_round_tools.append(tool_name)
                    tool_call_copy = tool_call.copy()
                    if "id" in tool_call_copy:
                        del tool_call_copy["id"]
                    tool_call_str = str(tool_call_copy)
                    tool_vector = create_bigram_vector((tool_call_str,))
                    tool_vector_norm = normalize_vector(tool_vector)
                    self.tool_call_vectors.append(tool_vector_norm)
        if self.last_round_tools:
            self.tool_usage_history += self.last_round_tools
            self.tool_usage_history = list(filter(None, self.tool_usage_history))
        if len(self.tool_usage_history) > self.tool_usage_retries:
            self.tool_usage_history.pop(0)
        if len(self.tool_call_vectors) > self.max_tool_vector_history:
            self.tool_call_vectors.pop(0)
        return await super().process_tool_calls(tool_call_response)

    async def reply_completed(self):
        """Process the completed response from the LLM.

        This is a key method that:
        1. Processes any tool commands in the response (only after a '---' line)
        2. Processes any SEARCH/REPLACE blocks in the response (only before the '---' line if one exists)
        3. If tool commands were found, sets up for another automatic round

        This enables the "auto-exploration" workflow where the LLM can
        iteratively discover and analyze relevant files before providing
        a final answer to the user's question.
        """
        content = self.partial_response_content
        if not content or not content.strip():
            if len(self.tool_usage_history) > self.tool_usage_retries:
                self.tool_usage_history = []
            return True
        original_content = content
        (
            processed_content,
            result_messages,
            tool_calls_found,
            content_before_last_separator,
            tool_names_this_turn,
        ) = await self._process_tool_commands(content)
        if self.agent_finished:
            self.tool_usage_history = []
            if self.files_edited_by_tools:
                _ = await self.auto_commit(self.files_edited_by_tools)
            return False
        self.partial_response_content = processed_content.strip()
        self._process_file_mentions(processed_content)
        has_search = "<<<<<<< SEARCH" in self.partial_response_content
        has_divider = "=======" in self.partial_response_content
        has_replace = ">>>>>>> REPLACE" in self.partial_response_content
        edit_match = has_search and has_divider and has_replace
        separator_marker = "\n---\n"
        if separator_marker in original_content and edit_match:
            has_search_before = "<<<<<<< SEARCH" in content_before_last_separator
            has_divider_before = "=======" in content_before_last_separator
            has_replace_before = ">>>>>>> REPLACE" in content_before_last_separator
            edit_match = has_search_before and has_divider_before and has_replace_before
        if edit_match:
            self.io.tool_output("Detected edit blocks, applying changes within Agent...")
            edited_files = await self._apply_edits_from_response()
            if self.reflected_message:
                return False
            if edited_files and self.num_reflections < self.max_reflections:
                if self.cur_messages and len(self.cur_messages) >= 1:
                    for msg in reversed(self.cur_messages):
                        if msg["role"] == "user":
                            original_question = msg["content"]
                            break
                    else:
                        original_question = (
                            "Please continue your exploration and provide a final answer."
                        )
                    next_prompt = f"""
I have applied the edits you suggested.
The following files were modified: {', '.join(edited_files)}. Let me continue working on your request.
Your original question was: {original_question}"""
                    self.reflected_message = next_prompt
                    self.io.tool_output("Continuing after applying edits...")
                    return False
        if tool_calls_found and self.num_reflections < self.max_reflections:
            self.tool_call_count = 0
            self.files_added_in_exploration = set()
            if self.cur_messages and len(self.cur_messages) >= 1:
                for msg in reversed(self.cur_messages):
                    if msg["role"] == "user":
                        original_question = msg["content"]
                        break
                else:
                    original_question = (
                        "Please continue your exploration and provide a final answer."
                    )
                next_prompt_parts = []
                next_prompt_parts.append(
                    "I have processed the results of the previous tool calls. Let me analyze them"
                    " and continue working towards your request."
                )
                if result_messages:
                    next_prompt_parts.append("\nResults from previous tool calls:")
                    next_prompt_parts.extend(result_messages)
                    next_prompt_parts.append("""
Based on these results and the updated file context, I will proceed.""")
                else:
                    next_prompt_parts.append("""
No specific results were returned from the previous tool calls, but the file context may have been updated.
I will proceed based on the current context.""")
                next_prompt_parts.append(f"\nYour original question was: {original_question}")
                self.reflected_message = "\n".join(next_prompt_parts)
                self.io.tool_output("Continuing exploration...")
                return False
        elif result_messages:
            results_block = "\n\n" + "\n".join(result_messages)
            self.partial_response_content += results_block
        if self.files_edited_by_tools:
            saved_message = await self.auto_commit(self.files_edited_by_tools)
            if not saved_message and hasattr(self.gpt_prompts, "files_content_gpt_edits_no_repo"):
                saved_message = self.gpt_prompts.files_content_gpt_edits_no_repo
            self.move_back_cur_messages(saved_message)
        self.tool_call_count = 0
        self.files_added_in_exploration = set()
        self.files_edited_by_tools = set()
        self.move_back_cur_messages(None)
        return False

    async def _execute_tool_with_registry(self, norm_tool_name, params):
        """
        Execute a tool using the tool registry.

        Args:
            norm_tool_name: Normalized tool name (lowercase)
            params: Dictionary of parameters

        Returns:
            str: Result message
        """
        if norm_tool_name in self.tool_registry:
            tool_module = self.tool_registry[norm_tool_name]
            try:
                result = tool_module.process_response(self, params)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except Exception as e:
                self.io.tool_error(f"""Error during {norm_tool_name} execution: {e}
{traceback.format_exc()}""")
                return f"Error executing {norm_tool_name}: {str(e)}"
        if self.mcp_tools:
            for server_name, server_tools in self.mcp_tools:
                if any(t.get("function", {}).get("name") == norm_tool_name for t in server_tools):
                    server = next((s for s in self.mcp_servers if s.name == server_name), None)
                    if server:
                        return await self._execute_mcp_tool(server, norm_tool_name, params)
                    else:
                        return f"Error: Could not find server instance for {server_name}"
        return f"Error: Unknown tool name '{norm_tool_name}'"

    def _convert_concatenated_json_to_tool_calls(self, content):
        """
        Check if content contains concatenated JSON objects and convert them to tool call format.

        Args:
            content (str): Content to check for concatenated JSON

        Returns:
            str: Content with concatenated JSON converted to tool call format, or original content if no JSON found
        """
        try:
            json_chunks = utils.split_concatenated_json(content)
            if len(json_chunks) >= 1:
                tool_calls = []
                for chunk in json_chunks:
                    try:
                        json_obj = json.loads(chunk)
                        if (
                            isinstance(json_obj, dict)
                            and "name" in json_obj
                            and "arguments" in json_obj
                        ):
                            tool_name = json_obj["name"]
                            arguments = json_obj["arguments"]
                            kw_args = []
                            for key, value in arguments.items():
                                if isinstance(value, str):
                                    escaped_value = value.replace('"', '\\"')
                                    kw_args.append(f'{key}="{escaped_value}"')
                                elif isinstance(value, bool):
                                    kw_args.append(f"{key}={str(value).lower()}")
                                elif value is None:
                                    kw_args.append(f"{key}=None")
                                else:
                                    kw_args.append(f"{key}={repr(value)}")
                            kw_args_str = ", ".join(kw_args)
                            tool_call = f"[tool_call({tool_name}, {kw_args_str})]"
                            tool_calls.append(tool_call)
                        else:
                            tool_calls.append(chunk)
                    except json.JSONDecodeError:
                        tool_calls.append(chunk)
                if any(call.startswith("[tool_") for call in tool_calls):
                    return "".join(tool_calls)
        except Exception as e:
            self.io.tool_warning(f"Error converting concatenated JSON to tool calls: {str(e)}")
        return content

    async def _process_tool_commands(self, content):
        """
        Process tool commands in the `[tool_call(name, param=value)]` format within the content.

        Rules:
        1. Tool calls must appear after the LAST '---' line separator in the content
        2. Any tool calls before this last separator are treated as text (not executed)
        3. SEARCH/REPLACE blocks can only appear before this last separator

        Returns processed content, result messages, and a flag indicating if any tool calls were found.
        Also returns the content before the last separator for SEARCH/REPLACE block validation.
        """
        result_messages = []
        modified_content = content
        tool_calls_found = False
        call_count = 0
        max_calls = self.max_tool_calls
        tool_names = []
        content = self._convert_concatenated_json_to_tool_calls(content)
        separator_marker = "---"
        content_parts = content.split(separator_marker)
        if len(content_parts) == 1:
            tool_call_pattern = "\\[tool_call\\([^\\]]+\\)\\]"
            if re.search(tool_call_pattern, content):
                content_before_separator = ""
                content_after_separator = content
            else:
                return content, result_messages, False, content, tool_names
        content_before_separator = separator_marker.join(content_parts[:-1])
        content_after_separator = content_parts[-1]
        processed_content = content_before_separator + separator_marker
        last_index = 0
        tool_call_pattern = re.compile("\\[tool_.*?\\(", re.DOTALL)
        end_marker = "]"
        while True:
            match = tool_call_pattern.search(content_after_separator, last_index)
            if not match:
                processed_content += content_after_separator[last_index:]
                break
            start_pos = match.start()
            start_marker = match.group(0)
            backslashes = 0
            p = start_pos - 1
            while p >= 0 and content_after_separator[p] == "\\":
                backslashes += 1
                p -= 1
            if backslashes % 2 == 1:
                processed_content += content_after_separator[
                    last_index : start_pos + len(start_marker)
                ]
                last_index = start_pos + len(start_marker)
                continue
            processed_content += content_after_separator[last_index:start_pos]
            scan_start_pos = start_pos + len(start_marker)
            paren_level = 1
            in_single_quotes = False
            in_double_quotes = False
            escaped = False
            end_paren_pos = -1
            for i in range(scan_start_pos, len(content_after_separator)):
                char = content_after_separator[i]
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "'" and not in_double_quotes:
                    in_single_quotes = not in_single_quotes
                elif char == '"' and not in_single_quotes:
                    in_double_quotes = not in_double_quotes
                elif char == "(" and not in_single_quotes and not in_double_quotes:
                    paren_level += 1
                elif char == ")" and not in_single_quotes and not in_double_quotes:
                    paren_level -= 1
                    if paren_level == 0:
                        end_paren_pos = i
                        break
            expected_end_marker_start = end_paren_pos + 1
            actual_end_marker_start = -1
            end_marker_found = False
            if end_paren_pos != -1:
                for j in range(expected_end_marker_start, len(content_after_separator)):
                    if not content_after_separator[j].isspace():
                        actual_end_marker_start = j
                        if content_after_separator[actual_end_marker_start] == end_marker:
                            end_marker_found = True
                        break
            if not end_marker_found:
                tool_name = "unknown"
                try:
                    partial_content = content_after_separator[scan_start_pos : scan_start_pos + 100]
                    comma_pos = partial_content.find(",")
                    if comma_pos > 0:
                        tool_name = partial_content[:comma_pos].strip()
                    else:
                        space_pos = partial_content.find(" ")
                        paren_pos = partial_content.find("(")
                        if space_pos > 0 and (paren_pos < 0 or space_pos < paren_pos):
                            tool_name = partial_content[:space_pos].strip()
                        elif paren_pos > 0:
                            tool_name = partial_content[:paren_pos].strip()
                except Exception:
                    pass
                self.io.tool_warning(
                    f"Malformed tool call for '{tool_name}'. Missing closing parenthesis or"
                    " bracket. Skipping."
                )
                processed_content += start_marker
                last_index = scan_start_pos
                continue
            full_match_str = content_after_separator[start_pos : actual_end_marker_start + 1]
            inner_content = content_after_separator[scan_start_pos:end_paren_pos].strip()
            last_index = actual_end_marker_start + 1
            call_count += 1
            if call_count > max_calls:
                self.io.tool_warning(
                    f"Exceeded maximum tool calls ({max_calls}). Skipping remaining calls."
                )
                continue
            tool_calls_found = True
            tool_name = None
            params = {}
            result_message = None
            tool_calls_found = True
            try:
                if inner_content:
                    parts = inner_content.split(",", 1)
                    potential_tool_name = parts[0].strip()
                    is_string = (
                        potential_tool_name.startswith("'")
                        and potential_tool_name.endswith("'")
                        or potential_tool_name.startswith('"')
                        and potential_tool_name.endswith('"')
                    )
                    if not potential_tool_name.isidentifier() and not is_string:
                        quoted_tool_name = json.dumps(potential_tool_name)
                        if len(parts) > 1:
                            inner_content = quoted_tool_name + ", " + parts[1]
                        else:
                            inner_content = quoted_tool_name
                parse_str = f"f({inner_content})"
                parsed_ast = ast.parse(parse_str)
                if (
                    not isinstance(parsed_ast, ast.Module)
                    or not parsed_ast.body
                    or not isinstance(parsed_ast.body[0], ast.Expr)
                ):
                    raise ValueError("Unexpected AST structure")
                call_node = parsed_ast.body[0].value
                if not isinstance(call_node, ast.Call):
                    raise ValueError("Expected a Call node")
                if not call_node.args:
                    raise ValueError("Tool name not found or invalid")
                tool_name_node = call_node.args[0]
                if isinstance(tool_name_node, ast.Name):
                    tool_name = tool_name_node.id
                elif isinstance(tool_name_node, ast.Constant) and isinstance(
                    tool_name_node.value, str
                ):
                    tool_name = tool_name_node.value
                else:
                    raise ValueError("Tool name must be an identifier or a string literal")
                tool_names.append(tool_name)
                for keyword in call_node.keywords:
                    key = keyword.arg
                    value_node = keyword.value
                    if isinstance(value_node, ast.Constant):
                        value = value_node.value
                        if isinstance(value, str) and "\n" in value:
                            lineno = value_node.lineno if hasattr(value_node, "lineno") else 0
                            end_lineno = (
                                value_node.end_lineno
                                if hasattr(value_node, "end_lineno")
                                else lineno
                            )
                            if end_lineno > lineno:
                                if value.startswith("\n"):
                                    value = value[1:]
                                if value.endswith("\n"):
                                    value = value[:-1]
                    elif isinstance(value_node, ast.Name):
                        id_val = value_node.id.lower()
                        if id_val == "true":
                            value = True
                        elif id_val == "false":
                            value = False
                        elif id_val == "none":
                            value = None
                        else:
                            value = value_node.id
                    else:
                        try:
                            value = ast.unparse(value_node)
                        except AttributeError:
                            raise ValueError(
                                f"Unsupported argument type for key '{key}': {type(value_node)}"
                            )
                        except Exception as unparse_e:
                            raise ValueError(
                                f"Could not unparse value for key '{key}': {unparse_e}"
                            )
                    suppressed_arg_values = ["..."]
                    if isinstance(value, str) and value in suppressed_arg_values:
                        self.io.tool_warning(
                            f"Skipping suppressed argument value '{value}' for key '{key}' in tool"
                            f" '{tool_name}'"
                        )
                        continue
                    params[key] = value
            except (SyntaxError, ValueError) as e:
                result_message = f"Error parsing tool call '{inner_content}': {e}"
                self.io.tool_error(f"Failed to parse tool call: {full_match_str}\nError: {e}")
                result_messages.append(f"[Result (Parse Error): {result_message}]")
                continue
            except Exception as e:
                result_message = f"Unexpected error parsing tool call '{inner_content}': {e}"
                self.io.tool_error(f"""Unexpected error during parsing: {full_match_str}
Error: {e}
{traceback.format_exc()}""")
                result_messages.append(f"[Result (Parse Error): {result_message}]")
                continue
            try:
                norm_tool_name = tool_name.lower()
                result_message = await self._execute_tool_with_registry(norm_tool_name, params)
            except Exception as e:
                result_message = f"Error executing {tool_name}: {str(e)}"
                self.io.tool_error(f"""Error during {tool_name} execution: {e}
{traceback.format_exc()}""")
            if result_message:
                result_messages.append(f"[Result ({tool_name}): {result_message}]")
        self.tool_call_count += call_count
        modified_content = processed_content
        return (
            modified_content,
            result_messages,
            tool_calls_found,
            content_before_separator,
            tool_names,
        )

    def _get_repetitive_tools(self):
        """
        Identifies repetitive tool usage patterns from rounds of tool calls.

        This method combines count-based and similarity-based detection:
        1. If the last round contained a write tool, it assumes progress and returns no repetitive tools.
        2. It checks for any read tool that has been used 2 or more times across rounds.
        3. If no tools are repeated, but all tools in the history are read tools,
           it flags all of them as potentially repetitive.
        4. It checks for similarity-based repetition using cosine similarity on tool call strings.

        It avoids flagging repetition if a "write" tool was used recently,
        as that suggests progress is being made.
        """
        history_len = len(self.tool_usage_history)
        if history_len < 5:
            return set()
        similarity_repetitive_tools = self._get_repetitive_tools_by_similarity()
        all_tools = []
        for round_tools in self.tool_usage_history:
            all_tools.extend(round_tools)
        if self.last_round_tools:
            last_round_has_write = any(
                tool.lower() in self.write_tools for tool in self.last_round_tools
            )
            if last_round_has_write:
                self.tool_usage_history = []
                return similarity_repetitive_tools if len(similarity_repetitive_tools) else set()
        if all(tool.lower() in self.read_tools for tool in all_tools):
            return set(all_tools)
        tool_counts = Counter(all_tools)
        count_repetitive_tools = {
            tool
            for tool, count in tool_counts.items()
            if count >= 5 and tool.lower() in self.read_tools
        }
        repetitive_tools = count_repetitive_tools.union(similarity_repetitive_tools)
        if repetitive_tools:
            return repetitive_tools
        return set()

    def _get_repetitive_tools_by_similarity(self):
        """
        Identifies repetitive tool usage patterns using cosine similarity on tool call strings.

        This method checks if the latest tool calls are highly similar (>0.99 threshold)
        to historical tool calls using bigram vector similarity.

        Returns:
            set: Set of tool names that are repetitive based on similarity
        """
        if not self.tool_usage_history or len(self.tool_call_vectors) < 2:
            return set()
        latest_vector = self.tool_call_vectors[-1]
        for i, historical_vector in enumerate(self.tool_call_vectors[:-1]):
            similarity = cosine_similarity(latest_vector, historical_vector)
            if similarity >= self.tool_similarity_threshold:
                if i < len(self.tool_usage_history):
                    return {self.tool_usage_history[i]}
        return set()

    def _generate_tool_context(self, repetitive_tools):
        """
        Generate a context message for the LLM about recent tool usage.
        """
        if not self.tool_usage_history:
            return ""
        context_parts = ['<context name="tool_usage_history">']
        context_parts.append("## Turn and Tool Call Statistics")
        context_parts.append(f"- Current turn: {self.num_reflections + 1}")
        context_parts.append(f"- Total tool calls this turn: {self.num_tool_calls}")
        context_parts.append("\n\n")
        context_parts.append("## Recent Tool Usage History")
        if len(self.tool_usage_history) > 10:
            recent_history = self.tool_usage_history[-10:]
            context_parts.append("(Showing last 10 tools)")
        else:
            recent_history = self.tool_usage_history
        for i, tool in enumerate(recent_history, 1):
            context_parts.append(f"{i}. {tool}")
        context_parts.append("\n\n")
        if repetitive_tools:
            context_parts.append("""**Instruction:**
You have used the following tool(s) repeatedly:""")
            context_parts.append("### DO NOT USE THE FOLLOWING TOOLS/FUNCTIONS")
            for tool in repetitive_tools:
                context_parts.append(f"- `{tool}`")
            context_parts.append(
                "Your exploration appears to be stuck in a loop. Please try a different approach."
                " Use the `Thinking` tool to clarify your intentions and new approach to what you"
                " are currently attempting to accomplish."
            )
            context_parts.append("\n")
            context_parts.append("**Suggestions for alternative approaches:**")
            context_parts.append(
                "- If you've been searching for files, try working with the files already in"
                " context"
            )
            context_parts.append(
                "- If you've been viewing files, try making actual edits to move forward"
            )
            context_parts.append("- Consider using different tools that you haven't used recently")
            context_parts.append(
                "- Focus on making concrete progress rather than gathering more information"
            )
            context_parts.append(
                "- Use the files you've already discovered to implement the requested changes"
            )
            context_parts.append("\n")
            context_parts.append(
                "You most likely have enough context for a subset of the necessary changes."
            )
            context_parts.append("Please prioritize file editing over further exploration.")
        context_parts.append("</context>")
        return "\n".join(context_parts)

    def _generate_write_context(self):
        if self.last_round_tools:
            last_round_has_write = any(
                tool.lower() in self.write_tools for tool in self.last_round_tools
            )
            if last_round_has_write:
                context_parts = [
                    '<context name="tool_usage_history">',
                    "A file was just edited.",
                    (
                        " Do not just modify comments and/or logging statements with placeholder"
                        " information."
                    ),
                    "Make sure that something of value was done.</context>",
                ]
                return "\n".join(context_parts)
        return ""

    async def _apply_edits_from_response(self):
        """
        Parses and applies SEARCH/REPLACE edits found in self.partial_response_content.
        Returns a set of relative file paths that were successfully edited.
        """
        edited_files = set()
        try:
            edits = list(
                find_original_update_blocks(
                    self.partial_response_content, self.fence, self.get_inchat_relative_files()
                )
            )
            self.shell_commands += [edit[1] for edit in edits if edit[0] is None]
            edits = [edit for edit in edits if edit[0] is not None]
            prepared_edits = []
            seen_paths = dict()
            self.need_commit_before_edits = set()
            for edit in edits:
                path = edit[0]
                if path in seen_paths:
                    allowed = seen_paths[path]
                else:
                    allowed = await self.allowed_to_edit(path)
                    seen_paths[path] = allowed
                if allowed:
                    prepared_edits.append(edit)
            await self.dirty_commit()
            self.need_commit_before_edits = set()
            failed = []
            passed = []
            for edit in prepared_edits:
                path, original, updated = edit
                full_path = self.abs_root_path(path)
                new_content = None
                if Path(full_path).exists():
                    content = self.io.read_text(full_path)
                    new_content = do_replace(full_path, content, original, updated, self.fence)
                if not new_content and original.strip():
                    for other_full_path in self.abs_fnames:
                        if other_full_path == full_path:
                            continue
                        other_content = self.io.read_text(other_full_path)
                        other_new_content = do_replace(
                            other_full_path, other_content, original, updated, self.fence
                        )
                        if other_new_content:
                            path = self.get_rel_fname(other_full_path)
                            full_path = other_full_path
                            new_content = other_new_content
                            self.io.tool_warning(f"Applied edit intended for {edit[0]} to {path}")
                            break
                if new_content:
                    if not self.dry_run:
                        self.io.write_text(full_path, new_content)
                        self.io.tool_output(f"Applied edit to {path}")
                    else:
                        self.io.tool_output(f"Did not apply edit to {path} (--dry-run)")
                    passed.append((path, original, updated))
                else:
                    failed.append(edit)
            if failed:
                blocks = "block" if len(failed) == 1 else "blocks"
                error_message = f"# {len(failed)} SEARCH/REPLACE {blocks} failed to match!\n"
                for edit in failed:
                    path, original, updated = edit
                    full_path = self.abs_root_path(path)
                    content = self.io.read_text(full_path)
                    error_message += f"""
## SearchReplaceNoExactMatch: This SEARCH block failed to exactly match lines in {path}
<<<<<<< SEARCH
{original}=======
{updated}>>>>>>> REPLACE

"""
                    did_you_mean = find_similar_lines(original, content)
                    if did_you_mean:
                        error_message += f"""Did you mean to match some of these actual lines from {path}?

{self.fence[0]}
{did_you_mean}
{self.fence[1]}

"""
                    if updated in content and updated:
                        error_message += f"""Are you sure you need this SEARCH/REPLACE block?
The REPLACE lines are already in {path}!

"""
                error_message += (
                    "The SEARCH section must exactly match an existing block of lines including all"
                    " white space, comments, indentation, docstrings, etc"
                )
                if passed:
                    pblocks = "block" if len(passed) == 1 else "blocks"
                    error_message += f"""
# The other {len(passed)} SEARCH/REPLACE {pblocks} were applied successfully.
Don't re-send them.
Just reply with fixed versions of the {blocks} above that failed to match.
"""
                self.io.tool_error(error_message)
                self.reflected_message = error_message
            edited_files = set(edit[0] for edit in passed)
            if edited_files:
                self.coder_edited_files.update(edited_files)
                self.auto_commit(edited_files)
                if self.auto_lint:
                    lint_errors = self.lint_edited(edited_files)
                    self.auto_commit(edited_files, context="Ran the linter")
                    if lint_errors and not self.reflected_message:
                        ok = await self.io.confirm_ask("Attempt to fix lint errors?")
                        if ok:
                            self.reflected_message = lint_errors
                shared_output = await self.run_shell_commands()
                if shared_output:
                    self.io.tool_output("Shell command output:\n" + shared_output)
                if self.auto_test and not self.reflected_message:
                    test_errors = await self.commands.cmd_test(self.test_cmd)
                    if test_errors:
                        ok = await self.io.confirm_ask("Attempt to fix test errors?")
                        if ok:
                            self.reflected_message = test_errors
            self.show_undo_hint()
        except ValueError as err:
            self.num_malformed_responses += 1
            error_message = err.args[0]
            self.io.tool_error("The LLM did not conform to the edit format.")
            self.io.tool_output(urls.edit_errors)
            self.io.tool_output()
            self.io.tool_output(str(error_message))
            self.reflected_message = str(error_message)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Git error during edit application: {str(err)}")
            self.reflected_message = f"Git error during edit application: {str(err)}"
        except Exception as err:
            self.io.tool_error("Exception while applying edits:")
            self.io.tool_error(str(err), strip=False)
            self.io.tool_error(traceback.format_exc())
            self.reflected_message = f"Exception while applying edits: {str(err)}"
        return edited_files

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
                file_tokens = self.main_model.token_count(content)
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

    def _process_file_mentions(self, content):
        """
        Process implicit file mentions in the content, adding files if they're not already in context.

        This handles the case where the LLM mentions file paths without using explicit tool commands.
        """
        mentioned_files = set(self.get_file_mentions(content, ignore_current=False))
        current_files = set(self.get_inchat_relative_files())
        mentioned_files - current_files
        pass

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
        if inp and not inp.startswith('<context name="user_input">'):
            inp = f'<context name="user_input">\n{inp}\n</context>'
        return inp

    def get_directory_structure(self):
        """
        Generate a structured directory listing of the project file structure.
        Returns a formatted string representation of the directory tree.
        """
        if not self.use_enhanced_context:
            return None
        try:
            result = '<context name="directoryStructure">\n'
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
        Generate a todo list context block from the .cecli.todo.txt file.
        Returns formatted string with the current todo list or None if empty/not present.
        """
        try:
            todo_file_path = ".cecli.todo.txt"
            abs_path = self.abs_root_path(todo_file_path)
            import os

            if not os.path.isfile(abs_path):
                return """<context name="todo_list">
Todo list does not exist. Please update it with the `UpdataTodoList` tool.</context>"""
            content = self.io.read_text(abs_path)
            if content is None or not content.strip():
                return None
            result = '<context name="todo_list">\n'
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

    def get_git_status(self):
        """
        Generate a git status context block for repository information.
        Returns a formatted string with git branch, status, and recent commits.
        """
        if not self.use_enhanced_context or not self.repo:
            return None
        try:
            result = '<context name="gitStatus">\n'
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

    def _log_chunks(self, chunks):
        try:
            import hashlib
            import json

            if not hasattr(self, "_message_hashes"):
                self._message_hashes = {
                    "system": None,
                    "static": None,
                    "examples": None,
                    "readonly_files": None,
                    "repo": None,
                    "chat_files": None,
                    "pre_message": None,
                    "done": None,
                    "edit_files": None,
                    "cur": None,
                    "post_message": None,
                    "reminder": None,
                }
            changes = []
            for key, value in self._message_hashes.items():
                json_obj = json.dumps(
                    getattr(chunks, key, ""), sort_keys=True, separators=(",", ":")
                )
                new_hash = hashlib.sha256(json_obj.encode("utf-8")).hexdigest()
                if self._message_hashes[key] != new_hash:
                    changes.append(key)
                self._message_hashes[key] = new_hash
            print("")
            print("MESSAGE CHUNK HASHES")
            print(self._message_hashes)
            print("")
            print(changes)
            print("")
        except Exception as e:
            print(e)
            pass
