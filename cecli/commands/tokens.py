from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.helpers.conversation import ConversationService, MessageTag


class TokensCommand(BaseCommand):
    NORM_NAME = "tokens"
    DESCRIPTION = "Report on the number of tokens used by the current chat context"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        res = []

        coder.choose_fence()
        coder.format_chat_chunks()

        # Show progress indicator
        total_files = len(coder.abs_fnames) + len(coder.abs_read_only_fnames)
        if total_files > 20:
            io.tool_output(f"Calculating tokens for {total_files} files...")

        # system messages - sum of SYSTEM, STATIC, EXAMPLES, and REMINDER tags
        system_tags = [
            MessageTag.SYSTEM,
            MessageTag.STATIC,
            MessageTag.EXAMPLES,
            MessageTag.REMINDER,
        ]
        system_tokens = 0

        for tag in system_tags:
            msgs = ConversationService.get_manager(coder).get_messages_dict(tag=tag)
            if msgs:
                system_tokens += coder.main_model.token_count(msgs)

        # Calculate context block tokens (they are part of STATIC messages)
        context_block_total = 0

        # Enhanced context blocks (only for agent mode)
        if hasattr(coder, "use_enhanced_context") and coder.use_enhanced_context:
            # Force token calculation if it hasn't been done yet
            if hasattr(coder, "_calculate_context_block_tokens"):
                if not hasattr(coder, "tokens_calculated") or not coder.tokens_calculated:
                    coder._calculate_context_block_tokens()

            # Calculate total context block tokens
            if hasattr(coder, "context_block_tokens") and coder.context_block_tokens:
                context_block_total = sum(coder.context_block_tokens.values())

                # Subtract context block tokens from system token count
                # Context blocks are part of STATIC messages, so we need to subtract them
                system_tokens = max(0, system_tokens - context_block_total)

        res.append((system_tokens, "system messages", ""))

        # chat history
        msgs_done = ConversationService.get_manager(coder).get_messages_dict(tag=MessageTag.DONE)
        msgs_cur = ConversationService.get_manager(coder).get_messages_dict(tag=MessageTag.CUR)
        msgs_diffs = ConversationService.get_manager(coder).get_messages_dict(tag=MessageTag.DIFFS)
        msgs_file_contexts = ConversationService.get_manager(coder).get_messages_dict(
            tag=MessageTag.FILE_CONTEXTS
        )
        tokens_done = 0
        tokens_cur = 0
        tokens_diffs = 0
        tokens_file_contexts = 0

        if msgs_done:
            tokens_done = coder.main_model.token_count(msgs_done)

        if msgs_cur:
            tokens_cur = coder.main_model.token_count(msgs_cur)

        if msgs_diffs:
            tokens_diffs = coder.main_model.token_count(msgs_diffs)

        if msgs_file_contexts:
            tokens_file_contexts = coder.main_model.token_count(msgs_file_contexts)

        if tokens_cur + tokens_done:
            res.append((tokens_cur + tokens_done, "chat history", "use /clear to clear"))
            # Add separate line for diffs if they exist

        if tokens_diffs:
            res.append((tokens_diffs, "file diffs", "part of chat history"))

        if tokens_file_contexts:
            res.append((tokens_file_contexts, "numbered context messages", "part of chat history"))

        # rules files
        msgs_rules = ConversationService.get_manager(coder).get_messages_dict(tag=MessageTag.RULES)
        if msgs_rules:
            tokens_rules = coder.main_model.token_count(msgs_rules)
            res.append((tokens_rules, "rules files", "/drop to remove"))

        # repo map
        if coder.repo_map:
            tokens = coder.main_model.token_count(
                ConversationService.get_manager(coder).get_messages_dict(tag=MessageTag.REPO)
            )
            res.append((tokens, "repository map", "use --map-tokens to resize"))

        # Display enhanced context blocks (only for agent mode)
        # Note: Context block tokens were already calculated and subtracted from system messages
        if hasattr(coder, "use_enhanced_context") and coder.use_enhanced_context:
            if hasattr(coder, "context_block_tokens") and coder.context_block_tokens:
                for block_name, tokens in coder.context_block_tokens.items():
                    # Format the block name more nicely
                    display_name = block_name.replace("_", " ").title()
                    res.append(
                        (tokens, f"{display_name} context block", "/context-blocks to toggle")
                    )

        file_res = []

        # Calculate tokens for read-only files using READONLY_FILES tag
        readonly_msgs = ConversationService.get_manager(coder).get_messages_dict(
            tag=MessageTag.READONLY_FILES
        )
        if readonly_msgs:
            # Group messages by file (each file has user and assistant messages)
            file_tokens = {}
            for msg in readonly_msgs:
                # Extract file name from message content
                content = msg.get("content", "")
                if content.startswith("Original File Contents For"):
                    # Extract file path from "File Contents {path}:"
                    lines = content.split("\n", 3)
                    if lines:
                        file_line = lines[1]
                        fname = file_line.strip()
                        # Calculate tokens for this message
                        tokens = coder.main_model.token_count([msg])
                        if fname not in file_tokens:
                            file_tokens[fname] = 0
                        file_tokens[fname] += tokens
                elif "image_file" in msg:
                    # Handle image files
                    fname = msg.get("image_file")
                    if fname:
                        tokens = coder.main_model.token_count([msg])
                        if fname not in file_tokens:
                            file_tokens[fname] = 0
                        file_tokens[fname] += tokens

            # Add to results
            for fname, tokens in file_tokens.items():
                relative_fname = coder.get_rel_fname(fname)
                file_res.append((tokens, f"{relative_fname} (read-only)", "/drop to remove"))

        # Calculate tokens for editable files using CHAT_FILES and EDIT_FILES tags
        editable_tags = [MessageTag.CHAT_FILES, MessageTag.EDIT_FILES]
        editable_file_tokens = {}

        for tag in editable_tags:
            msgs = ConversationService.get_manager(coder).get_messages_dict(tag=tag)
            if msgs:
                for msg in msgs:
                    # Extract file name from message content
                    content = msg.get("content", "")
                    if content.startswith("Original File Contents For"):
                        # Extract file path from "File Contents {path}:"
                        lines = content.split("\n", 3)
                        if lines:
                            file_line = lines[1]
                            fname = file_line.strip()
                            # Calculate tokens for this message
                            tokens = coder.main_model.token_count([msg])
                            if fname not in editable_file_tokens:
                                editable_file_tokens[fname] = 0
                            editable_file_tokens[fname] += tokens
                    elif "image_file" in msg:
                        # Handle image files
                        fname = msg.get("image_file")
                        if fname:
                            tokens = coder.main_model.token_count([msg])
                            if fname not in editable_file_tokens:
                                editable_file_tokens[fname] = 0
                            editable_file_tokens[fname] += tokens

        # Add editable files to results
        for fname, tokens in editable_file_tokens.items():
            relative_fname = coder.get_rel_fname(fname)
            file_res.append((tokens, f"{relative_fname}", "/drop to remove"))

        if file_res:
            file_res.sort()
            res.extend(file_res)

        io.tool_output(f"Approximate context window usage for {coder.main_model.name}, in tokens:")
        io.tool_output()

        width = 8
        cost_width = 9

        def fmt(v):
            return format(int(v), ",").rjust(width)

        col_width = max(len(row[1]) for row in res) if res else 0

        cost_pad = " " * cost_width
        total = 0
        total_cost = 0.0
        for tk, msg, tip in res:
            total += tk
            cost = tk * (coder.main_model.info.get("input_cost_per_token") or 0)
            total_cost += cost
            msg = msg.ljust(col_width)
            io.tool_output(f"${cost:7.4f} {fmt(tk)} {msg} {tip}")  # noqa: E231

        io.tool_output("=" * (width + cost_width + 1))
        io.tool_output(f"${total_cost:7.4f} {fmt(total)} tokens total")  # noqa: E231

        limit = coder.main_model.info.get("max_input_tokens") or 0
        if not limit:
            return format_command_result(io, "tokens", "Token report generated")

        remaining = limit - total
        if remaining > 1024:
            io.tool_output(f"{cost_pad}{fmt(remaining)} tokens remaining in context window")
        elif remaining > 0:
            io.tool_error(
                f"{cost_pad}{fmt(remaining)} tokens remaining in context window (use /drop or"
                " /clear to make space)"
            )
        else:
            io.tool_error(
                f"{cost_pad}{fmt(remaining)} tokens remaining, window exhausted (use /drop or"
                " /clear to make space)"
            )
        io.tool_output(f"{cost_pad}{fmt(limit)} tokens max context window size")

        return format_command_result(io, "tokens", "Token report generated")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for tokens command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the tokens command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /tokens  # Show token usage for current chat context\n"
        help_text += "\nThis command calculates and displays the approximate token usage for:\n"
        help_text += "  - System messages\n"
        help_text += "  - Chat history\n"
        help_text += "  - Repository map\n"
        help_text += "  - Editable files in chat\n"
        help_text += "  - Read-only files\n"
        help_text += "  - Read-only stub files\n"
        help_text += "  - Enhanced context blocks (agent mode only)\n"
        help_text += (
            "\nThe report shows token counts, estimated costs, and remaining context window"
            " space.\n"
        )
        return help_text
