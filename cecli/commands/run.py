from typing import List

import cecli.prompts.utils.system as prompts
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.helpers.conversation import ConversationService, MessageTag
from cecli.run_cmd import run_cmd_async


class RunCommand(BaseCommand):
    NORM_NAME = "run"
    DESCRIPTION = "Run a shell command and optionally add the output to the chat (alias: !)"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the run command with given parameters."""
        suppress_add = kwargs.get("suppress_add", False)
        background = kwargs.get("background", False)
        add_on_nonzero_exit = kwargs.get("add_on_nonzero_exit", False)

        # Background mode: suspend the TUI and run interactively
        if background:
            return await cls._execute_background(io, coder, args)

        should_print = True

        if coder.args.tui:
            should_print = False

        exit_status, combined_output = await run_cmd_async(
            args,
            coder.interrupt_event,
            verbose=coder.args.verbose if hasattr(coder.args, "verbose") else False,
            cwd=coder.root,
            should_print=should_print,
        )

        if coder.args.tui:
            print(combined_output)
        else:
            # This print statement, for whatever reason,
            # allows the thread to properly yield control of the terminal
            # to the main program
            print("")

        if combined_output is None:
            return format_command_result(io, "run", "Command executed with no output")

        # Calculate token count of output
        token_count = coder.main_model.token_count(combined_output)
        k_tokens = token_count / 1000

        # When suppress_add is True, skip the confirmation and never add
        if suppress_add:
            add = False
        elif add_on_nonzero_exit:
            add = exit_status != 0
        else:
            add = await io.confirm_ask(f"Add {k_tokens:.1f}k tokens of command output to the chat?")

        if add:
            num_lines = len(combined_output.strip().splitlines())
            line_plural = "line" if num_lines == 1 else "lines"
            io.tool_output(f"Added {num_lines} {line_plural} of output to the chat.")

            msg = prompts.run_output.format(
                command=args,
                output=combined_output,
            )

            # Add user message with CUR tag
            ConversationService.get_manager(coder).add_message(
                dict(role="user", content=msg), MessageTag.CUR
            )
            # Add assistant acknowledgment with CUR tag
            ConversationService.get_manager(coder).add_message(
                dict(role="assistant", content="Ok."), MessageTag.CUR
            )

            if add_on_nonzero_exit and exit_status != 0:
                # Return the formatted output message for test failures
                return msg
            elif add and exit_status != 0:
                io.placeholder = "What's wrong? Fix"

        if add_on_nonzero_exit and not exit_status:
            return ""  # No test failures

        # Return None if output wasn't added or command succeeded
        return format_command_result(io, "run", "Command executed successfully")

    @classmethod
    async def _execute_background(cls, io, coder, args):
        """
        Execute a command in background/obstructive mode with the TUI suspended.

        This allows running interactive commands (e.g., sudo) that require
        direct terminal access for user input. The TUI is suspended while
        the command runs and is resumed upon completion.
        """
        import subprocess

        def _run_sync():
            """Run the command synchronously with direct terminal access."""
            subprocess.run(
                args,
                shell=True,
                cwd=coder.root,
            )

        if coder.tui and coder.tui():
            # Suspend the TUI and run the command with direct terminal access
            coder.tui().run_obstructive(_run_sync)
        else:
            # Not in TUI mode, run directly
            _run_sync()

        io.tool_output(f"Background command completed: {args}")
        return format_command_result(io, "run", "Command executed in background mode")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for run command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the run command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /run <command>     # Run a shell command\n"
        help_text += "  !<command>         # Alias for /run\n"
        help_text += "\nExamples:\n"
        help_text += "  /run ls -la        # List files\n"
        help_text += "  !pytest tests/     # Run tests (alias)\n"
        help_text += "  !git status        # Show git status (alias)\n"
        help_text += (
            "\nAfter running a command, you'll be asked if you want to add the output to the"
            " chat.\n"
        )
        help_text += "The output will be added as a user message with the command and its output.\n"
        help_text += "\nNote: Commands are run in the project root directory.\n"
        return help_text
