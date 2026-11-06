from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.helpers.browser import is_browser_harness_available
from cecli.helpers.conversation import ConversationService, MessageTag
from cecli.scrape import Scraper


class WebCommand(BaseCommand):
    NORM_NAME = "web"
    DESCRIPTION = "Scrape a webpage, convert to markdown and send in a message"
    show_completion_notification = True

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the web command with given parameters."""
        url = args.strip()
        if not url:
            io.tool_error("Please provide a URL to scrape.")
            return format_command_result(io, "web", "No URL provided")

        io.tool_output(f"Scraping {url}...")

        # Get scraper instance from kwargs or create new one
        scraper = kwargs.get("scraper")

        if not scraper:
            verify_ssl = kwargs.get("verify_ssl", True)

            scraper = Scraper(
                print_error=io.tool_error,
                browser_harness_available=is_browser_harness_available(),
                browser_config=getattr(getattr(coder, "args", None), "browser", None),
                verify_ssl=verify_ssl,
            )

        content = await scraper.scrape(url) or ""
        content = f"Here is the content of {url}:\n\n" + content

        return_content = kwargs.get("return_content", False)
        if return_content:
            return content

        io.tool_output("... added to chat.")

        # Add user message with CUR tag
        ConversationService.get_manager(coder).add_message(
            dict(role="user", content=content), MessageTag.CUR
        )
        # Add assistant acknowledgment with CUR tag
        ConversationService.get_manager(coder).add_message(
            dict(role="assistant", content="Ok."), MessageTag.CUR
        )

        return format_command_result(io, "web", f"Scraped and added content from {url} to chat")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for web command."""
        # For web command, we could return recent URLs or common patterns
        # For now, return empty list
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the web command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /web <url>  # Scrape a webpage and add its content to the chat\n"
        help_text += "\nExamples:\n"
        help_text += "  /web https://example.com  # Scrape example.com\n"
        help_text += "  /web https://github.com/dwash96/aider-ce  # Scrape cecli GitHub page\n"
        help_text += (
            "\nThis command scrapes a webpage, converts it to markdown, and adds it to the chat.\n"
        )
        help_text += (
            "It uses browser-harness for JavaScript-rendered pages and falls back to plain HTTP.\n"
        )
        return help_text
