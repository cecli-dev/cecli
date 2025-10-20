import types
from pathlib import Path

import pytest


def have_llama_index():
    try:
        import llama_index  # noqa: F401

        return True
    except Exception:
        return False


class FakeAttrItem:
    def __init__(self, emb):
        self.embedding = emb


@pytest.mark.skipif(not have_llama_index(), reason="llama_index not installed")
def test_litellm_adapter_basic(monkeypatch):
    from aider.embeddings_litellm import LitellmEmbeddingAdapter

    # Mock litellm.embedding to return a response-like obj with .data
    class FakeResp:
        def __init__(self, data):
            self.data = data

    calls = []

    def fake_embedding(model, input, api_key=None):  # noqa: A002 - shadowing ok in test
        calls.append((model, list(input), api_key))
        # Return alternating attribute/dict style
        data = []
        for i, _ in enumerate(input):
            if i % 2 == 0:
                data.append(FakeAttrItem([float(i), float(i + 1)]))
            else:
                data.append({"embedding": [float(i), float(i + 1)]})
        return FakeResp(data)

    # Patch aider.llm.litellm.embedding
    from aider import llm as _llm

    monkeypatch.setattr(_llm.LazyLiteLLM, "embedding", staticmethod(fake_embedding), raising=False)

    adapter = LitellmEmbeddingAdapter(model="openai/text-embedding-small-3", batch_size=2)
    out = adapter.embed_documents(["a", "b", "c"])  # 3 items -> two batches (2,1)

    assert len(out) == 3
    assert out[0] == [0.0, 1.0]
    assert out[1] == [1.0, 2.0]
    assert out[2] == [0.0, 1.0]  # second batch resets i
    # Ensure litellm.embedding called
    assert calls and calls[0][0].endswith("text-embedding-small-3")


@pytest.mark.skipif(not have_llama_index(), reason="llama_index not installed")
def test_repo_rag_with_litellm(tmp_path, monkeypatch):
    # Minimal files
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.md").write_text("Alpha bravo charlie")
    (proj / "b.py").write_text("def func():\n    return 'ok'\n")

    cache_dir = tmp_path / "cache"

    # Fake litellm.embedding deterministic
    class FakeResp:
        def __init__(self, data):
            self.data = data

    def fake_embedding(model, input, api_key=None):  # noqa: A002
        # constant 2D vectors
        return FakeResp([{"embedding": [0.1, 0.2, 0.3]} for _ in input])

    from aider import llm as _llm

    monkeypatch.setattr(_llm.LazyLiteLLM, "embedding", staticmethod(fake_embedding), raising=False)

    from aider.rag import RepoRAG

    # Force provider to litellm via config
    rag = RepoRAG(project_root=proj, persist_dir=cache_dir, embedding_config={
        "provider": "litellm",
        "model_name": "openai/text-embedding-small-3",
        "batch_size": 10,
    })
    rag.build_index(force_reindex=True, quiet=True)
    ctx = rag.query("Alpha?", top_k=2)
    assert "a.md" in ctx or "Alpha" in ctx

