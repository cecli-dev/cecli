import sys
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
                self.args = type("Args", (), {"disable_playwright": False})()

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

        return Commands(io, DummyCoder())

    @patch("cecli.commands.web.install_playwright")
    @patch("cecli.commands.web.Scraper")
    async def test_cmd_web_imports_playwright(
        self, mock_scraper_class, mock_install_playwright, commands
    ):
        async def mock_install(*args, **kwargs):
            sys.modules["playwright"] = MagicMock()
            return True

        mock_install_playwright.side_effect = mock_install
        mock_scraper_instance = mock_scraper_class.return_value
        mock_scraper_instance.scrape = AsyncMock(return_value="Scraped content")

        commands.io.tool_error = MagicMock()

        try:
            result = await commands.do_run("web", "https://example.com", return_content=True)

            assert result is not None
            assert "Scraped content" in result

            playwright_imported = "playwright" in sys.modules
            assert playwright_imported, "Playwright should be importable after running cmd_web"

            commands.io.tool_error.assert_not_called()
        finally:
            if "playwright" in sys.modules:
                del sys.modules["playwright"]

    @patch("cecli.scrape.Scraper.scrape_with_httpx")
    @patch("cecli.scrape.Scraper.scrape_with_playwright")
    async def test_scrape_self_signed_ssl(self, mock_scrape_playwright, mock_scrape_httpx):
        # Test with SSL verification - playwright fails
        mock_scrape_playwright.return_value = (None, None)

        scraper_verify = Scraper(
            print_error=MagicMock(), playwright_available=True, verify_ssl=True
        )
        result_verify = await scraper_verify.scrape("https://self-signed.badssl.com")
        assert result_verify is None
        scraper_verify.print_error.assert_called()

        # Test without SSL verification - playwright succeeds
        mock_scrape_playwright.return_value = (
            "<html><body>self-signed content</body></html>",
            "text/html",
        )
        scraper_no_verify = Scraper(
            print_error=MagicMock(), playwright_available=True, verify_ssl=False
        )
        result_no_verify = await scraper_no_verify.scrape("https://self-signed.badssl.com")
        assert result_no_verify is not None
        assert "self-signed" in result_no_verify
        scraper_no_verify.print_error.assert_not_called()

    @patch("cecli.scrape.Scraper.scrape_with_playwright")
    async def test_scrape_actual_url_with_playwright(self, mock_scrape_playwright):
        # Create a Scraper instance with a mock print_error function
        mock_print_error = MagicMock()
        scraper = Scraper(print_error=mock_print_error, playwright_available=True)

        # Mock the playwright scrape to return content
        mock_scrape_playwright.return_value = (
            "<html><body><h1>Example Domain</h1></body></html>",
            "text/html",
        )

        # Scrape a mocked URL
        result = await scraper.scrape("https://example.com")

        # Assert that the result contains expected content
        assert result is not None
        assert "Example Domain" in result

        # Assert that print_error was never called
        mock_print_error.assert_not_called()

    def test_scraper_print_error_not_called(self):
        # Create a Scraper instance with a mock print_error function
        mock_print_error = MagicMock()
        scraper = Scraper(print_error=mock_print_error)

        # Test various methods of the Scraper class
        scraper.scrape_with_httpx("https://example.com")
        scraper.try_pandoc()
        scraper.html_to_markdown("<html><body><h1>Test</h1></body></html>")

        # Assert that print_error was never called
        mock_print_error.assert_not_called()

    async def test_scrape_with_playwright_error_handling(self):
        # Create a Scraper instance with a mock print_error function
        mock_print_error = MagicMock()
        scraper = Scraper(print_error=mock_print_error, playwright_available=True)

        # Mock the necessary objects and methods
        scraper.scrape_with_playwright = AsyncMock()
        scraper.scrape_with_playwright.return_value = (None, None)

        # Call the scrape method
        result = await scraper.scrape("https://example.com")

        # Assert that the result is None
        assert result is None

        # Assert that print_error was called with the expected error message
        mock_print_error.assert_called_once_with(
            "Failed to retrieve content from https://example.com"
        )

        # Reset the mock
        mock_print_error.reset_mock()

        # Test with a different return value
        scraper.scrape_with_playwright.return_value = ("Some content", "text/html")
        result = await scraper.scrape("https://example.com")

        # Assert that the result is not None
        assert result is not None

        # Assert that print_error was not called
        mock_print_error.assert_not_called()

    async def test_scrape_text_plain(self):
        # Create a Scraper instance
        scraper = Scraper(print_error=MagicMock(), playwright_available=True)

        # Mock the scrape_with_playwright method
        plain_text = "This is plain text content."
        scraper.scrape_with_playwright = AsyncMock(return_value=(plain_text, "text/plain"))

        # Call the scrape method
        result = await scraper.scrape("https://example.com")

        # Assert that the result is the same as the input plain text
        assert result == plain_text

    async def test_scrape_text_html(self):
        # Create a Scraper instance
        scraper = Scraper(print_error=MagicMock(), playwright_available=True)

        # Mock the scrape_with_playwright method
        html_content = "<html><body><h1>Test</h1><p>This is HTML content.</p></body></html>"
        scraper.scrape_with_playwright = AsyncMock(return_value=(html_content, "text/html"))

        # Mock the html_to_markdown method
        expected_markdown = "# Test\n\nThis is HTML content."
        scraper.html_to_markdown = MagicMock(return_value=expected_markdown)

        # Call the scrape method
        result = await scraper.scrape("https://example.com")

        # Assert that the result is the expected markdown
        assert result == expected_markdown

        # Assert that html_to_markdown was called with the HTML content
        scraper.html_to_markdown.assert_called_once_with(html_content)
