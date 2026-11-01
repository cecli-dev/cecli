"""Session config options for ``cecli --acp``: chat mode, model and thinking effort.

ACP clients render these as pickers next to the prompt box:
https://agentclientprotocol.com/protocol/session-config-options

Picking a value runs the matching cecli command (``/ask``, ``/model ...``,
``/reasoning-effort ...``), so a switch behaves exactly as if it were typed.
"""

from __future__ import annotations

import fnmatch
from typing import Any

import yaml

from cecli.helpers.server.acp.agent.transport import log

MODES = [
    ("code", "Code", "Make the requested changes to the code"),
    ("ask", "Ask", "Answer questions without editing files"),
    ("architect", "Architect", "Plan with the main model, then edit with the editor model"),
    ("context", "Context", "Work out which files a change needs"),
    ("agent", "Agent", "Work autonomously, finding files and running tools"),
    ("agent-yolo", "Agent (YOLO)", "Agent mode that runs tools and commands without asking"),
]
# Agent mode with what --yolo turns on: every confirmation answered yes
YOLO_MODE = "agent-yolo"
REASONING_EFFORTS = ["low", "medium", "high"]
THINKING_BUDGETS = ["4k", "8k", "16k", "32k"]
# Model metadata modes cecli can chat with (not image generation and the like)
CHAT_MODES = ("chat", "responses")


def _value(value: str, name: str | None = None, description: str | None = None) -> dict:
    entry = {"value": value, "name": name or value}
    if description:
        entry["description"] = description
    return entry


def _select(config_id: str, name: str, category: str, current: str, values: list[dict]) -> dict:
    return {
        "id": config_id,
        "name": name,
        "category": category,
        "type": "select",
        "currentValue": current,
        "options": values,
    }


def _token_count(budget: str) -> float:
    """``"8k"`` -> 8192, as cecli formats thinking budgets."""
    scale = {"k": 1024, "m": 1024 * 1024}.get(budget[-1:].lower())
    return float(budget[:-1]) * scale if scale else float(budget)


def _flat_values(option: dict) -> list[dict]:
    """A select option's values, with any groups flattened."""
    values = []
    for entry in option["options"]:
        values.extend(entry["options"] if "group" in entry else [entry])
    return values


def current_value(options: list[dict], config_id: str) -> str | None:
    option = next((o for o in options if o["id"] == config_id), None)
    return option["currentValue"] if option else None


def resolve_model(value: str) -> tuple[str, bool]:
    """The model name cecli would run for ``value``, and whether a tag override applies."""
    from cecli import models

    name = models.MODEL_ALIASES.get(value, value)
    base, overrides = models.ModelOverrides.apply(name)
    return (base, True) if overrides else (name, False)


def settings_file_models(coder: Any) -> list[str]:
    """Models defined in the user's .cecli.model.settings.yml files."""
    from cecli.helpers.file_searcher import generate_search_path_list

    args = getattr(coder, "args", None)
    repo = getattr(coder, "repo", None)
    fnames = generate_search_path_list(
        ".cecli.model.settings.yml",
        getattr(repo, "root", None),
        getattr(args, "model_settings_file", None),
    )
    names = []
    for fname in fnames:
        try:
            with open(fname, encoding="utf-8") as f:
                entries = yaml.safe_load(f) or []
        except (OSError, yaml.YAMLError):
            continue
        for entry in entries if isinstance(entries, list) else []:
            name = entry.get("name") if isinstance(entry, dict) else None
            # cecli/extra_params holds settings for every model, not a model
            if isinstance(name, str) and not name.endswith("/extra_params"):
                names.append(name)
    return names


def keyed_provider_models() -> list[tuple[str, str, list[str]]]:
    """``(slug, name, models)`` for each provider whose API key is set."""
    from cecli.helpers.onboarding.providers import (
        get_models_for_provider,
        iter_providers,
        provider_has_key,
    )

    groups = []
    for provider in iter_providers():
        if provider_has_key(provider):
            models = get_models_for_provider(provider["slug"], modes=CHAT_MODES)
            if models:
                groups.append((provider["slug"], provider["display_name"], models))
    return groups


def matches_filter(name: str, patterns: list[str]) -> bool:
    """Whether ``name`` matches any of ``patterns``, as ``/models`` matches its search."""
    name = name.lower()
    for pattern in patterns:
        pattern = pattern.lower()
        if any(char in pattern for char in "*?["):
            if fnmatch.fnmatchcase(name, f"*{pattern}*"):
                return True
        elif pattern in name:
            return True
    return False


class SessionConfig:
    """Builds the config options from a coder and maps choices to cecli commands."""

    def __init__(self):
        self.model_choice: str | None = None  # how the user last named the model
        # (group id, group name, [(value, description, model it runs)])
        self._model_groups: list[tuple[str, str, list[tuple[str, str | None, str]]]] | None = None
        self._before_yolo: tuple[Any, Any] | None = None

    def options(self, coder: Any) -> list[dict]:
        if coder is None:
            return []
        options = [self._mode_option(coder), self._model_option(coder)]
        effort = self._effort_option(coder)
        if effort is not None:
            options.append(effort)
        return options

    def command(self, coder: Any, config_id: Any, value: Any) -> str | None:
        """The cecli command that applies ``value``, or None if it is already current.

        Raises ValueError for an unknown option or value.
        """
        option = next((o for o in self.options(coder) if o["id"] == config_id), None)
        if option is None:
            raise ValueError(f"Unknown config option: {config_id}")
        if value not in {entry["value"] for entry in _flat_values(option)}:
            raise ValueError(f"Unknown value for {config_id}: {value}")
        if value == option["currentValue"]:
            return None

        if config_id == "mode":
            yolo = value == YOLO_MODE
            # Leaving YOLO, or picking plain Agent, brings the confirmations back
            if yolo or value == "agent" or option["currentValue"] == YOLO_MODE:
                self._set_yolo(coder, yolo)
            target = "agent" if yolo else value
            return None if coder.edit_format == target else f"/{target}"
        if config_id == "model":
            self.model_choice = value
            # Agent mode answers with the agent model, which /model leaves alone
            command = "/agent-model" if coder.edit_format == "agent" else "/model"
            return f"{command} {value}"
        if config_id == "reasoning_effort":
            return f"/reasoning-effort {'none' if value == 'default' else value}"
        return f"/think-tokens {value}"

    @staticmethod
    def modes(options: list[dict]) -> dict | None:
        """The same choice as the legacy ``modes`` state, for clients without config options."""
        mode = next((o for o in options if o["id"] == "mode"), None)
        if mode is None:
            return None
        return {
            "currentModeId": mode["currentValue"],
            "availableModes": [
                {"id": v["value"], "name": v["name"], "description": v.get("description")}
                for v in mode["options"]
            ],
        }

    # ── Options ─────────────────────────────────────────────────

    def _set_yolo(self, coder: Any, on: bool) -> None:
        """Turn on (or back off) the two settings ``--yolo`` sets at startup."""
        args = coder.args
        if on:
            if self._before_yolo is None:
                self._before_yolo = (coder.io.yes, getattr(args, "yes_always_commands", False))
            coder.io.yes = True
            args.yes_always_commands = True
        else:
            # Launched with --yolo: nothing to restore, so ask again (None asks)
            coder.io.yes, args.yes_always_commands = self._before_yolo or (None, False)
            self._before_yolo = None

    def _mode_option(self, coder: Any) -> dict:
        ids = [mode_id for mode_id, _, _ in MODES]
        # Every other edit format (diff, whole, udiff, ...) is code mode
        current = coder.edit_format if coder.edit_format in ids else "code"
        if self._before_yolo is not None and current != "agent":
            # Left agent mode with a typed command; YOLO doesn't outlive it
            self._set_yolo(coder, False)
        if current == "agent" and getattr(coder.args, "yes_always_commands", False):
            current = YOLO_MODE
        values = [_value(*mode) for mode in MODES]
        return _select("mode", "Mode", "mode", current, values)

    def _model_option(self, coder: Any) -> dict:
        # The model that answers in this mode (the agent model in agent mode)
        running = coder.get_active_model().name
        groups = []
        matches = []
        for group_id, name, entries in self._models(coder):
            values = []
            for value, description, model in entries:
                values.append(_value(value, description=description))
                if model == running:
                    matches.append(value)
            groups.append((group_id, name, values))

        if self.model_choice in matches:
            current = self.model_choice
        elif matches:
            current = matches[0]
        else:
            # Switched with /model to something not listed
            current = running
            groups[0][2].insert(0, _value(running))
        options = [
            {"group": group_id, "name": name, "options": values}
            for group_id, name, values in groups
            if values
        ]
        return _select("model", "Model", "model", current, options)

    def _models(self, coder: Any) -> list[tuple[str, str, list[tuple[str, str | None, str]]]]:
        """The models you configured, then those of every provider with an API key set."""
        if self._model_groups is not None:
            return self._model_groups

        from cecli import models

        args = getattr(coder, "args", None)
        candidates: list[tuple[str, str | None]] = []
        if getattr(args, "model", None):
            candidates.append((args.model, None))
        for alias_def in getattr(args, "alias", None) or []:
            alias, _, target = alias_def.partition(":")
            if alias.strip() and target.strip():
                candidates.append((alias.strip(), target.strip()))
        for base, tags in getattr(models.ModelOverrides, "_overrides", {}).items():
            for tag in tags if isinstance(tags, dict) else []:
                candidates.append((f"{base}:{tag}", None))
        try:
            candidates.extend((name, None) for name in settings_file_models(coder))
        except Exception:
            pass

        seen = set()
        configured = []
        for value, description in candidates:
            name, tagged = resolve_model(value)
            key = value if tagged else name
            if key in seen:
                continue
            seen.add(key)
            if description is None and name != value and not tagged:
                description = name
            configured.append((value, description, name))
        self._model_groups = [("configured", "Configured", configured)]

        try:
            providers = keyed_provider_models()
        except Exception as err:  # the configured models still work
            log(f"could not list provider models: {err!r}")
            providers = []
        patterns = getattr(args, "acp_models", None) or []
        for slug, provider_name, names in providers:
            entries = []
            for value in names:
                if value in seen or (patterns and not matches_filter(value, patterns)):
                    continue
                seen.add(value)
                entries.append((value, None, resolve_model(value)[0]))
            if entries:
                self._model_groups.append((slug, provider_name, entries))
        return self._model_groups

    def _effort_option(self, coder: Any) -> dict | None:
        model = coder.get_active_model()
        accepts = getattr(model, "accepts_settings", None) or []

        effort = model.get_reasoning_effort()
        if "reasoning_effort" in accepts or effort is not None:
            current = "default" if effort is None else str(effort)
            choices = ["default", *REASONING_EFFORTS]
            if current not in choices:
                choices.append(current)
            values = [_value(v, "Default" if v == "default" else v.capitalize()) for v in choices]
            return _select("reasoning_effort", "Reasoning effort", "thought_level", current, values)

        budget = model.get_raw_thinking_tokens()
        if "thinking_tokens" in accepts or budget is not None:
            current = model.get_thinking_tokens() if budget else "0"
            choices = ["0", *THINKING_BUDGETS]
            if current not in choices:
                choices = sorted([*choices, current], key=_token_count)
            values = [_value(v, "Off" if v == "0" else f"{v} tokens") for v in choices]
            return _select("thinking_tokens", "Thinking budget", "thought_level", current, values)
        return None
