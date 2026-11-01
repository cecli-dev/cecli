from .utils.base_command import BaseCommand


class CompactCommand(BaseCommand):
    NORM_NAME = "compact"
    DESCRIPTION = "Force compaction of the chat history context"
    show_completion_notification = True

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        # Pass args as message parameter if it's not empty
        message = args.strip() if args else ""
        await coder.compact_context_if_needed(force=True, message=message)

        # CLI-71: compaction is a command, so run_one() returns early after it.
        # Set the drain flag so any queued prompts process automatically once
        # compaction finishes, instead of stalling until a manual /queue run.
        coder._drain_queue_after_command = True

    @classmethod
    def get_help(cls) -> str:
        return "Force compaction of the chat history context."
