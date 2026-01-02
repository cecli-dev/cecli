from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ContextBlocksCommand(BaseCommand):
    NORM_NAME = "context-blocks"
    DESCRIPTION = "Toggle enhanced context blocks or print a specific block"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the context-blocks command with given parameters."""
        if not hasattr(coder, "use_enhanced_context"):
            io.tool_error("Enhanced context blocks are only available in agent mode.")
            return format_command_result(
                io, "context-blocks", "Enhanced context blocks only available in agent mode"
            )

        # If an argument is provided, try to print that specific context block
        if args.strip():
            # Format block name to match internal naming conventions
            block_name = args.strip().lower().replace(" ", "_")

            # Check if the coder has the necessary method to get context blocks
            if hasattr(coder, "_generate_context_block"):
                # Force token recalculation to ensure blocks are fresh
                if hasattr(coder, "_calculate_context_block_tokens"):
                    coder._calculate_context_block_tokens(force=True)

                # Try to get the requested block
                block_content = coder._generate_context_block(block_name)

                if block_content:
                    # Calculate token count
                    tokens = coder.main_model.token_count(block_content)
                    io.tool_output(f"Context block '{args.strip()}' ({tokens} tokens):")
                    io.tool_output(block_content)
                    return format_command_result(
                        io, "context-blocks", f"Displayed context block: {args.strip()}"
                    )
                else:
                    # List available blocks if the requested one wasn't found
                    io.tool_error(f"Context block '{args.strip()}' not found or empty.")
                    if hasattr(coder, "context_block_tokens"):
                        available_blocks = list(coder.context_block_tokens.keys())
                        formatted_blocks = [
                            name.replace("_", " ").title() for name in available_blocks
                        ]
                        io.tool_output(f"Available blocks: {', '.join(formatted_blocks)}")
                    return format_command_result(
                        io, "context-blocks", f"Context block not found: {args.strip()}"
                    )
            else:
                io.tool_error("This coder doesn't support generating context blocks.")
                return format_command_result(
                    io, "context-blocks", "Coder doesn't support generating context blocks"
                )

        # If no argument, toggle the enhanced context setting
        coder.use_enhanced_context = not coder.use_enhanced_context

        # Report the new state
        if coder.use_enhanced_context:
            io.tool_output(
                "Enhanced context blocks are now ON - directory structure and git status will be"
                " included."
            )
            if hasattr(coder, "context_block_tokens"):
                available_blocks = list(coder.context_block_tokens.keys())
                formatted_blocks = [name.replace("_", " ").title() for name in available_blocks]
                io.tool_output(f"Available blocks: {', '.join(formatted_blocks)}")
                io.tool_output("Use '/context-blocks [block name]' to view a specific block.")
            return format_command_result(io, "context-blocks", "Enhanced context blocks are now ON")
        else:
            io.tool_output(
                "Enhanced context blocks are now OFF - directory structure and git status will not"
                " be included."
            )
            return format_command_result(
                io, "context-blocks", "Enhanced context blocks are now OFF"
            )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Return available context block names for auto-completion."""
        if not hasattr(coder, "use_enhanced_context") or not coder.use_enhanced_context:
            return []

        # If the coder has context blocks available
        if hasattr(coder, "context_block_tokens") and coder.context_block_tokens:
            # Get all block names from the tokens dictionary
            block_names = list(coder.context_block_tokens.keys())
            # Format them for display (convert snake_case to Title Case)
            formatted_blocks = [name.replace("_", " ").title() for name in block_names]
            return formatted_blocks

        # Standard blocks that are typically available
        return [
            "Context Summary",
            "Directory Structure",
            "Environment Info",
            "Git Status",
            "Symbol Outline",
        ]

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the context-blocks command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /context-blocks              # Toggle enhanced context blocks\n"
        help_text += "  /context-blocks <block-name> # View a specific context block\n"
        help_text += "\nExamples:\n"
        help_text += "  /context-blocks              # Toggle context blocks on/off\n"
        help_text += "  /context-blocks git status   # View git status context block\n"
        help_text += "  /context-blocks directory structure  # View directory structure block\n"
        help_text += "\nThis command controls enhanced context blocks in agent mode.\n"
        help_text += (
            "When enabled, directory structure, git status, and other context information\n"
        )
        help_text += "are automatically included in the chat context.\n"
        help_text += "You can also view specific context blocks by name.\n"
        return help_text
