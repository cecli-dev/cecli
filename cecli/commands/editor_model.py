from typing import List

import cecli.models as models
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.helpers.conversation import ConversationService


class EditorModelCommand(BaseCommand):
    NORM_NAME = "editor-model"
    DESCRIPTION = "Switch the Editor Model to a new LLM"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the editor-model command with given parameters."""
        arg_split = args.split(" ", 1)
        model_name = arg_split[0].strip()
        if not model_name:
            # If no model name provided, show current editor model
            current_editor_model = coder.main_model.editor_model.name
            io.tool_output(f"Current editor model: {current_editor_model}")
            return format_command_result(
                io, "editor-model", f"Displayed current editor model: {current_editor_model}"
            )

        # Create a new model with the same main model and editor model, but updated editor model
        model = models.Model(
            coder.main_model.name,
            editor_model=model_name,
            weak_model=coder.main_model.weak_model.name,
            agent_model=coder.main_model.agent_model.name,
            io=io,
            retries=coder.main_model.retries,
            debug=coder.main_model.debug,
        )
        await models.sanity_check_models(io, model)

        if len(arg_split) > 1:
            # implement architect coder-like generation call for editor model
            message = arg_split[1].strip()

            # Store the original model configuration
            original_main_model = coder.main_model
            original_edit_format = coder.edit_format

            # Create a temporary coder with the new model
            from cecli.coders import Coder

            kwargs = dict()
            kwargs["main_model"] = model
            kwargs["edit_format"] = coder.edit_format  # Keep the same edit format
            kwargs["suggest_shell_commands"] = False
            kwargs["total_cost"] = coder.total_cost
            kwargs["num_cache_warming_pings"] = 0
            kwargs["summarize_from_coder"] = False
            kwargs["done_messages"] = []
            kwargs["cur_messages"] = []

            new_kwargs = dict(io=io, from_coder=coder)
            new_kwargs.update(kwargs)

            # Save current conversation state
            original_coder = coder

            temp_coder = await Coder.create(**new_kwargs)

            # Re-initialize ConversationManager with temp coder
            ConversationService.get_manager(temp_coder).initialize(
                reset=True,
                reformat=True,
                preserve_tags=True,
            )

            verbose = kwargs.get("verbose", False)
            if verbose:
                temp_coder.show_announcements()

            try:
                await temp_coder.generate(user_message=message, preproc=False)
                coder.total_cost = temp_coder.total_cost
                coder.coder_commit_hashes = temp_coder.coder_commit_hashes

                # Clear manager and restore original state
                ConversationService.get_manager(original_coder).initialize(
                    reset=True,
                    reformat=True,
                    preserve_tags=True,
                )

                # Restore the original model configuration
                from cecli.commands import SwitchCoderSignal

                raise SwitchCoderSignal(
                    main_model=original_main_model, edit_format=original_edit_format
                )
            except Exception as e:
                # If there's an error, still restore the original model
                if not isinstance(e, SwitchCoderSignal):
                    io.tool_error(str(e))
                    raise SwitchCoderSignal(
                        main_model=original_main_model, edit_format=original_edit_format
                    )
                else:
                    # Re-raise SwitchCoderSignal if that's what was thrown
                    raise
        else:
            from cecli.commands import SwitchCoderSignal

            raise SwitchCoderSignal(main_model=model, edit_format=coder.edit_format)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for editor-model command."""
        return models.get_chat_model_names()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the editor-model command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /editor-model <model-name>              # Switch to a new editor model\n"
        help_text += (
            "  /editor-model <model-name> <prompt>     # Use a specific editor model for a single"
            " prompt\n"
        )
        help_text += "\nExamples:\n"
        help_text += (
            "  /editor-model gpt-4o-mini               # Switch to GPT-4o Mini as editor model\n"
        )
        help_text += (
            "  /editor-model claude-3-haiku            # Switch to Claude 3 Haiku as editor model\n"
        )
        help_text += '  /editor-model o1-mini "review this code" # Use o1-mini to review code\n'
        help_text += (
            "\nWhen switching editor models, the main model and editor model remain unchanged.\n"
        )
        help_text += (
            "\nIf you provide a prompt after the model name, that editor model will be used\n"
        )
        help_text += "just for that prompt, then you'll return to your original editor model.\n"
        return help_text
