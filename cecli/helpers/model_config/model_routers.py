"""Router / multi-segment model-name resolution helpers.

OpenRouter-style names encode a router, an upstream vendor, and a model in one
slash-delimited name (``openrouter/z-ai/glm-5.3-flash``). The bundled metadata
usually stores the same model under its upstream provider slug
(``zai/glm-5.3-flash``), so resolving a router model needs vendor alias
expansion and a route-tail fallback.

This module owns that name-space logic; :mod:`.pipeline` keeps the metadata
loading and record-lookup chain.
"""

from __future__ import annotations

import re

from .utils import get_entry_from_raw, top_level_keys

#: Suffix segments dropped when looking for a nearby model family.
#: ``gpt-5.6-luna`` -> ``gpt-5.6`` -> ``gpt-5`` -> ``gpt``
#: ``claude-sonnet-4-5`` -> ``claude-sonnet-4`` -> ``claude-sonnet`` -> ``claude``
#: ``[^.-]`` (no dots, no hyphens) ensures exactly one trailing ``-X`` / ``.X``
#: segment is dropped per pass instead of collapsing the whole remainder.
_TRAILING_SEGMENT_RE = re.compile(r"[-.][^.-]+$")

#: Router/upstream vendor tokens that differ from the provider slug used in
#: the bundled metadata. OpenRouter-style names look like
#: ``openrouter/<vendor>/<model>``; the vendor token often needs normalizing
#: before it matches a metadata key (``z-ai`` -> ``zai``, ``google`` ->
#: ``gemini``, ...).
_VENDOR_ALIASES = {
    "z-ai": "zai",
    "z_ai": "zai",
    "z.ai": "zai",
    "x-ai": "xai",
    "x_ai": "xai",
    "x.ai": "xai",
    "mistralai": "mistral",
    "moonshotai": "moonshot",
    "meta-llama": "meta_llama",
    "metallama": "meta_llama",
    "google": "gemini",
    "cohere": "cohere_chat",
    "qwen": "dashscope",
    "xiaomi": "xiaomi_mimo",
}

_SLUG_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def candidate_keys(model_name, route, provider):
    """Ordered lookup keys: full name, same-provider families, route, bare families.

    Same-provider family candidates come before the bare route so a provider
    prefix is never silently dropped for a bare (possibly different-provider)
    record, e.g. ``github_copilot/gpt-5.6-luna`` should resolve to the
    ``github_copilot/gpt-5`` family rather than the bare ``gpt-5.6-luna``
    (openai) record.

    Multi-segment routes (``openrouter/z-ai/glm-5.3-flash``) are also expanded
    with vendor aliases (``zai/glm-5.3-flash``) and with the leading vendor
    segment dropped (``glm-5.3-flash``) so router-hosted models inherit the
    upstream model's limits and costs.
    """
    keys = []

    def add(key):
        if key and key not in keys:
            keys.append(key)

    add(model_name)
    variants = _route_variants(route)
    shortened = []

    for variant in variants:
        shortened.extend(_shorten_route(variant))

    if provider and route:
        for variant in variants:
            add(f"{provider}/{variant}")

        for candidate in shortened:
            add(f"{provider}/{candidate}")

    for variant in variants:
        add(variant)

    for candidate in shortened:
        add(candidate)

    tail = route.rsplit("/", 1)[-1] if route else ""

    for candidate in [tail, *_shorten_route(tail)]:
        add(candidate)

    return keys


def closest_route_match(sources, route):
    """Return the record whose route best matches the requested route tail.

    Cross-provider fallback for router models (``openrouter/z-ai/glm-5.3-flash``)
    when no same-provider record exists. The final route segment (the model
    name) must match case-insensitively; ties prefer the record whose provider
    is the upstream vendor token (aliases included) so ``z-ai/glm-5.3-flash``
    resolves to ``zai/glm-5.3-flash`` rather than an arbitrary rehost.
    """
    if not route or "/" not in route:
        return None

    best = None
    best_score = -1

    for source in reversed(sources):
        if source["kind"] == "dict":
            for key, record in source["data"].items():
                if not isinstance(record, dict):
                    continue

                score = _route_match_score(route, key)

                if score > best_score:
                    best_score = score
                    best = record

        else:
            for key in top_level_keys(source["text"]):
                score = _route_match_score(route, key)

                if score <= best_score:
                    continue

                record = get_entry_from_raw(source["text"], key)

                if not record:
                    continue

                best_score = score
                best = record

    return best if best_score > 0 else None


def _shorten_route(route):
    """Yield progressively shorter routes, e.g. ``gpt-5.6-luna`` -> ``gpt-5``."""
    candidates = []
    current = route

    while current:
        shortened = _TRAILING_SEGMENT_RE.sub("", current)

        if not shortened or shortened == current:
            break

        candidates.append(shortened)
        current = shortened

    return candidates


def _route_variants(route):
    """Return the route plus any vendor-alias / vendor-less variants.

    ``z-ai/glm-5.3-flash`` -> ``[z-ai/glm-5.3-flash, zai/glm-5.3-flash,
    glm-5.3-flash]``. Single-segment routes are returned unchanged.
    """
    if not route:
        return [route]

    variants = [route]
    segments = route.split("/")

    if len(segments) < 2:
        return variants

    vendor = segments[0]
    rest = "/".join(segments[1:])

    for alias in _vendor_aliases(vendor):
        variants.append(f"{alias}/{rest}")

    variants.append(rest)

    return variants


def _vendor_aliases(vendor):
    """Return normalized/aliased forms of a vendor token (never the original)."""
    token = vendor.lower()
    normalized = _SLUG_NORMALIZE_RE.sub("", token)
    candidates = [normalized]

    alias = _VENDOR_ALIASES.get(token) or _VENDOR_ALIASES.get(normalized)

    if alias:
        candidates.append(alias)

    return list(dict.fromkeys(c for c in candidates if c and c != token))


def _route_match_score(requested_route, key):
    """Score how well a metadata ``key`` matches a requested route tail.

    Returns ``-1`` unless the final route segment matches. Extra score is
    awarded for contiguous trailing segments and for an upstream vendor whose
    provider slug matches the requested vendor (``z-ai``/``zai``).
    """
    key_route = key.split("/", 1)[-1] if "/" in key else key
    requested_parts = requested_route.lower().split("/")
    key_parts = key_route.lower().split("/")

    matched = 0

    for left, right in zip(reversed(requested_parts), reversed(key_parts)):
        if _SLUG_NORMALIZE_RE.sub("", left) != _SLUG_NORMALIZE_RE.sub("", right):
            break

        matched += 1

    if matched == 0:
        return -1

    score = matched * 100
    vendor = requested_parts[-2] if len(requested_parts) >= 2 else ""

    if vendor:
        key_provider = key.split("/", 1)[0].lower() if "/" in key else ""

        if key_provider in (vendor, *_vendor_aliases(vendor)):
            score += 40

        if len(key_parts) >= 2 and key_parts[-2] in (
            vendor,
            *_vendor_aliases(vendor),
        ):
            score += 25

    return score
