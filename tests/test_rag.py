import os
from pathlib import Path

import pytest


def have_llama_index():
    try:
        import llama_index  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.skipif(not have_llama_index(), reason="llama_index not installed")
def test_repo_rag_basic(tmp_path, monkeypatch):
    # Create tiny repo tree
    proj = tmp_path / "proj"
    proj.mkdir()

    # Two small files
    (proj / "README.md").write_text("""
# Sample Project

Initialize the database using init_db() in db.py.
""".strip())
    (proj / "db.py").write_text(
        """
def init_db():
    return "ok"
""".strip()
    )

    # Optional .aiderignore to ensure it's honored (not excluding our files)
    (proj / ".aiderignore").write_text("# nothing ignored\n")

    # Build index under a temp cache dir to avoid touching user cache
    cache_dir = tmp_path / "cache"

    # Mock litellm.embedding to avoid network
    class FakeResp:
        def __init__(self, data):
            self.data = data

    def fake_embedding(model, input, api_key=None):  # noqa: A002
        return FakeResp([{"embedding": [0.01, 0.02, 0.03]} for _ in input])

    from aider import llm as _llm

    # Inject fake litellm module on the lazy loader instance
    import types as _types

    _fake_mod = _types.SimpleNamespace(embedding=fake_embedding)
    # Set the lazy module so __getattr__ returns attributes from our fake module
    _llm.litellm._lazy_module = _fake_mod

    from aider.rag import RepoRAG

    rag = RepoRAG(project_root=proj, persist_dir=cache_dir, embedding_config={
        "provider": "litellm",
        "model_name": "openai/text-embedding-small-3",
    })
    rag.build_index(force_reindex=True, quiet=True)

    # Query a known phrase
    ctx = rag.query("How do I initialize the database?", top_k=3)

    # Should reference db.py or include snippet
    assert "db.py" in ctx or "init_db" in ctx
