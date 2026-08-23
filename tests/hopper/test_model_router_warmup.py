"""Tests for warmup_keep_alive — keep-alive requests in priority order."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from cecli.hopper.router import warmup_keep_alive

# ---------------------------------------------------------------------------
# Mock Ollama client
# ---------------------------------------------------------------------------


@dataclass
class MockOllamaClient:
    """Mock OllamaClient for testing warmup_keep_alive."""

    generate_calls: list[tuple[str, int]] = field(default_factory=list)
    failing_models: set[str] = field(default_factory=set)

    async def post_generate(self, model: str, *, keep_alive: int = -1) -> None:
        self.generate_calls.append((model, keep_alive))
        if model in self.failing_models:
            raise RuntimeError(f"Keep-alive failed: model '{model}' not found")

    async def show_model(self, model: str) -> dict[str, Any]:
        return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_sends_requests_in_priority_order():
    """Keep-alive requests are sent in priority-list index order."""
    client = MockOllamaClient()
    priority = ["model-a:7b", "model-b:13b", "model-c:32b"]

    result = await warmup_keep_alive(priority, ollama_client=client)

    assert result == ["model-a:7b", "model-b:13b", "model-c:32b"]
    assert client.generate_calls == [
        ("model-a:7b", -1),
        ("model-b:13b", -1),
        ("model-c:32b", -1),
    ]


@pytest.mark.asyncio
async def test_warmup_higher_priority_refreshes_first():
    """Index 0 (highest priority) refreshes TTL before index N-1."""
    client = MockOllamaClient()
    priority = ["high-priority:7b", "mid-priority:13b", "low-priority:32b"]

    await warmup_keep_alive(priority, ollama_client=client)

    # Verify ordering: high-priority called first
    call_models = [call[0] for call in client.generate_calls]
    assert call_models == ["high-priority:7b", "mid-priority:13b", "low-priority:32b"]


@pytest.mark.asyncio
async def test_warmup_strips_ollama_prefix():
    """ollama_chat/ prefix is stripped for API calls but preserved in results."""
    client = MockOllamaClient()
    priority = ["ollama_chat/deepseek-r1:32b", "ollama/qwen:7b"]

    result = await warmup_keep_alive(priority, ollama_client=client)

    assert result == ["ollama_chat/deepseek-r1:32b", "ollama/qwen:7b"]
    assert client.generate_calls == [
        ("deepseek-r1:32b", -1),
        ("qwen:7b", -1),
    ]


@pytest.mark.asyncio
async def test_warmup_failure_skips_and_continues():
    """On keep-alive failure, log error, skip model, continue with next."""
    client = MockOllamaClient(failing_models={"model-b:13b"})
    priority = ["model-a:7b", "model-b:13b", "model-c:32b"]

    result = await warmup_keep_alive(priority, ollama_client=client)

    assert result == ["model-a:7b", "model-c:32b"]
    # All three were attempted
    assert len(client.generate_calls) == 3


@pytest.mark.asyncio
async def test_warmup_empty_list():
    """Empty priority list returns empty result."""
    client = MockOllamaClient()
    result = await warmup_keep_alive([], ollama_client=client)
    assert result == []
    assert client.generate_calls == []


@pytest.mark.asyncio
async def test_warmup_skips_whitespace_only_entries():
    """Whitespace-only entries in priority list are skipped."""
    client = MockOllamaClient()
    priority = ["model-a:7b", "  ", "", "model-b:7b"]

    result = await warmup_keep_alive(priority, ollama_client=client)

    assert result == ["model-a:7b", "model-b:7b"]
    assert len(client.generate_calls) == 2


@pytest.mark.asyncio
async def test_warmup_uses_keep_alive_minus_one():
    """All keep-alive requests use keep_alive=-1 to refresh TTL indefinitely."""
    client = MockOllamaClient()
    priority = ["model-a:7b", "model-b:7b"]

    await warmup_keep_alive(priority, ollama_client=client)

    for _, keep_alive_val in client.generate_calls:
        assert keep_alive_val == -1


@pytest.mark.asyncio
async def test_warmup_all_failures_returns_empty():
    """When all models fail, returns empty list."""
    client = MockOllamaClient(failing_models={"model-a:7b", "model-b:7b"})
    priority = ["model-a:7b", "model-b:7b"]

    result = await warmup_keep_alive(priority, ollama_client=client)

    assert result == []
    # Both attempted
    assert len(client.generate_calls) == 2
