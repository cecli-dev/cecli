import copy
import json
import logging
import os
from typing import Any, Dict, List

import yaml

from cecli.decoding import safe_open


def load_and_apply_cecli_conf_files(
    cecli_conf_yml_files: List[str], args: Any, parser: Any
) -> None:
    """
    Read .cecli.conf.yml files directly from disk, deep-merge them together,
    and then merge the result ON TOP OF existing args values (from .cecli/conf.yml).
    """
    from cecli.args import DEEP_MERGE_JSON_FIELDS, DEEP_MERGE_LIST_FIELDS

    existing_cecli_conf = [cf for cf in cecli_conf_yml_files if os.path.exists(cf)]

    if existing_cecli_conf:
        cecli_conf_dicts = []

        for config_file in existing_cecli_conf:
            try:
                with safe_open(config_file, "r") as f:
                    config_data = yaml.safe_load(f)

                    if isinstance(config_data, dict):
                        cecli_conf_dicts.append(_normalize_keys(config_data))

            except yaml.YAMLError as e:
                logging.warning("Could not parse YAML file %s: %s", config_file, e)

        if cecli_conf_dicts:
            # Deep-merge .cecli.conf.yml files together
            merged_cecli_conf = deep_merge_config_dicts(cecli_conf_dicts)

            # ── List fields: concatenate with existing args values ──────
            for key in DEEP_MERGE_LIST_FIELDS:
                if key in merged_cecli_conf and hasattr(args, key):
                    cecli_val = merged_cecli_conf[key]

                    if not isinstance(cecli_val, list):
                        if cecli_val is None:
                            # YAML null / empty key → treat as empty list
                            cecli_val = []

                        elif isinstance(cecli_val, str):
                            # Scalar string → wrap in single-element list
                            cecli_val = [cecli_val]

                        else:
                            logging.warning(
                                "Merged .cecli.conf.yml value for %s is not a list (type: %s), "
                                "expected list — skipping",
                                key,
                                type(cecli_val).__name__,
                            )
                            continue

                    existing_val = getattr(args, key)

                    if isinstance(existing_val, list):
                        # Concatenate: .cecli/conf.yml values first, then
                        # .cecli.conf.yml values (deduplicated)
                        setattr(args, key, _deduplicate_list(list(existing_val), cecli_val))

                    else:
                        setattr(args, key, cecli_val)

            # ── JSON fields: deep-merge into existing args values ───────
            for key in DEEP_MERGE_JSON_FIELDS:
                if key in merged_cecli_conf and hasattr(args, key):
                    cecli_val = merged_cecli_conf[key]

                    if isinstance(cecli_val, str):
                        try:
                            parsed_json = json.loads(cecli_val)
                            if isinstance(parsed_json, dict):
                                cecli_val = parsed_json
                        except (json.JSONDecodeError, TypeError):
                            pass

                    if not isinstance(cecli_val, dict):
                        if cecli_val is None:
                            # YAML null / empty key → treat as empty dict
                            cecli_val = {}

                        else:
                            logging.warning(
                                "Merged .cecli.conf.yml value for %s is not a dict (type: %s), "
                                "expected dict — skipping",
                                key,
                                type(cecli_val).__name__,
                            )
                            continue

                    existing_val = getattr(args, key)

                    if existing_val is not None:
                        # Parse existing value (may be JSON string from configargparse)
                        # and deep-merge .cecli.conf.yml values into it
                        if isinstance(existing_val, str):
                            try:
                                existing_val = json.loads(existing_val)

                            except json.JSONDecodeError:
                                try:
                                    existing_val = yaml.safe_load(existing_val)

                                except yaml.YAMLError:
                                    logging.warning(
                                        "Could not parse existing %s value as JSON/YAML, "
                                        "overwriting with .cecli.conf.yml value",
                                        key,
                                    )
                                    existing_val = {}

                        if isinstance(existing_val, dict):
                            merged_val = deep_merge(existing_val, cecli_val, deep_merge_arrays=True)

                        else:
                            merged_val = cecli_val

                    else:
                        merged_val = cecli_val

                    try:
                        setattr(args, key, json.dumps(merged_val))

                    except (TypeError, ValueError) as e:
                        logging.warning("Could not serialize merged config for %s: %s", key, e)

            # ── Apply remaining scalar fields from .cecli.conf.yml ────────────────
            all_deep_fields = DEEP_MERGE_LIST_FIELDS | DEEP_MERGE_JSON_FIELDS

            for key, value in merged_cecli_conf.items():
                if key not in all_deep_fields and hasattr(args, key):
                    existing_val = getattr(args, key)
                    default_val = parser.get_default(key)

                    if existing_val == default_val:
                        setattr(args, key, value)

    else:
        logging.debug(
            "No .cecli.conf.yml files found — shallow-merge-only mode active "
            "(configargparse handles .cecli/conf.yml)"
        )

    # ── Normalize array fields to never be None ───────────────────────────
    for key in DEEP_MERGE_LIST_FIELDS:
        if hasattr(args, key):
            val = getattr(args, key)

            if val is None or (isinstance(val, str) and val.strip() == ""):
                setattr(args, key, [])

            elif isinstance(val, str):
                setattr(args, key, [val])

            elif not isinstance(val, list):
                logging.warning(
                    "args.%s is not a list (type: %s), coercing to empty list",
                    key,
                    type(val).__name__,
                )
                setattr(args, key, [])

    for key in DEEP_MERGE_JSON_FIELDS:
        if hasattr(args, key):
            val = getattr(args, key)

            if val is None or (isinstance(val, str) and val.strip() == ""):
                setattr(args, key, "{}")


def read_and_merge_all_configs(
    all_config_paths: List[str],
    conf_yml_paths: List[str],
    cecli_conf_yml_paths: List[str],
) -> Dict[str, Any]:
    """
    Read all config files as YAML, shallow-merge .cecli/conf.yml files
    first, then deep-merge .cecli.conf.yml files on top.

    This processes ALL config files upfront as raw YAML, applies the
    correct merge strategy for each file type, and returns the fully
    resolved configuration dict — before any CLI args are parsed.

    Priority (lowest → highest):
      1. .cecli/conf.yml files (shallow-merged, later files win)
      2. .cecli.conf.yml files (deep-merged on top, nested dicts merged,
         arrays concatenated and deduplicated)
    """
    config_dicts: Dict[str, Dict[str, Any]] = {}

    for path in all_config_paths:
        if os.path.exists(path):
            try:
                with safe_open(path, "r") as f:
                    data = yaml.safe_load(f)

                    if isinstance(data, dict):
                        config_dicts[path] = data

            except yaml.YAMLError as e:
                logging.warning("Could not parse YAML file %s: %s", path, e)

    # Step 1: Shallow-merge .cecli/conf.yml files (later files override)
    merged: Dict[str, Any] = {}

    for path in conf_yml_paths:
        if path in config_dicts:
            merged.update(config_dicts[path])

    # Step 2: Deep-merge .cecli.conf.yml files on top
    cecli_dicts = [config_dicts[p] for p in cecli_conf_yml_paths if p in config_dicts]

    if cecli_dicts:
        merged = deep_merge_config_dicts([merged] + cecli_dicts)

    return merged


def deep_merge(dict1: dict, dict2: dict, deep_merge_arrays: bool = True) -> dict:
    """
    Recursively merges dict2 into dict1.
    """
    merged = copy.deepcopy(dict1)

    for key, value in dict2.items():
        if deep_merge_arrays and value is None:
            continue

        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value, deep_merge_arrays=deep_merge_arrays)

        elif (
            deep_merge_arrays
            and key in merged
            and isinstance(merged[key], list)
            and isinstance(value, list)
        ):
            merged[key] = _deduplicate_list(merged[key], value)

        else:
            merged[key] = copy.deepcopy(value)

    return merged


def is_cecli_conf_file(filepath: str) -> bool:
    """
    Return True if filepath refers to a .cecli.conf.yml file.
    """
    basename = os.path.basename(filepath)

    return basename == ".cecli.conf.yml"


def deep_merge_config_dicts(
    config_dicts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Cumulatively deep-merge a list of raw config dictionaries.
    """
    if not config_dicts:
        return {}

    merged = copy.deepcopy(config_dicts[0])

    for next_dict in config_dicts[1:]:
        merged = deep_merge(merged, next_dict, deep_merge_arrays=True)

    return merged


# ── Private Helper Functions (at bottom of file) ─────────────────────────────


def _normalize_keys(obj: Any) -> Any:
    """
    Recursively convert hyphenated dict keys to underscore-separated keys.
    """
    if isinstance(obj, dict):
        return {key.replace("-", "_"): _normalize_keys(value) for key, value in obj.items()}

    if isinstance(obj, list):
        return [_normalize_keys(item) for item in obj]

    return obj


def _deduplicate_list(merged_list: list, new_list: list) -> list:
    """
    Append elements from new_list to merged_list, skipping duplicates.
    """
    seen: set = set()

    for item in merged_list:
        seen.add(_canonical_repr(item))

    for item in new_list:
        key = _canonical_repr(item)

        if key not in seen:
            seen.add(key)
            merged_list.append(copy.deepcopy(item))

    return merged_list


def _canonical_repr(item: Any) -> Any:
    """
    Return a hashable, equality-comparable canonical representation of item.
    """
    if isinstance(item, dict):
        return json.dumps(item, sort_keys=True, default=str)

    if isinstance(item, list):
        return tuple(_canonical_repr(e) for e in item)

    return item
