"""Inline onboarding wizard for cecli.

When a user has no default model configured and no API keys are detected,
:func:`run_onboarding` launches a full-screen Textual picker that lets them:

    #. pick a model provider (OpenAI, Anthropic, or any provider from ``providers.json``)
    #. enter the provider's ``_API_KEY`` environment variable(s)
    #. pick a default model

The entered keys are persisted to ``~/.cecli/.env`` and the chosen default
model is persisted to ``~/.cecli/conf.yml`` so future sessions load them
automatically.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

from .providers import iter_providers


def _env_file() -> Path:
    return Path.home() / ".cecli" / ".env"


def _conf_file() -> Path:
    return Path.home() / ".cecli" / "conf.yml"


def _persist_api_keys(api_keys: Optional[Dict[str, str]]) -> None:
    if not api_keys:
        return

    import dotenv

    env_file = _env_file()
    env_file.parent.mkdir(parents=True, exist_ok=True)
    for name, value in api_keys.items():
        dotenv.set_key(str(env_file), name, value, quote_mode="always")


def _persist_default_model(model: str) -> None:
    import yaml

    conf_file = _conf_file()
    conf_file.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if conf_file.exists():
        try:
            with conf_file.open("r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                if isinstance(content, dict):
                    config = content
        except Exception:
            config = {}

    config["model"] = model
    config["agent"] = True

    with conf_file.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)


async def run_onboarding(io) -> Optional[str]:
    """Run the onboarding wizard and return the chosen default model name.

    Returns ``None`` when the user cancels or the wizard cannot be launched
    (for example when ``textual`` is not installed).
    """
    try:
        from .app import OnboardingApp
    except ImportError as e:
        io.tool_error("Onboarding requires the 'textual' package.")
        io.tool_output(f"Install with: pip install cecli-dev[tui] ({e})")
        return None

    if sys.stdin is None or not sys.stdin.isatty():
        return None

    providers: List[Dict] = iter_providers()
    app = OnboardingApp(providers)

    try:
        result = await app.run_async()
    except Exception as e:
        io.tool_error(f"Onboarding failed: {e}")
        return None

    if not result:
        return None

    try:
        _persist_api_keys(result.get("api_keys") or {})
        _persist_default_model(result["model"])
    except Exception as e:
        io.tool_warning(f"Failed to persist onboarding settings: {e}")

    return result["model"]
