from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.utils import is_image_file


class TokensCommand(BaseCommand):
    NORM_NAME = "tokens"
    DESCRIPTION = "Report on the number of tokens used by the current chat context"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        res = []

        coder.choose_fence()

        # Show progress indicator
        total_files = len(coder.abs_fnames) + len(coder.abs_read_only_fnames)
        if total_files > 20:
            io.tool_output(f"Calculating tokens for {total_files} files...")

        # system messages
        main_sys = coder.fmt_system_prompt(coder.gpt_prompts.main_system)
        main_sys += "\n" + coder.fmt_system_prompt(coder.gpt_prompts.system_reminder)
        msgs = [
            dict(role="system", content=main_sys),
            dict(
                role="system",
                content=coder.fmt_system_prompt(coder.gpt_prompts.system_reminder),
            ),
        ]

        tokens = coder.main_model.token_count(msgs)
        res.append((tokens, "system messages", ""))

        # chat history
        msgs = coder.done_messages + coder.cur_messages
        if msgs:
            tokens = coder.main_model.token_count(msgs)
            res.append((tokens, "chat history", "use /clear to clear"))

        # repo map
        other_files = set(coder.get_all_abs_files()) - set(coder.abs_fnames)
        if coder.repo_map:
            repo_content = coder.repo_map.get_repo_map(coder.abs_fnames, other_files)
            if repo_content:
                tokens = coder.main_model.token_count(repo_content)
                res.append((tokens, "repository map", "use --map-tokens to resize"))

        # Enhanced context blocks (only for agent mode)
        if hasattr(coder, "use_enhanced_context") and coder.use_enhanced_context:
            # Force token calculation if it hasn't been done yet
            if hasattr(coder, "_calculate_context_block_tokens"):
                if not hasattr(coder, "tokens_calculated") or not coder.tokens_calculated:
                    coder._calculate_context_block_tokens()

            # Add enhanced context blocks to the display
            if hasattr(coder, "context_block_tokens") and coder.context_block_tokens:
                for block_name, tokens in coder.context_block_tokens.items():
                    # Format the block name more nicely
                    display_name = block_name.replace("_", " ").title()
                    res.append(
                        (tokens, f"{display_name} context block", "/context-blocks to toggle")
                    )

        fence = "`" * 3

        file_res = []
        # Process files with progress indication
        total_editable_files = len(coder.abs_fnames)
        total_readonly_files = len(coder.abs_read_only_fnames)

        # Display progress for editable files
        if total_editable_files > 0:
            if total_editable_files > 20:
                io.tool_output(f"Calculating tokens for {total_editable_files} editable files...")

            # Calculate tokens for editable files
            for i, fname in enumerate(coder.abs_fnames):
                if i > 0 and i % 20 == 0 and total_editable_files > 20:
                    io.tool_output(f"Processed {i}/{total_editable_files} editable files...")

                relative_fname = coder.get_rel_fname(fname)
                content = io.read_text(fname)

                if not content:
                    continue

                if is_image_file(relative_fname):
                    tokens = coder.main_model.token_count_for_image(fname)
                else:
                    # approximate
                    content = f"{relative_fname}\n{fence}\n" + content + f"{fence}\n"
                    tokens = coder.main_model.token_count(content)
                file_res.append((tokens, f"{relative_fname}", "/drop to remove"))

        # Display progress for read-only files
        if total_readonly_files > 0:
            if total_readonly_files > 20:
                io.tool_output(f"Calculating tokens for {total_readonly_files} read-only files...")

            # Calculate tokens for read-only files
            for i, fname in enumerate(coder.abs_read_only_fnames):
                if i > 0 and i % 20 == 0 and total_readonly_files > 20:
                    io.tool_output(f"Processed {i}/{total_readonly_files} read-only files...")

                relative_fname = coder.get_rel_fname(fname)
                content = io.read_text(fname)

                if not content:
                    continue

                if not is_image_file(relative_fname):
                    # approximate
                    content = f"{relative_fname}\n{fence}\n" + content + f"{fence}\n"
                    tokens = coder.main_model.token_count(content)
                    file_res.append((tokens, f"{relative_fname} (read-only)", "/drop to remove"))

        if total_files > 20:
            io.tool_output("Token calculation complete. Generating report...")

        file_res.sort()
        res.extend(file_res)

        # stub files
        for fname in coder.abs_read_only_stubs_fnames:
            relative_fname = coder.get_rel_fname(fname)
            if not is_image_file(relative_fname):
                stub = coder.get_file_stub(fname)

                if not stub:
                    continue

                content = f"{relative_fname} (stub)\n{fence}\n" + stub + "{fence}\n"
                tokens = coder.main_model.token_count(content)
                res.append((tokens, f"{relative_fname} (read-only stub)", "/drop to remove"))

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
