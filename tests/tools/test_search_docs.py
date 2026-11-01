"""Tests for the creator-scoped SearchDocs tool."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cecli.helpers.conversation import ConversationService
from cecli.tools import search_docs


def _result(response):
    return response.to_dict()


def _coder(creator=True):
    return SimpleNamespace(agent_config={"creator_mode": creator})


@pytest.mark.asyncio
async def test_search_docs_returns_retrieved_chunks(monkeypatch):
    chunks = SimpleNamespace(
        retrieve_creator_docs=Mock(
            return_value=[
                {
                    "id": "config/hooks.md#0",
                    "url": "https://cecli.dev/docs/config/hooks/",
                    "document": "Hook documentation body.",
                }
            ]
        )
    )
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: chunks))
    coder = _coder()

    response = await search_docs.Tool.execute(
        coder, query="  hook config  ", mode="content", max_results=3
    )

    call = chunks.retrieve_creator_docs.call_args
    assert call.args == (coder, "hook config")
    assert call.kwargs["n_results"] == 9
    result = _result(response)["result"]
    assert len(result) == 1
    assert "https://cecli.dev/docs/config/hooks/" in result[0]["content"]
    assert "Hook documentation body." in result[0]["content"]
    assert result[0]["_"]["id"] == "config/hooks.md#0"


@pytest.mark.asyncio
async def test_search_docs_reports_no_results(monkeypatch):
    chunks = SimpleNamespace(retrieve_creator_docs=Mock(return_value=[]))
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: chunks))

    response = await search_docs.Tool.execute(_coder(), query="hooks", mode="content")

    result = _result(response)["result"]
    assert "No documentation matched" in result[0]["content"]


@pytest.mark.asyncio
async def test_search_docs_rejects_empty_query(monkeypatch):
    chunks = SimpleNamespace(retrieve_creator_docs=Mock())
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: chunks))

    response = await search_docs.Tool.execute(_coder(), query="   ")

    data = _result(response)
    assert data["result"] == []
    assert "Provide 'query'" in data["errors"][0]
    chunks.retrieve_creator_docs.assert_not_called()


@pytest.mark.asyncio
async def test_search_docs_is_scoped_to_creator(monkeypatch):
    monkeypatch.setattr(search_docs, "is_creator_coder", lambda coder: False)

    response = await search_docs.Tool.execute(_coder(creator=False), query="hooks", mode="content")

    data = _result(response)
    assert data["result"] == []
    assert "scoped to the creator sub-agent" in data["errors"][0]


@pytest.mark.asyncio
async def test_search_docs_clamps_max_results(monkeypatch):
    chunks = SimpleNamespace(retrieve_creator_docs=Mock(return_value=[]))
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: chunks))

    await search_docs.Tool.execute(_coder(), query="hooks", mode="content", max_results=500)

    assert chunks.retrieve_creator_docs.call_args.kwargs["n_results"] == 60


@pytest.mark.asyncio
async def test_search_docs_reports_retrieval_failure(monkeypatch):
    chunks = SimpleNamespace(
        retrieve_creator_docs=Mock(side_effect=RuntimeError("index unavailable"))
    )
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: chunks))

    response = await search_docs.Tool.execute(_coder(), query="hooks", mode="content")

    data = _result(response)
    assert data["result"] == []
    assert "SearchDocs failed: index unavailable" in data["errors"][0]


@pytest.mark.asyncio
async def test_search_docs_appends_ranked_navigation(monkeypatch):
    chunks = SimpleNamespace(
        retrieve_creator_docs=Mock(
            return_value=[
                {
                    "id": "config/hooks.md#0",
                    "url": "https://cecli.dev/docs/config/hooks/",
                    "document": "Hook documentation body.",
                }
            ]
        ),
        retrieve_creator_doc_navigation=Mock(
            return_value={
                "files": [
                    {
                        "path": "config/hooks.md",
                        "url": "https://cecli.dev/docs/config/hooks/",
                        "matched_terms": ["hook", "config"],
                        "score": 2,
                        "section_count": 4,
                    }
                ],
                "sections": [
                    {
                        "path": "config/hooks.md",
                        "url": "https://cecli.dev/docs/config/hooks/",
                        "heading": "Hooks > Configuration",
                        "line": 12,
                        "matched_terms": ["hook", "config"],
                        "score": 2,
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: chunks))
    coder = _coder()

    response = await search_docs.Tool.execute(
        coder, query="  hook config  ", mode="content", max_results=3
    )

    chunks.retrieve_creator_doc_navigation.assert_called_once_with(
        coder, "hook config", n_files=3, n_sections=3
    )
    result = _result(response)["result"]
    assert len(result) == 2
    assert result[0]["_"]["id"] == "config/hooks.md#0"
    assert result[1]["_"]["type"] == "doc_navigation"
    assert "<doc_navigation>" in result[1]["content"]
    assert "config/hooks.md (2 terms: hook, config; 4 matching sections)" in result[1]["content"]
    assert (
        "config/hooks.md:12 Hooks > Configuration (2 terms: hook, config)" in result[1]["content"]
    )


@pytest.mark.asyncio
async def test_search_docs_returns_navigation_without_chunks(monkeypatch):
    chunks = SimpleNamespace(
        retrieve_creator_docs=Mock(return_value=[]),
        retrieve_creator_doc_navigation=Mock(
            return_value={
                "files": [
                    {
                        "path": "config/hooks.md",
                        "url": "",
                        "matched_terms": ["hooks"],
                        "score": 1,
                        "section_count": 2,
                    }
                ],
                "sections": [],
            }
        ),
    )
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: chunks))

    response = await search_docs.Tool.execute(_coder(), query="hooks", mode="content")

    result = _result(response)["result"]
    assert len(result) == 1
    assert "No documentation matched" not in result[0]["content"]
    assert "config/hooks.md (1 terms: hooks; 2 matching sections)" in result[0]["content"]


@pytest.mark.asyncio
async def test_navigation_failure_does_not_hide_chunks(monkeypatch):
    chunks = SimpleNamespace(
        retrieve_creator_docs=Mock(
            return_value=[
                {
                    "id": "config/hooks.md#0",
                    "url": "https://cecli.dev/docs/config/hooks/",
                    "document": "Hook documentation body.",
                }
            ]
        ),
        retrieve_creator_doc_navigation=Mock(side_effect=RuntimeError("navigation failed")),
    )
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: chunks))

    response = await search_docs.Tool.execute(_coder(), query="hooks", mode="content")

    data = _result(response)
    assert data["errors"] == []
    assert len(data["result"]) == 1
    assert "Hook documentation body." in data["result"][0]["content"]
