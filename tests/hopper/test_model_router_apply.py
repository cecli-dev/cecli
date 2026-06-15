"""Apply-route tests — per-turn LiteLLM think override + keep_alive."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cecli.hopper.apply import (
    apply_hopper_extra_params,
    apply_route_to_coder,
    apply_thinking_extra_params,
    merge_extra_params,
)
from cecli.hopper.router import ModelPoolEntry, ModelRouterConfig, RouteDecision


def test_apply_thinking_extra_params_sets_bool():
    model = MagicMock()
    model.extra_params = {}
    apply_thinking_extra_params(model, True)
    assert model.extra_params["think"] is True
    apply_thinking_extra_params(model, False)
    assert model.extra_params["think"] is False


def test_merge_extra_params_deep_merges_dicts():
    base = {"extra_headers": {"A": "1"}, "top_p": 0.5}
    merge_extra_params(base, {"extra_headers": {"B": "2"}, "top_p": 0.9})
    assert base["extra_headers"] == {"A": "1", "B": "2"}
    assert base["top_p"] == 0.9


def test_apply_hopper_extra_params_skips_keep_alive():
    model = MagicMock()
    model.extra_params = {"keep_alive": 99}
    apply_hopper_extra_params(model, {"keep_alive": 0, "top_p": 0.8})
    assert model.extra_params.get("keep_alive") == 99
    assert model.extra_params.get("top_p") == 0.8


def test_apply_route_merges_hopper_extra_params():
    prev = MagicMock()
    prev.name = "ollama_chat/qwen3.6:27b"
    prev.is_ollama.return_value = True
    prev.extra_params = {"think": False}

    created: dict = {}

    def _model_ctor(name, from_model=None):
        m = MagicMock()
        m.name = name
        m.is_ollama.return_value = True
        m.extra_params = dict(from_model.extra_params)
        m._ensure_extra_params_dict = lambda: None
        created["model"] = m
        return m

    coder = MagicMock()
    coder.main_model = prev

    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/fast",
        code_model="ollama_chat/code",
        model_pool=[
            ModelPoolEntry(
                model="ollama_chat/code",
                tier="code",
                enabled=True,
                extra_params={"top_p": 0.85, "think": True},
            )
        ],
    )
    decision = RouteDecision(
        tier="code",
        role="code",
        model_name="ollama_chat/code",
        estimated_tokens=100,
        enable_thinking=False,
    )

    with patch("cecli.hopper.apply.models.Model", side_effect=_model_ctor):
        apply_route_to_coder(coder, decision, router)

    assert created["model"].extra_params.get("top_p") == 0.85
    assert created["model"].extra_params.get("think") is False
    assert created["model"].extra_params.get("keep_alive") == -1


def test_apply_route_code_disables_think():
    prev = MagicMock()
    prev.name = "ollama_chat/qwen3.6:27b"
    prev.is_ollama.return_value = True
    prev.extra_params = {"think": False}

    created: dict = {}

    def _model_ctor(name, from_model=None):
        m = MagicMock()
        m.name = name
        m.is_ollama.return_value = True
        m.extra_params = dict(from_model.extra_params)
        m._ensure_extra_params_dict = lambda: None
        created["model"] = m
        return m

    coder = MagicMock()
    coder.main_model = prev

    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/fast",
        code_model="ollama_chat/code",
    )
    decision = RouteDecision(
        tier="code",
        role="code",
        model_name="ollama_chat/code",
        estimated_tokens=100,
        enable_thinking=False,
    )

    with patch("cecli.hopper.apply.models.Model", side_effect=_model_ctor):
        apply_route_to_coder(coder, decision, router)

    assert created["model"].extra_params.get("think") is False
    assert created["model"].extra_params.get("keep_alive") == -1


def test_apply_route_think_enables_think():
    prev = MagicMock()
    prev.name = "ollama_chat/qwen3.6:27b"
    prev.is_ollama.return_value = True
    prev.extra_params = {"think": False}

    created: dict = {}

    def _model_ctor(name, from_model=None):
        m = MagicMock()
        m.name = name
        m.is_ollama.return_value = True
        m.extra_params = dict(from_model.extra_params)
        m._ensure_extra_params_dict = lambda: None
        created["model"] = m
        return m

    coder = MagicMock()
    coder.main_model = prev

    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/fast",
        code_model="ollama_chat/code",
        think_model="ollama_chat/deepseek-r1:32b",
    )
    decision = RouteDecision(
        tier="think",
        role="think",
        model_name="ollama_chat/deepseek-r1:32b",
        estimated_tokens=100,
        enable_thinking=True,
    )

    with patch("cecli.hopper.apply.models.Model", side_effect=_model_ctor):
        apply_route_to_coder(coder, decision, router)

    assert created["model"].extra_params.get("think") is True


def test_apply_route_qwen_sets_no_think_prefix():
    prev = MagicMock()
    prev.name = "ollama_chat/qwen3.6:27b"
    prev.is_ollama.return_value = True
    prev.extra_params = {}
    prev.system_prompt_prefix = ""

    created: dict = {}

    def _model_ctor(name, from_model=None):
        m = MagicMock()
        m.name = name
        m.is_ollama.return_value = True
        m.extra_params = {}
        m.system_prompt_prefix = ""
        m._ensure_extra_params_dict = lambda: None
        created["model"] = m
        return m

    coder = MagicMock()
    coder.main_model = prev

    router = ModelRouterConfig(
        enabled=True,
        fast_model="ollama_chat/fast",
        code_model="ollama_chat/qwen3.6:27b",
    )
    decision = RouteDecision(
        tier="code",
        role="code",
        model_name="ollama_chat/qwen3.6:27b",
        estimated_tokens=100,
        enable_thinking=False,
    )

    with patch("cecli.hopper.apply.models.Model", side_effect=_model_ctor):
        apply_route_to_coder(coder, decision, router)

    assert created["model"].extra_params.get("think") is False
    assert created["model"].system_prompt_prefix == "/no_think"
