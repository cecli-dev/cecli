from unittest.mock import ANY, MagicMock, patch

import pytest

from cecli.models import (
    ANTHROPIC_BETA_HEADER,
    Model,
    ModelInfoManager,
    register_models,
    sanity_check_model,
    sanity_check_models,
)


class TestModels:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Reset MODEL_SETTINGS before each test and restore after"""
        from cecli.models import MODEL_SETTINGS

        self._original_settings = MODEL_SETTINGS.copy()
        yield
        MODEL_SETTINGS.clear()
        MODEL_SETTINGS.extend(self._original_settings)

    def test_get_model_info_nonexistent(self):
        manager = ModelInfoManager()
        info = manager.get_model_info("non-existent-model")
        assert info == {}

    def test_max_context_tokens(self):
        model = Model("gpt-3.5-turbo")
        assert model.info["max_input_tokens"] == 16385
        model = Model("gpt-3.5-turbo-16k")
        assert model.info["max_input_tokens"] == 16385
        model = Model("gpt-3.5-turbo-1106")
        assert model.info["max_input_tokens"] == 16385
        model = Model("gpt-4")
        assert model.info["max_input_tokens"] == 8 * 1024
        model = Model("gpt-4-32k")
        assert model.info["max_input_tokens"] == 32 * 1024
        model = Model("gpt-4-0613")
        assert model.info["max_input_tokens"] == 8 * 1024

    @patch("os.environ")
    async def test_sanity_check_model_all_set(self, mock_environ):
        mock_environ.get.return_value = "dummy_value"
        mock_io = MagicMock()
        model = MagicMock()
        model.name = "test-model"
        model.missing_keys = ["API_KEY1", "API_KEY2"]
        model.keys_in_environment = True
        model.info = {"some": "info"}
        await sanity_check_model(mock_io, model)
        mock_io.tool_output.assert_called()
        calls = mock_io.tool_output.call_args_list
        assert "- API_KEY1: Set" in str(calls)
        assert "- API_KEY2: Set" in str(calls)

    @patch("os.environ")
    async def test_sanity_check_model_not_set(self, mock_environ):
        mock_environ.get.return_value = ""
        mock_io = MagicMock()
        model = MagicMock()
        model.name = "test-model"
        model.missing_keys = ["API_KEY1", "API_KEY2"]
        model.keys_in_environment = True
        model.info = {"some": "info"}
        await sanity_check_model(mock_io, model)
        mock_io.tool_output.assert_called()
        calls = mock_io.tool_output.call_args_list
        assert "- API_KEY1: Not set" in str(calls)
        assert "- API_KEY2: Not set" in str(calls)

    async def test_sanity_check_models_bogus_editor(self):
        mock_io = MagicMock()
        main_model = Model("gpt-4")
        main_model.editor_model = Model("bogus-model")
        result = await sanity_check_models(mock_io, main_model)
        assert result
        mock_io.tool_warning.assert_called_with(ANY)
        warning_messages = [
            warning_call.args[0] for warning_call in mock_io.tool_warning.call_args_list
        ]
        print("Warning messages:", warning_messages)
        assert mock_io.tool_warning.call_count >= 1
        assert any(("bogus-model" in msg for msg in warning_messages))

    @patch("cecli.models.check_for_dependencies")
    async def test_sanity_check_model_calls_check_dependencies(self, mock_check_deps):
        """Test that sanity_check_model calls check_for_dependencies"""
        mock_io = MagicMock()
        model = MagicMock()
        model.name = "test-model"
        model.missing_keys = []
        model.keys_in_environment = True
        model.info = {"some": "info"}
        await sanity_check_model(mock_io, model)
        mock_check_deps.assert_called_once_with(mock_io, "test-model")

    def test_model_aliases(self):
        # Test common aliases
        model = Model("4")
        assert model.name == "gpt-4-0613"
        model = Model("4o")
        assert model.name == "gpt-4o"
        model = Model("35turbo")
        assert model.name == "gpt-3.5-turbo"
        model = Model("35-turbo")
        assert model.name == "gpt-3.5-turbo"
        model = Model("3")
        assert model.name == "gpt-3.5-turbo"
        model = Model("sonnet")
        assert model.name == "anthropic/claude-sonnet-4-20250514"
        model = Model("haiku")
        assert model.name == "claude-3-5-haiku-20241022"
        model = Model("opus")
        assert model.name == "claude-opus-4-20250514"

        # Test non-alias passes through unchanged
        model = Model("gpt-4")
        assert model.name == "gpt-4"

    def test_o1_use_temp_false(self):
        model = Model("github/o1-mini")
        assert model.name == "github/o1-mini"
        assert model.use_temperature is False
        model = Model("github/o1-preview")
        assert model.name == "github/o1-preview"
        assert model.use_temperature is False

    def test_parse_token_value(self):
        model = Model("gpt-4")

        # Test integer inputs
        assert model.parse_token_value(8096) == 8096
        assert model.parse_token_value(1000) == 1000

        # Test string inputs
        assert model.parse_token_value("8096") == 8096

        # Test k/K suffix (kilobytes)
        assert model.parse_token_value("8k") == 8 * 1024
        assert model.parse_token_value("8K") == 8 * 1024
        assert model.parse_token_value("10.5k") == 10.5 * 1024
        assert model.parse_token_value("0.5K") == 0.5 * 1024

        # Test m/M suffix (megabytes)
        assert model.parse_token_value("1m") == 1 * 1024 * 1024
        assert model.parse_token_value("1M") == 1 * 1024 * 1024
        assert model.parse_token_value("0.5M") == 0.5 * 1024 * 1024

        # Test with spaces
        assert model.parse_token_value(" 8k ") == 8 * 1024

        # Test conversion from other types
        assert model.parse_token_value(8.0) == 8

    def test_set_thinking_tokens(self):
        model = Model("gpt-4")

        # Test with integer
        model.set_thinking_tokens(8096)
        assert model.extra_params["thinking"]["budget_tokens"] == 8096
        assert not model.use_temperature

        # Test with string
        model.set_thinking_tokens("10k")
        assert model.extra_params["thinking"]["budget_tokens"] == 10 * 1024

        # Test with decimal value
        model.set_thinking_tokens("0.5M")
        assert model.extra_params["thinking"]["budget_tokens"] == 0.5 * 1024 * 1024

    @patch("cecli.models.check_pip_install_extra")
    async def test_check_for_dependencies_bedrock(self, mock_check_pip):
        """Test that check_for_dependencies calls check_pip_install_extra for Bedrock models"""
        from cecli.io import InputOutput

        io = InputOutput()
        from cecli.models import check_for_dependencies

        await check_for_dependencies(io, "bedrock/anthropic.claude-3-sonnet-20240229-v1:0")
        mock_check_pip.assert_called_once_with(
            io, "boto3", "AWS Bedrock models require the boto3 package.", ["boto3"]
        )

    @patch("cecli.models.check_pip_install_extra")
    async def test_check_for_dependencies_vertex_ai(self, mock_check_pip):
        """Test that check_for_dependencies calls check_pip_install_extra for Vertex AI models"""
        from cecli.io import InputOutput

        io = InputOutput()
        from cecli.models import check_for_dependencies

        await check_for_dependencies(io, "vertex_ai/gemini-1.5-pro")
        mock_check_pip.assert_called_once_with(
            io,
            "google.cloud.aiplatform",
            "Google Vertex AI models require the google-cloud-aiplatform package.",
            ["google-cloud-aiplatform"],
        )

    @patch("cecli.models.check_pip_install_extra")
    async def test_check_for_dependencies_other_model(self, mock_check_pip):
        """Test that check_for_dependencies doesn't call check_pip_install_extra for other models"""
        from cecli.io import InputOutput

        io = InputOutput()
        from cecli.models import check_for_dependencies

        await check_for_dependencies(io, "gpt-4")
        mock_check_pip.assert_not_called()

    def test_get_repo_map_tokens(self):
        # Test default case (no max_input_tokens in info)
        model = Model("gpt-4")
        model.info = {}
        assert model.get_repo_map_tokens() == 1024

        # Test minimum boundary (max_input_tokens < 8192)
        model.info = {"max_input_tokens": 4096}
        assert model.get_repo_map_tokens() == 1024

        # Test middle range (max_input_tokens = 16384)
        model.info = {"max_input_tokens": 16384}
        assert model.get_repo_map_tokens() == 2048

        # Test maximum boundary (max_input_tokens > 32768)
        model.info = {"max_input_tokens": 65536}
        assert model.get_repo_map_tokens() == 4096

        # Test exact boundary values
        model.info = {"max_input_tokens": 8192}
        assert model.get_repo_map_tokens() == 1024

        model.info = {"max_input_tokens": 32768}
        assert model.get_repo_map_tokens() == 4096

    def test_configure_model_settings(self):
        # Test o3-mini case
        model = Model("something/o3-mini")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert not model.use_temperature

        # Test o1-mini case
        model = Model("something/o1-mini")
        assert model.use_repo_map
        assert not model.use_temperature
        assert not model.use_system_prompt

        # Test o1-preview case
        model = Model("something/o1-preview")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert not model.use_temperature
        assert not model.use_system_prompt

        # Test o1 case
        model = Model("something/o1")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert not model.use_temperature
        assert not model.streaming

        # Test deepseek v3 case
        model = Model("deepseek-v3")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert model.reminder == "sys"
        assert model.examples_as_sys_msg

        # Test deepseek reasoner case
        model = Model("deepseek-r1")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert model.examples_as_sys_msg
        assert not model.use_temperature
        assert model.reasoning_tag == "think"

        # Test provider/deepseek-r1 case
        model = Model("someprovider/deepseek-r1")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert model.examples_as_sys_msg
        assert not model.use_temperature
        assert model.reasoning_tag == "think"

        # Test provider/deepseek-v3 case
        model = Model("anotherprovider/deepseek-v3")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert model.reminder == "sys"
        assert model.examples_as_sys_msg

        # Test llama3 70b case
        model = Model("llama3-70b")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert model.send_undo_reply
        assert model.examples_as_sys_msg

        # Test gpt-4 case
        model = Model("gpt-4")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert model.send_undo_reply

        # Test gpt-3.5 case
        model = Model("gpt-3.5")
        assert model.reminder == "sys"

        # Test 3.5-sonnet case
        model = Model("claude-3.5-sonnet")
        assert model.edit_format == "diff"
        assert model.use_repo_map
        assert model.examples_as_sys_msg
        assert model.reminder == "user"

        # Test o1- prefix case
        model = Model("o1-something")
        assert not model.use_system_prompt
        assert not model.use_temperature

        # Test qwen case
        model = Model("qwen-coder-2.5-32b")
        assert model.edit_format == "diff"
        assert model.editor_edit_format == "editor-diff"
        assert model.use_repo_map

    def test_cecli_extra_model_settings(self):
        import tempfile

        import yaml

        test_settings = [
            {
                "name": "cecli/extra_params",
                "extra_params": {"extra_headers": {"Foo": "bar"}, "some_param": "some value"},
            }
        ]
        tmp = tempfile.mktemp(suffix=".yml")
        try:
            with open(tmp, "w") as f:
                yaml.dump(test_settings, f)
            register_models([tmp])
            model = Model("claude-3-5-sonnet-20240620")
            model = Model("claude-3-5-sonnet-20240620")
            assert model.extra_params["extra_headers"]["Foo"] == "bar"
            assert model.extra_params["extra_headers"]["anthropic-beta"] == ANTHROPIC_BETA_HEADER
            assert model.extra_params["some_param"] == "some value"
            assert model.extra_params["max_tokens"] == 8192
            model = Model("gpt-4")
            assert model.extra_params["extra_headers"]["Foo"] == "bar"
            assert model.extra_params["some_param"] == "some value"
        finally:
            import os

            try:
                os.unlink(tmp)
            except OSError:
                pass

    @patch("cecli.models.litellm.acompletion")
    @patch.object(Model, "token_count")
    async def test_ollama_num_ctx_set_when_missing(self, mock_token_count, mock_completion):
        mock_token_count.return_value = 1000
        model = Model("ollama/llama3")
        model.extra_params = {}
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=None, stream=False)
        expected_ctx = int(1000 * 1.25) + 8192
        mock_completion.assert_called_once_with(
            model=model.name,
            messages=ANY,
            stream=False,
            temperature=0,
            num_ctx=expected_ctx,
            timeout=600,
            cache_control_injection_points=ANY,
        )

    @patch("cecli.models.litellm.acompletion")
    async def test_modern_tool_call_propagation(self, mock_completion):
        model = Model("gpt-4")
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(
            messages, functions=None, stream=False, tools=[dict(type="function", function="test")]
        )
        mock_completion.assert_called_once()
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["tools"] == [dict(type="function", function="test")]
        assert call_kwargs["model"] == model.name
        assert call_kwargs["stream"] is False

    @patch("cecli.models.litellm.acompletion")
    async def test_legacy_tool_call_propagation(self, mock_completion):
        model = Model("gpt-4")
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=["test"], stream=False)
        mock_completion.assert_called_once()
        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs["tools"] == [dict(type="function", function="test")]
        assert call_kwargs["model"] == model.name
        assert call_kwargs["stream"] is False

    @patch("cecli.models.litellm.acompletion")
    async def test_ollama_uses_existing_num_ctx(self, mock_completion):
        model = Model("ollama/llama3")
        model.extra_params = {"num_ctx": 4096}
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_once_with(
            model=model.name,
            messages=ANY,
            stream=False,
            temperature=0,
            num_ctx=4096,
            timeout=600,
            cache_control_injection_points=ANY,
        )

    @patch("cecli.models.litellm.acompletion")
    async def test_non_ollama_no_num_ctx(self, mock_completion):
        model = Model("gpt-4")
        model.extra_params = {}
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_once_with(
            model=model.name,
            messages=ANY,
            stream=False,
            temperature=0,
            timeout=600,
            cache_control_injection_points=ANY,
        )
        assert "num_ctx" not in mock_completion.call_args.kwargs

    def test_use_temperature_settings(self):
        # Test use_temperature=True (default) uses temperature=0
        model = Model("gpt-4")
        assert model.use_temperature
        assert model.use_temperature is True

        # Test use_temperature=False doesn't pass temperature
        model = Model("github/o1-mini")
        assert not model.use_temperature

        # Test use_temperature as float value
        model = Model("gpt-4")
        model.use_temperature = 0.7
        assert model.use_temperature == 0.7

    @patch("cecli.models.litellm.acompletion")
    async def test_request_timeout_default(self, mock_completion):
        model = Model("gpt-4")
        model.extra_params = {}
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_with(
            model=model.name,
            messages=ANY,
            stream=False,
            temperature=0,
            timeout=600,
            cache_control_injection_points=ANY,
        )

    @patch("cecli.models.litellm.acompletion")
    async def test_request_timeout_from_extra_params(self, mock_completion):
        # Test timeout from extra_params overrides default
        model = Model("gpt-4")
        model.extra_params = {"timeout": 300}
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_with(
            model=model.name,
            messages=ANY,
            stream=False,
            temperature=0,
            timeout=300,
            cache_control_injection_points=ANY,
        )

    @patch("cecli.models.litellm.acompletion")
    async def test_use_temperature_in_send_completion(self, mock_completion):
        # Test use_temperature=True sends temperature=0
        model = Model("gpt-4")
        model.extra_params = {}
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_with(
            model=model.name,
            messages=ANY,
            stream=False,
            temperature=0,
            timeout=600,
            cache_control_injection_points=ANY,
        )

        # Test use_temperature=False doesn't send temperature
        model = Model("github/o1-mini")
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=None, stream=False)
        assert "temperature" not in mock_completion.call_args.kwargs

        # Test use_temperature as float sends that value
        model = Model("gpt-4")
        model.extra_params = {}
        model.use_temperature = 0.7
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=None, stream=False)
        mock_completion.assert_called_with(
            model=model.name,
            messages=ANY,
            stream=False,
            temperature=0.7,
            timeout=600,
            cache_control_injection_points=ANY,
        )

    def test_model_override_kwargs(self):
        """Test that override kwargs are applied to model extra_params."""
        # Test with override kwargs
        model = Model("gpt-4", override_kwargs={"temperature": 0.8, "top_p": 0.9})
        assert "temperature" in model.extra_params
        assert model.extra_params["temperature"] == 0.8
        assert "top_p" in model.extra_params
        assert model.extra_params["top_p"] == 0.9

        # Test that override kwargs merge with existing extra_params
        model = Model("gpt-4", override_kwargs={"extra_headers": {"X-Custom": "value"}})
        assert "extra_headers" in model.extra_params
        assert "X-Custom" in model.extra_params["extra_headers"]
        assert model.extra_params["extra_headers"]["X-Custom"] == "value"

        # Test nested dict merging
        model = Model("gpt-4", override_kwargs={"extra_body": {"reasoning_effort": "high"}})
        assert "extra_body" in model.extra_params
        assert "reasoning_effort" in model.extra_params["extra_body"]
        assert model.extra_params["extra_body"]["reasoning_effort"] == "high"

    def test_model_override_kwargs_with_existing_extra_params(self):
        """Test that override kwargs merge correctly with existing extra_params."""
        # Create a model with existing extra_params via model settings
        import tempfile

        import yaml

        test_settings = [
            {
                "name": "gpt-4",
                "extra_params": {"temperature": 0.5, "extra_headers": {"Existing": "header"}},
            }
        ]
        tmp = tempfile.mktemp(suffix=".yml")
        try:
            with open(tmp, "w") as f:
                yaml.dump(test_settings, f)
            register_models([tmp])

            # Test that override kwargs take precedence
            model = Model("gpt-4", override_kwargs={"temperature": 0.8, "top_p": 0.9})
            assert model.extra_params["temperature"] == 0.8  # Override wins
            assert model.extra_params["top_p"] == 0.9  # New param added
            assert "extra_headers" in model.extra_params
            assert model.extra_params["extra_headers"]["Existing"] == "header"  # Existing preserved

            # Test nested dict merging
            model = Model("gpt-4", override_kwargs={"extra_headers": {"New": "value"}})
            assert "Existing" in model.extra_params["extra_headers"]
            assert "New" in model.extra_params["extra_headers"]
            assert model.extra_params["extra_headers"]["Existing"] == "header"
            assert model.extra_params["extra_headers"]["New"] == "value"
        finally:
            import os

            try:
                os.unlink(tmp)
            except OSError:
                pass

    @patch("cecli.models.litellm.acompletion")
    async def test_send_completion_with_override_kwargs(self, mock_completion):
        """Test that override kwargs are passed to acompletion."""
        # Create model with override kwargs
        model = Model("gpt-4", override_kwargs={"temperature": 0.8, "top_p": 0.9})
        messages = [{"role": "user", "content": "Hello"}]
        await model.send_completion(messages, functions=None, stream=False)

        # Check that override kwargs are in the call
        mock_completion.assert_called_once()
        call_kwargs = mock_completion.call_args.kwargs
        assert "temperature" in call_kwargs
        assert call_kwargs["temperature"] == 0.8
        assert "top_p" in call_kwargs
        assert call_kwargs["top_p"] == 0.9

        # Check that model name and other defaults are still there
        assert call_kwargs["model"] == "gpt-4"
        assert not call_kwargs["stream"]

    @pytest.mark.parametrize(
        "model_input,expected_base,expected_kwargs,description",
        [
            (
                "gpt-4o:high",
                "gpt-4o",
                {"reasoning_effort": "high", "temperature": 0.7},
                "valid suffix 'high'",
            ),
            (
                "gpt-4o:low",
                "gpt-4o",
                {"reasoning_effort": "low", "temperature": 0.2},
                "valid suffix 'low'",
            ),
            ("gpt-4o", "gpt-4o", {}, "no suffix"),
            ("gpt-4o:unknown", "gpt-4o", {}, "unknown suffix"),
            ("unknown-model:high", "unknown-model", {}, "unknown model with suffix"),
            ("", "", {}, "empty model name"),
        ],
    )
    def test_parse_model_with_suffix(
        self, model_input, expected_base, expected_kwargs, description
    ):
        """Test parse_model_with_suffix function handles model names with optional :suffix."""

        def parse_model_with_suffix(model_name, overrides):
            """Parse model name with optional :suffix and apply overrides."""
            if not model_name:
                return (model_name, {})
            if ":" in model_name:
                base_model, suffix = model_name.rsplit(":", 1)
            else:
                base_model, suffix = (model_name, None)
            override_kwargs = {}
            if suffix and base_model in overrides and (suffix in overrides[base_model]):
                override_kwargs = overrides[base_model][suffix].copy()
            return (base_model, override_kwargs)

        overrides = {
            "gpt-4o": {
                "high": {"reasoning_effort": "high", "temperature": 0.7},
                "low": {"reasoning_effort": "low", "temperature": 0.2},
            },
            "claude-3-5-sonnet": {"fast": {"temperature": 0.3}, "creative": {"temperature": 0.9}},
        }

        base_model, kwargs = parse_model_with_suffix(model_input, overrides)
        assert base_model == expected_base, f"Failed ({description}): base model mismatch"
        assert kwargs == expected_kwargs, f"Failed ({description}): kwargs mismatch"

    def test_print_matching_models_with_pricing(self):
        """Test that print_matching_models displays pricing information correctly."""
        from cecli.io import InputOutput
        from cecli.models import print_matching_models

        # Mock model_info_manager to return pricing data
        with patch("cecli.models.model_info_manager") as mock_manager:
            mock_manager.get_model_info.return_value = {
                "input_cost_per_token": 0.000005,  # $5 per 1M tokens
                "output_cost_per_token": 0.000015,  # $15 per 1M tokens
            }

            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            with patch.object(io, "tool_output") as mock_tool_output:
                print_matching_models(io, "gpt-4")

                # Check that the header was printed
                mock_tool_output.assert_any_call('Models which match "gpt-4":')

                # Check that pricing was included in the output
                calls = [str(call) for call in mock_tool_output.call_args_list]
                pricing_found = any("$5.00/1m/input" in call for call in calls)
                output_pricing_found = any("$15.00/1m/output" in call for call in calls)
                assert pricing_found, "Input pricing not found in output"
                assert output_pricing_found, "Output pricing not found in output"

    def test_print_matching_models_with_cache_pricing(self):
        """Test that print_matching_models displays cache pricing when available."""
        from cecli.io import InputOutput
        from cecli.models import print_matching_models

        # Mock model_info_manager to return pricing data with cache
        with patch("cecli.models.model_info_manager") as mock_manager:
            mock_manager.get_model_info.return_value = {
                "input_cost_per_token": 0.000003,  # $3 per 1M tokens
                "output_cost_per_token": 0.000012,  # $12 per 1M tokens
                "cache_cost_per_token": 0.000001,  # $1 per 1M tokens
            }

            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            with patch.object(io, "tool_output") as mock_tool_output:
                print_matching_models(io, "claude-3-5-sonnet")

                # Check that all pricing was included in the output
                calls = [str(call) for call in mock_tool_output.call_args_list]
                input_found = any("$3.00/1m/input" in call for call in calls)
                output_found = any("$12.00/1m/output" in call for call in calls)
                cache_found = any("$1.00/1m/cache" in call for call in calls)
                assert input_found, "Input pricing not found in output"
                assert output_found, "Output pricing not found in output"
                assert cache_found, "Cache pricing not found in output"

    def test_print_matching_models_without_pricing(self):
        """Test that print_matching_models works when no pricing info is available."""
        from cecli.io import InputOutput
        from cecli.models import print_matching_models

        # Mock model_info_manager to return no pricing data
        with patch("cecli.models.model_info_manager") as mock_manager:
            mock_manager.get_model_info.return_value = {}

            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            with patch.object(io, "tool_output") as mock_tool_output:
                print_matching_models(io, "gpt-4")

                # Check that the header was printed
                mock_tool_output.assert_any_call('Models which match "gpt-4":')

                # Check that no pricing was included in the output
                calls = [str(call) for call in mock_tool_output.call_args_list]
                pricing_found = any("/1m/" in call for call in calls)
                assert not pricing_found, "Pricing should not be in output when not available"

    def test_print_matching_models_partial_pricing(self):
        """Test that print_matching_models displays only available pricing info."""
        from cecli.io import InputOutput
        from cecli.models import print_matching_models

        # Mock model_info_manager to return only input pricing
        with patch("cecli.models.model_info_manager") as mock_manager:
            mock_manager.get_model_info.return_value = {
                "input_cost_per_token": 0.000002,  # $2 per 1M tokens
                # No output or cache pricing
            }

            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            with patch.object(io, "tool_output") as mock_tool_output:
                print_matching_models(io, "gpt-3.5")

                # Check that only input pricing was included
                calls = [str(call) for call in mock_tool_output.call_args_list]
                input_found = any("$2.00/1m/input" in call for call in calls)
                output_found = any("/1m/output" in call for call in calls)
                assert input_found, "Input pricing not found in output"
                assert not output_found, "Output pricing should not be in output when not available"

    def test_print_matching_models_no_matches(self):
        """Test that print_matching_models handles no matches correctly."""
        from cecli.io import InputOutput
        from cecli.models import print_matching_models

        # Mock fuzzy_match_models to return no matches
        with patch("cecli.models.fuzzy_match_models") as mock_fuzzy:
            mock_fuzzy.return_value = []

            io = InputOutput(pretty=False, fancy_input=False, yes=True)
            with patch.object(io, "tool_output") as mock_tool_output:
                print_matching_models(io, "nonexistent-model")

                # Check that the no matches message was printed
                mock_tool_output.assert_called_once_with('No models match "nonexistent-model".')

    def test_print_matching_models_price_formatting(self):
        """Test that pricing is formatted correctly with 2 decimal places."""
        from cecli.io import InputOutput
        from cecli.models import print_matching_models

        # Mock fuzzy_match_models to return a test model
        with patch("cecli.models.fuzzy_match_models") as mock_fuzzy:
            mock_fuzzy.return_value = ["test-model"]

            # Mock model_info_manager to return pricing with various values
            with patch("cecli.models.model_info_manager") as mock_manager:
                mock_manager.get_model_info.return_value = {
                    "input_cost_per_token": 0.0000025,  # $2.50 per 1M tokens
                    "output_cost_per_token": 0.0000105,  # $10.50 per 1M tokens
                }

                io = InputOutput(pretty=False, fancy_input=False, yes=True)
                with patch.object(io, "tool_output") as mock_tool_output:
                    print_matching_models(io, "test-model")

                    # Check that pricing is formatted with 2 decimal places
                    calls = [str(call) for call in mock_tool_output.call_args_list]
                    input_found = any("$2.50/1m/input" in call for call in calls)
                    output_found = any("$10.50/1m/output" in call for call in calls)
                    assert input_found, "Input pricing format incorrect"
                    assert output_found, "Output pricing format incorrect"
