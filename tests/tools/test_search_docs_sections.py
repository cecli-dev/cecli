"""Tests for heading-scoped SearchDocs reads and browse section counts."""

from types import SimpleNamespace

import pytest

from cecli.help import get_doc
from cecli.helpers.conversation import ConversationService
from cecli.tools import search_docs

CONF_PATH = "config/conf.md"
CONF_SECTION = "YAML Config File > Merge Precedence"


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
async def test_section_read_returns_only_that_subtree():
    response = await search_docs.Tool.execute(_coder(), path=f"{CONF_PATH}#Merge Precedence")

    entry = _result(response)["result"][0]
    content = entry["content"]

    assert entry["_"]["section"] == CONF_SECTION
    assert entry["_"]["level"] == 2
    assert entry["_"]["range"] == [28, 183]
    assert entry["_"]["lines"] == 646

    assert content.startswith(f'<doc_file path="{CONF_PATH}"')
    assert f'section="{CONF_SECTION}"' in content
    assert 'level="2"' in content
    assert 'lines="28-183"' in content
    assert 'of_lines="646"' in content

    assert "## Merge Precedence" in content
    assert "### Deduplication" in content
    assert "## Sample YAML config file" not in content


@pytest.mark.asyncio
async def test_section_read_matches_a_nested_heading_by_segment():
    response = await search_docs.Tool.execute(_coder(), path=f"{CONF_PATH}#Deduplication")

    entry = _result(response)["result"][0]

    assert entry["_"]["section"] == f"{CONF_SECTION} > Deduplication"
    assert entry["_"]["level"] == 3


@pytest.mark.asyncio
async def test_section_read_accepts_url_anchors():
    for path in (
        "https://cecli.dev/docs/config/conf/#merge-precedence",
        f"{CONF_PATH}#merge-precedence",
    ):
        response = await search_docs.Tool.execute(_coder(), path=path)

        entry = _result(response)["result"][0]
        assert entry["_"]["section"] == CONF_SECTION


@pytest.mark.asyncio
async def test_unknown_heading_fails_with_suggestions():
    response = await search_docs.Tool.execute(_coder(), path=f"{CONF_PATH}#Merge Precedance")

    data = _result(response)
    assert data["result"] == []

    error = data["errors"][0]
    assert 'No heading or key matched "Merge Precedance"' in error
    assert CONF_SECTION in error
    assert "13 headings" in error


@pytest.mark.asyncio
async def test_anchor_requires_an_exact_file():
    for path in ("config/#hooks", "config/*.md#hooks", "config/nope.md#hooks"):
        response = await search_docs.Tool.execute(_coder(), path=path)

        data = _result(response)
        assert data["result"] == []
        assert "Anchors require an exact file path" in data["errors"][0]


@pytest.mark.asyncio
async def test_empty_anchor_returns_the_file_outline():
    response = await search_docs.Tool.execute(_coder(), path=f"{CONF_PATH}#")

    entry = _result(response)["result"][0]

    assert entry["_"]["type"] == "doc_toc"
    assert entry["_"]["path"] == CONF_PATH
    assert entry["_"]["sections"] > 0
    assert "<doc_toc path=" in entry["content"]


@pytest.mark.asyncio
async def test_browse_reports_section_counts():
    result = get_doc("config/", max_results=2)

    assert result["files"]
    assert all(entry["sections"] > 0 for entry in result["files"])

    response = await search_docs.Tool.execute(_coder(), path="config/", max_results=2)
    content = _result(response)["result"][0]["content"]

    assert " lines, " in content
    assert " sections)" in content


@pytest.mark.asyncio
async def test_section_read_is_scoped_to_creator():
    response = await search_docs.Tool.execute(
        _coder(creator=False), path=f"{CONF_PATH}#Merge Precedence"
    )

    data = _result(response)
    assert data["result"] == []
    assert "scoped to the creator sub-agent" in data["errors"][0]


@pytest.mark.asyncio
async def test_section_attribute_escapes_quotes_in_headings():
    response = await search_docs.Tool.execute(
        _coder(), path="config/model-providers.md#provider-not-found"
    )

    entry = _result(response)["result"][0]

    assert entry["_"]["section"] == 'Model Providers > Troubleshooting > "Provider not found"'
    assert (
        'section="Model Providers &gt; Troubleshooting &gt; &quot;Provider not found&quot;"'
        not in (entry["content"])
    )
    assert 'section="Model Providers > Troubleshooting > &quot;Provider not found&quot;"' in (
        entry["content"]
    )
