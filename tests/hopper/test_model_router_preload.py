"""Tests for preload_priority_list — priority-ordered preloading with VRAM budget."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from cecli.hopper.router import (
    _strip_ollama_prefix,
    preload_priority_list,
)

# ---------------------------------------------------------------------------
# Mock Ollama client
# ---------------------------------------------------------------------------


@dataclass
class MockOllamaClient:
    """Mock OllamaClient for testing preload_priority_list."""

    # Track calls for assertions
    generate_calls: list[tuple[str, int]] = field(default_factory=list)
    show_calls: list[str] = field(default_factory=list)

    # Configurable behavior
    model_sizes: dict[str, int] = field(default_factory=dict)
    failing_models: set[str] = field(default_factory=set)
    show_failures: set[str] = field(default_factory=set)

    async def post_generate(self, model: str, *, keep_alive: int = -1) -> None:
        self.generate_calls.append((model, keep_alive))
        if model in self.failing_models:
            raise RuntimeError(f"Preload failed: model '{model}' not found")

    async def show_model(self, model: str) -> dict[str, Any]:
        self.show_calls.append(model)
        if model in self.show_failures:
            raise RuntimeError(f"Show failed for '{model}'")
        size = self.model_sizes.get(model)
        if size is not None:
            return {"size": size}
        return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preload_all_models_in_order():
    """All models preload successfully in priority order."""
    client = MockOllamaClient()
    priority = ["model-a:7b", "model-b:13b", "model-c:32b"]

    result = await preload_priority_list(priority, ollama_client=client)

    assert result == ["model-a:7b", "model-b:13b", "model-c:32b"]
    assert client.generate_calls == [
        ("model-a:7b", -1),
        ("model-b:13b", -1),
        ("model-c:32b", -1),
    ]


@pytest.mark.asyncio
async def test_preload_strips_ollama_prefix():
    """ollama_chat/ prefix is stripped for API calls but preserved in results."""
    client = MockOllamaClient()
    priority = ["ollama_chat/deepseek-r1:32b", "ollama/qwen:7b"]

    result = await preload_priority_list(priority, ollama_client=client)

    assert result == ["ollama_chat/deepseek-r1:32b", "ollama/qwen:7b"]
    assert client.generate_calls == [
        ("deepseek-r1:32b", -1),
        ("qwen:7b", -1),
    ]


@pytest.mark.asyncio
async def test_preload_failure_skips_and_continues():
    """On preload failure, log error, skip model, continue with next."""
    client = MockOllamaClient(failing_models={"model-b:13b"})
    priority = ["model-a:7b", "model-b:13b", "model-c:32b"]

    result = await preload_priority_list(priority, ollama_client=client)

    assert result == ["model-a:7b", "model-c:32b"]
    # All three were attempted
    assert len(client.generate_calls) == 3


@pytest.mark.asyncio
async def test_preload_vram_budget_stops_when_exceeded():
    """When cumulative VRAM exceeds budget, stop preloading remaining models."""
    client = MockOllamaClient(
        model_sizes={
            "model-a:7b": 4_000_000_000,  # 4 GB
            "model-b:13b": 8_000_000_000,  # 8 GB
            "model-c:32b": 18_000_000_000,  # 18 GB
        }
    )
    priority = ["model-a:7b", "model-b:13b", "model-c:32b"]
    # Budget: 11 GB → model-a (4 GB) + model-b (8 GB) = 12 GB > 11 GB
    # So model-a fits, model-b does NOT fit, stop.
    budget = 11_000_000_000

    result = await preload_priority_list(priority, ollama_client=client, vram_budget_bytes=budget)

    assert result == ["model-a:7b"]
    # Only model-a was actually preloaded (generate called)
    assert len(client.generate_calls) == 1
    assert client.generate_calls[0][0] == "model-a:7b"


@pytest.mark.asyncio
async def test_preload_vram_budget_all_fit():
    """All models fit within VRAM budget."""
    client = MockOllamaClient(
        model_sizes={
            "model-a:7b": 4_000_000_000,
            "model-b:7b": 4_000_000_000,
        }
    )
    priority = ["model-a:7b", "model-b:7b"]
    budget = 10_000_000_000  # 10 GB — both fit

    result = await preload_priority_list(priority, ollama_client=client, vram_budget_bytes=budget)

    assert result == ["model-a:7b", "model-b:7b"]
    assert len(client.generate_calls) == 2


@pytest.mark.asyncio
async def test_preload_vram_unknown_size_proceeds():
    """When model size info unavailable, skip budget check and preload anyway."""
    client = MockOllamaClient(
        model_sizes={
            "model-a:7b": 4_000_000_000,
            # model-b has no size info
        }
    )
    priority = ["model-a:7b", "model-b:unknown"]
    budget = 5_000_000_000  # 5 GB

    result = await preload_priority_list(priority, ollama_client=client, vram_budget_bytes=budget)

    # Both preloaded — model-b has no size info, so budget check skipped for it
    assert result == ["model-a:7b", "model-b:unknown"]


@pytest.mark.asyncio
async def test_preload_no_budget_preloads_all():
    """Without VRAM budget, all models preloaded regardless of size."""
    client = MockOllamaClient(
        model_sizes={
            "huge:70b": 40_000_000_000,
            "also-huge:70b": 40_000_000_000,
        }
    )
    priority = ["huge:70b", "also-huge:70b"]

    result = await preload_priority_list(priority, ollama_client=client)

    assert result == ["huge:70b", "also-huge:70b"]
    # No show calls when budget is None
    assert client.show_calls == []


@pytest.mark.asyncio
async def test_preload_empty_list():
    """Empty priority list returns empty result."""
    client = MockOllamaClient()
    result = await preload_priority_list([], ollama_client=client)
    assert result == []
    assert client.generate_calls == []


@pytest.mark.asyncio
async def test_preload_skips_whitespace_only_entries():
    """Whitespace-only entries in priority list are skipped."""
    client = MockOllamaClient()
    priority = ["model-a:7b", "  ", "", "model-b:7b"]

    result = await preload_priority_list(priority, ollama_client=client)

    assert result == ["model-a:7b", "model-b:7b"]
    assert len(client.generate_calls) == 2


@pytest.mark.asyncio
async def test_preload_uses_backend_resolver_when_no_ollama_client():
    """Host resolver hook supplies BackendClient.preload_models when no ollama_client."""
    from unittest.mock import AsyncMock

    from cecli.hopper.router import set_backend_client_resolver

    mock_client = AsyncMock()
    mock_client.preload_models = AsyncMock(return_value=[])

    set_backend_client_resolver(lambda: mock_client)
    try:
        result = await preload_priority_list(["model-a:7b"])
    finally:
        set_backend_client_resolver(None)

    assert result == []
    mock_client.preload_models.assert_called_once_with(["model-a:7b"])


@pytest.mark.asyncio
async def test_preload_show_failure_skips_budget_check():
    """When show_model fails, skip budget check and preload anyway."""
    client = MockOllamaClient(show_failures={"model-a:7b"})
    priority = ["model-a:7b"]
    budget = 1_000  # Tiny budget — but show fails, so budget check skipped

    result = await preload_priority_list(priority, ollama_client=client, vram_budget_bytes=budget)

    assert result == ["model-a:7b"]


# ---------------------------------------------------------------------------
# Unit tests for _strip_ollama_prefix
# ---------------------------------------------------------------------------


def test_strip_ollama_prefix_chat():
    assert _strip_ollama_prefix("ollama_chat/deepseek-r1:32b") == "deepseek-r1:32b"


def test_strip_ollama_prefix_plain():
    assert _strip_ollama_prefix("ollama/qwen:7b") == "qwen:7b"


def test_strip_ollama_prefix_no_prefix():
    assert _strip_ollama_prefix("deepseek-r1:32b") == "deepseek-r1:32b"
