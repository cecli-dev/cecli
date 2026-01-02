from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ReportCommand(BaseCommand):
    NORM_NAME = "report"
    DESCRIPTION = "Report a problem by opening a GitHub Issue"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        from cecli.report import report_github_issue

        announcements = "\n".join(coder.get_announcements())
        issue_text = announcements

        if args.strip():
            title = args.strip()
        else:
            title = None

        report_github_issue(issue_text, title=title, confirm=False)
        return format_command_result(io, "report", "Opened GitHub issue for reporting")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for report command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the report command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /report              # Open GitHub issue with current context\n"
        help_text += "  /report <title>      # Open GitHub issue with specific title\n"
        help_text += "\nNote: This command opens a GitHub issue pre-filled with the current\n"
        help_text += "context and announcements for reporting problems or bugs.\n"
        return help_text
