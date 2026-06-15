"""Apply a route decision to a live cecli Coder (swap main_model + Ollama keep_alive)."""

from __future__ import annotations

from typing import Any

from cecli import models

from cecli.hopper.router import (
    ModelRouterConfig,
    RouteDecision,
    RouteRole,
    find_pool_entry,
    normalize_keep_alive_for_tier,
    normalize_route_role,
    resolve_pool_entry_thinking,
)


def merge_extra_params(into: dict[str, Any], patch: dict[str, Any]) -> None:
    """Deep-merge LiteLLM kwargs (cecli-style); router owns ``keep_alive``."""
    for key, value in patch.items():
        if key == "keep_alive":
            continue
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            merge_extra_params(into[key], value)
        else:
            into[key] = value


def apply_hopper_extra_params(model, extra: dict[str, Any] | None) -> None:
    if not extra:
        return
    model._ensure_extra_params_dict()
    merge_extra_params(model.extra_params, extra)


def apply_thinking_extra_params(model, enable: bool | None) -> None:
    """Set Ollama ``think`` for this model; overrides hopper/global ``think``."""
    if enable is None:
        return
    model._ensure_extra_params_dict()
    model.extra_params["think"] = enable
    name = (getattr(model, "name", "") or "").lower()
    if "qwen3" in name:
        if enable:
            if getattr(model, "system_prompt_prefix", "") == "/no_think":
                model.system_prompt_prefix = ""
        else:
            model.system_prompt_prefix = "/no_think"


def _resolve_enable_thinking(
    decision: RouteDecision,
    router: ModelRouterConfig,
    role: RouteRole,
    pool_entry,
) -> bool | None:
    enable = decision.enable_thinking
    if enable is not None:
        return enable
    if pool_entry is not None:
        return resolve_pool_entry_thinking(pool_entry)
    return None


def apply_route_to_coder(coder, decision: RouteDecision, router: ModelRouterConfig) -> None:
    """Point the coder at the routed model for this turn."""
    prev = coder.main_model
    new_model = models.Model(decision.model_name, from_model=prev)
    role = decision.role or normalize_route_role(decision.tier) or "code"
    pool_entry = (
        find_pool_entry(router.model_pool, decision.model_name, role)
        if router.model_pool
        else None
    )
    apply_hopper_extra_params(
        new_model,
        pool_entry.extra_params if pool_entry else None,
    )
    if new_model.is_ollama():
        new_model._ensure_extra_params_dict()
        keep_alive = normalize_keep_alive_for_tier(
            role,
            router.keep_alive_fast if role == "fast" else router.keep_alive_heavy,
        )
        new_model.extra_params["keep_alive"] = keep_alive
    enable = _resolve_enable_thinking(decision, router, role, pool_entry)
    apply_thinking_extra_params(new_model, enable)
    coder.main_model = new_model
