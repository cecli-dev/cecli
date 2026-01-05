import json
import sys
import types


def _install_stubs():
    if "PIL" not in sys.modules:
        pil_module = types.ModuleType("PIL")
        image_module = types.ModuleType("PIL.Image")
        image_grab_module = types.ModuleType("PIL.ImageGrab")

        class _DummyImage:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            @property
            def size(self):
                return (1024, 1024)

        def _dummy_open(*args, **kwargs):
            return _DummyImage()

        image_module.open = _dummy_open
        image_grab_module.grab = _dummy_open
        pil_module.Image = image_module
        pil_module.ImageGrab = image_grab_module
        sys.modules["PIL"] = pil_module
        sys.modules["PIL.Image"] = image_module
        sys.modules["PIL.ImageGrab"] = image_grab_module

    if "numpy" not in sys.modules:
        numpy_module = types.ModuleType("numpy")
        numpy_module.ndarray = object
        numpy_module.array = lambda *a, **k: None
        numpy_module.dot = lambda *a, **k: 0.0
        numpy_module.linalg = types.SimpleNamespace(norm=lambda *a, **k: 1.0)
        sys.modules["numpy"] = numpy_module

    if "oslex" not in sys.modules:
        oslex_module = types.ModuleType("oslex")
        oslex_module.__all__ = []
        sys.modules["oslex"] = oslex_module

    if "rich" not in sys.modules:
        rich_module = types.ModuleType("rich")
        console_module = types.ModuleType("rich.console")

        class _DummyConsole:
            def __init__(self, *args, **kwargs):
                pass

            def status(self, *args, **kwargs):
                return self

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def update(self, *args, **kwargs):
                return None

        console_module.Console = _DummyConsole
        rich_module.console = console_module
        sys.modules["rich"] = rich_module
        sys.modules["rich.console"] = console_module

    if "pyperclip" not in sys.modules:
        pyperclip_module = types.ModuleType("pyperclip")

        class _DummyPyperclipException(Exception):
            pass

        pyperclip_module.PyperclipException = _DummyPyperclipException
        pyperclip_module.copy = lambda *args, **kwargs: None
        sys.modules["pyperclip"] = pyperclip_module

    if "pexpect" not in sys.modules:
        pexpect_module = types.ModuleType("pexpect")

        class _DummySpawn:
            def __init__(self, *args, **kwargs):
                pass

            def sendline(self, *args, **kwargs):
                return 0

            def close(self, *args, **kwargs):
                return 0

        pexpect_module.spawn = _DummySpawn
        sys.modules["pexpect"] = pexpect_module

    if "psutil" not in sys.modules:
        psutil_module = types.ModuleType("psutil")

        class _DummyProcess:
            def __init__(self, *args, **kwargs):
                pass

            def children(self, *args, **kwargs):
                return []

            def terminate(self):
                return None

        psutil_module.Process = _DummyProcess
        sys.modules["psutil"] = psutil_module

    if "pypandoc" not in sys.modules:
        pypandoc_module = types.ModuleType("pypandoc")
        pypandoc_module.convert_text = lambda *args, **kwargs: ""
        sys.modules["pypandoc"] = pypandoc_module


_install_stubs()

from cecli.helpers.model_providers import ModelProviderManager  # noqa: E402
from cecli.models import MODEL_SETTINGS, Model, ModelInfoManager  # noqa: E402


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _make_manager(tmp_path, config):
    manager = ModelProviderManager(provider_configs=config)
    manager.cache_dir = tmp_path  # Avoid touching real home dir
    return manager


def test_model_provider_matches_suffix_variants(monkeypatch, tmp_path):
    payload = {
        "data": [
            {
                "id": "demo/model",
                "context_length": 2048,
                "pricing": {"prompt": "1.0", "completion": "2.0"},
            }
        ]
    }

    config = {
        "openrouter": {
            "api_base": "https://openrouter.ai/api/v1",
            "models_url": "https://openrouter.ai/api/v1/models",
            "requires_api_key": False,
        }
    }

    manager = _make_manager(tmp_path, config)
    cache_file = manager._get_cache_file("openrouter")
    cache_file.write_text(json.dumps(payload))
    manager._cache_loaded["openrouter"] = True
    manager._provider_cache["openrouter"] = payload

    info = manager.get_model_info("openrouter/demo/model:extended")

    assert info["max_input_tokens"] == 2048
    assert info["input_cost_per_token"] == 1.0 / manager.DEFAULT_TOKEN_PRICE_RATIO
    assert info["litellm_provider"] == "openrouter"


def test_model_provider_uses_top_provider_context(tmp_path):
    payload = {
        "data": [
            {
                "id": "demo/model",
                "top_provider": {"context_length": 4096},
                "pricing": {"prompt": "3", "completion": "4"},
            }
        ]
    }

    config = {
        "demo": {
            "api_base": "https://example.com/v1",
            "models_url": "https://example.com/v1/models",
            "requires_api_key": False,
        }
    }

    manager = _make_manager(tmp_path, config)
    cache_file = manager._get_cache_file("demo")
    cache_file.write_text(json.dumps(payload))
    manager._cache_loaded["demo"] = True
    manager._provider_cache["demo"] = payload

    info = manager.get_model_info("demo/demo/model")

    assert info["max_input_tokens"] == 4096
    assert info["max_tokens"] == 4096
    assert info["max_output_tokens"] == 4096


def test_fetch_provider_models_injects_headers(monkeypatch, tmp_path):
    payload = {"data": []}
    captured = {}

    def _fake_get(url, *, headers=None, timeout=None, verify=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["verify"] = verify
        return DummyResponse(payload)

    monkeypatch.setattr("requests.get", _fake_get)

    config = {
        "demo": {
            "api_base": "https://example.com/v1",
            "default_headers": {"X-Test": "demo"},
            "requires_api_key": False,
        }
    }

    manager = _make_manager(tmp_path, config)
    manager.set_verify_ssl(False)

    result = manager._fetch_provider_models("demo")

    assert result == payload
    assert captured["url"] == "https://example.com/v1/models"
    assert captured["headers"] == {"X-Test": "demo"}
    assert captured["timeout"] == 10
    assert captured["verify"] is False


def test_get_api_key_prefers_first_valid(monkeypatch, tmp_path):
    config = {
        "demo": {
            "api_base": "https://example.com/v1",
            "api_key_env": ["DEMO_FALLBACK", "DEMO_KEY"],
            "requires_api_key": True,
        }
    }

    manager = _make_manager(tmp_path, config)
    monkeypatch.delenv("DEMO_FALLBACK", raising=False)
    monkeypatch.setenv("DEMO_KEY", "secret")

    assert manager._get_api_key("demo") == "secret"


def test_refresh_provider_cache_uses_static_models(monkeypatch, tmp_path):
    config = {
        "demo": {
            "api_base": "https://example.com/v1",
            "static_models": [
                {
                    "id": "demo/foo",
                    "max_input_tokens": 1024,
                    "pricing": {"prompt": "0.5", "completion": "1.0"},
                }
            ],
        }
    }

    manager = _make_manager(tmp_path, config)

    def _failing_fetch(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("requests.get", _failing_fetch)

    refreshed = manager.refresh_provider_cache("demo")

    assert refreshed is True
    info = manager.get_model_info("demo/demo/foo")
    assert info["max_input_tokens"] == 1024
    assert info["input_cost_per_token"] == 0.5 / manager.DEFAULT_TOKEN_PRICE_RATIO


def test_pricing_normalization_detects_token_format(tmp_path):
    """Test that pricing < 0.001 is treated as $/token, not $/M."""
    payload = {
        "data": [
            {
                "id": "demo/model",
                "context_length": 2048,
                # Pricing in $/token format (like synthetic provider)
                "pricing": {"prompt": "0.00000055", "completion": "0.00000219"},
            }
        ]
    }

    config = {
        "demo": {
            "api_base": "https://example.com/v1",
            "requires_api_key": False,
        }
    }

    manager = _make_manager(tmp_path, config)
    cache_file = manager._get_cache_file("demo")
    cache_file.write_text(json.dumps(payload))
    manager._cache_loaded["demo"] = True
    manager._provider_cache["demo"] = payload

    info = manager.get_model_info("demo/demo/model")

    assert info["max_input_tokens"] == 2048
    # Values < 0.001 should NOT be divided (already in $/token format)
    assert info["input_cost_per_token"] == 0.00000055
    assert info["output_cost_per_token"] == 0.00000219


def test_pricing_normalization_detects_million_format(tmp_path):
    """Test that pricing >= 0.001 is treated as $/M and converted to $/token."""
    payload = {
        "data": [
            {
                "id": "demo/model",
                "context_length": 2048,
                # Pricing in $/M format (like some providers)
                "pricing": {"prompt": "1.0", "completion": "2.0"},
            }
        ]
    }

    config = {
        "demo": {
            "api_base": "https://example.com/v1",
            "requires_api_key": False,
        }
    }

    manager = _make_manager(tmp_path, config)
    cache_file = manager._get_cache_file("demo")
    cache_file.write_text(json.dumps(payload))
    manager._cache_loaded["demo"] = True
    manager._provider_cache["demo"] = payload

    info = manager.get_model_info("demo/demo/model")

    assert info["max_input_tokens"] == 2048
    # Values >= 0.001 should be divided by 1000000 (convert $/M to $/token)
    assert info["input_cost_per_token"] == 1.0 / manager.DEFAULT_TOKEN_PRICE_RATIO
    assert info["output_cost_per_token"] == 2.0 / manager.DEFAULT_TOKEN_PRICE_RATIO


def test_model_info_manager_delegates_to_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cecli.models.litellm",
        types.SimpleNamespace(
            _lazy_module=None,
            get_model_info=lambda *a, **k: {},
            validate_environment=lambda model: {"keys_in_environment": True, "missing_keys": []},
            encode=lambda *a, **k: [],
            token_counter=lambda *a, **k: 0,
        ),
    )

    stub_info = {
        "max_input_tokens": 512,
        "max_tokens": 512,
        "max_output_tokens": 512,
        "input_cost_per_token": 1.0,
        "output_cost_per_token": 2.0,
        "litellm_provider": "openrouter",
    }

    monkeypatch.setattr(
        "cecli.helpers.model_providers.ModelProviderManager.supports_provider",
        lambda self, provider: provider == "openrouter",
    )
    monkeypatch.setattr(
        "cecli.helpers.model_providers.ModelProviderManager.get_model_info",
        lambda self, model: stub_info,
    )

    mim = ModelInfoManager()
    info = mim.get_model_info("openrouter/demo/model")

    assert info == stub_info


def test_model_dynamic_settings_added(monkeypatch, tmp_path):
    provider = "demo"
    model_name = "demo/org/foo"
    manager = ModelInfoManager()

    def _fake_supports(self, prov):
        return prov == provider

    def _fake_get(self, model):
        return {
            "max_input_tokens": 2048,
            "max_tokens": 2048,
            "max_output_tokens": 2048,
            "litellm_provider": provider,
        }

    monkeypatch.setattr(
        "cecli.helpers.model_providers.ModelProviderManager.supports_provider",
        _fake_supports,
    )
    monkeypatch.setattr(
        "cecli.helpers.model_providers.ModelProviderManager.get_model_info",
        _fake_get,
    )
    monkeypatch.setattr(
        "cecli.models.litellm",
        types.SimpleNamespace(
            _lazy_module=None,
            get_model_info=lambda *a, **k: {},
            validate_environment=lambda model: {"keys_in_environment": True, "missing_keys": []},
            encode=lambda *a, **k: [],
            token_counter=lambda *a, **k: 0,
        ),
    )

    assert not any(ms.name == model_name for ms in MODEL_SETTINGS)

    info = manager.get_model_info(model_name)
    assert info["max_tokens"] == 2048

    assert any(ms.name == model_name for ms in MODEL_SETTINGS)

    model = Model(model_name)
    assert model.info["max_tokens"] == 2048


def test_get_account_id_from_env(monkeypatch, tmp_path):
    config = {
        "fireworks_ai": {
            "api_base": "https://api.fireworks.ai/inference/v1",
            "api_key_env": ["FIREWORKS_AI_API_KEY"],
            "account_id_env": "FIREWORKS_AI_ACCOUNT_ID",
        }
    }

    manager = _make_manager(tmp_path, config)
    monkeypatch.setenv("FIREWORKS_AI_ACCOUNT_ID", "test-account-123")

    assert manager._get_account_id("fireworks_ai") == "test-account-123"


def test_get_account_id_missing_env(monkeypatch, tmp_path):
    config = {
        "fireworks_ai": {
            "api_base": "https://api.fireworks.ai/inference/v1",
            "api_key_env": ["FIREWORKS_AI_API_KEY"],
            "account_id_env": "FIREWORKS_AI_ACCOUNT_ID",
        }
    }

    manager = _make_manager(tmp_path, config)
    monkeypatch.delenv("FIREWORKS_AI_ACCOUNT_ID", raising=False)

    assert manager._get_account_id("fireworks_ai") is None


def test_get_account_id_no_config(tmp_path):
    config = {
        "demo": {
            "api_base": "https://example.com/v1",
            "api_key_env": ["DEMO_KEY"],
        }
    }

    manager = _make_manager(tmp_path, config)

    assert manager._get_account_id("demo") is None


def test_models_url_account_id_substitution(monkeypatch, tmp_path):
    config = {
        "fireworks_ai": {
            "api_base": "https://api.fireworks.ai/inference/v1",
            "api_key_env": ["FIREWORKS_AI_API_KEY"],
            "models_url": "https://api.fireworks.ai/v1/accounts/{account_id}/models",
            "account_id_env": "FIREWORKS_AI_ACCOUNT_ID",
            "requires_api_key": False,
        }
    }

    manager = _make_manager(tmp_path, config)
    monkeypatch.setenv("FIREWORKS_AI_ACCOUNT_ID", "my-account-id")

    captured = {}

    def _fake_get(url, *, headers=None, timeout=None, verify=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["verify"] = verify
        return DummyResponse({"data": []})

    monkeypatch.setattr("requests.get", _fake_get)

    manager._fetch_provider_models("fireworks_ai")

    assert captured["url"] == "https://api.fireworks.ai/v1/accounts/my-account-id/models"


def test_models_url_account_id_missing_skips_fetch(monkeypatch, tmp_path, capsys):
    config = {
        "fireworks_ai": {
            "api_base": "https://api.fireworks.ai/inference/v1",
            "api_key_env": ["FIREWORKS_AI_API_KEY"],
            "models_url": "https://api.fireworks.ai/v1/accounts/{account_id}/models",
            "account_id_env": "FIREWORKS_AI_ACCOUNT_ID",
            "requires_api_key": False,
        }
    }

    manager = _make_manager(tmp_path, config)
    monkeypatch.delenv("FIREWORKS_AI_ACCOUNT_ID", raising=False)

    assert manager._fetch_provider_models("fireworks_ai") is None

    captured = capsys.readouterr()
    assert "account_id_env not set" in captured.out


def test_models_url_without_placeholder_unchanged(monkeypatch, tmp_path):
    config = {
        "demo": {
            "api_base": "https://example.com/v1",
            "api_key_env": ["DEMO_KEY"],
            "models_url": "https://example.com/v1/models",
            "requires_api_key": False,
        }
    }

    manager = _make_manager(tmp_path, config)

    captured = {}

    def _fake_get(url, *, headers=None, timeout=None, verify=None):
        captured["url"] = url
        return DummyResponse({"data": []})

    monkeypatch.setattr("requests.get", _fake_get)

    manager._fetch_provider_models("demo")

    assert captured["url"] == "https://example.com/v1/models"
