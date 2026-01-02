from typing import List

import cecli.prompts.utils.system as prompts
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.repo import ANY_GIT_ERROR


class UndoCommand(BaseCommand):
    NORM_NAME = "undo"
    DESCRIPTION = "Undo the last git commit if it was done by cecli"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        try:
            return await cls._raw_cmd_undo(io, coder, args)
        except ANY_GIT_ERROR as err:
            io.tool_error(f"Unable to complete undo: {err}")
            return format_command_result(io, "undo", f"Unable to complete undo: {err}", err)

    @classmethod
    async def _raw_cmd_undo(cls, io, coder, args):
        if not coder.repo:
            io.tool_error("No git repository found.")
            return format_command_result(io, "undo", "No git repository found")

        last_commit = coder.repo.get_head_commit()
        if not last_commit or not last_commit.parents:
            io.tool_error("This is the first commit in the repository. Cannot undo.")
            return format_command_result(io, "undo", "First commit, cannot undo")

        last_commit_hash = coder.repo.get_head_commit_sha(short=True)
        last_commit_message = coder.repo.get_head_commit_message("(unknown)").strip()
        last_commit_message = (last_commit_message.splitlines() or [""])[0]
        if last_commit_hash not in coder.coder_commit_hashes:
            io.tool_error("The last commit was not made by cecli in this chat session.")
            io.tool_output(
                "You could try `/git reset --hard HEAD^` but be aware that this is a destructive"
                " command!"
            )
            return format_command_result(io, "undo", "Last commit not made by cecli")

        if len(last_commit.parents) > 1:
            io.tool_error(
                f"The last commit {last_commit.hexsha} has more than 1 parent, can't undo."
            )
            return format_command_result(io, "undo", "Commit has multiple parents")

        prev_commit = last_commit.parents[0]
        changed_files_last_commit = [item.a_path for item in last_commit.diff(prev_commit)]

        for fname in changed_files_last_commit:
            if coder.repo.repo.is_dirty(path=fname):
                io.tool_error(
                    f"The file {fname} has uncommitted changes. Please stash them before undoing."
                )
                return format_command_result(io, "undo", f"File {fname} has uncommitted changes")

            # Check if the file was in the repo in the previous commit
            try:
                prev_commit.tree[fname]
            except KeyError:
                io.tool_error(
                    f"The file {fname} was not in the repository in the previous commit. Cannot"
                    " undo safely."
                )
                return format_command_result(io, "undo", f"File {fname} not in previous commit")

        local_head = coder.repo.repo.git.rev_parse("HEAD")
        current_branch = coder.repo.repo.active_branch.name
        try:
            remote_head = coder.repo.repo.git.rev_parse(f"origin/{current_branch}")
            has_origin = True
        except ANY_GIT_ERROR:
            has_origin = False

        if has_origin:
            if local_head == remote_head:
                io.tool_error(
                    "The last commit has already been pushed to the origin. Undoing is not"
                    " possible."
                )
                return format_command_result(io, "undo", "Commit already pushed to origin")

        # Reset only the files which are part of `last_commit`
        restored = set()
        unrestored = set()
        for file_path in changed_files_last_commit:
            try:
                coder.repo.repo.git.checkout("HEAD~1", file_path)
                restored.add(file_path)
            except ANY_GIT_ERROR:
                unrestored.add(file_path)

        if unrestored:
            io.tool_error(f"Error restoring {file_path}, aborting undo.")
            io.tool_output("Restored files:")
            for file in restored:
                io.tool_output(f"  {file}")
            io.tool_output("Unable to restore files:")
            for file in unrestored:
                io.tool_output(f"  {file}")
            return format_command_result(io, "undo", "Error restoring files")

        # Move the HEAD back before the latest commit
        coder.repo.repo.git.reset("--soft", "HEAD~1")

        io.tool_output(f"Removed: {last_commit_hash} {last_commit_message}")

        # Get the current HEAD after undo
        current_head_hash = coder.repo.get_head_commit_sha(short=True)
        current_head_message = coder.repo.get_head_commit_message("(unknown)").strip()
        current_head_message = (current_head_message.splitlines() or [""])[0]
        io.tool_output(f"Now at:  {current_head_hash} {current_head_message}")

        if coder.main_model.send_undo_reply:
            return prompts.undo_command_reply

        return format_command_result(io, "undo", "Successfully undone last cecli commit")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for undo command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the undo command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /undo  # Undo the last git commit if it was made by cecli\n"
        help_text += (
            "\nThis command undoes the last git commit if it was made by cecli in the current chat"
            " session.\n"
        )
        help_text += "It checks various safety conditions before performing the undo:\n"
        help_text += "  - The commit must have been made by cecli in this session\n"
        help_text += "  - The commit must not have multiple parents (merge commit)\n"
        help_text += "  - Files must not have uncommitted changes\n"
        help_text += "  - Files must exist in the previous commit\n"
        help_text += "  - The commit must not have been pushed to origin\n"
        help_text += (
            "\nIf undo is successful, it restores files to their state before the commit.\n"
        )
        return help_text
