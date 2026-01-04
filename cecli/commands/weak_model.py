from typing import List

import cecli.models as models
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class WeakModelCommand(BaseCommand):
    NORM_NAME = "weak-model"
    DESCRIPTION = "Switch the Weak Model to a new LLM"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the weak_model command with given parameters."""
        arg_split = args.split(" ", 1)
        model_name = arg_split[0].strip()
        if not model_name:
            # If no model name provided, show current weak model
            current_weak_model = coder.main_model.weak_model.name
            io.tool_output(f"Current weak model: {current_weak_model}")
            return format_command_result(
                io, "weak-model", f"Displayed current weak model: {current_weak_model}"
            )

        # Create a new model with the same main model and editor model, but updated weak model
        model = models.Model(
            coder.main_model.name,
            editor_model=coder.main_model.editor_model.name,
            weak_model=model_name,
            io=io,
        )
        await models.sanity_check_models(io, model)

        if len(arg_split) > 1:
            # implement architect coder-like generation call for weak model
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

            new_kwargs = dict(io=io, from_coder=coder)
            new_kwargs.update(kwargs)

            temp_coder = await Coder.create(**new_kwargs)
            temp_coder.cur_messages = []
            temp_coder.done_messages = []

            verbose = kwargs.get("verbose", False)
            if verbose:
                temp_coder.show_announcements()

            try:
                await temp_coder.generate(user_message=message, preproc=False)
                coder.move_back_cur_messages(
                    f"Weak model {model_name} made those changes to the files."
                )
                coder.total_cost = temp_coder.total_cost
                coder.coder_commit_hashes = temp_coder.coder_commit_hashes

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
        """Get completion options for weak_model command."""
        return models.get_chat_model_names()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the weak_model command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /weak_model <model-name>              # Switch to a new weak model\n"
        help_text += (
            "  /weak_model <model-name> <prompt>     # Use a specific weak model for a single"
            " prompt\n"
        )
        help_text += "\nExamples:\n"
        help_text += (
            "  /weak_model gpt-4o-mini               # Switch to GPT-4o Mini as weak model\n"
        )
        help_text += (
            "  /weak_model claude-3-haiku            # Switch to Claude 3 Haiku as weak model\n"
        )
        help_text += '  /weak_model o1-mini "review this code" # Use o1-mini to review code\n'
        help_text += (
            "\nWhen switching weak models, the main model and editor model remain unchanged.\n"
        )
        help_text += (
            "\nIf you provide a prompt after the model name, that weak model will be used\n"
        )
        help_text += "just for that prompt, then you'll return to your original weak model.\n"
        return help_text
