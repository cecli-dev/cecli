#!/usr/bin/env python

import asyncio
import re
import sys

import pypandoc

from cecli import __version__, urls
from cecli.dump import dump  # noqa: F401
from cecli.helpers.browser import is_browser_harness_available

coder_user_agent = f"cecli/{__version__} +{urls.website}"


class Scraper:
    pandoc_available = None
    _browser_harness_tab_ready = False

    # Public API...
    def __init__(
        self,
        print_error=None,
        verify_ssl=True,
        browser_harness_available=None,
        browser_config=None,
    ):
        """
        `print_error` - a function to call to print error/debug info.
        `verify_ssl` - if False, disable SSL certificate verification when scraping.
        """
        if print_error:
            self.print_error = print_error
        else:
            self.print_error = print

        self.verify_ssl = verify_ssl
        if browser_harness_available is None:
            browser_harness_available = is_browser_harness_available()

        self.browser_harness_available = browser_harness_available
        self.browser_config = browser_config or {}

    async def scrape(self, url):
        """
        Scrape a url and turn it into readable markdown if it's HTML.
        If it's plain text or non-HTML, return it as-is.

        `url` - the URL to scrape.
        """

        content = None
        mime_type = None

        if self.browser_harness_available:
            content, mime_type = await self.scrape_with_browser_harness(url)

        if not content:
            content, mime_type = self.scrape_with_httpx(url)

        if not content:
            self.print_error(f"Failed to retrieve content from {url}")
            return None

        # Check if the content is HTML based on MIME type or content
        if (mime_type and mime_type.startswith("text/html")) or (
            mime_type is None and self.looks_like_html(content)
        ):
            self.try_pandoc()
            content = self.html_to_markdown(content)
        elif mime_type and mime_type.startswith("image/"):
            content = "(Response is an image, not HTML)"

        return content

    def looks_like_html(self, content):
        """
        Check if the content looks like HTML.
        """
        if isinstance(content, str):
            # Check for common HTML tags
            html_patterns = [
                r"<!DOCTYPE\s+html",
                r"<html",
                r"<head",
                r"<body",
                r"<div",
                r"<p>",
                r"<a\s+href=",
            ]
            return any(re.search(pattern, content, re.IGNORECASE) for pattern in html_patterns)
        return False

    # Internals...
    async def scrape_with_browser_harness(self, url):
        """Render a page through browser-harness and return its outer HTML."""
        import json
        import os
        import tempfile

        from cecli.helpers.browser import (
            browser_harness_env,
            get_browser_config,
            is_browser_harness_available,
        )

        if not is_browser_harness_available():
            return None, None

        config = get_browser_config(self.browser_config)
        output_fd, output_path = tempfile.mkstemp(prefix="cecli-browser-", suffix=".json")
        os.close(output_fd)

        url_literal = json.dumps(url)
        output_literal = json.dumps(output_path)
        reuse_tab = Scraper._browser_harness_tab_ready

        script = f"""
import json
import pathlib

url = {url_literal}
reuse_tab = {reuse_tab!r}

try:
    if reuse_tab:
        ensure_real_tab()
        goto_url(url)
    else:
        new_tab(url)
except Exception:
    new_tab(url)

wait_for_load()

data = {{
    "contentType": js("document.contentType"),
    "html": js("document.documentElement.outerHTML"),
}}
pathlib.Path({output_literal}).write_text(json.dumps(data), encoding="utf-8")
"""

        process = None
        try:
            env = await asyncio.to_thread(browser_harness_env, self.browser_config, True)
            process = await asyncio.create_subprocess_exec(
                "browser-harness",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _stdout, stderr = await asyncio.wait_for(
                process.communicate(script.encode("utf-8")),
                timeout=config["harness_timeout"],
            )

            if process.returncode != 0:
                error_text = stderr.decode("utf-8", errors="replace").strip()
                if error_text:
                    self.print_error(f"browser-harness scrape failed: {error_text[-1000:]}")

                return None, None

            with open(output_path, encoding="utf-8") as output_file:
                data = json.load(output_file)
        except asyncio.TimeoutError:
            if process is not None:
                process.kill()
                await process.wait()

            self.print_error(f"browser-harness timed out scraping {url}")
            return None, None
        except (OSError, ValueError):
            return None, None
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass

        content = data.get("html") or ""
        mime_type = data.get("contentType") or None

        if not content:
            return None, None

        if mime_type and not (
            mime_type.startswith("text/html") or mime_type.startswith("application/xhtml")
        ):
            return None, None

        Scraper._browser_harness_tab_ready = True

        return content, mime_type

    def scrape_with_httpx(self, url):
        from cecli.http import httpx

        headers = {"User-Agent": f"Mozilla./5.0 ({coder_user_agent})"}
        try:
            with httpx.Client(
                headers=headers, verify=self.verify_ssl, follow_redirects=True
            ) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text, response.headers.get("content-type", "").split(";")[0]
        except httpx.HTTPError as http_err:
            self.print_error(f"HTTP error occurred: {http_err}")
        except Exception as err:
            self.print_error(f"An error occurred: {err}")
        return None, None

    def try_pandoc(self):
        if self.pandoc_available is not None:
            return

        try:
            pypandoc.get_pandoc_version()
            self.pandoc_available = True
            return
        except OSError:
            pass

        try:
            pypandoc.download_pandoc(delete_installer=True)
            self.pandoc_available = True
        except Exception:
            self.pandoc_available = False

    def html_to_markdown(self, page_source):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(page_source, "html.parser")
        soup = slimdown_html(soup)
        page_source = str(soup)

        if not self.pandoc_available:
            return page_source

        try:
            md = pypandoc.convert_text(page_source, "markdown", format="html")
        except OSError:
            return page_source

        md = re.sub(r"</div>", "      ", md)
        md = re.sub(r"<div>", "     ", md)

        md = re.sub(r"\n\s*\n", "\n\n", md)

        return md


def slimdown_html(soup):
    for svg in soup.find_all("svg"):
        svg.decompose()

    if soup.img:
        soup.img.decompose()

    for tag in soup.find_all(href=lambda x: x and x.startswith("data:")):
        tag.decompose()

    for tag in soup.find_all(src=lambda x: x and x.startswith("data:")):
        tag.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr != "href":
                tag.attrs.pop(attr, None)

    return soup


async def main(url):
    from cecli.helpers.browser import is_browser_harness_available

    scraper = Scraper(
        browser_harness_available=is_browser_harness_available(),
    )
    content = await scraper.scrape(url)
    print(content)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python playw.py <URL>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
