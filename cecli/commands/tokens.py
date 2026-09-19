import json
from typing import Any, Dict, List, Optional

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.helpers.conversation import ConversationService, MessageTag


class TokensCommand(BaseCommand):
    NORM_NAME = "tokens"
    DESCRIPTION = "Report on the number of tokens used by the current chat context"

    @classmethod
    def _extract_file_name(cls, msg: Dict[str, Any]) -> Optional[str]:
        """Extract file name from a message dictionary."""
        if not isinstance(msg, dict):
            return None

        # Check explicit image_file metadata first
        fname = msg.get("image_file")
        if fname:
            return fname

        content = msg.get("content")
        if isinstance(content, str):
            if content.startswith(("Original File Contents For", "Current File Contents For")):
                lines = content.split("\n", 3)
                if len(lines) > 1:
                    return lines[1].strip()
            elif content.startswith("Image file: "):
                return content[len("Image file: ") :].strip()
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("image_file"):
                        return part.get("image_file")
                    text = part.get("text")
                    if isinstance(text, str):
                        if text.startswith(
                            ("Original File Contents For", "Current File Contents For")
                        ):
                            lines = text.split("\n", 3)
                            if len(lines) > 1:
                                return lines[1].strip()
                        elif text.startswith("Image file: "):
                            return text[len("Image file: ") :].strip()
                elif isinstance(part, str):
                    if part.startswith(("Original File Contents For", "Current File Contents For")):
                        lines = part.split("\n", 3)
                        if len(lines) > 1:
                            return lines[1].strip()
                    elif part.startswith("Image file: "):
                        return part[len("Image file: ") :].strip()

        return None

    @staticmethod
    def binary_token_count(data_url: str, bytes_per_pixel: float = 1.0) -> int:
        """Estimate OpenAI vision tokens for a base64 media data URL.

        Assumes a 4:3 aspect ratio and 1 byte per pixel, which is a reasonable middle
        ground for binary media when the true dimensions are unknown. The tile cost is
        inflated by 1.33 and floored to keep the estimate on the pessimistic side.
        """
        import math

        b64_data = data_url.split(",", 1)[1] if "," in data_url else data_url
        padding = b64_data.count("=")
        rough_bytes = max(0, (len(b64_data) * 3 // 4) - padding)
        total_pixels = rough_bytes / bytes_per_pixel
        height = math.sqrt((3 / 4) * total_pixels)
        width = (4 / 3) * height

        if max(width, height) > 2048:
            scale = 2048 / max(width, height)
            width *= scale
            height *= scale

        if min(width, height) > 768:
            scale = 768 / min(width, height)
            width *= scale
            height *= scale

        tiles = math.ceil(width / 512) * math.ceil(height / 512)

        return math.floor((85 + (170 * tiles)) * 1.33)

    @classmethod
    def _extract_key_paths(cls, obj: Any, prefix: str = "") -> List[str]:
        """Return the dot-separated paths of every leaf in a nested structure.

        List indices are included as numeric segments, e.g. "0.image_url.url".
        """
        if isinstance(obj, dict):
            items = obj.items()
        elif isinstance(obj, list):
            items = enumerate(obj)
        else:
            return [prefix] if prefix else []

        paths = []
        for key, value in items:
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(cls._extract_key_paths(value, path))

        return paths

    @classmethod
    def _get_path_value(cls, obj: Any, path: str) -> Any:
        """Resolve a dot-separated path produced by _extract_key_paths."""
        for part in path.split("."):
            obj = obj[int(part)] if isinstance(obj, list) else obj[part]

        return obj

    @classmethod
    def _count_value_tokens(cls, coder, key: str, value: Any) -> int:
        """Count tokens for an extracted value, estimating data URLs as binary media."""
        if key == "url" and isinstance(value, str) and value.startswith("data:"):
            return cls.binary_token_count(value)

        return coder.main_model.token_count(value)

    @classmethod
    def _count_message_tokens(cls, coder, msg: Dict[str, Any]) -> int:
        """Count tokens for a message, estimating binary data URLs instead of raw base64."""
        content = msg.get("content") if isinstance(msg, dict) else None

        if not isinstance(content, (list, dict)):
            return coder.main_model.token_count([msg])

        total = 0

        for path in cls._extract_key_paths(content):
            key = path.rsplit(".", 1)[-1]

            if not key.isdigit() and key not in ("text", "content", "url"):
                continue

            value = cls._get_path_value(content, path)

            if isinstance(value, str):
                total += cls._count_value_tokens(coder, key, value)

        return total

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

        # tool definitions
        tool_list = coder.get_tool_list()

        if tool_list:
            tokens_tools = coder.main_model.token_count(json.dumps(tool_list))
            res.append((tokens_tools, "tool schemas", ""))

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
                fname = cls._extract_file_name(msg)
                if fname:
                    tokens = cls._count_message_tokens(coder, msg)
                    file_tokens[fname] = file_tokens.get(fname, 0) + tokens

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
                    fname = cls._extract_file_name(msg)
                    if fname:
                        tokens = cls._count_message_tokens(coder, msg)
                        editable_file_tokens[fname] = editable_file_tokens.get(fname, 0) + tokens

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
