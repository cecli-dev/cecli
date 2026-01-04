from typing import List

import cecli.models as models
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ModelCommand(BaseCommand):
    NORM_NAME = "model"
    DESCRIPTION = "Switch the Main Model to a new LLM"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the model command with given parameters."""
        arg_split = args.split(" ", 1)
        model_name = arg_split[0].strip()
        if not model_name:
            announcements = "\n".join(coder.get_announcements())
            io.tool_output(announcements)
            return format_command_result(io, "model", "Displayed announcements")

        model = models.Model(
            model_name,
            editor_model=coder.main_model.editor_model.name,
            weak_model=coder.main_model.weak_model.name,
            io=io,
        )
        await models.sanity_check_models(io, model)

        # Check if the current edit format is the default for the old model
        old_model_edit_format = coder.main_model.edit_format
        current_edit_format = coder.edit_format

        new_edit_format = current_edit_format
        if current_edit_format == old_model_edit_format:
            # If the user was using the old model's default, switch to the new model's default
            new_edit_format = model.edit_format

        if len(arg_split) > 1:
            # implement architect coder-like generation call for model
            message = arg_split[1].strip()

            # Store the original model configuration
            original_main_model = coder.main_model
            original_edit_format = coder.edit_format

            # Create a temporary coder with the new model
            from cecli.coders import Coder

            kwargs = dict()
            kwargs["main_model"] = model
            kwargs["edit_format"] = new_edit_format
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
                coder.move_back_cur_messages(f"Model {model_name} made those changes to the files.")
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

            raise SwitchCoderSignal(main_model=model, edit_format=new_edit_format)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for model command."""
        return models.get_chat_model_names()

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the model command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /model <model-name>              # Switch to a new model\n"
        help_text += (
            "  /model <model-name> <prompt>     # Use a specific model for a single prompt\n"
        )
        help_text += "\nExamples:\n"
        help_text += "  /model gpt-4o                    # Switch to GPT-4o\n"
        help_text += "  /model claude-3-opus             # Switch to Claude 3 Opus\n"
        help_text += '  /model o1-preview "fix this bug" # Use o1-preview to fix a bug\n'
        help_text += "\nWhen switching models, the edit format may also change if you were using\n"
        help_text += "the previous model's default edit format.\n"
        help_text += "\nIf you provide a prompt after the model name, that model will be used\n"
        help_text += "just for that prompt, then you'll return to your original model.\n"
        return help_text
