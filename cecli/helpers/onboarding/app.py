"""Textual onboarding wizard for cecli.

Runs an inline full-screen picker that lets a user choose a model provider,
enter the relevant API key(s), and pick a default model. The collected values
are returned to :func:`cecli.helpers.onboarding.run_onboarding` for
persistence to ``~/.cecli/.env`` and ``~/.cecli/conf.yml``.
"""

import os
from functools import lru_cache
from typing import Dict, List, Optional

import textual.strip
from rich.color import ColorSystem
from rich.style import Style
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from .providers import get_models_for_provider, provider_display, provider_needs_key

# Sentinel returned by a screen to signal "go back a step" rather than cancel.
_BACK = object()


class FilterableList(Vertical):
    """A search-as-you-type input paired with an option list."""

    BINDINGS = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
    ]

    class Selected(Message):
        """Posted when the user selects an option."""

        def __init__(self, value) -> None:
            super().__init__()
            self.value = value

    def __init__(
        self, values: List, label_fn=None, prompt: str = "Search...", id: Optional[str] = None
    ):
        super().__init__(id=id)
        self.values = list(values)
        self.label_fn = label_fn or (lambda v: str(v))
        self._visible = list(self.values)
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        yield Input(placeholder=self.prompt, id="filter")
        yield OptionList(id="options")

    def on_mount(self) -> None:
        self._render_options()
        self.query_one("#filter", Input).focus()

    def _render_options(self) -> None:
        options = self.query_one("#options", OptionList)
        options.clear_options()
        for value in self._visible:
            options.add_option(Option(self.label_fn(value)))
        if self._visible:
            options.highlighted = 0

    def on_input_changed(self, event) -> None:
        query = event.value.strip().lower()
        if query:
            self._visible = [v for v in self.values if query in self.label_fn(v).lower()]
        else:
            self._visible = list(self.values)
        self._render_options()

    def on_input_submitted(self, event) -> None:
        self._select_highlighted()

    def _select_highlighted(self) -> None:
        options = self.query_one("#options", OptionList)
        index = options.highlighted
        if index is not None and 0 <= index < len(self._visible):
            self.post_message(self.Selected(self._visible[index]))

    def action_move_up(self) -> None:
        self.query_one("#options", OptionList).action_cursor_up()

    def action_move_down(self) -> None:
        self.query_one("#options", OptionList).action_cursor_down()

    def on_option_list_option_selected(self, event) -> None:
        index = event.option_index
        if index is not None and 0 <= index < len(self._visible):
            self.post_message(self.Selected(self._visible[index]))


class ProviderScreen(Screen):
    """First step: pick a provider."""

    def __init__(self, providers: List[Dict]) -> None:
        super().__init__()
        self.providers = providers

    def compose(self) -> ComposeResult:
        yield Static("Pick a model provider")
        yield FilterableList(
            self.providers, label_fn=provider_display, prompt="Search providers...", id="providers"
        )
        yield Footer()

    def on_filterable_list_selected(self, event) -> None:
        self.dismiss(event.value)


class ApiKeyScreen(Screen):
    """Second step: enter the provider's API key(s)."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(
        self, provider: Dict, env_vars: List[str], collected: Optional[Dict] = None
    ) -> None:
        super().__init__()
        self.provider = provider
        self.env_vars = list(env_vars)
        self.index = 0
        self.collected = dict(collected or {})

    def action_back(self) -> None:
        self.dismiss(_BACK)

    def compose(self) -> ComposeResult:
        yield Static(id="prompt")
        yield Input(password=True, placeholder="", id="key")
        yield Static("Press Enter to continue", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        env_var = self.env_vars[self.index]
        self.query_one("#prompt", Static).update(f"Enter your {env_var}")
        self.query_one("#key", Input).placeholder = env_var
        self.query_one("#key", Input).focus()

    def on_input_submitted(self, event) -> None:
        value = event.value.strip()
        if not value:
            self.query_one("#key", Input).focus()
            return

        self.collected[self.env_vars[self.index]] = value
        self.index += 1
        if self.index < len(self.env_vars):
            self.query_one("#key", Input).value = ""
            self._refresh()
        else:
            self.dismiss(self.collected)


class LoadingScreen(Screen):
    """Transient screen shown while provider models are fetched."""

    def compose(self) -> ComposeResult:
        yield Static("Fetching available models...")
        yield Footer()


class ModelScreen(Screen):
    """Model picker (when provider discovery returns models)."""

    def __init__(self, models: List[str]) -> None:
        super().__init__()
        self.models = models

    def compose(self) -> ComposeResult:
        yield Static("Pick a default model")
        yield FilterableList(self.models, prompt="Search models...", id="models")
        yield Footer()

    def on_filterable_list_selected(self, event) -> None:
        self.dismiss(event.value)


class ModelManualScreen(Screen):
    """Manual model entry (when provider discovery returns no models)."""

    def __init__(self, provider: Dict) -> None:
        super().__init__()
        self.provider = provider

    def compose(self) -> ComposeResult:
        yield Static(
            f"No models found for '{self.provider['display_name']}'. Enter a model name manually:"
        )
        yield Input(placeholder="model name", id="model")
        yield Footer()

    def on_input_submitted(self, event) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)


class OnboardingApp(App):
    """Inline onboarding wizard."""

    CSS = """
    FilterableList {
        height: 1fr;
        padding: 0 1;
    }
    FilterableList OptionList {
        height: 1fr;
        border: round #00ff87 50%;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }
    FilterableList OptionList > .option-list--option-highlighted {
        color: #00b365;
        background: transparent;
        text-style: bold;
    }
    FilterableList OptionList:focus > .option-list--option-highlighted {
        color: #00b365;
        background: transparent;
        text-style: bold;
    }
    Input {
        border: round #00ff87 50%;
        margin: 0;
    }
    Static {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+c", "cancel", "Cancel"),
    ]

    def __init__(self, providers: List[Dict]) -> None:
        super().__init__()
        self.providers = providers
        self.provider: Optional[Dict] = None
        self.api_keys: Dict[str, str] = {}
        self.result = None

    def on_mount(self) -> None:
        self.push_screen(ProviderScreen(self.providers), self._on_provider)

    def action_cancel(self) -> None:
        self.result = None
        self.exit(None)

    def _on_provider(self, provider) -> None:
        if provider is None:
            self.exit(None)
            return
        self.provider = provider
        env_vars = provider.get("api_key_env") or []
        if (
            provider_needs_key(provider)
            and env_vars
            and not all(os.environ.get(v) for v in env_vars)
        ):
            self.push_screen(ApiKeyScreen(provider, env_vars), self._on_api_keys)
        else:
            present = {v: os.environ[v] for v in env_vars if os.environ.get(v)}
            self._on_api_keys(present)

    def _on_api_keys(self, keys) -> None:
        if keys is _BACK:
            self._back_to_provider()
            return
        if keys is None:
            self.exit(None)
            return
        self.api_keys = keys or {}
        for name, value in self.api_keys.items():
            os.environ[name] = value
        self._fetch_models()

    def _back_to_provider(self) -> None:
        self.provider = None
        self.api_keys = {}
        self.push_screen(ProviderScreen(self.providers), self._on_provider)

    def _fetch_models(self) -> None:
        slug = self.provider["slug"]
        self.push_screen(LoadingScreen())

        def worker() -> None:
            try:
                models = get_models_for_provider(slug)
            except Exception:
                models = []
            self.call_from_thread(self._finish_fetch, models)

        self.run_worker(worker, thread=True)

    def _finish_fetch(self, models) -> None:
        if self.screen is not None:
            self.pop_screen()
        self._on_models(models)

    def _on_models(self, models) -> None:
        if not models:
            self.push_screen(ModelManualScreen(self.provider), self._on_model)
        else:
            self.push_screen(ModelScreen(models), self._on_model)

    def _on_model(self, model) -> None:
        if model is None:
            self.result = None
            self.exit(None)
            return
        self.result = {
            "provider": self.provider["slug"],
            "api_keys": self.api_keys,
            "model": model,
        }
        self.exit(self.result)


def patch_textual_strip_render_with_cache():
    """Monkey-patch Textual's ANSI renderer to ignore background colors.

    Applied permanently at import time so the inline onboarding wizard keeps the
    terminal's own background rather than cecli's dark theme painting over it.
    """

    def modified_render_ansi(cls, style: Style, color_system: ColorSystem) -> str:
        """Modified ANSI generator that ignores background colors."""
        sgr: list[str]
        if attributes := style._attributes & style._set_attributes:
            _style_map = textual.strip.SGR_STYLES
            sgr = [
                _style_map[bit_offset]
                for bit_offset in range(attributes.bit_length())
                if attributes & (1 << bit_offset)
            ]
        else:
            sgr = []

        if (color := style._color) is not None:
            sgr.extend(color.downgrade(color_system).get_ansi_codes())

        # BACKGROUND OVERRIDE: Skip the bgcolor block entirely
        ansi = style._ansi = ";".join(sgr)
        return ansi

    cached_version = lru_cache(maxsize=16384)(modified_render_ansi)
    textual.strip.Strip.render_ansi = classmethod(cached_version)


# Apply the no-background-color hack permanently for the onboarding wizard.
patch_textual_strip_render_with_cache()
