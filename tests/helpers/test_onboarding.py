import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cecli.helpers.onboarding import run_onboarding
from cecli.helpers.onboarding.app import OnboardingApp
from cecli.helpers.onboarding.providers import (
    get_models_for_provider,
    iter_providers,
    provider_needs_key,
)


def _clear_api_keys() -> None:
    for key in [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY",
    ]:
        os.environ.pop(key, None)


def test_iter_providers_includes_builtin_and_providers_json():
    providers = iter_providers()
    slugs = {provider["slug"] for provider in providers}

    # Builtin / default providers from llms config
    assert "openai" in slugs
    assert "anthropic" in slugs
    assert "github_copilot" in slugs
    assert "deepseek" in slugs
    assert "openrouter" in slugs
    assert "gemini" in slugs
    assert "meta" in slugs
    # A handful from providers.json
    assert "groq" in slugs
    assert "together_ai" in slugs
    assert len(slugs) == len(providers)


@pytest.mark.parametrize("slug", ["github_copilot", "bedrock", "bedrock_mantle"])
def test_no_key_providers_skip_key_prompt(slug):
    provider = next(provider for provider in iter_providers() if provider["slug"] == slug)

    assert provider_needs_key(provider) is False


def test_openai_provider_needs_key():
    provider = next(provider for provider in iter_providers() if provider["slug"] == "openai")

    assert provider_needs_key(provider) is True


def test_get_models_for_provider_openai():
    models = get_models_for_provider("openai")

    assert models
    assert "openai/gpt-4o" in models


def test_get_models_for_provider_anthropic_prefixed():
    models = get_models_for_provider("anthropic")

    assert models
    assert all(model.startswith("anthropic/") for model in models)


def test_persist_api_keys_and_default_model(monkeypatch, tmp_path):
    from cecli.helpers import onboarding

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    config_dir = tmp_path / ".cecli"
    config_dir.mkdir()
    (config_dir / ".env").write_text("EXISTING=1\n", encoding="utf-8")
    (config_dir / "conf.yml").write_text("dark-mode: true\n", encoding="utf-8")

    onboarding._persist_api_keys({"OPENAI_API_KEY": "sk-123"})
    onboarding._persist_default_model("gpt-4o")

    env_text = (config_dir / ".env").read_text(encoding="utf-8")
    assert "EXISTING=1" in env_text
    assert "OPENAI_API_KEY" in env_text

    conf_text = (config_dir / "conf.yml").read_text(encoding="utf-8")
    assert "dark-mode: true" in conf_text
    assert "model: gpt-4o" in conf_text
    assert "agent: true" in conf_text


@pytest.mark.asyncio
async def test_onboarding_app_prompts_for_key_and_returns_result():
    _clear_api_keys()
    app = OnboardingApp(iter_providers())

    async with app.run_test() as pilot:
        await pilot.pause(0.2)

        for char in "anthropic":
            await pilot.press(char)
            await pilot.pause(0.05)
        await pilot.press("tab")
        await pilot.pause(0.05)
        await pilot.press("enter")
        await pilot.pause(0.2)

        assert app.provider and app.provider["slug"] == "anthropic"
        assert type(app.screen).__name__ == "ApiKeyScreen"

        for char in "sk-x":
            await pilot.press(char)
        await pilot.press("enter")
        await pilot.pause(0.2)

        assert app.api_keys == {"ANTHROPIC_API_KEY": "sk-x"}

        for _ in range(80):
            await pilot.pause(0.1)
            if type(app.screen).__name__ == "ModelScreen":
                break
        assert type(app.screen).__name__ == "ModelScreen"

        await pilot.press("tab")
        await pilot.pause(0.05)
        await pilot.press("enter")
        await pilot.pause(0.2)

        assert app.result
        assert app.result["model"].startswith("anthropic/")
        assert app.result["api_keys"] == {"ANTHROPIC_API_KEY": "sk-x"}


@pytest.mark.asyncio
async def test_onboarding_app_skips_key_for_no_key_provider():
    _clear_api_keys()
    app = OnboardingApp(iter_providers())

    async with app.run_test() as pilot:
        await pilot.pause(0.2)

        for char in "bedrock":
            await pilot.press(char)
            await pilot.pause(0.05)
        await pilot.press("tab")
        await pilot.pause(0.05)
        await pilot.press("enter")
        await pilot.pause(0.2)

        assert app.provider and app.provider["slug"] == "bedrock"

        for _ in range(80):
            await pilot.pause(0.1)
            if type(app.screen).__name__ in ("ModelScreen", "ModelManualScreen"):
                break
        assert type(app.screen).__name__ in ("ModelScreen", "ModelManualScreen")
        assert app.api_keys == {}


@pytest.mark.asyncio
async def test_filterable_list_arrow_keys_move_highlight_when_input_focused():
    _clear_api_keys()
    app = OnboardingApp(iter_providers())

    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        screen = app.screen
        source = screen.query_one("#providers")
        option_list = source.query_one("#options")
        search = source.query_one("#filter")

        # Focus sits on the search input, not the items box.
        assert screen.focused is search
        assert option_list.highlighted == 0

        await pilot.press("down")
        await pilot.pause(0.05)
        assert option_list.highlighted == 1

        await pilot.press("down")
        await pilot.pause(0.05)
        assert option_list.highlighted == 2

        await pilot.press("up")
        await pilot.pause(0.05)
        assert option_list.highlighted == 1


@pytest.mark.asyncio
async def test_filterable_list_enter_submits_highlighted_when_input_focused():
    _clear_api_keys()
    app = OnboardingApp(iter_providers())

    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        fl = app.screen.query_one("#providers")
        fl.query_one("#options").highlighted = 1

        await pilot.press("enter")
        await pilot.pause(0.2)

        assert app.provider and app.provider["slug"] == "anthropic"


@pytest.mark.asyncio
async def test_escape_on_api_key_screen_returns_to_provider():
    _clear_api_keys()
    app = OnboardingApp(iter_providers())

    async with app.run_test() as pilot:
        await pilot.pause(0.3)

        for char in "anthropic":
            await pilot.press(char)
            await pilot.pause(0.02)
        await pilot.press("tab")
        await pilot.pause(0.05)
        await pilot.press("enter")
        await pilot.pause(0.2)

        assert type(app.screen).__name__ == "ApiKeyScreen"

        await pilot.press("escape")
        await pilot.pause(0.3)

        assert type(app.screen).__name__ == "ProviderScreen"
        assert app.provider is None
        assert app.result is None


@pytest.mark.asyncio
async def test_run_onboarding_skips_when_not_tty():
    io = MagicMock()
    io.tool_error = MagicMock()
    io.tool_output = MagicMock()

    with patch("sys.stdin.isatty", return_value=False):
        result = await run_onboarding(io)

    assert result is None
