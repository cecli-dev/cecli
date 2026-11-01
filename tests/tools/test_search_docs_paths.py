"""Tests for the SearchDocs path mode (whole-file read and path browsing)."""

from types import SimpleNamespace

import pytest

from cecli.help import get_doc
from cecli.helpers.conversation import ConversationService
from cecli.tools import search_docs


def _result(response):
    return response.to_dict()


def _coder(creator=True):
    return SimpleNamespace(agent_config={"creator_mode": creator})


class _Chunks:
    """Minimal chunk service backed by the real docs resolver."""

    def retrieve_creator_docs(self, coder, query, n_results=8):
        return []

    def retrieve_creator_doc(self, coder, path, n_results=20):
        return get_doc(path, max_results=n_results)


@pytest.fixture(autouse=True)
def _patch_chunks(monkeypatch):
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: _Chunks()))


@pytest.mark.asyncio
async def test_read_returns_whole_file():
    response = await search_docs.Tool.execute(_coder(), path="config/hooks.md")

    result = _result(response)["result"]
    assert len(result) == 1

    entry = result[0]
    assert entry["_"]["type"] == "doc_file"
    assert entry["_"]["path"] == "config/hooks.md"
    assert entry["_"]["url"] == "https://cecli.dev/docs/config/hooks/"

    content = entry["content"]
    assert content.startswith('<doc_file path="config/hooks.md"')
    assert 'lines="' in content
    assert content.endswith("</doc_file>")
    assert "# Hooks" in content
    # The whole document, not a chunk: the last heading is present too.
    assert "## Managing Hooks" in content


@pytest.mark.asyncio
async def test_read_accepts_omitted_suffix_and_url():
    omitted = await search_docs.Tool.execute(_coder(), path="config/hooks")
    url = await search_docs.Tool.execute(_coder(), path="https://cecli.dev/docs/config/hooks/")

    for response in (omitted, url):
        entry = _result(response)["result"][0]
        assert entry["_"]["type"] == "doc_file"
        assert entry["_"]["path"] == "config/hooks.md"


@pytest.mark.asyncio
async def test_browse_lists_files_and_reports_total():
    response = await search_docs.Tool.execute(_coder(), path="config/", max_results=3)

    entry = _result(response)["result"][0]
    content = entry["content"]

    assert entry["_"]["type"] == "doc_paths"
    assert entry["_"]["count"] == 3
    assert entry["_"]["total"] > entry["_"]["count"]
    assert '<doc_paths path="config" count="3"' in content
    assert 'total="' in content
    assert "config/acp.md (117 lines," in content
    assert "sections)" in content
    assert "</doc_paths>" in content


@pytest.mark.asyncio
async def test_browse_lists_subdirectories_for_root():
    response = await search_docs.Tool.execute(_coder(), path=".", max_results=3)

    entry = _result(response)["result"][0]
    content = entry["content"]

    assert entry["_"]["count"] == 3

    assert "- config/ (dir," in content


@pytest.mark.asyncio
async def test_bare_basename_miss_returns_suggestion():
    response = await search_docs.Tool.execute(_coder(), path="hooks")

    data = _result(response)
    assert data["errors"] == []

    entry = data["result"][0]
    assert entry["_"]["type"] == "doc_path_suggestions"
    assert 'No exact match for path="hooks"' in entry["content"]
    assert "config/hooks.md (344 lines," in entry["content"]


@pytest.mark.asyncio
async def test_unknown_path_reports_error_not_empty_listing():
    for path in ("zzz", "config/nope.md", "docs/missing"):
        response = await search_docs.Tool.execute(_coder(), path=path)

        data = _result(response)
        assert data["result"] == []
        assert "No documentation matched" in data["errors"][0]


@pytest.mark.asyncio
async def test_absolute_path_is_rejected():
    response = await search_docs.Tool.execute(_coder(), path="/etc/passwd")

    data = _result(response)
    assert data["result"] == []
    assert "Invalid documentation path" in data["errors"][0]


@pytest.mark.asyncio
async def test_excluded_from_search_still_readable():
    response = await search_docs.Tool.execute(_coder(), path="ctags.md")

    entry = _result(response)["result"][0]
    assert entry["_"]["type"] == "doc_file"
    assert entry["_"]["path"] == "ctags.md"


@pytest.mark.asyncio
async def test_query_and_path_are_mutually_exclusive():
    response = await search_docs.Tool.execute(_coder(), query="hooks", path="config/hooks.md")

    data = _result(response)
    assert data["result"] == []
    assert "not both" in data["errors"][0]


@pytest.mark.asyncio
async def test_path_mode_is_scoped_to_creator():
    response = await search_docs.Tool.execute(_coder(creator=False), path="config/hooks.md")

    data = _result(response)
    assert data["result"] == []
    assert "scoped to the creator sub-agent" in data["errors"][0]
