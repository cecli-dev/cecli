from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cecli.commands import Commands
from cecli.io import InputOutput
from cecli.scrape import Scraper


class TestScrape:
    @pytest.fixture
    def commands(self):
        io = InputOutput(yes=True)

        class DummyCoder:
            def __init__(self):
                self.cur_messages = []
                self.main_model = type(
                    "M", (), {"edit_format": "code", "name": "dummy", "info": {}}
                )()
                self.tui = None
                self.args = SimpleNamespace(browser=None)
                self.io = io

            def get_rel_fname(self, fname):
                return fname

            def get_inchat_relative_files(self):
                return []

            def abs_root_path(self, fname):
                return fname

            def get_all_abs_files(self):
                return []

            def get_announcements(self):
                return []

        coder = DummyCoder()
        cmds = Commands(io, coder)
        cmds._test_coder = coder
        return cmds

    @patch("cecli.commands.web.Scraper")
    async def test_cmd_web_uses_browser_harness_scraper(self, mock_scraper_class, commands):
        mock_scraper_instance = mock_scraper_class.return_value
        mock_scraper_instance.scrape = AsyncMock(return_value="Scraped content")
        commands.io.tool_error = MagicMock()

        result = await commands.execute("web", "https://example.com", return_content=True)

        assert "Scraped content" in result
        commands.io.tool_error.assert_not_called()

        _args, kwargs = mock_scraper_class.call_args
        assert kwargs["browser_harness_available"] is True

    async def test_scrape_uses_browser_harness_when_available(self):
        scraper = Scraper(
            print_error=MagicMock(),
            browser_harness_available=True,
        )
        html = "<html><body><h1>Rendered</h1></body></html>"
        scraper.scrape_with_browser_harness = AsyncMock(return_value=(html, "text/html"))
        scraper.html_to_markdown = MagicMock(return_value="# Rendered")

        result = await scraper.scrape("https://example.com")

        assert result == "# Rendered"
        scraper.html_to_markdown.assert_called_once_with(html)

    async def test_scrape_falls_back_to_httpx_when_browser_harness_fails(self):
        scraper = Scraper(
            print_error=MagicMock(),
            browser_harness_available=True,
        )
        scraper.scrape_with_browser_harness = AsyncMock(return_value=(None, None))
        scraper.scrape_with_httpx = MagicMock(return_value=("plain text", "text/plain"))

        result = await scraper.scrape("https://example.com")

        assert result == "plain text"
        scraper.scrape_with_httpx.assert_called_once_with("https://example.com")

    async def test_scrape_without_browser_harness_uses_httpx(self):
        scraper = Scraper(
            print_error=MagicMock(),
            browser_harness_available=False,
        )
        scraper.scrape_with_httpx = MagicMock(return_value=("plain text", "text/plain"))

        result = await scraper.scrape("https://example.com")

        assert result == "plain text"

    async def test_scrape_text_html(self):
        scraper = Scraper(
            print_error=MagicMock(),
            browser_harness_available=True,
        )
        html = "<html><body><h1>Test</h1><p>This is HTML content.</p></body></html>"
        scraper.scrape_with_browser_harness = AsyncMock(return_value=(html, "text/html"))
        scraper.html_to_markdown = MagicMock(return_value="# Test\n\nThis is HTML content.")

        result = await scraper.scrape("https://example.com")

        assert result == "# Test\n\nThis is HTML content."

    async def test_scrape_failure_returns_none(self):
        scraper = Scraper(
            print_error=MagicMock(),
            browser_harness_available=False,
        )
        scraper.scrape_with_httpx = MagicMock(return_value=(None, None))

        result = await scraper.scrape("https://example.com")

        assert result is None
        scraper.print_error.assert_called_once_with(
            "Failed to retrieve content from https://example.com"
        )

    def test_scraper_print_error_not_called(self):
        scraper = Scraper(print_error=MagicMock(), browser_harness_available=False)

        scraper.scrape_with_httpx("https://example.com")
        scraper.try_pandoc()
        scraper.html_to_markdown("<html><body><h1>Test</h1></body></html>")

        scraper.print_error.assert_not_called()
