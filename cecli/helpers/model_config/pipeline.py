"""Metadata-driven model config pipeline.

This module mirrors the request pipeline in ``cecli/helpers/requests.py``:
``get_default_config`` feeds a small context dict through a chain of step
functions, each of which transforms the context and returns it.

Like ``cecli/models.py``, user-supplied metadata files are scanned as raw
JSON strings (one entry at a time) instead of being ``json.loads``-ed
wholesale, so a lookup never materializes a large metadata dict in memory.
The small bundled ``model-metadata.json`` default is parsed once and cached
so lookups against it are O(1) rather than re-scanning the raw text per key.
"""

from __future__ import annotations

import importlib.resources as importlib_resources
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from cecli.helpers.config_utils import deep_merge

from .agent import derive_agent_config
from .api import derive_api_config
from .formatters.reasoning import format_reasoning
from .formatters.thinking import format_thinking
from .llm import derive_llm_config
from .utils import get_entry_from_raw, top_level_keys

RESOURCE_FILE = "model-metadata.json"

#: Suffix segments dropped when looking for a nearby model family.
#: ``gpt-5.6-luna`` -> ``gpt-5.6`` -> ``gpt-5`` -> ``gpt``
#: ``claude-sonnet-4-5`` -> ``claude-sonnet-4`` -> ``claude-sonnet`` -> ``claude``
#: ``[^.-]`` (no dots, no hyphens) ensures exactly one trailing ``-X`` / ``.X``
#: segment is dropped per pass instead of collapsing the whole remainder.
_TRAILING_SEGMENT_RE = re.compile(r"[-.][^.-]+$")

#: Lazily loaded raw text of the bundled metadata file (never json.loads-ed).
_BUNDLED_RAW_CACHE: Optional[str] = None

#: Parsed bundled metadata dict, cached once so bundled lookups are O(1)
#: instead of re-scanning the raw JSON text for each candidate key.
_BUNDLED_JSON_CACHE: Optional[Dict[str, Any]] = None

MetadataSource = Union[str, Path, Dict[str, Any]]


class ModelConfigPipeline:
    """Chain a model name and metadata sources through the config steps."""

    def __init__(self, metadata_files: Optional[List[MetadataSource]] = None) -> None:
        self.metadata_files = metadata_files

    def get_default_config(
        self, model_name: str, metadata_files: Optional[List[MetadataSource]] = None
    ) -> Dict[str, Any]:
        """Return the ``{api, llm, agent}`` default config for ``model_name``.

        Args:
            model_name: Fully qualified model name, e.g. ``openai/gpt-5``.
            metadata_files: Optional list of JSON file paths, raw JSON strings,
                or already-parsed metadata dicts. Defaults to the bundled
                ``cecli/resources/model-metadata.json``.

        Returns:
            A dict with ``api``, ``llm`` and ``agent`` blocks in the same shape
            as the ``model-overrides`` entries of ``.cecli.conf.yml``.
        """
        if metadata_files is None:
            metadata_files = self.metadata_files

        context = dict(model_name=model_name, metadata_files=metadata_files)
        context = _split_model_name(context)
        context = _load_metadata(context)
        context = _find_model_record(context)
        context = _build_config(context)
        return context["config"]


def get_default_config(
    model_name: str, metadata_files: Optional[List[MetadataSource]] = None
) -> Dict[str, Any]:
    """Convenience wrapper around a default :class:`ModelConfigPipeline`."""
    return ModelConfigPipeline().get_default_config(model_name, metadata_files)


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def _split_model_name(context):
    """Split the model name into (provider, route) on the first slash."""
    model = context["model_name"]
    provider, route = None, model

    if "/" in model:
        provider, route = model.split("/", 1)

    context["provider"] = provider
    context["route"] = route
    return context


def _load_metadata(context):
    """Normalize the metadata sources into scan-able source dicts."""
    files = context["metadata_files"]

    if files is None:
        context["sources"] = [{"kind": "dict", "data": _bundled_metadata()}]
        return context

    context["sources"] = [_normalize_source(source) for source in _as_list(files)]
    return context


def _find_model_record(context):
    """Resolve the metadata record for the model (exact or closest match)."""
    context["record"] = _find_record(
        context["sources"],
        context["model_name"],
        context["provider"],
        context["route"],
    )
    return context


def _build_config(context):
    """Derive the api/llm/agent blocks from the resolved metadata record."""
    provider = context["provider"]
    route = context["route"]
    record = context["record"]
    llm = derive_llm_config(provider, route, record)
    api = derive_api_config(provider, route, record)
    agent = derive_agent_config(provider, route, record)

    if llm.get("mode") == "responses":
        # Responses-mode models do not use sampling temperature, and reasoning
        # is returned via the encrypted content path rather than stored. Deep
        # merge so an existing extra_body "include" list is combined, not
        # replaced.
        agent["use_temperature"] = False
        api["extra_body"] = deep_merge(
            api.get("extra_body", {}),
            {"store": False, "include": ["reasoning.encrypted_content"]},
        )

    context["config"] = {
        "api": api,
        "llm": llm,
        "agent": agent,
        "helpers": {
            "format_reasoning": format_reasoning(provider, route, record),
            "format_thinking": format_thinking(provider, route, record),
        },
    }
    return context


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _bundled_metadata_raw() -> str:
    """Return the raw text of the packaged metadata file (cached, not parsed)."""
    global _BUNDLED_RAW_CACHE

    if _BUNDLED_RAW_CACHE is None:
        try:
            resource = importlib_resources.files("cecli.resources").joinpath(RESOURCE_FILE)
            _BUNDLED_RAW_CACHE = resource.read_text()

        except Exception:
            _BUNDLED_RAW_CACHE = ""

    return _BUNDLED_RAW_CACHE


def _bundled_metadata() -> Dict[str, Any]:
    """Return the parsed bundled metadata dict, cached after the first load.

    The raw text is kept for callers that only need a single record; the
    parsed dict makes lookups against the bundled default O(1) instead of
    re-scanning the raw JSON string once per candidate key.
    """
    global _BUNDLED_JSON_CACHE

    if _BUNDLED_JSON_CACHE is None:
        try:
            parsed = json.loads(_bundled_metadata_raw())
            _BUNDLED_JSON_CACHE = parsed if isinstance(parsed, dict) else {}

        except (ValueError, TypeError):
            _BUNDLED_JSON_CACHE = {}

    return _BUNDLED_JSON_CACHE


def _as_list(value):
    """Normalize a single source or a list of sources into a list."""
    if isinstance(value, (list, tuple)):
        return list(value)

    return [value]


def _normalize_source(source):
    """Return a scan-able source: ``{"kind": "dict", ...}`` or ``{"kind": "raw", ...}``."""
    if isinstance(source, dict):
        return {"kind": "dict", "data": source}

    if isinstance(source, (str, Path)):
        path = Path(source)

        if _path_exists(path):
            try:
                if path.name == RESOURCE_FILE:
                    return {"kind": "dict", "data": _bundled_metadata()}

                return {"kind": "raw", "text": path.read_text()}

            except OSError:
                return {"kind": "dict", "data": {}}

        # Not a file path: treat it as a raw JSON string.
        return {"kind": "raw", "text": source}

    return {"kind": "dict", "data": {}}


def _path_exists(path):
    """Like ``Path.exists()`` but tolerant of paths that are too long to stat.

    Raw JSON metadata strings can be far longer than the OS path limit; on
    Python <= 3.12 ``Path.exists()`` re-raises ``OSError`` [Errno 36]
    ENAMETOOLONG for them instead of returning ``False`` (newer Pythons
    delegate to ``os.path.exists()`` and return ``False``). Treat either
    outcome as "not a file path" so the caller falls back to a raw source.
    """
    try:
        return path.exists()

    except OSError:
        return False


def _find_record(sources, model_name, provider, route):
    """Find the best metadata record for a model name.

    Lookup order:
        1. Exact match on the full model name.
        2. Exact match on the route (name after the provider prefix).
        3. Progressively shortened routes, preferring newer model families
           (``gpt-5.6-luna`` -> ``gpt-5.6`` -> ``gpt-5`` -> ``gpt``).
        4. Closest same-provider match by longest shared route prefix.
    """
    if not sources:
        return None

    for key in _candidate_keys(model_name, route, provider):
        record = _lookup_entry(sources, key)

        if record:
            return record

    return _closest_provider_match(sources, provider, route)


def _candidate_keys(model_name, route, provider):
    """Ordered lookup keys: full name, same-provider families, route, bare families.

    Same-provider family candidates come before the bare route so a provider
    prefix is never silently dropped for a bare (possibly different-provider)
    record, e.g. ``github_copilot/gpt-5.6-luna`` should resolve to the
    ``github_copilot/gpt-5`` family rather than the bare ``gpt-5.6-luna``
    (openai) record.
    """
    keys = [model_name]
    shortened = _shorten_route(route) if provider and route else []

    if provider and route:
        keys.extend(f"{provider}/{candidate}" for candidate in shortened)

    if route and route != model_name:
        keys.append(route)

    if provider and route:
        keys.extend(shortened)

    return keys


def _lookup_entry(sources, key):
    """Return the entry for ``key`` from the sources (later sources win)."""
    for source in reversed(sources):
        if source["kind"] == "dict":
            record = source["data"].get(key)

            if record:
                return record

        else:
            record = get_entry_from_raw(source["text"], key)

            if record:
                return record

    return None


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


def _closest_provider_match(sources, provider, route):
    """Return the same-provider record with the longest shared route prefix.

    Raw sources are enumerated via a lightweight top-level key scan (a string
    pass, never a full parse) and only ``provider/``-prefixed keys are parsed
    for scoring, so the fallback stays memory friendly.
    """
    if not provider:
        return None

    best = None
    best_score = -1
    prefix = provider + "/"

    for source in reversed(sources):
        if source["kind"] == "dict":
            for key, record in source["data"].items():
                if not isinstance(record, dict):
                    continue

                key_route = key.split("/", 1)[-1] if "/" in key else key
                same_provider = record.get("litellm_provider") == provider or key.startswith(prefix)

                if not same_provider:
                    continue

                score = _prefix_score(route or "", key_route)

                if score > best_score:
                    best_score = score
                    best = record

        else:
            for key in top_level_keys(source["text"]):
                if not key.startswith(prefix):
                    continue

                record = get_entry_from_raw(source["text"], key)

                if not record:
                    continue

                score = _prefix_score(route or "", key[len(prefix) :])

                if score > best_score:
                    best_score = score
                    best = record

    return best


def _prefix_score(left, right):
    """Count the number of matching leading characters between two strings."""
    score = 0

    for a, b in zip(left, right):
        if a != b:
            break
        score += 1

    return score
