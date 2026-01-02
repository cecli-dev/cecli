#!/usr/bin/env python
"""
Interactively generate cecli/resources/providers.json from litellm data.

This script reads litellm's openai_like provider definitions and walks the user
through building cecli's provider registry, mirroring the workflow used by
clean_metadata.py (prompting when decisions are needed).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable

AUTO_APPROVE = False


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt user for yes/no input, returning bool."""

    suffix = " [Y/n] " if default else " [y/N] "
    if AUTO_APPROVE:
        print(f"{question}{suffix}-> {'Y' if default else 'N'} (auto)")
        return default
    while True:
        resp = input(question + suffix).strip().lower()
        if not resp:
            return default
        if resp in ("y", "yes"):
            return True
        if resp in ("n", "no"):
            return False
        print("Please enter 'y' or 'n'.")


def _format_default(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(parsed, list):
            return ", ".join(str(item) for item in parsed)
    return value


def prompt_value(question: str, default: str | None = None) -> str | None:
    """Prompt user for a string; empty input keeps default."""

    display_default = _format_default(default)
    suffix = f" [{display_default}]" if display_default is not None else ""
    if AUTO_APPROVE:
        print(f"{question}{suffix}: -> {display_default or ''} (auto)")
        return default
    resp = input(f"{question}{suffix}: ").strip()
    if not resp:
        return default
    return resp


def ensure_json_object(prompt_text: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Prompt for a JSON object, re-prompting on parse errors."""

    default_str = json.dumps(default, indent=2) if default else ""
    while True:
        raw = prompt_value(prompt_text, default_str)
        if not raw:
            return default or {}
        if AUTO_APPROVE:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return default or {}
            return parsed
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - interactive error path
            print(f"Invalid JSON ({exc}). Please try again.")
            continue
        if not isinstance(parsed, dict):
            print('Please provide a JSON object (e.g., {"Header": "value"}).')
            continue
        return parsed


def _list_to_csv(value: Iterable[str] | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return ", ".join(str(item) for item in value)


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def main():
    global AUTO_APPROVE

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-y",
        "--yes",
        "--auto-approve",
        dest="auto",
        action="store_true",
        help="Automatically include all providers and accept defaults without prompting.",
    )
    args = parser.parse_args()
    AUTO_APPROVE = args.auto

    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent

    litellm_providers_path = (
        script_dir.parent / "../litellm/litellm/llms/openai_like/providers.json"
    ).resolve()
    output_path = (repo_root / "cecli" / "resources" / "providers.json").resolve()

    if not litellm_providers_path.exists():
        print(f"Error: Could not find litellm providers at {litellm_providers_path}")
        return

    try:
        litellm_data = json.loads(litellm_providers_path.read_text())
    except json.JSONDecodeError as exc:
        print(f"Error: Failed to parse litellm providers ({exc}).")
        return

    existing = {}
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text())
        except json.JSONDecodeError as exc:
            print(f"Warning: Existing {output_path} is invalid JSON ({exc}); ignoring.")

    new_config: Dict[str, Dict[str, Any]] = {}

    for provider_name in sorted(litellm_data.keys()):
        litellm_entry = litellm_data[provider_name]
        existing_entry = existing.get(provider_name, {})
        default_keep = bool(existing_entry)

        print("\n" + "=" * 60)
        print(f"Provider: {provider_name}")
        print(f"  Display name : {litellm_entry.get('display_name', provider_name)}")
        print(f"  Base URL     : {litellm_entry.get('base_url', 'N/A')}")

        api_key_list = litellm_entry.get("api_key_env")
        api_key_display = _list_to_csv(api_key_list) if api_key_list else "N/A"
        print(f"  API key env  : {api_key_display}")

        include = prompt_yes_no(
            f"Include provider '{provider_name}'?", default=default_keep or True
        )
        if not include:
            continue

        display_name = prompt_value(
            "Display name",
            existing_entry.get("display_name")
            or litellm_entry.get("display_name")
            or provider_name,
        )
        api_base = prompt_value(
            "API base URL",
            existing_entry.get("api_base") or litellm_entry.get("base_url") or "",
        )
        base_url_env = prompt_value(
            "Comma-separated env vars for overriding base URL",
            _list_to_csv(existing_entry.get("base_url_env")) or "",
        )
        api_key_env = prompt_value(
            "Comma-separated env vars for API key lookup",
            _list_to_csv(existing_entry.get("api_key_env", litellm_entry.get("api_key_env", [])))
            or "",
        )
        models_url = prompt_value(
            "Models endpoint URL (leave blank if none)",
            existing_entry.get("models_url", ""),
        )
        default_headers = ensure_json_object(
            "Default headers JSON (empty for none)",
            existing_entry.get("default_headers"),
        )

        record: Dict[str, Any] = {}
        if display_name:
            record["display_name"] = display_name
        if api_base:
            record["api_base"] = api_base
        if api_key_env:
            record["api_key_env"] = _parse_csv(api_key_env)
        if base_url_env:
            record["base_url_env"] = _parse_csv(base_url_env)
        if models_url:
            record["models_url"] = models_url
        if default_headers:
            record["default_headers"] = default_headers

        new_config[provider_name] = record

    # Preserve providers that only exist in the existing file (not litellm) if user wants.
    for provider_name in sorted(existing.keys()):
        if provider_name in new_config or provider_name in litellm_data:
            continue
        print("\n" + "=" * 60)
        print(f"Provider '{provider_name}' exists only in {output_path}.")
        if prompt_yes_no("Keep this provider?", default=True):
            new_config[provider_name] = existing[provider_name]

    output_path.write_text(json.dumps(new_config, indent=2, sort_keys=True) + "\n")
    print(f"\nWrote {len(new_config)} providers to {output_path}.\n")


if __name__ == "__main__":
    main()
