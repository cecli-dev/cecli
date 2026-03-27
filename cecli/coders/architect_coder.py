import asyncio

from ..commands import SwitchCoderSignal
from ..helpers.conversation import ConversationService
from .ask_coder import AskCoder
from .base_coder import Coder


class ArchitectCoder(AskCoder):
    edit_format = "architect"
    prompt_format = "architect"
    auto_accept_architect = False

    async def reply_completed(self):
        content = self.partial_response_content

        if not content or not content.strip():
            return

        tweak_responses = getattr(self.args, "tweak_responses", False)
        confirmation = await self.io.confirm_ask(
            "Edit the files?",
            allow_tweak=tweak_responses,
            explicit_yes_required=not self.auto_accept_architect,
        )

        if not confirmation:
            return

        if confirmation == "tweak":
            if self.tui and self.tui():
                content = self.tui().get_response_from_editor(content)
            else:
                content = self.io.edit_in_editor(content)

        await asyncio.sleep(0.1)

        kwargs = dict()

        # Use the editor_model from the main_model if it exists, otherwise use the main_model itself
        editor_model = self.main_model.editor_model or self.main_model

        kwargs["main_model"] = editor_model
        kwargs["edit_format"] = self.main_model.editor_edit_format
        kwargs["args"] = self.args
        kwargs["suggest_shell_commands"] = False
        kwargs["map_tokens"] = 0
        kwargs["total_cost"] = self.total_cost
        kwargs["cache_prompts"] = False
        kwargs["num_cache_warming_pings"] = 0
        kwargs["summarize_from_coder"] = False
        kwargs["done_messages"] = []
        kwargs["cur_messages"] = []

        new_kwargs = dict(io=self.io, from_coder=self)
        new_kwargs.update(kwargs)

        # Save current conversation state
        original_coder = self

        editor_coder = await Coder.create(**new_kwargs)

        # Re-initialize ConversationManager with editor coder
        ConversationService.get_manager(editor_coder).initialize(
            reset=True, reformat=True, preserve_tags=True
        )
        if self.verbose:
            editor_coder.show_announcements()

        postamble = """
        The above changes are proposed changes.
        You must repeat SEARCH/REPLACE blocks in order to apply edits.
        Shell commands must also be duplicated in order to run them.
        """

        content = f"Please implement all requested changes from:\n{content}\n{postamble}"

        try:
            await editor_coder.generate(user_message=content, preproc=False)

            # Clear manager and restore original state
            ConversationService.get_manager(original_coder or self).initialize(
                reset=True,
                reformat=True,
                preserve_tags=True,
            )

            self.total_cost = editor_coder.total_cost
            self.coder_commit_hashes = editor_coder.coder_commit_hashes
        except Exception as e:
            self.io.tool_error(e)
            # Restore original state on error
            ConversationService.get_manager(original_coder or self).initialize(
                reset=True,
                reformat=True,
                preserve_tags=True,
            )

        raise SwitchCoderSignal(main_model=self.main_model, edit_format="architect")
