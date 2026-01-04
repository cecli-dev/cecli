import asyncio
import difflib
import hashlib
import importlib.resources
import json
import math
import os
import platform
import sys
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional, Union

import yaml
from PIL import Image

from cecli import __version__
from cecli.dump import dump
from cecli.helpers.file_searcher import handle_core_files
from cecli.helpers.model_providers import ModelProviderManager
from cecli.helpers.requests import model_request_parser
from cecli.llm import litellm
from cecli.sendchat import sanity_check_messages
from cecli.utils import check_pip_install_extra

RETRY_TIMEOUT = 60
COPY_PASTE_PREFIX = "cp:"
request_timeout = 600
DEFAULT_MODEL_NAME = "gpt-4o"
ANTHROPIC_BETA_HEADER = "prompt-caching-2024-07-31,pdfs-2024-09-25"
OPENAI_MODELS = """
o1
o1-preview
o1-mini
o3-mini
gpt-4
gpt-4o
gpt-4o-2024-05-13
gpt-4-turbo-preview
gpt-4-0314
gpt-4-0613
gpt-4-32k
gpt-4-32k-0314
gpt-4-32k-0613
gpt-4-turbo
gpt-4-turbo-2024-04-09
gpt-4-1106-preview
gpt-4-0125-preview
gpt-4-vision-preview
gpt-4-1106-vision-preview
gpt-4o-mini
gpt-4o-mini-2024-07-18
gpt-3.5-turbo
gpt-3.5-turbo-0301
gpt-3.5-turbo-0613
gpt-3.5-turbo-1106
gpt-3.5-turbo-0125
gpt-3.5-turbo-16k
gpt-3.5-turbo-16k-0613
"""
OPENAI_MODELS = [ln.strip() for ln in OPENAI_MODELS.splitlines() if ln.strip()]
ANTHROPIC_MODELS = """
claude-2
claude-2.1
claude-3-haiku-20240307
claude-3-5-haiku-20241022
claude-3-opus-20240229
claude-3-sonnet-20240229
claude-3-5-sonnet-20240620
claude-3-5-sonnet-20241022
claude-sonnet-4-20250514
claude-opus-4-20250514
"""
ANTHROPIC_MODELS = [ln.strip() for ln in ANTHROPIC_MODELS.splitlines() if ln.strip()]
MODEL_ALIASES = {
    "sonnet": "anthropic/claude-sonnet-4-20250514",
    "haiku": "claude-3-5-haiku-20241022",
    "opus": "claude-opus-4-20250514",
    "4": "gpt-4-0613",
    "4o": "gpt-4o",
    "4-turbo": "gpt-4-1106-preview",
    "35turbo": "gpt-3.5-turbo",
    "35-turbo": "gpt-3.5-turbo",
    "3": "gpt-3.5-turbo",
    "deepseek": "deepseek/deepseek-chat",
    "flash": "gemini/gemini-2.5-flash",
    "flash-lite": "gemini/gemini-2.5-flash-lite",
    "quasar": "openrouter/openrouter/quasar-alpha",
    "r1": "deepseek/deepseek-reasoner",
    "gemini-2.5-pro": "gemini/gemini-2.5-pro",
    "gemini-3-pro-preview": "gemini/gemini-3-pro-preview",
    "gemini": "gemini/gemini-3-pro-preview",
    "gemini-exp": "gemini/gemini-2.5-pro-exp-03-25",
    "grok3": "xai/grok-3-beta",
    "optimus": "openrouter/openrouter/optimus-alpha",
}


@dataclass
class ModelSettings:
    name: str
    edit_format: str = "diff"
    weak_model_name: Optional[str] = None
    use_repo_map: bool = False
    send_undo_reply: bool = False
    lazy: bool = False
    overeager: bool = False
    reminder: str = "user"
    examples_as_sys_msg: bool = False
    extra_params: Optional[dict] = None
    cache_control: bool = False
    caches_by_default: bool = False
    use_system_prompt: bool = True
    use_temperature: Union[bool, float] = True
    streaming: bool = True
    editor_model_name: Optional[str] = None
    editor_edit_format: Optional[str] = None
    reasoning_tag: Optional[str] = None
    remove_reasoning: Optional[str] = None
    system_prompt_prefix: Optional[str] = None
    accepts_settings: Optional[list] = None


MODEL_SETTINGS = []
with importlib.resources.open_text("cecli.resources", "model-settings.yml") as f:
    model_settings_list = yaml.safe_load(f)
    for model_settings_dict in model_settings_list:
        MODEL_SETTINGS.append(ModelSettings(**model_settings_dict))


class ModelInfoManager:
    MODEL_INFO_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
    CACHE_TTL = 60 * 60 * 24

    def __init__(self):
        self.cache_dir = handle_core_files(Path.home() / ".cecli" / "caches")
        self.cache_file = self.cache_dir / "model_prices_and_context_window.json"
        self.content = None
        self.local_model_metadata = {}
        self.verify_ssl = True
        self._cache_loaded = False
        self.provider_manager = ModelProviderManager()
        self.openai_provider_manager = self.provider_manager

    def set_verify_ssl(self, verify_ssl):
        self.verify_ssl = verify_ssl
        self.provider_manager.set_verify_ssl(verify_ssl)

    def _load_cache(self):
        if self._cache_loaded:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if self.cache_file.exists():
                cache_age = time.time() - self.cache_file.stat().st_mtime
                if cache_age < self.CACHE_TTL:
                    try:
                        self.content = json.loads(self.cache_file.read_text())
                    except json.JSONDecodeError:
                        self.content = None
        except OSError:
            pass
        self._cache_loaded = True

    def _update_cache(self):
        try:
            import requests

            response = requests.get(self.MODEL_INFO_URL, timeout=5, verify=self.verify_ssl)
            if response.status_code == 200:
                self.content = response.json()
                try:
                    self.cache_file.write_text(json.dumps(self.content, indent=4))
                except OSError:
                    pass
        except Exception as ex:
            print(str(ex))
            try:
                self.cache_file.write_text("{}")
            except OSError:
                pass

    def get_model_from_cached_json_db(self, model):
        data = self.local_model_metadata.get(model)
        if data:
            return data
        self._load_cache()
        if not self.content:
            self._update_cache()
        if not self.content:
            return dict()
        info = self.content.get(model, dict())
        if info:
            return info
        pieces = model.split("/")
        if len(pieces) == 2:
            info = self.content.get(pieces[1])
            if info and info.get("litellm_provider") == pieces[0]:
                return info
        return dict()

    def get_model_info(self, model):
        cached_info = self.get_model_from_cached_json_db(model)
        litellm_info = None
        if litellm._lazy_module or not cached_info:
            try:
                litellm_info = litellm.get_model_info(model)
            except Exception as ex:
                if "model_prices_and_context_window.json" not in str(ex):
                    print(str(ex))
        provider_info = self._resolve_via_provider(model, cached_info)
        if provider_info:
            return provider_info
        if litellm_info:
            return litellm_info
        return cached_info

    def _resolve_via_provider(self, model, cached_info):
        if cached_info:
            return None
        provider = model.split("/", 1)[0] if "/" in model else None
        if not self.provider_manager.supports_provider(provider):
            return None
        provider_info = self.provider_manager.get_model_info(model)
        if provider_info:
            self._record_dynamic_model(model, provider_info)
            return provider_info
        if provider == "openrouter":
            openrouter_info = self.fetch_openrouter_model_info(model)
            if openrouter_info:
                openrouter_info.setdefault("litellm_provider", "openrouter")
                self._record_dynamic_model(model, openrouter_info)
                return openrouter_info
        return None

    def _record_dynamic_model(self, model, info):
        self.local_model_metadata[model] = info
        self._ensure_model_settings_entry(model)

    def _ensure_model_settings_entry(self, model):
        if any(ms.name == model for ms in MODEL_SETTINGS):
            return
        MODEL_SETTINGS.append(ModelSettings(name=model))

    def fetch_openrouter_model_info(self, model):
        """
        Fetch model info by scraping the openrouter model page.
        Expected URL: https://openrouter.ai/<model_route>
        Example: openrouter/qwen/qwen-2.5-72b-instruct:free
        Returns a dict with keys: max_tokens, max_input_tokens, max_output_tokens,
        input_cost_per_token, output_cost_per_token.
        """
        url_part = model[len("openrouter/") :]
        url = "https://openrouter.ai/" + url_part
        try:
            import requests

            response = requests.get(url, timeout=5, verify=self.verify_ssl)
            if response.status_code != 200:
                return {}
            html = response.text
            import re

            if re.search(
                f"The model\\s*.*{re.escape(url_part)}.* is not available", html, re.IGNORECASE
            ):
                print(f"\x1b[91mError: Model '{url_part}' is not available\x1b[0m")
                return {}
            text = re.sub("<[^>]+>", " ", html)
            context_match = re.search("([\\d,]+)\\s*context", text)
            if context_match:
                context_str = context_match.group(1).replace(",", "")
                context_size = int(context_str)
            else:
                context_size = None
            input_cost_match = re.search("\\$\\s*([\\d.]+)\\s*/M input tokens", text, re.IGNORECASE)
            output_cost_match = re.search(
                "\\$\\s*([\\d.]+)\\s*/M output tokens", text, re.IGNORECASE
            )
            input_cost = float(input_cost_match.group(1)) / 1000000 if input_cost_match else None
            output_cost = float(output_cost_match.group(1)) / 1000000 if output_cost_match else None
            if context_size is None or input_cost is None or output_cost is None:
                return {}
            params = {
                "max_input_tokens": context_size,
                "max_tokens": context_size,
                "max_output_tokens": context_size,
                "input_cost_per_token": input_cost,
                "output_cost_per_token": output_cost,
                "litellm_provider": "openrouter",
            }
            return params
        except Exception as e:
            print("Error fetching openrouter info:", str(e))
            return {}


model_info_manager = ModelInfoManager()


class Model(ModelSettings):
    def __init__(
        self,
        model,
        weak_model=None,
        editor_model=None,
        editor_edit_format=None,
        verbose=False,
        io=None,
        override_kwargs=None,
    ):
        provided_model = model or ""
        if isinstance(provided_model, Model):
            provided_model = provided_model.name
        elif not isinstance(provided_model, str):
            provided_model = str(provided_model)
        self.io = io
        self.verbose = verbose
        self.override_kwargs = override_kwargs or {}
        self.copy_paste_mode = False
        self.copy_paste_transport = "api"
        if provided_model.startswith(COPY_PASTE_PREFIX):
            model = provided_model.removeprefix(COPY_PASTE_PREFIX)
            self.enable_copy_paste_mode(transport="clipboard")
        else:
            model = provided_model
        model = MODEL_ALIASES.get(model, model)
        self.name = model
        self.max_chat_history_tokens = 1024
        self.weak_model = None
        self.editor_model = None
        self.extra_model_settings = next(
            (ms for ms in MODEL_SETTINGS if ms.name == "cecli/extra_params"), None
        )
        self.info = self.get_model_info(model)
        self.litellm_provider = (self.info.get("litellm_provider") or "").lower()
        res = self.validate_environment()
        self.missing_keys = res.get("missing_keys")
        self.keys_in_environment = res.get("keys_in_environment")
        max_input_tokens = self.info.get("max_input_tokens") or 0
        self.max_chat_history_tokens = min(max(max_input_tokens / 16, 1024), 8192)
        self.configure_model_settings(model)
        self._apply_provider_defaults()
        self.get_weak_model(weak_model)
        if editor_model is False:
            self.editor_model_name = None
        else:
            self.get_editor_model(editor_model, editor_edit_format)
        if self.copy_paste_transport == "clipboard":
            self.streaming = False

    def get_model_info(self, model):
        return model_info_manager.get_model_info(model)

    def _copy_fields(self, source):
        """Helper to copy fields from a ModelSettings instance to self"""
        for field in fields(ModelSettings):
            val = getattr(source, field.name)
            setattr(self, field.name, val)
        if self.reasoning_tag is None and self.remove_reasoning is not None:
            self.reasoning_tag = self.remove_reasoning

    def configure_model_settings(self, model):
        exact_match = False
        for ms in MODEL_SETTINGS:
            if model == ms.name:
                self._copy_fields(ms)
                exact_match = True
                break
        if self.accepts_settings is None:
            self.accepts_settings = []
        model = model.lower()
        if not exact_match:
            self.apply_generic_model_settings(model)
        if (
            self.extra_model_settings
            and self.extra_model_settings.extra_params
            and self.extra_model_settings.name == "cecli/extra_params"
        ):
            if not self.extra_params:
                self.extra_params = {}
            for key, value in self.extra_model_settings.extra_params.items():
                if isinstance(value, dict) and isinstance(self.extra_params.get(key), dict):
                    self.extra_params[key] = {**self.extra_params[key], **value}
                else:
                    self.extra_params[key] = value
        if self.name.startswith("openrouter/"):
            if self.accepts_settings is None:
                self.accepts_settings = []
            if "thinking_tokens" not in self.accepts_settings:
                self.accepts_settings.append("thinking_tokens")
            if "reasoning_effort" not in self.accepts_settings:
                self.accepts_settings.append("reasoning_effort")
        if self.override_kwargs:
            if not self.extra_params:
                self.extra_params = {}
            for key, value in self.override_kwargs.items():
                if isinstance(value, dict) and isinstance(self.extra_params.get(key), dict):
                    self.extra_params[key] = {**self.extra_params[key], **value}
                else:
                    self.extra_params[key] = value

    def apply_generic_model_settings(self, model):
        if "/o3-mini" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.use_temperature = False
            self.system_prompt_prefix = "Formatting re-enabled. "
            self.system_prompt_prefix = "Formatting re-enabled. "
            if "reasoning_effort" not in self.accepts_settings:
                self.accepts_settings.append("reasoning_effort")
            return
        if "gpt-4.1-mini" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.reminder = "sys"
            self.examples_as_sys_msg = False
            return
        if "gpt-4.1" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.reminder = "sys"
            self.examples_as_sys_msg = False
            return
        last_segment = model.split("/")[-1]
        if last_segment in ("gpt-5", "gpt-5-2025-08-07") or "gpt-5.1" in model:
            self.use_temperature = False
            self.edit_format = "diff"
            if "reasoning_effort" not in self.accepts_settings:
                self.accepts_settings.append("reasoning_effort")
            return
        if "/o1-mini" in model:
            self.use_repo_map = True
            self.use_temperature = False
            self.use_system_prompt = False
            return
        if "/o1-preview" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.use_temperature = False
            self.use_system_prompt = False
            return
        if "/o1" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.use_temperature = False
            self.streaming = False
            self.system_prompt_prefix = "Formatting re-enabled. "
            if "reasoning_effort" not in self.accepts_settings:
                self.accepts_settings.append("reasoning_effort")
            return
        if "deepseek" in model and "v3" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.reminder = "sys"
            self.examples_as_sys_msg = True
            return
        if "deepseek" in model and ("r1" in model or "reasoning" in model):
            self.edit_format = "diff"
            self.use_repo_map = True
            self.examples_as_sys_msg = True
            self.use_temperature = False
            self.reasoning_tag = "think"
            return
        if ("llama3" in model or "llama-3" in model) and "70b" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.send_undo_reply = True
            self.examples_as_sys_msg = True
            return
        if "gpt-4-turbo" in model or "gpt-4-" in model and "-preview" in model:
            self.edit_format = "udiff"
            self.use_repo_map = True
            self.send_undo_reply = True
            return
        if "gpt-4" in model or "claude-3-opus" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.send_undo_reply = True
            return
        if "gpt-3.5" in model or "gpt-4" in model:
            self.reminder = "sys"
            return
        if "3-7-sonnet" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.examples_as_sys_msg = True
            self.reminder = "user"
            if "thinking_tokens" not in self.accepts_settings:
                self.accepts_settings.append("thinking_tokens")
            return
        if "3.5-sonnet" in model or "3-5-sonnet" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            self.examples_as_sys_msg = True
            self.reminder = "user"
            return
        if model.startswith("o1-") or "/o1-" in model:
            self.use_system_prompt = False
            self.use_temperature = False
            return
        if (
            "qwen" in model
            and "coder" in model
            and ("2.5" in model or "2-5" in model)
            and "32b" in model
        ):
            self.edit_format = "diff"
            self.editor_edit_format = "editor-diff"
            self.use_repo_map = True
            return
        if "qwq" in model and "32b" in model and "preview" not in model:
            self.edit_format = "diff"
            self.editor_edit_format = "editor-diff"
            self.use_repo_map = True
            self.reasoning_tag = "think"
            self.examples_as_sys_msg = True
            self.use_temperature = 0.6
            self.extra_params = dict(top_p=0.95)
            return
        if "qwen3" in model:
            self.edit_format = "diff"
            self.use_repo_map = True
            if "235b" in model:
                self.system_prompt_prefix = "/no_think"
                self.use_temperature = 0.7
                self.extra_params = {"top_p": 0.8, "top_k": 20, "min_p": 0.0}
            else:
                self.examples_as_sys_msg = True
                self.use_temperature = 0.6
                self.reasoning_tag = "think"
                self.extra_params = {"top_p": 0.95, "top_k": 20, "min_p": 0.0}
            return
        if self.edit_format == "diff":
            self.use_repo_map = True
            return

    def __str__(self):
        return self.name

    def enable_copy_paste_mode(self, *, transport="api"):
        self.copy_paste_mode = True
        self.copy_paste_transport = transport

    def get_weak_model(self, provided_weak_model):
        if provided_weak_model is False:
            self.weak_model = self
            self.weak_model_name = None
            return
        if self.copy_paste_transport == "clipboard":
            self.weak_model = self
            self.weak_model_name = None
            return
        if isinstance(provided_weak_model, Model):
            self.weak_model = provided_weak_model
            self.weak_model_name = provided_weak_model.name
            return
        if provided_weak_model:
            self.weak_model_name = provided_weak_model
        if not self.weak_model_name:
            self.weak_model = self
            return
        if self.weak_model_name == self.name:
            self.weak_model = self
            return
        self.weak_model = Model(self.weak_model_name, weak_model=False, io=self.io)
        return self.weak_model

    def commit_message_models(self):
        return [self.weak_model, self]

    def get_editor_model(self, provided_editor_model, editor_edit_format):
        if self.copy_paste_transport == "clipboard":
            provided_editor_model = False
            self.editor_model_name = self.name
            self.editor_model = self
        if isinstance(provided_editor_model, Model):
            self.editor_model = provided_editor_model
            self.editor_model_name = provided_editor_model.name
        elif provided_editor_model:
            self.editor_model_name = provided_editor_model
        if editor_edit_format:
            self.editor_edit_format = editor_edit_format
        if not self.editor_model_name or self.editor_model_name == self.name:
            self.editor_model = self
        else:
            self.editor_model = Model(self.editor_model_name, editor_model=False, io=self.io)
        if not self.editor_edit_format:
            self.editor_edit_format = self.editor_model.edit_format
            if self.editor_edit_format in ("diff", "whole", "diff-fenced"):
                self.editor_edit_format = "editor-" + self.editor_edit_format
        return self.editor_model

    def _ensure_extra_params_dict(self):
        if self.extra_params is None:
            self.extra_params = {}
        elif not isinstance(self.extra_params, dict):
            self.extra_params = dict(self.extra_params)

    def _apply_provider_defaults(self):
        provider = (self.info.get("litellm_provider") or "").lower()
        self.litellm_provider = provider or None
        if not provider:
            return
        provider_config = model_info_manager.provider_manager.get_provider_config(provider)
        if not provider_config:
            return
        self._ensure_extra_params_dict()
        self.extra_params.setdefault("custom_llm_provider", provider)
        if provider_config.get("supports_stream") is False:
            self.streaming = False
        base_url = model_info_manager.provider_manager.get_provider_base_url(provider)
        if base_url:
            self.extra_params.setdefault("base_url", base_url)
        default_headers = provider_config.get("default_headers") or {}
        if default_headers:
            headers = self.extra_params.setdefault("extra_headers", {})
            for key, value in default_headers.items():
                headers.setdefault(key, value)
        provider_extra = provider_config.get("extra_params") or {}
        for key, value in provider_extra.items():
            if key not in self.extra_params:
                self.extra_params[key] = value

    def tokenizer(self, text):
        return litellm.encode(model=self.name, text=text)

    def token_count(self, messages):
        if isinstance(messages, dict):
            messages = [messages]
        if isinstance(messages, list):
            try:
                return litellm.token_counter(model=self.name, messages=messages)
            except Exception:
                pass
        if not self.tokenizer:
            return 0
        if isinstance(messages, str):
            msgs = messages
        else:
            msgs = json.dumps(messages)
        try:
            return len(self.tokenizer(msgs))
        except Exception as err:
            print(f"Unable to count tokens with tokenizer: {err}")
            return 0

    def token_count_for_image(self, fname):
        """
        Calculate the token cost for an image assuming high detail.
        The token cost is determined by the size of the image.
        :param fname: The filename of the image.
        :return: The token cost for the image.
        """
        width, height = self.get_image_size(fname)
        max_dimension = max(width, height)
        if max_dimension > 2048:
            scale_factor = 2048 / max_dimension
            width = int(width * scale_factor)
            height = int(height * scale_factor)
        min_dimension = min(width, height)
        scale_factor = 768 / min_dimension
        width = int(width * scale_factor)
        height = int(height * scale_factor)
        tiles_width = math.ceil(width / 512)
        tiles_height = math.ceil(height / 512)
        num_tiles = tiles_width * tiles_height
        token_cost = num_tiles * 170 + 85
        return token_cost

    def get_image_size(self, fname):
        """
        Retrieve the size of an image.
        :param fname: The filename of the image.
        :return: A tuple (width, height) representing the image size in pixels.
        """
        with Image.open(fname) as img:
            return img.size

    def fast_validate_environment(self):
        """Fast path for common models. Avoids forcing litellm import."""
        model = self.name
        pieces = model.split("/")
        if len(pieces) > 1:
            provider = pieces[0]
        else:
            provider = None
        keymap = dict(
            openrouter="OPENROUTER_API_KEY",
            openai="OPENAI_API_KEY",
            deepseek="DEEPSEEK_API_KEY",
            gemini="GEMINI_API_KEY",
            anthropic="ANTHROPIC_API_KEY",
            groq="GROQ_API_KEY",
            fireworks_ai="FIREWORKS_API_KEY",
        )
        var = None
        if model in OPENAI_MODELS:
            var = "OPENAI_API_KEY"
        elif model in ANTHROPIC_MODELS:
            var = "ANTHROPIC_API_KEY"
        else:
            var = keymap.get(provider)
        if var and os.environ.get(var):
            return dict(keys_in_environment=[var], missing_keys=[])
        if not var and provider and model_info_manager.provider_manager.supports_provider(provider):
            provider_keys = model_info_manager.provider_manager.get_required_api_keys(provider)
            for env_var in provider_keys:
                if os.environ.get(env_var):
                    return dict(keys_in_environment=[env_var], missing_keys=[])

    def validate_environment(self):
        res = self.fast_validate_environment()
        if res:
            return res
        model = self.name
        res = litellm.validate_environment(model)
        if res["missing_keys"] and any(
            key in ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"] for key in res["missing_keys"]
        ):
            if model.startswith("bedrock/") or model.startswith("us.anthropic."):
                if os.environ.get("AWS_PROFILE"):
                    res["missing_keys"] = [
                        k
                        for k in res["missing_keys"]
                        if k not in ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
                    ]
                    if not res["missing_keys"]:
                        res["keys_in_environment"] = True
        if res["keys_in_environment"]:
            return res
        if res["missing_keys"]:
            return res
        provider = self.info.get("litellm_provider", "").lower()
        provider_config = model_info_manager.provider_manager.get_provider_config(provider)
        if provider_config:
            envs = provider_config.get("api_key_env", [])
            available = [env for env in envs if os.environ.get(env)]
            if available:
                return dict(keys_in_environment=available, missing_keys=[])
            if envs:
                return dict(keys_in_environment=False, missing_keys=envs)
        if provider == "cohere_chat":
            return validate_variables(["COHERE_API_KEY"])
        if provider == "gemini":
            return validate_variables(["GEMINI_API_KEY"])
        if provider == "groq":
            return validate_variables(["GROQ_API_KEY"])
        return res

    def get_repo_map_tokens(self):
        map_tokens = 1024
        max_inp_tokens = self.info.get("max_input_tokens")
        if max_inp_tokens:
            map_tokens = max_inp_tokens / 8
            map_tokens = min(map_tokens, 4096)
            map_tokens = max(map_tokens, 1024)
        return map_tokens

    def set_reasoning_effort(self, effort):
        """Set the reasoning effort parameter for models that support it"""
        if effort is not None:
            if self.name.startswith("openrouter/"):
                if not self.extra_params:
                    self.extra_params = {}
                if "extra_body" not in self.extra_params:
                    self.extra_params["extra_body"] = {}
                self.extra_params["extra_body"]["reasoning"] = {"effort": effort}
            else:
                if not self.extra_params:
                    self.extra_params = {}
                if "extra_body" not in self.extra_params:
                    self.extra_params["extra_body"] = {}
                self.extra_params["extra_body"]["reasoning_effort"] = effort

    def parse_token_value(self, value):
        """
        Parse a token value string into an integer.
        Accepts formats: 8096, "8k", "10.5k", "0.5M", "10K", etc.

        Args:
            value: String or int token value

        Returns:
            Integer token value
        """
        if isinstance(value, int):
            return value
        if not isinstance(value, str):
            return int(value)
        value = value.strip().upper()
        if value.endswith("K"):
            multiplier = 1024
            value = value[:-1]
        elif value.endswith("M"):
            multiplier = 1024 * 1024
            value = value[:-1]
        else:
            multiplier = 1
        return int(float(value) * multiplier)

    def set_thinking_tokens(self, value):
        """
        Set the thinking token budget for models that support it.
        Accepts formats: 8096, "8k", "10.5k", "0.5M", "10K", etc.
        Pass "0" to disable thinking tokens.
        """
        if value is not None:
            num_tokens = self.parse_token_value(value)
            self.use_temperature = False
            if not self.extra_params:
                self.extra_params = {}
            if self.name.startswith("openrouter/"):
                if "extra_body" not in self.extra_params:
                    self.extra_params["extra_body"] = {}
                if num_tokens > 0:
                    self.extra_params["extra_body"]["reasoning"] = {"max_tokens": num_tokens}
                elif "reasoning" in self.extra_params["extra_body"]:
                    del self.extra_params["extra_body"]["reasoning"]
            elif num_tokens > 0:
                self.extra_params["thinking"] = {"type": "enabled", "budget_tokens": num_tokens}
            elif "thinking" in self.extra_params:
                del self.extra_params["thinking"]

    def get_raw_thinking_tokens(self):
        """Get formatted thinking token budget if available"""
        budget = None
        if self.extra_params:
            if self.name.startswith("openrouter/"):
                if (
                    "extra_body" in self.extra_params
                    and "reasoning" in self.extra_params["extra_body"]
                    and "max_tokens" in self.extra_params["extra_body"]["reasoning"]
                ):
                    budget = self.extra_params["extra_body"]["reasoning"]["max_tokens"]
            elif (
                "thinking" in self.extra_params and "budget_tokens" in self.extra_params["thinking"]
            ):
                budget = self.extra_params["thinking"]["budget_tokens"]
        return budget

    def get_thinking_tokens(self):
        budget = self.get_raw_thinking_tokens()
        if budget is not None:
            if budget >= 1024 * 1024:
                value = budget / (1024 * 1024)
                if value == int(value):
                    return f"{int(value)}M"
                else:
                    return f"{value:.1f}M"
            else:
                value = budget / 1024
                if value == int(value):
                    return f"{int(value)}k"
                else:
                    return f"{value:.1f}k"
        return None

    def get_reasoning_effort(self):
        """Get reasoning effort value if available"""
        if self.extra_params:
            if self.name.startswith("openrouter/"):
                if (
                    "extra_body" in self.extra_params
                    and "reasoning" in self.extra_params["extra_body"]
                    and "effort" in self.extra_params["extra_body"]["reasoning"]
                ):
                    return self.extra_params["extra_body"]["reasoning"]["effort"]
            elif (
                "extra_body" in self.extra_params
                and "reasoning_effort" in self.extra_params["extra_body"]
            ):
                return self.extra_params["extra_body"]["reasoning_effort"]
        return None

    def is_deepseek(self):
        name = self.name.lower()
        if "deepseek" not in name:
            return
        return True

    def is_anthropic(self):
        name = self.name.lower()
        if "claude" not in name:
            return
        return True

    def is_ollama(self):
        return self.name.startswith("ollama/") or self.name.startswith("ollama_chat/")

    async def send_completion(
        self, messages, functions, stream, temperature=None, tools=None, max_tokens=None
    ):
        if os.environ.get("CECLI_SANITY_CHECK_TURNS"):
            sanity_check_messages(messages)
        messages = model_request_parser(self, messages)
        if self.verbose:
            for message in messages:
                msg_role = message.get("role")
                msg_content = message.get("content") if message.get("content") else ""
                msg_trunc = ""
                if message.get("content"):
                    msg_trunc = message.get("content")[:30]
                print(f"{msg_role} ({len(msg_content)}): {msg_trunc}")
        kwargs = dict(model=self.name, stream=stream)
        if self.use_temperature is not False:
            if temperature is None:
                if isinstance(self.use_temperature, bool):
                    temperature = 0
                else:
                    temperature = float(self.use_temperature)
            kwargs["temperature"] = temperature
        effective_tools = tools
        if effective_tools is None and functions:
            effective_tools = [dict(type="function", function=f) for f in functions]
        if effective_tools:
            kwargs["tools"] = effective_tools
        if functions and len(functions) == 1:
            function = functions[0]
            if "name" in function:
                tool_name = function.get("name")
                if tool_name:
                    kwargs["tool_choice"] = {"type": "function", "function": {"name": tool_name}}
        if self.extra_params:
            kwargs.update(self.extra_params)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if "max_tokens" in kwargs and kwargs["max_tokens"]:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        if self.is_ollama() and "num_ctx" not in kwargs:
            num_ctx = int(self.token_count(messages) * 1.25) + 8192
            kwargs["num_ctx"] = num_ctx
        key = json.dumps(kwargs, sort_keys=True).encode()
        hash_object = hashlib.sha1(key)
        if "timeout" not in kwargs:
            kwargs["timeout"] = request_timeout
        if self.verbose:
            dump(kwargs)
        kwargs["messages"] = messages
        if not self.is_anthropic():
            kwargs["cache_control_injection_points"] = [
                {"location": "message", "role": "system"},
                {"location": "message", "index": -1},
                {"location": "message", "index": -2},
            ]
        if "GITHUB_COPILOT_TOKEN" in os.environ or self.name.startswith("github_copilot/"):
            if "extra_headers" not in kwargs:
                kwargs["extra_headers"] = {
                    "Editor-Version": f"cecli/{__version__}",
                    "Copilot-Integration-Id": "vscode-chat",
                }
        try:
            res = await litellm.acompletion(**kwargs)
        except Exception as err:
            print(f"LiteLLM API Error: {str(err)}")
            res = self.model_error_response()
            if self.verbose:
                print(f"LiteLLM API Error: {str(err)}")
                raise
        return hash_object, res

    async def simple_send_with_retries(self, messages, max_tokens=None):
        from cecli.exceptions import LiteLLMExceptions

        litellm_ex = LiteLLMExceptions()
        messages = model_request_parser(self, messages)
        retry_delay = 0.125
        if self.verbose:
            dump(messages)
        while True:
            try:
                _hash, response = await self.send_completion(
                    messages=messages, functions=None, stream=False, max_tokens=max_tokens
                )
                if not response or not hasattr(response, "choices") or not response.choices:
                    return None
                res = response.choices[0].message.content
                from cecli.reasoning_tags import remove_reasoning_content

                return remove_reasoning_content(res, self.reasoning_tag)
            except litellm_ex.exceptions_tuple() as err:
                ex_info = litellm_ex.get_ex_info(err)
                print(str(err))
                if ex_info.description:
                    print(ex_info.description)
                should_retry = ex_info.retry
                if should_retry:
                    retry_delay *= 2
                    if retry_delay > RETRY_TIMEOUT:
                        should_retry = False
                if not should_retry:
                    return None
                print(f"Retrying in {retry_delay:.1f} seconds...")
                time.sleep(retry_delay)
                continue
            except AttributeError:
                return None

    async def model_error_response(self):
        for i in range(1):
            await asyncio.sleep(0.1)
            yield litellm.ModelResponse(
                choices=[
                    litellm.Choices(
                        finish_reason="stop",
                        index=0,
                        message=litellm.Message(
                            content="Model API Response Error. Please retry the previous request"
                        ),
                    )
                ],
                model=self.name,
            )


def register_models(model_settings_fnames):
    files_loaded = []
    for model_settings_fname in model_settings_fnames:
        if not os.path.exists(model_settings_fname):
            continue
        if not Path(model_settings_fname).read_text().strip():
            continue
        try:
            with open(model_settings_fname, "r") as model_settings_file:
                model_settings_list = yaml.safe_load(model_settings_file)
            for model_settings_dict in model_settings_list:
                model_settings = ModelSettings(**model_settings_dict)
                MODEL_SETTINGS[:] = [ms for ms in MODEL_SETTINGS if ms.name != model_settings.name]
                MODEL_SETTINGS.append(model_settings)
        except Exception as e:
            raise Exception(f"Error loading model settings from {model_settings_fname}: {e}")
        files_loaded.append(model_settings_fname)
    return files_loaded


def register_litellm_models(model_fnames):
    files_loaded = []
    for model_fname in model_fnames:
        if not os.path.exists(model_fname):
            continue
        try:
            data = Path(model_fname).read_text()
            if not data.strip():
                continue
            model_def = json.loads(data)
            if not model_def:
                continue
            model_info_manager.local_model_metadata.update(model_def)
        except Exception as e:
            raise Exception(f"Error loading model definition from {model_fname}: {e}")
        files_loaded.append(model_fname)
    return files_loaded


def validate_variables(vars):
    missing = []
    for var in vars:
        if var not in os.environ:
            missing.append(var)
    if missing:
        return dict(keys_in_environment=False, missing_keys=missing)
    return dict(keys_in_environment=True, missing_keys=missing)


async def sanity_check_models(io, main_model):
    problem_main = await sanity_check_model(io, main_model)
    problem_weak = None
    if main_model.weak_model and main_model.weak_model is not main_model:
        problem_weak = await sanity_check_model(io, main_model.weak_model)
    problem_editor = None
    if (
        main_model.editor_model
        and main_model.editor_model is not main_model
        and main_model.editor_model is not main_model.weak_model
    ):
        problem_editor = await sanity_check_model(io, main_model.editor_model)
    return problem_main or problem_weak or problem_editor


async def sanity_check_model(io, model):
    if getattr(model, "copy_paste_transport", "api") == "clipboard":
        return False
    show = False
    if model.missing_keys:
        show = True
        io.tool_warning(f"Warning: {model} expects these environment variables")
        for key in model.missing_keys:
            value = os.environ.get(key, "")
            status = "Set" if value else "Not set"
            io.tool_output(f"- {key}: {status}")
        if platform.system() == "Windows":
            io.tool_output(
                "Note: You may need to restart your terminal or command prompt for `setx` to take"
                " effect."
            )
    elif not model.keys_in_environment:
        show = True
        io.tool_warning(f"Warning for {model}: Unknown which environment variables are required.")
    await check_for_dependencies(io, model.name)
    if not model.info:
        show = True
        io.tool_warning(
            f"Warning for {model}: Unknown context window size and costs, using sane defaults."
        )
        possible_matches = fuzzy_match_models(model.name)
        if possible_matches:
            io.tool_output("Did you mean one of these?")
            for match in possible_matches:
                io.tool_output(f"- {match}")
    return show


async def check_for_dependencies(io, model_name):
    """
    Check for model-specific dependencies and install them if needed.

    Args:
        io: The IO object for user interaction
        model_name: The name of the model to check dependencies for
    """
    if model_name.startswith("bedrock/"):
        await check_pip_install_extra(
            io, "boto3", "AWS Bedrock models require the boto3 package.", ["boto3"]
        )
    elif model_name.startswith("vertex_ai/"):
        await check_pip_install_extra(
            io,
            "google.cloud.aiplatform",
            "Google Vertex AI models require the google-cloud-aiplatform package.",
            ["google-cloud-aiplatform"],
        )


def get_chat_model_names():
    chat_models = set()
    model_metadata = list(litellm.model_cost.items())
    model_metadata += list(model_info_manager.local_model_metadata.items())
    openai_provider_models = model_info_manager.provider_manager.get_models_for_listing()
    model_metadata += list(openai_provider_models.items())
    for orig_model, attrs in model_metadata:
        if attrs.get("mode") != "chat":
            continue
        provider = (attrs.get("litellm_provider") or "").lower()
        if provider:
            prefix = provider + "/"
            if orig_model.lower().startswith(prefix):
                fq_model = orig_model
            else:
                fq_model = f"{provider}/{orig_model}"
            chat_models.add(fq_model)
        chat_models.add(orig_model)
    return sorted(chat_models)


def fuzzy_match_models(name):
    name = name.lower()
    chat_models = get_chat_model_names()
    matching_models = [m for m in chat_models if name in m.lower()]
    if matching_models:
        return sorted(set(matching_models))
    models = set(chat_models)
    matching_models = difflib.get_close_matches(name, models, n=3, cutoff=0.8)
    return sorted(set(matching_models))


def print_matching_models(io, search):
    matches = fuzzy_match_models(search)
    if matches:
        io.tool_output(f'Models which match "{search}":')
        for model in matches:
            # Get model info to check for prices
            info = model_info_manager.get_model_info(model)

            # Build price string
            price_parts = []

            # Check for input cost
            input_cost = info.get("input_cost_per_token")
            if input_cost is not None:
                # Convert from per-token to per-1M tokens
                input_cost_per_1m = input_cost * 1000000
                price_parts.append(f"${input_cost_per_1m:.2f}/1m/input")

            # Check for output cost
            output_cost = info.get("output_cost_per_token")
            if output_cost is not None:
                # Convert from per-token to per-1M tokens
                output_cost_per_1m = output_cost * 1000000
                price_parts.append(f"${output_cost_per_1m:.2f}/1m/output")

            # Check for cache cost (if available)
            cache_cost = info.get("cache_cost_per_token")
            if cache_cost is not None:
                # Convert from per-token to per-1M tokens
                cache_cost_per_1m = cache_cost * 1000000
                price_parts.append(f"${cache_cost_per_1m:.2f}/1m/cache")

            # Format the output
            if price_parts:
                price_str = " (" + ", ".join(price_parts) + ")"
                io.tool_output(f"- {model}{price_str}")
            else:
                io.tool_output(f"- {model}")
    else:
        io.tool_output(f'No models match "{search}".')


def get_model_settings_as_yaml():
    from dataclasses import fields

    import yaml

    model_settings_list = []
    defaults = {}
    for field in fields(ModelSettings):
        defaults[field.name] = field.default
    defaults["name"] = "(default values)"
    model_settings_list.append(defaults)
    for ms in sorted(MODEL_SETTINGS, key=lambda x: x.name):
        model_settings_dict = {}
        for field in fields(ModelSettings):
            value = getattr(ms, field.name)
            if value != field.default:
                model_settings_dict[field.name] = value
        model_settings_list.append(model_settings_dict)
        model_settings_list.append(None)
    yaml_str = yaml.dump(
        [ms for ms in model_settings_list if ms is not None],
        default_flow_style=False,
        sort_keys=False,
    )
    return yaml_str.replace("\n- ", "\n\n- ")


def main():
    if len(sys.argv) < 2:
        print("Usage: python models.py <model_name> or python models.py --yaml")
        sys.exit(1)
    if sys.argv[1] == "--yaml":
        yaml_string = get_model_settings_as_yaml()
        print(yaml_string)
    else:
        model_name = sys.argv[1]
        matching_models = fuzzy_match_models(model_name)
        if matching_models:
            print(f"Matching models for '{model_name}':")
            for model in matching_models:
                print(model)
        else:
            print(f"No matching models found for '{model_name}'.")


if __name__ == "__main__":
    main()
