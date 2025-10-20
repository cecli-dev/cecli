"""
LiteLLM Embedding Adapter for Aider RAG.

This module provides a small adapter class that implements the two methods
llama_index expects on an embed model: embed_documents() and embed_query().
It uses litellm.embedding under the hood with simple batching, retries, and
optionally temporary switching of OPENAI_API_BASE when the provider is
"openai" to avoid conflicts with any custom base used for chat models.

Example
-------
    from aider.embeddings_litellm import LitellmEmbeddingAdapter
    adapter = LitellmEmbeddingAdapter(model="openai/text-embedding-small-3")
    vecs = adapter.embed_documents(["hello", "world"])  # list[list[float]]

Notes
-----
- We rely on aider.llm.LazyLiteLLM to import litellm lazily.
- Responses from litellm.embedding(...).data may expose each embedding either
  as an object with attribute `.embedding` or as a dict with key 'embedding'.
  The adapter supports both.
- Batching and exponential backoff retries are implemented for robustness.
"""

from __future__ import annotations

import os
import time
from typing import List, Optional

from aider.llm import litellm


class LitellmEmbeddingAdapter:
    """Thin adapter exposing embed_documents/embed_query using litellm.embedding.

    Parameters
    ----------
    model:
        Provider and model name for litellm, e.g. "openai/text-embedding-small-3".
    api_key:
        Optional API key. If None, litellm/env will handle auth. For OpenAI,
        OPENAI_API_KEY is typically used.
    batch_size:
        Batch size for embedding calls.
    original_openai_api_base:
        If set and provider is "openai", temporarily set OPENAI_API_BASE to
        this value during embedding calls. This helps when chat models may be
        pointed at a custom base (eg Azure) while embeddings should use the
        original OpenAI base.
    """

    def __init__(
        self,
        model: str = "openai/text-embedding-small-3",
        api_key: Optional[str] = None,
        batch_size: int = 100,
        original_openai_api_base: Optional[str] = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.batch_size = max(1, int(batch_size or 1))
        self.original_openai_api_base = original_openai_api_base

    # llama_index calls this for lists of texts
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        # Detect provider (prefix like "openai/") for special handling
        provider = None
        if "/" in self.model:
            provider = self.model.split("/", 1)[0].lower()

        # Temporarily switch OPENAI_API_BASE if requested
        restore_env = None
        if provider == "openai" and self.original_openai_api_base:
            restore_env = os.environ.get("OPENAI_API_BASE")
            if self.original_openai_api_base is not None:
                os.environ["OPENAI_API_BASE"] = self.original_openai_api_base

        try:
            vectors: List[List[float]] = []
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i : i + self.batch_size]
                data = self._embed_batch_with_retry(batch)
                for item in data:
                    emb = None
                    if hasattr(item, "embedding"):
                        emb = getattr(item, "embedding")
                    else:
                        # Try as mapping style: item["embedding"] or item.get("embedding")
                        try:
                            emb = item["embedding"]  # type: ignore[index]
                        except Exception:
                            try:
                                emb = item.get("embedding")  # type: ignore[attr-defined]
                            except Exception:
                                emb = None
                    if emb is None:
                        raise RuntimeError("Missing embedding in litellm response item")
                    vectors.append(list(emb))
            return vectors
        finally:
            # Restore original base if we changes it
            if provider == "openai" and self.original_openai_api_base is not None:
                if restore_env is None:
                    os.environ.pop("OPENAI_API_BASE", None)
                else:
                    os.environ["OPENAI_API_BASE"] = restore_env

    def _embed_batch_with_retry(self, batch: List[str]):
        # Retry on transient network/server errors using exponential backoff
        max_retries = 3
        delay = 0.5
        last_err = None
        for _ in range(max_retries + 1):
            try:
                resp = litellm.embedding(model=self.model, input=batch, api_key=self.api_key)
                return getattr(resp, "data", resp)
            except Exception as e:  # pragma: no cover - precise exceptions vary by provider
                last_err = e
                time.sleep(delay)
                delay *= 2
        # If we get here, all retries failed
        raise RuntimeError(f"Embedding call failed after retries: {last_err}")

    # llama_index calls this for single text queries
    def embed_query(self, text: str) -> List[float]:
        vecs = self.embed_documents([text])
        return vecs[0]


__all__ = ["LitellmEmbeddingAdapter"]
