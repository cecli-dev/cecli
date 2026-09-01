#!/usr/bin/env python3
"""Condense cecli/resources/model-settings.yml into a defaults/templates/mapping form.

The source file is a long, ever growing YAML list of per-model setting entries
that mostly share the same configuration. This script reorganizes it into:

    defaults:
      <provider>:                  # everything before the last "/" of a name
        weak_model_name: <model>   # weak/editor model of the provider's LAST entry
        editor_model_name: <model>
    templates:
      <provider>/<letter>:          # provider of the first model with this
                                   # config, lettered per provider in file order
        <settings sans the ignored fields, keys sorted alphabetically>
    mapping:
      <model name>: <template name>   # keys are natural-sorted

Ignored when computing template identity (and omitted from template bodies):
name, editor_model_name, weak_model_name, use_repo_map, examples_as_sys_msg,
edit_format, reminder, and max_tokens inside extra_params.

Provider rules:
  - names containing "/" belong to the provider named by everything before the
    last slash (e.g. openrouter/openai/gpt-4o -> openrouter/openai)
  - providerless names (no "/") are dropped from the condensed output: models
    must always declare a provider, in both the mapping keys and the template
    names.

The per-provider default weak/editor models come from the LAST entry of that
provider in the file (later entries override earlier ones).

Usage:
    python3 scripts/condense_model_settings.py [SOURCE] [OUTPUT]
"""

import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

import yaml

DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "cecli" / "resources" / "model-settings.yml"
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1] / "cecli" / "resources" / "model-settings-condensed.yml"
)

IGNORED_FIELDS = (
    "name",
    "editor_model_name",
    "weak_model_name",
    "use_repo_map",
    "examples_as_sys_msg",
    "edit_format",
    "reminder",
)


def provider_of(model_name):
    """Return the provider for a model name per the documented rules."""
    if "/" in model_name:
        return model_name.rsplit("/", 1)[0]
    if "claude" in model_name.lower():
        return "anthropic"
    return "openai"


def condense(entries):
    """Build (defaults, templates, mapping) from the source entry list."""

    # Models must declare a provider: drop providerless names (no "/") so both
    # the mapping keys and the template names are provider-prefixed.
    entries = [entry for entry in entries if "/" in entry["name"]]
    providers = OrderedDict()  # provider -> last entry seen in file order
    templates = OrderedDict()  # template name -> config dict
    template_for = OrderedDict()  # canonical config -> template name
    next_letter = OrderedDict()  # provider -> next template letter index
    mapping = OrderedDict()  # model name -> template name

    for entry in entries:
        name = entry["name"]
        provider = provider_of(name)
        # Later entries override earlier ones, so the final value is the last.
        providers[provider] = entry

        config = _template_config(entry)
        config_key = json.dumps(config, sort_keys=True)
        if config_key not in template_for:
            # Templates are named <provider>/<letter>, lettered per provider in
            # the order each config is first seen in the file (a, b, ..., z,
            # aa, ab, ...).
            index = next_letter.get(provider, 1)
            next_letter[provider] = index + 1
            template_name = f"{provider}/{_index_to_letters(index)}"
            template_for[config_key] = template_name
            templates[template_name] = config
        mapping[name] = template_for[config_key]

    defaults = OrderedDict()
    for provider, last_entry in providers.items():
        provider_defaults = OrderedDict()
        for field in ("weak_model_name", "editor_model_name"):
            model = last_entry.get(field)
            if model is not None:
                provider_defaults[field] = model
        defaults[provider] = provider_defaults

    # Natural-sort the template and mapping keys (e.g. .../a before .../b).
    templates = OrderedDict(sorted(templates.items(), key=lambda item: natural_key(item[0])))
    mapping = OrderedDict(sorted(mapping.items(), key=lambda item: natural_key(item[0])))

    return defaults, templates, mapping


# ---------------------------------------------------------------------------
# Minimal YAML writer so the output stays clean and readable (no sort_keys,
# no flow-style nesting, blank lines between entries, double-quoted strings).
# ---------------------------------------------------------------------------


def _scalar(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if _is_plain_safe(text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _is_plain_safe(text):
    """Conservative check: can this string be a plain YAML scalar?"""
    if not text or text != text.strip():
        return False
    if text.lower() in ("true", "false", "null", "yes", "no", "on", "off", "~"):
        return False
    if text[0] in "!&*{}[],#|>@`\"'%-?: " or text[-1] in ":" or " #" in text:
        return False
    if ": " in text or "\n" in text:
        return False
    return all(c.isalnum() or c in "._/@+-" for c in text)


def _emit(value, indent, lines):
    pad = "  " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{_scalar(key)}:")
                _emit(item, indent + 1, lines)
            elif isinstance(item, (dict, list)):
                lines.append(f"{pad}{_scalar(key)}: {{}}")
            else:
                lines.append(f"{pad}{_scalar(key)}: {_scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}-")
                _emit(item, indent + 1, lines)
            elif isinstance(item, (dict, list)):
                lines.append(f"{pad}- {{}}")
            else:
                lines.append(f"{pad}- {_scalar(item)}")


def _template_config(entry):
    """Config used for template identity: the entry sans the ignored fields,
    with max_tokens stripped from extra_params (dropped if it empties), and
    keys sorted alphabetically."""
    config = OrderedDict(
        sorted((key, value) for key, value in entry.items() if key not in IGNORED_FIELDS)
    )
    extra = config.get("extra_params")
    if isinstance(extra, dict) and extra:
        stripped = OrderedDict(
            sorted((key, value) for key, value in extra.items() if key != "max_tokens")
        )
        if stripped:
            config["extra_params"] = stripped
        else:
            del config["extra_params"]
    return config


def _index_to_letters(index):
    """1-based index to spreadsheet-style letters (1 -> a, 26 -> z, 27 -> aa)."""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters


def natural_key(text):
    """Sort key ordering embedded numbers numerically (e.g. gpt-4 before gpt-10)."""
    return [
        (1, int(chunk)) if chunk.isdigit() else (0, chunk.lower())
        for chunk in re.split(r"(\d+)", text)
    ]


def render(result):
    """Render the top-level structure with blank lines between entries.

    defaults and templates get a blank line between each entry so the nested
    blocks are easy to scan; the flat mapping section stays compact.
    """
    blank_between = {"defaults": True, "templates": True, "mapping": False}
    lines = []
    for section_index, (section, body) in enumerate(result.items()):
        if section_index:
            lines.append("")
        lines.append(f"{section}:")
        if isinstance(body, dict):
            for item_index, (key, value) in enumerate(body.items()):
                if item_index and blank_between.get(section):
                    lines.append("")
                if isinstance(value, dict) and value:
                    lines.append(f"  {_scalar(key)}:")
                    _emit(value, 2, lines)
                elif isinstance(value, (dict, list)):
                    lines.append(f"  {_scalar(key)}: {{}}")
                else:
                    lines.append(f"  {_scalar(key)}: {_scalar(value)}")
    return "\n".join(lines) + "\n"


def main(argv):
    source = Path(argv[0]) if len(argv) > 0 and argv[0] != "-" else DEFAULT_SOURCE
    output = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT

    with open(source) as f:
        entries = yaml.safe_load(f)
    if not isinstance(entries, list):
        raise SystemExit(f"Expected a YAML list in {source}, got {type(entries).__name__}")

    defaults, templates, mapping = condense(entries)
    result = OrderedDict(defaults=defaults, templates=templates, mapping=mapping)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        f.write(render(result))

    print(f"Read {len(entries)} entries from {source}")
    print(f"Found {len(defaults)} providers, {len(templates)} templates")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main(sys.argv[1:])
