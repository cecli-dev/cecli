"""
Model hopper + local LLM routing: classify prompts and pick fast vs code vs think models.

Security: only uses model names supplied in config — no runtime fetch of arbitrary models.
Hosts may register optional preload resolvers via :func:`set_backend_client_resolver`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_backend_client_resolver: Callable[[], Any] | None = None
_static_vram_bytes_resolver: Callable[[str], int | None] | None = None


def set_backend_client_resolver(fn: Callable[[], Any] | None) -> None:
    """Host hook: return active backend client for preload when none is passed explicitly."""
    global _backend_client_resolver
    _backend_client_resolver = fn


def set_static_vram_bytes_resolver(fn: Callable[[str], int | None] | None) -> None:
    """Host hook: estimate model VRAM in bytes from a bare tag (no live show API)."""
    global _static_vram_bytes_resolver
    _static_vram_bytes_resolver = fn


RouteRole = Literal["fast", "code", "think"]
RouteTier = Literal["fast", "heavy", "code", "think"]


@runtime_checkable
class OllamaClient(Protocol):
    """Protocol for an async Ollama HTTP client (preload / show)."""

    async def post_generate(self, model: str, *, keep_alive: int = -1) -> None:
        """Issue a zero-token generate to preload the model into VRAM."""
        ...

    async def show_model(self, model: str) -> dict[str, Any]:
        """Return model info (at minimum ``size`` in bytes). Empty dict on failure."""
        ...


def normalize_route_role(tier_or_role: str | None) -> RouteRole | None:
    """Map API/UI tier names to a routing role (``heavy`` → ``code``)."""
    if not tier_or_role:
        return None
    key = tier_or_role.strip().lower()
    if key == "fast":
        return "fast"
    if key in ("heavy", "code"):
        return "code"
    if key == "think":
        return "think"
    return None


def role_to_legacy_tier(role: RouteRole) -> RouteTier:
    """SSE/UI tier field: fast stays fast; code+think map to distinct tiers."""
    return role


def normalize_pool_tier(raw: str | None) -> RouteRole | None:
    if not raw:
        return None
    return normalize_route_role(raw)


# Code + think tiers keep models loaded during agent loops (keep_alive=0 → empty Ollama).
def normalize_keep_alive_for_tier(tier: RouteTier | RouteRole, value: int | str) -> int | str:
    if tier in ("heavy", "code", "think") and value in (0, "0"):
        return -1
    return value


# Per-file context bump for *display* only (routing uses message_tokens).
_FILE_TOKEN_PER_FILE = 500
_FILE_TOKEN_CAP = 2_000

# Reserve completion tokens when comparing session context to fast model window.
_FAST_CONTEXT_OUTPUT_RESERVE = 2_048

# Intent signals (case-insensitive word boundaries).
_THINK_PATTERNS = re.compile(
    r"\b("
    r"architecture|architectural|architect|refactor|rewrite|migrate|migration|"
    r"race\s+condition|deadlock|concurrency|distributed|microservice|"
    r"security|vulnerability|root\s+cause|design\s+review|"
    r"performance|scalability|profil(?:e|ing)|"
    r"from\s+scratch|greenfield|system\s+design|"
    r"analyze|analyse|debug|why\s+does|explain\s+why|investigate|"
    r"tradeoff|trade-off|compare\s+approaches|plan\s+the"
    r")\b",
    re.IGNORECASE,
)

_FAST_PATTERNS = re.compile(
    r"\b("
    r"rename|typo|whitespace|format(?:ting)?|lint|prettier|"
    r"color|colour|style|css|spacing|margin|padding|"
    r"label|tooltip|copy|wording|comment(?:s)?|"
    r"tweak|ui\s+text|button\s+text|"
    r"references?|chips?|filesystem|autocomplete|mention|"
    r"chat\s+panel|message\s+input|text\s+field|component|"
    r"like\s+we\s+have|@\s*\w"
    r")\b",
    re.IGNORECASE,
)

# "add" alone is ambiguous (UI copy vs new feature); routing uses stronger verbs only.
_CODE_TASK_STRONG = re.compile(
    r"\b(implement|fix|create|update|change|patch|write|build)\b",
    re.IGNORECASE,
)


def _parse_pool_extra_params(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict) and raw:
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) and parsed else None
    return None


def _parse_capabilities(raw: Any) -> dict[str, Any] | None:
    """Parse model capabilities from payload (dict with bool/int values)."""
    if isinstance(raw, dict) and raw:
        return dict(raw)
    return None


@dataclass
class ModelPoolEntry:
    model: str
    tier: RouteRole
    enabled: bool = True
    """Per-model LiteLLM ``think`` override; ``None`` → derive from tier."""
    enable_thinking: bool | None = None
    """Per-model LiteLLM kwargs when this hopper row is routed."""
    extra_params: dict[str, Any] | None = None
    """Priority rank within the global priority list (0 = highest). None when unset."""
    priority_rank: int | None = None
    """When True, route to the second-highest-priority model in this tier."""
    prefer_secondary: bool = False
    """Model capabilities: vision, large_context, specializations."""
    capabilities: dict[str, Any] | None = None

    @property
    def has_vision(self) -> bool:
        """True when this model supports multimodal/vision input."""
        return bool(self.capabilities and self.capabilities.get("vision"))

    @property
    def max_context(self) -> int | None:
        """Max context window size in tokens, if declared."""
        if not self.capabilities:
            return None
        raw = self.capabilities.get("max_context")
        return int(raw) if raw is not None and int(raw) > 0 else None


def resolve_tier_models(pool: list[ModelPoolEntry], tier: RouteRole) -> list[ModelPoolEntry]:
    """Return all enabled models for a tier, sorted by priority_rank (ascending = highest priority first).

    Models with priority_rank=None are sorted after those with a rank.
    """
    filtered = [e for e in pool if e.enabled and e.tier == tier]
    filtered.sort(
        key=lambda e: (
            e.priority_rank is None,
            e.priority_rank if e.priority_rank is not None else 0,
        )
    )
    return filtered


def pick_tier_model(
    pool: list[ModelPoolEntry],
    tier: RouteRole,
    *,
    resident_models: set[str] | None = None,
    require_vision: bool = False,
    context_tokens: int | None = None,
    prefer_warm: bool = False,
) -> tuple[str, bool]:
    """Pick the model to route to for a tier.

    Returns (model_name, is_swap).
    Respects capability requirements, context limits, residency preference,
    prefer_secondary flag, and priority ordering.

    Fallback logic (in order):
    1. If require_vision: filter to vision-capable models. If none, fall through to all.
    2. If context_tokens set: filter out models whose max_context < context_tokens. If none pass, use all.
    3. If prefer_warm and resident_models: prefer resident models (but don't require).
    4. Apply prefer_secondary / priority ordering on the remaining candidates.
    """
    models = resolve_tier_models(pool, tier)
    if not models:
        raise ValueError(f"No enabled models available for tier '{tier}'")

    candidates = models

    # --- Capability filter: vision ---
    if require_vision:
        vision_models = [m for m in candidates if m.has_vision]
        if vision_models:
            candidates = vision_models

    # --- Context window filter ---
    if context_tokens is not None and context_tokens > 0:
        fits = [m for m in candidates if m.max_context is None or m.max_context >= context_tokens]
        if fits:
            candidates = fits
        # If none fit, keep all candidates (best-effort routing)

    # --- Residency preference (soft — prefer warm, don't require) ---
    if prefer_warm and resident_models and len(candidates) > 1:
        warm = [m for m in candidates if m.model in resident_models]
        if warm:
            candidates = warm

    # --- Priority / prefer_secondary selection ---
    prefer_secondary = any(m.prefer_secondary for m in candidates)
    if prefer_secondary and len(candidates) >= 2:
        chosen = candidates[1]
    else:
        chosen = candidates[0]

    # Determine is_swap: True when model not in resident_models
    is_swap = False
    if resident_models is not None and chosen.model not in resident_models:
        is_swap = True

    return (chosen.model, is_swap)


async def preload_priority_list(
    priority_list: list[str],
    *,
    ollama_client: Any | None = None,
    vram_budget_bytes: int | None = None,
    backend_client: Any | None = None,
) -> list[str]:
    """Preload models in priority order, respecting VRAM budget.

    Iterates ``priority_list`` from index 0 (highest priority) onward. For each model:
    - If ``vram_budget_bytes`` is set, fetches model size info and checks cumulative VRAM.
      When the budget would be exceeded, logs deferred models and stops.
    - Attempts to preload via ``backend_client``, optional host resolver, or ``ollama_client``.
    - On success, appends to the returned list.
    - On failure, logs the error, skips the model, and continues with the next.

    Returns the list of successfully preloaded model tags.
    """
    preloaded: list[str] = []
    cumulative_vram: int = 0

    for idx, model_tag in enumerate(priority_list):
        tag = model_tag.strip()
        if not tag:
            continue

        raw_tag = _strip_ollama_prefix(tag)

        model_size: int | None = None
        if vram_budget_bytes is not None:
            model_size = await _get_model_size_for_budget(raw_tag, ollama_client=ollama_client)
            if model_size is not None:
                if cumulative_vram + model_size > vram_budget_bytes:
                    deferred = [t.strip() for t in priority_list[idx:] if t.strip()]
                    logger.info(
                        "VRAM budget exceeded (%.1f MB used of %.1f MB). " "Deferring models: %s",
                        cumulative_vram / (1024 * 1024),
                        vram_budget_bytes / (1024 * 1024),
                        deferred,
                    )
                    break

        if await _preload_single_model(
            raw_tag,
            ollama_client=ollama_client,
            backend_client=backend_client,
        ):
            preloaded.append(tag)
            if model_size is not None:
                cumulative_vram += model_size

    return preloaded


async def warmup_keep_alive(
    priority_list: list[str],
    *,
    ollama_client: Any | None = None,
    backend_client: Any | None = None,
) -> list[str]:
    """Send keep-alive requests in priority order to refresh model TTLs.

    Iterates ``priority_list`` from index 0 (highest priority) onward. For each model:
    - Strips the ``ollama_chat/`` or ``ollama/`` prefix for backend API calls.
    - Sends a keep-alive/preload request via the active backend (or legacy client).
    - On success, appends to the returned list.
    - On failure, logs the error, skips the model, and continues with the next.

    Returns the list of model tags that were successfully kept alive.
    """
    kept_alive: list[str] = []

    for model_tag in priority_list:
        tag = model_tag.strip()
        if not tag:
            continue

        raw_tag = _strip_ollama_prefix(tag)

        if await _preload_single_model(
            raw_tag,
            ollama_client=ollama_client,
            backend_client=backend_client,
        ):
            kept_alive.append(tag)
        else:
            logger.error("Keep-alive warmup failed for model '%s'", tag)

    return kept_alive


def _strip_ollama_prefix(tag: str) -> str:
    """Remove ``ollama_chat/`` or ``ollama/`` prefix from a model tag."""
    if tag.startswith("ollama_chat/"):
        return tag[len("ollama_chat/") :]
    if tag.startswith("ollama/"):
        return tag[len("ollama/") :]
    return tag


async def _get_model_size(ollama_client: Any, raw_tag: str) -> int | None:
    """Attempt to get model size in bytes via ollama show. Returns None on failure."""
    try:
        info = await ollama_client.show_model(raw_tag)
        size = info.get("size") if isinstance(info, dict) else None
        if isinstance(size, (int, float)) and size > 0:
            return int(size)
        return None
    except Exception:
        return None


def _estimate_model_size_bytes(raw_tag: str) -> int | None:
    """Static VRAM estimate via optional host resolver (bytes)."""
    if _static_vram_bytes_resolver is None:
        return None
    return _static_vram_bytes_resolver(raw_tag)


async def _get_model_size_for_budget(
    raw_tag: str,
    *,
    ollama_client: Any | None,
) -> int | None:
    """Resolve model size for VRAM budgeting (Ollama show or static metadata)."""
    if ollama_client is not None:
        return await _get_model_size(ollama_client, raw_tag)
    return _estimate_model_size_bytes(raw_tag)


async def _preload_single_model(
    raw_tag: str,
    *,
    ollama_client: Any | None = None,
    backend_client: Any | None = None,
) -> bool:
    """Preload one model via Ollama client or host-injected backend client."""
    if ollama_client is not None:
        try:
            await ollama_client.post_generate(raw_tag, keep_alive=-1)
            return True
        except Exception as exc:
            logger.error("Preload failed for model '%s': %s", raw_tag, exc)
            return False

    client = backend_client
    if client is None and _backend_client_resolver is not None:
        client = _backend_client_resolver()
    if client is None:
        return False
    try:
        loaded = await client.preload_models([raw_tag])
        return raw_tag in loaded
    except Exception as exc:
        logger.error("Preload failed for model '%s': %s", raw_tag, exc)
        return False


def find_pool_entry(
    pool: list[ModelPoolEntry],
    model_name: str,
    role: RouteRole,
) -> ModelPoolEntry | None:
    """Match hopper row for a routed model (empty code id → session code tier)."""
    target = (model_name or "").strip()
    for entry in pool:
        if not entry.enabled:
            continue
        name = entry.model.strip()
        if name and name != target:
            continue
        if name == target or (not name and role == "code"):
            return entry
    return None


def thinking_for_pool_tier(tier: RouteRole) -> bool:
    return tier == "think"


def resolve_pool_entry_thinking(entry: ModelPoolEntry) -> bool:
    if entry.enable_thinking is not None:
        return entry.enable_thinking
    return thinking_for_pool_tier(entry.tier)


def pool_thinking_for_model(model_name: str, pool: list[ModelPoolEntry]) -> bool | None:
    """Explicit hopper ``enable_thinking`` for a resolved model id."""
    target = (model_name or "").strip()
    if not target:
        return None
    for entry in pool:
        if not entry.enabled:
            continue
        name = entry.model.strip()
        if name and name == target:
            return resolve_pool_entry_thinking(entry)
    return None


@dataclass
class ResolvedModelPool:
    fast: str
    code: str
    think: str | None


def resolve_model_pool(
    pool: list[ModelPoolEntry],
    *,
    session_code: str,
    fallback_fast: str = "",
    fallback_code: str | None = None,
    fallback_think: str | None = None,
) -> ResolvedModelPool:
    """Pick first enabled fast/code/think from hopper order."""
    fast = fallback_fast.strip()
    code = (fallback_code or "").strip() or session_code
    think = (fallback_think or "").strip() or None
    for entry in pool:
        if not entry.enabled:
            continue
        name = entry.model.strip()
        if entry.tier == "fast" and name and not fast:
            fast = name
        elif entry.tier == "code":
            if name:
                code = name
            else:
                code = session_code
        elif entry.tier == "think" and name and not think:
            think = name
    return ResolvedModelPool(fast=fast, code=code, think=think)


def pool_prefers_think(pool: list[ModelPoolEntry]) -> bool:
    """True when the first enabled think entry appears before the first enabled code entry.

    This reflects the user dragging think to the top of the hopper (highest priority).
    """
    think_idx: int | None = None
    code_idx: int | None = None
    for i, entry in enumerate(pool):
        if not entry.enabled:
            continue
        if entry.tier == "think" and entry.model.strip() and think_idx is None:
            think_idx = i
        elif entry.tier == "code" and code_idx is None:
            code_idx = i
    if think_idx is None or code_idx is None:
        return False
    return think_idx < code_idx


def _parse_env_bool(key: str) -> bool | None:
    """Parse CODE_THINK / FAST_THINK from process env or local-llm config files."""
    # Check process env first
    val = os.environ.get(key, "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    # Fall back to optional local-llm env files on disk
    return _read_local_llm_env_bool(key)


def _local_llm_env_paths() -> list:
    """Candidate env files for tier think flags (last file wins)."""
    from pathlib import Path

    paths: list[Path] = []
    explicit = os.environ.get("CECLI_LLM_ENV", "").strip()
    if explicit:
        paths.append(Path(explicit))
    home = Path.home()
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    config_home = Path(xdg) if xdg else home / ".config"
    paths.append(config_home / "local-llm" / "env")
    repo_root = os.environ.get("CECLI_REPO_ROOT", "").strip()
    if repo_root:
        paths.append(Path(repo_root) / "local-llm.env")
    paths.append(Path.cwd() / "local-llm.env")
    return paths


def _read_local_llm_env_bool(key: str) -> bool | None:
    """Read a key from the local-llm env file chain (last file wins)."""

    result: bool | None = None
    for p in _local_llm_env_paths():
        try:
            if not p.is_file():
                continue
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() != key:
                    continue
                v = v.strip().strip("'\"").lower()
                if v in ("1", "true", "yes", "on"):
                    result = True
                elif v in ("0", "false", "no", "off"):
                    result = False
        except OSError:
            continue
    return result


def _apply_env_think_to_pool(pool: list[ModelPoolEntry]) -> None:
    """Override pool enable_thinking from per-slot or tier-level env vars.

    Resolution order (highest priority first):
      1. Per-slot: ``CODE_MODEL_THINK=1`` (slot 0), ``CODE_MODEL_1_THINK=1`` (slot 1)
      2. Tier-level: ``CODE_THINK=1`` (applies to all slots in tier without per-slot override)

    The frontend may send stale localStorage values; the env file is authoritative.
    """
    code_think = _parse_env_bool("CODE_THINK")
    fast_think = _parse_env_bool("FAST_THINK")

    # Per-slot overrides: {TIER}_MODEL_THINK (slot 0), {TIER}_MODEL_{N}_THINK (slots 1-9)
    slot_think: dict[tuple[str, int], bool | None] = {}
    for tier_prefix in ("FAST", "CODE", "THINK"):
        # Slot 0: {TIER}_MODEL_THINK
        val = _parse_env_bool(f"{tier_prefix}_MODEL_THINK")
        if val is not None:
            slot_think[(tier_prefix.lower(), 0)] = val
        # Slots 1-9: {TIER}_MODEL_{N}_THINK
        for n in range(1, 10):
            val = _parse_env_bool(f"{tier_prefix}_MODEL_{n}_THINK")
            if val is not None:
                slot_think[(tier_prefix.lower(), n)] = val

    if code_think is None and fast_think is None and not slot_think:
        return

    for entry in pool:
        if not entry.enabled:
            continue
        # Determine slot index from priority_rank or default to 0
        slot_idx = entry.priority_rank if entry.priority_rank is not None else 0
        tier = entry.tier

        # Per-slot override takes priority
        per_slot = slot_think.get((tier, slot_idx))
        if per_slot is not None:
            entry.enable_thinking = per_slot
        elif tier == "code" and code_think is not None:
            entry.enable_thinking = code_think
        elif tier == "fast" and fast_think is not None:
            entry.enable_thinking = fast_think


@dataclass
class RouteTurnContext:
    agent_cmd: bool = False
    implement_turn: bool = False
    inject_todo_spec: bool = False
    spec_gen_turn: bool = False
    exploration_aborted: bool = False


_BACKEND_PROVIDER_PREFIXES: dict[str, str] = {
    "ollama": "ollama_chat/",
    "lmstudio": "openai/",
    "vllm": "openai/",
    "tgi": "openai/",
    "llamacpp": "openai/",
    "mlx-lm": "openai/",
}


def resolve_provider_prefix(backend: str) -> str:
    """Map a backend name to its LiteLLM provider prefix.

    Defaults to ``ollama_chat/`` for unknown backends.
    """
    return _BACKEND_PROVIDER_PREFIXES.get((backend or "").strip().lower(), "ollama_chat/")


def inject_backend_extra_params(
    backend: str, extra_params: dict[str, object] | None
) -> dict[str, object]:
    """Merge ``LITELLM_EXTRA_PARAMS`` for non-Ollama backends.

    Ollama uses its own env wiring; other backends may need auth headers or base URLs
    via JSON in ``LITELLM_EXTRA_PARAMS``. Existing *extra_params* keys are preserved.
    """
    merged: dict[str, object] = dict(extra_params or {})
    name = (backend or "").strip().lower()
    if name in ("", "ollama"):
        return merged
    raw = os.environ.get("LITELLM_EXTRA_PARAMS", "").strip()
    if not raw:
        return merged
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LITELLM_EXTRA_PARAMS is not valid JSON — ignoring for backend %s", name)
        return merged
    if isinstance(parsed, dict):
        merged.update(parsed)
    return merged


@dataclass
class ModelRouterConfig:
    enabled: bool = False
    fast_model: str = ""
    heavy_model: str | None = None
    code_model: str | None = None
    think_model: str | None = None
    model_pool: list[ModelPoolEntry] = field(default_factory=list)
    token_fast_max: int = 4_096
    token_heavy_min: int = 12_000
    keep_alive_fast: int | str = 300
    keep_alive_heavy: int | str = -1
    escalate_on_failure: bool = True
    prefer_think: bool = False
    """Global priority list of model tags in priority order (index 0 = highest)."""
    priority_list: list[str] = field(default_factory=list)
    backend: str = "ollama"
    provider_prefix: str = "ollama_chat/"

    def __post_init__(self) -> None:
        self.keep_alive_heavy = normalize_keep_alive_for_tier("code", self.keep_alive_heavy)
        if not self.code_model and self.heavy_model:
            self.code_model = self.heavy_model
        self.provider_prefix = resolve_provider_prefix(self.backend)

    @property
    def resolved_code_model(self) -> str:
        return (self.code_model or self.heavy_model or self.fast_model or "").strip()

    @property
    def resolved_think_model(self) -> str | None:
        name = (self.think_model or "").strip()
        return name or None

    @classmethod
    def from_payload(cls, raw: dict[str, Any] | None) -> ModelRouterConfig | None:
        if not raw:
            return None
        enabled = bool(raw.get("enabled"))
        if not enabled:
            return cls(enabled=False)
        pool_raw = raw.get("model_pool") or []
        pool: list[ModelPoolEntry] = []
        if isinstance(pool_raw, list):
            for item in pool_raw:
                if not isinstance(item, dict):
                    continue
                tier = normalize_pool_tier(str(item.get("tier") or ""))
                if tier is None:
                    continue
                raw_rank = item.get("priority_rank")
                priority_rank: int | None = int(raw_rank) if raw_rank is not None else None
                pool.append(
                    ModelPoolEntry(
                        model=str(item.get("model") or ""),
                        tier=tier,
                        enabled=bool(item.get("enabled", True)),
                        enable_thinking=(
                            item["enable_thinking"]
                            if item.get("enable_thinking") is not None
                            else None
                        ),
                        extra_params=_parse_pool_extra_params(item.get("extra_params")),
                        priority_rank=priority_rank,
                        prefer_secondary=bool(item.get("prefer_secondary", False)),
                        capabilities=_parse_capabilities(item.get("capabilities")),
                    )
                )
        fallback_fast = str(raw.get("fast_model") or "").strip()
        fallback_code = str(raw.get("code_model") or raw.get("heavy_model") or "").strip() or None
        fallback_think = str(raw.get("think_model") or "").strip() or None
        session_code = fallback_code or fallback_fast or ""
        if pool:
            resolved = resolve_model_pool(
                pool,
                session_code=session_code or fallback_fast,
                fallback_fast=fallback_fast,
                fallback_code=fallback_code,
                fallback_think=fallback_think,
            )
            fast, code, think = resolved.fast, resolved.code, resolved.think
        else:
            fast = fallback_fast
            code = fallback_code or fallback_fast
            think = fallback_think
        if not fast:
            return None
        # Override pool enable_thinking from env (CODE_THINK / FAST_THINK) —
        # the frontend may send stale localStorage values.
        _apply_env_think_to_pool(pool)
        # Parse global priority list from payload (list of model tag strings).
        priority_list_raw = raw.get("priority_list")
        priority_list: list[str] = []
        if isinstance(priority_list_raw, list):
            for tag in priority_list_raw:
                s = str(tag).strip()
                if s:
                    priority_list.append(s)
        return cls(
            enabled=True,
            fast_model=fast,
            heavy_model=code or None,
            code_model=code or None,
            think_model=think,
            model_pool=pool,
            token_fast_max=int(raw.get("token_fast_max") or 4_096),
            token_heavy_min=int(raw.get("token_heavy_min") or 12_000),
            keep_alive_fast=raw.get("keep_alive_fast", 300),
            keep_alive_heavy=normalize_keep_alive_for_tier("code", raw.get("keep_alive_heavy", -1)),
            escalate_on_failure=bool(raw.get("escalate_on_failure", True)),
            prefer_think=bool(
                raw.get("prefer_think")
                if raw.get("prefer_think") is not None
                else pool_prefers_think(pool)
            ),
            priority_list=priority_list,
        )


@dataclass
class RouteDecision:
    tier: RouteTier
    model_name: str
    estimated_tokens: int
    reasons: list[str] = field(default_factory=list)
    role: RouteRole = "code"
    enable_thinking: bool | None = None
    """Priority rank of the chosen model within the global priority list (0 = highest). None for single-model tiers."""
    priority_rank: int | None = None
    """Snapshot of the config's priority_list at decision time. None when not applicable."""
    priority_list_snapshot: list[str] | None = None
    """True when the chosen model is not currently resident in Ollama memory (cold-start swap)."""
    swap: bool = False


def thinking_for_role(
    role: RouteRole,
    model_name: str,
    *,
    pool: list[ModelPoolEntry] | None = None,
) -> bool | None:
    """Per-model LiteLLM ``think`` for this route (hopper entry overrides role)."""
    if pool:
        explicit = pool_thinking_for_model(model_name, pool)
        if explicit is not None:
            return explicit
    if role == "think":
        return True
    if role in ("fast", "code"):
        return False
    return None


def estimate_message_tokens(
    user_message: str,
    *,
    message_token_count: int | None = None,
) -> int:
    """Tokens from the user message only — used for routing."""
    if message_token_count is not None and message_token_count > 0:
        return message_token_count
    return max(len(user_message) // 4, 32)


def estimate_prompt_tokens(
    user_message: str,
    *,
    files_in_chat: int = 0,
    message_token_count: int | None = None,
) -> int:
    """Rough context size for UI (message + capped file bump). Not used for tier choice."""
    base = estimate_message_tokens(user_message, message_token_count=message_token_count)
    file_part = min(max(files_in_chat, 0) * _FILE_TOKEN_PER_FILE, _FILE_TOKEN_CAP)
    return base + file_part


@lru_cache(maxsize=64)
def lookup_model_max_input_tokens(model_name: str) -> int | None:
    """Cecli/LiteLLM metadata for a model id (e.g. ``ollama_chat/deepseek-coder:6.7b``)."""
    name = (model_name or "").strip()
    if not name:
        return None
    try:
        from cecli.models import model_info_manager

        info = model_info_manager.get_model_info(name) or {}
        raw = info.get("max_input_tokens") or 0
        return int(raw) if int(raw) > 0 else None
    except Exception:
        return None


def context_exceeds_fast_model_limit(
    context_tokens: int,
    fast_model_name: str,
    *,
    fast_max_input: int | None = None,
    output_reserve: int = _FAST_CONTEXT_OUTPUT_RESERVE,
) -> tuple[bool, int | None]:
    """
    True when the live session context cannot fit the fast model (plus completion reserve).

    ``fast_max_input`` overrides metadata lookup (tests).
    """
    if context_tokens <= 0:
        return False, None
    limit = fast_max_input
    if limit is None:
        limit = lookup_model_max_input_tokens(fast_model_name)
    if limit is None:
        return False, None
    return context_tokens + output_reserve > limit, limit


def _pick_think_model(
    router: ModelRouterConfig,
    *,
    reasons: list[str],
) -> tuple[RouteRole, str]:
    think = router.resolved_think_model
    if think:
        return "think", think
    reasons.append("think_unconfigured→code")
    return "code", router.resolved_code_model


def _has_multi_model_tier(pool: list[ModelPoolEntry], tier: RouteRole) -> bool:
    """True when the pool has multiple enabled entries for `tier` with priority_rank set."""
    ranked = [e for e in pool if e.enabled and e.tier == tier and e.priority_rank is not None]
    return len(ranked) >= 2


def _apply_multi_model_routing(
    role: RouteRole,
    model_name: str,
    *,
    router: ModelRouterConfig,
    display_tokens: int,
    reasons: list[str],
    resident_models: set[str] | None = None,
    require_vision: bool = False,
    context_tokens: int | None = None,
) -> RouteDecision:
    """Wrap _finish_decision with multi-model tier routing when applicable.

    If the resolved tier has multiple enabled models with priority_rank set,
    use pick_tier_model to select the model; otherwise fall back to the
    single-model behavior (the model_name already determined by classify_prompt).
    """
    pool = router.model_pool
    priority_rank: int | None = None
    priority_list_snapshot: list[str] | None = None
    swap = False

    if pool and _has_multi_model_tier(pool, role):
        chosen_model, is_swap = pick_tier_model(
            pool,
            role,
            resident_models=resident_models,
            require_vision=require_vision,
            context_tokens=context_tokens,
            prefer_warm=True,
        )
        model_name = chosen_model
        swap = is_swap
        # Find the priority_rank of the chosen model from the pool entry
        for entry in pool:
            if entry.enabled and entry.model == chosen_model and entry.tier == role:
                priority_rank = entry.priority_rank
                break
        # Snapshot the config's priority_list if non-empty
        if router.priority_list:
            priority_list_snapshot = list(router.priority_list)

        # Add reason if vision or context fallback was used
        if require_vision:
            reasons.append("vision_required")
        if context_tokens and context_tokens > 0:
            # Check if we fell through to a different model than the top priority
            top_models = resolve_tier_models(pool, role)
            if top_models and chosen_model != top_models[0].model:
                reasons.append(f"context_fallback:{chosen_model.split('/')[-1]}")

    return _finish_decision(
        role,
        model_name,
        router=router,
        display_tokens=display_tokens,
        reasons=reasons,
        priority_rank=priority_rank,
        priority_list_snapshot=priority_list_snapshot,
        swap=swap,
    )


def _finish_decision(
    role: RouteRole,
    model_name: str,
    *,
    router: ModelRouterConfig,
    display_tokens: int,
    reasons: list[str],
    priority_rank: int | None = None,
    priority_list_snapshot: list[str] | None = None,
    swap: bool = False,
) -> RouteDecision:
    return RouteDecision(
        tier=role_to_legacy_tier(role),
        role=role,
        model_name=model_name,
        estimated_tokens=display_tokens,
        reasons=reasons,
        enable_thinking=thinking_for_role(role, model_name, pool=router.model_pool),
        priority_rank=priority_rank,
        priority_list_snapshot=priority_list_snapshot,
        swap=swap,
    )


def classify_prompt(
    user_message: str,
    *,
    message_tokens: int,
    router: ModelRouterConfig,
    code_model_name: str | None = None,
    think_model_name: str | None = None,
    context_tokens: int | None = None,
    force_tier: RouteTier | None = None,
    turn: RouteTurnContext | None = None,
    # Back-compat for tests calling estimated_tokens=
    estimated_tokens: int | None = None,
    heavy_model_name: str | None = None,
    fast_max_input: int | None = None,
    resident_models: set[str] | None = None,
    has_images: bool = False,
) -> RouteDecision:
    if estimated_tokens is not None and context_tokens is None:
        context_tokens = estimated_tokens
    display_tokens = context_tokens if context_tokens is not None else message_tokens
    ctx = turn or RouteTurnContext()
    code = (code_model_name or heavy_model_name or router.resolved_code_model).strip()
    think = (think_model_name or router.resolved_think_model or "").strip() or None

    # Common kwargs for all _apply_multi_model_routing calls in this function.
    def _route(role: RouteRole, model: str, *, reasons: list[str]) -> RouteDecision:
        return _apply_multi_model_routing(
            role,
            model,
            router=router,
            display_tokens=display_tokens,
            reasons=reasons,
            resident_models=resident_models,
            require_vision=has_images,
            context_tokens=context_tokens,
        )

    forced = normalize_route_role(force_tier)
    if forced:
        if forced == "think" and not think:
            forced = "code"
        model = {
            "fast": router.fast_model,
            "code": code,
            "think": think or code,
        }[forced]
        return _route(forced, model, reasons=[f"forced:{forced}"])

    reasons: list[str] = []

    if ctx.implement_turn or ctx.agent_cmd:
        tag = "implement_turn" if ctx.implement_turn else "agent_cmd"
        reasons.append(tag)
        return _route("code", code, reasons=reasons)

    if ctx.inject_todo_spec and not ctx.implement_turn:
        reasons.append("inject_todo_spec")
        role, model = _pick_think_model(router, reasons=reasons)
        return _route(role, model, reasons=reasons)

    if ctx.spec_gen_turn:
        reasons.append("spec_gen")
        role, model = _pick_think_model(router, reasons=reasons)
        return _route(role, model, reasons=reasons)

    if ctx.exploration_aborted:
        reasons.append("exploration_aborted")
        role, model = _pick_think_model(router, reasons=reasons)
        return _route(role, model, reasons=reasons)

    if re.search(r"/agent\b", user_message, re.IGNORECASE):
        reasons.append("slash:/agent")
        return _route("code", code, reasons=reasons)

    if context_tokens is not None and context_tokens > 0:
        exceeds_fast, fast_limit = context_exceeds_fast_model_limit(
            context_tokens, router.fast_model, fast_max_input=fast_max_input
        )
        if exceeds_fast and fast_limit is not None:
            # Check if any fast-tier model in the pool can handle this context
            # (multi-model: a larger-context fast model may fit)
            pool = router.model_pool
            if pool:
                fast_models = resolve_tier_models(pool, "fast")
                fast_fits = [
                    m
                    for m in fast_models
                    if m.max_context is not None and m.max_context >= context_tokens
                ]
                if fast_fits:
                    # A fast model with sufficient context exists — stay in fast tier
                    reasons.append(
                        f"context_tokens>={fast_limit - _FAST_CONTEXT_OUTPUT_RESERVE} "
                        f"(fast_max={fast_limit}) but fast pool has larger model"
                    )
                    return _route("fast", fast_fits[0].model, reasons=reasons)

            reasons.append(
                f"context_tokens>={fast_limit - _FAST_CONTEXT_OUTPUT_RESERVE} "
                f"(fast_max={fast_limit})"
            )
            if router.prefer_think and think:
                reasons.append("prefer_think")
                return _route("think", think, reasons=reasons)
            return _route("code", code, reasons=reasons)

    if message_tokens >= router.token_heavy_min:
        reasons.append(f"msg_tokens>={router.token_heavy_min}")
        if _CODE_TASK_STRONG.search(user_message) and not router.prefer_think:
            return _route("code", code, reasons=reasons)
        role, model = _pick_think_model(router, reasons=reasons)
        return _route(role, model, reasons=reasons)

    think_hit = _THINK_PATTERNS.search(user_message)
    fast_hit = _FAST_PATTERNS.search(user_message)
    code_task = _CODE_TASK_STRONG.search(user_message) is not None

    if think_hit:
        reasons.append(f"keyword:{think_hit.group(0).lower()}")
        role, model = _pick_think_model(router, reasons=reasons)
        return _route(role, model, reasons=reasons)

    if fast_hit and not router.prefer_think:
        reasons.append(f"keyword:{fast_hit.group(0).lower()}")
        return _route("fast", router.fast_model, reasons=reasons)

    if code_task:
        reasons.append("code_task")
        if router.prefer_think and think:
            reasons.append("prefer_think")
            return _route("think", think, reasons=reasons)
        return _route("code", code, reasons=reasons)

    if message_tokens < router.token_fast_max:
        reasons.append(f"msg_tokens<{router.token_fast_max}")
        if router.prefer_think and think:
            reasons.append("prefer_think")
            return _route("think", think, reasons=reasons)
        return _route("fast", router.fast_model, reasons=reasons)

    reasons.append("default_code")
    if router.prefer_think and think:
        reasons.append("prefer_think")
        return _route("think", think, reasons=reasons)
    return _route("code", code, reasons=reasons)


_CONTEXT_LIMIT_RE = re.compile(
    r"exceeds the\s+[\d,]+\s+token limit",
    re.IGNORECASE,
)


def should_escalate_fast_turn(
    decision: RouteDecision,
    *,
    router: ModelRouterConfig,
    user_message: str,
    edited_files: list[str],
    assistant_text: str,
    had_tool_error: bool = False,
    tool_error_text: str = "",
) -> bool:
    role = decision.role if decision.role else normalize_route_role(decision.tier) or "code"
    if not router.escalate_on_failure or role != "fast":
        return False
    if edited_files:
        return False
    if had_tool_error and _CONTEXT_LIMIT_RE.search(tool_error_text):
        return True
    if had_tool_error:
        return _CODE_TASK_STRONG.search(user_message) is not None
    if len(assistant_text.strip()) > 400:
        return False
    if not _CODE_TASK_STRONG.search(user_message):
        return False
    return True


def should_escalate_code_turn(
    decision: RouteDecision,
    *,
    router: ModelRouterConfig,
    user_message: str,
    edited_files: list[str],
    assistant_text: str,
    had_tool_error: bool = False,
) -> bool:
    """Offer think tier when code model stalled on a reasoning-heavy prompt."""
    role = decision.role if decision.role else normalize_route_role(decision.tier) or "code"
    if not router.escalate_on_failure or role != "code":
        return False
    if not router.resolved_think_model:
        return False
    if edited_files:
        return False
    if had_tool_error and _THINK_PATTERNS.search(user_message):
        return True
    if _THINK_PATTERNS.search(user_message) and len(assistant_text.strip()) < 400:
        return True
    return False


def escalation_target(decision: RouteDecision | None) -> RouteRole:
    """Next tier when auto-escalating after a failed attempt."""
    if decision is None:
        return "code"
    role = decision.role if decision.role else normalize_route_role(decision.tier) or "code"
    if role == "fast":
        return "code"
    if role == "code":
        return "think"
    return "code"
