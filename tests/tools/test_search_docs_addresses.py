"""Golden-output tests for SearchDocs address ranking, TOC, key anchors and floors."""

from types import SimpleNamespace

import pytest

from cecli.help import (
    get_doc,
    keyword_retrieve,
    locate_doc_chunk,
    navigate_docs,
    rank_doc_addresses,
)
from cecli.helpers.conversation import ConversationService
from cecli.tools import search_docs


def _result(response):
    return response.to_dict()


def _coder():
    return SimpleNamespace(agent_config={"creator_mode": True})


class _Chunks:
    """Chunk service backed by the real docs resolver."""

    docs = None

    def retrieve_creator_docs(self, coder, query, n_results=8):
        if self.docs is not None:
            return self.docs[:n_results]

        return keyword_retrieve(query, n_results=n_results)

    def retrieve_creator_doc_navigation(self, coder, query, n_files=5, n_sections=10):
        return navigate_docs(query, n_files=n_files, n_sections=n_sections)

    def retrieve_creator_doc_addresses(self, coder, query, n_results=5):
        return rank_doc_addresses(query, max_results=n_results)

    def retrieve_creator_doc(self, coder, path, n_results=20):
        return get_doc(path, max_results=n_results)


@pytest.fixture(autouse=True)
def _patch_chunks(monkeypatch):
    _Chunks.docs = None
    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: _Chunks()))


@pytest.mark.asyncio
async def test_query_returns_addresses_by_default():
    data = _result(await search_docs.Tool.execute(_coder(), query="configure mcp servers"))
    entry = data["result"][0]

    assert data["errors"] == []
    assert entry["_"]["type"] == "doc_addresses"
    assert entry["_"]["count"] == 5

    content = entry["content"]
    assert content.startswith('<doc_addresses query="configure mcp servers" count="5"')
    assert content.endswith("</doc_addresses>")
    assert "config/mcp.md#" in content
    # addresses only: no embedded documentation bodies
    assert "<doc from_url" not in content

    paths = [line.split()[1].split("#")[0] for line in content.splitlines()[1:-1]]
    assert len(paths) == len(set(paths))


@pytest.mark.asyncio
async def test_query_addresses_are_feed_back_able():
    data = _result(await search_docs.Tool.execute(_coder(), query="configure mcp servers"))
    address = data["result"][0]["content"].splitlines()[1].split()[1]

    follow_up = _result(await search_docs.Tool.execute(_coder(), path=address))
    entry = follow_up["result"][0]

    assert follow_up["errors"] == []
    assert entry["_"]["type"] == "doc_file"


@pytest.mark.asyncio
async def test_content_mode_keeps_chunks_and_navigation():
    data = _result(await search_docs.Tool.execute(_coder(), query="hooks", mode="content"))

    types = [entry["_"].get("type", "chunk") for entry in data["result"]]
    assert "chunk" in types
    assert "doc_navigation" in types
    assert any("<doc from_url=" in entry["content"] for entry in data["result"])


@pytest.mark.asyncio
async def test_relevance_floor_drops_noise():
    _Chunks.docs = [
        dict(
            id=f"noise/{index}.md#0",
            url="",
            document="noise",
            distance=1.5 + index / 100,
        )
        for index in range(6)
    ]

    data = _result(await search_docs.Tool.execute(_coder(), query="xylophone quux", mode="content"))

    assert data["result"][0]["content"] == "No documentation matched this query."
    notices = [
        entry["content"] for entry in data["result"] if entry["_"].get("type") == "doc_notice"
    ]
    assert notices == [
        '<doc_notice dropped="6">6 more results scored below the relevance threshold.</doc_notice>'
    ]


@pytest.mark.asyncio
async def test_relevance_floor_keeps_relevant_hits():
    _Chunks.docs = [
        dict(id="a.md#0", url="", document="relevant", distance=0.9),
        dict(id="b.md#0", url="", document="edge", distance=1.4),
        dict(id="c.md#0", url="", document="noise", distance=1.6),
    ]

    data = _result(await search_docs.Tool.execute(_coder(), query="anything", mode="content"))
    contents = [entry["content"] for entry in data["result"]]

    assert any("relevant" in content for content in contents)
    assert any("edge" in content for content in contents)
    assert not any("noise" in content for content in contents)
    assert any('dropped="1"' in content for content in contents)


@pytest.mark.asyncio
async def test_toc_slugs_round_trip():
    data = _result(await search_docs.Tool.execute(_coder(), path="config/conf.md#"))
    entry = data["result"][0]

    assert entry["_"]["type"] == "doc_toc"
    assert entry["_"]["sections"] == 13
    assert entry["_"]["keys"] == 129
    assert '<doc_toc path="config/conf.md"' in entry["content"]
    assert "merge-precedence YAML Config File > Merge Precedence (L28-183)" in entry["content"]

    follow_up = _result(
        await search_docs.Tool.execute(_coder(), path="config/conf.md#merge-precedence")
    )
    section = follow_up["result"][0]

    assert section["_"]["section"] == "YAML Config File > Merge Precedence"
    assert section["_"]["range"] == [28, 183]


@pytest.mark.asyncio
async def test_config_key_anchor_reads_the_key_pair():
    data = _result(await search_docs.Tool.execute(_coder(), path="config/conf.md#dark-mode"))
    entry = data["result"][0]

    assert entry["_"]["type"] == "doc_file"
    assert entry["_"]["key"] == "dark-mode"
    assert entry["_"]["value"] == "false"
    assert entry["_"]["range"] == [361, 362]

    content = entry["content"]
    assert 'key="dark-mode"' in content
    assert 'lines="361-362"' in content
    assert "## Use colors suitable for a dark terminal background" in content
    assert "#dark-mode: false" in content


@pytest.mark.asyncio
async def test_unknown_key_fails_loud():
    data = _result(await search_docs.Tool.execute(_coder(), path="config/conf.md#dark-modes"))

    assert data["result"] == []
    error = data["errors"][0]
    assert 'No heading or key matched "dark-modes"' in error
    assert "Closest key: dark-mode" in error
    assert "129 keys" in error


@pytest.mark.asyncio
async def test_root_path_lists_docs_root():
    data = _result(await search_docs.Tool.execute(_coder(), path="/"))
    entry = data["result"][0]

    assert entry["_"]["type"] == "doc_paths"
    assert entry["_"]["total"] == 25
    assert "- config/ (dir, " in entry["content"]


@pytest.mark.asyncio
async def test_whole_file_read_strips_navigation_frontmatter():
    data = _result(await search_docs.Tool.execute(_coder(), path="config/hooks.md"))
    content = data["result"][0]["content"]

    assert "parent:" not in content
    assert "nav_order:" not in content
    assert "description:" in content
    assert 'lines="344"' in content


@pytest.mark.asyncio
async def test_glob_support_is_kept():
    data = _result(await search_docs.Tool.execute(_coder(), path="config/*.md", max_results=3))
    entry = data["result"][0]

    assert entry["_"]["type"] == "doc_paths"
    assert entry["_"]["count"] == 3


@pytest.mark.asyncio
async def test_address_ranking_unavailable_is_reported(monkeypatch):
    chunks = SimpleNamespace()

    monkeypatch.setattr(ConversationService, "get_chunks", staticmethod(lambda coder: chunks))
    data = _result(await search_docs.Tool.execute(_coder(), query="hooks"))

    assert data["result"] == []
    assert "address ranking is unavailable" in data["errors"][0]


@pytest.mark.asyncio
async def test_invalid_mode_is_rejected():
    data = _result(await search_docs.Tool.execute(_coder(), query="hooks", mode="bogus"))

    assert data["result"] == []
    assert "'mode' must be 'addresses' or 'content'." in data["errors"][0]


@pytest.mark.asyncio
async def test_no_match_query_returns_no_addresses():
    data = _result(await search_docs.Tool.execute(_coder(), query="xylophone quux zzzzq"))

    assert data["errors"] == []
    assert data["result"][0]["content"] == "No documentation matched this query."


@pytest.mark.asyncio
async def test_content_chunks_report_path_heading_and_line_range():
    docs = keyword_retrieve("mcp", n_results=8)
    doc = next(item for item in docs if (locate_doc_chunk(item["id"]) or {}).get("heading"))
    location = locate_doc_chunk(doc["id"])
    _Chunks.docs = [dict(doc, distance=0.5)]

    data = _result(
        await search_docs.Tool.execute(_coder(), query="mcp", mode="content", max_results=1)
    )
    entry = next(item for item in data["result"] if "type" not in item["_"])

    assert entry["_"]["path"] == location["path"]
    assert entry["_"]["heading"] == location["heading"]
    assert entry["_"]["range"] == [location["start_line"], location["end_line"]]
    assert 'path="{}"'.format(location["path"]) in entry["content"]
    assert 'heading="{}"'.format(location["heading"]) in entry["content"]
    assert 'lines="{}-{}"'.format(location["start_line"], location["end_line"]) in entry["content"]
