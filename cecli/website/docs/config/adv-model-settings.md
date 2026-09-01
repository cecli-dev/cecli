---
parent: Configuration
nav_order: 950
description: Configuring advanced settings for LLMs.
---

# Model Configuration Files

## Context window size and token costs

In most cases, you can safely ignore cecli's warning about unknown context window size and model costs.

> **Note:** cecli never *enforces* token limits, it only *reports* token limit errors from the API provider. You probably don't need to configure cecli with the proper token limits for unusual models.

But, you can register context window limits and costs for models that aren't known to cecli. Create a `.cecli.model.metadata.json` file in one of these locations:

- Your home directory.
- The root if your git repo.
- The current directory where you launch cecli.
- Or specify a specific file with the `--model-metadata-file <filename>` switch.

If the files above exist, they will be loaded in that order. Files loaded last will take priority.

The json file should be a dictionary with an entry for each model, as follows:

```
{
    "deepseek/deepseek-chat": {
        "max_tokens": 4096,
        "max_input_tokens": 32000,
        "max_output_tokens": 4096,
        "input_cost_per_token": 0.00000014,
        "output_cost_per_token": 0.00000028,
        "litellm_provider": "deepseek",
        "mode": "chat"
    }
}
```

> **Tip:** Use a fully qualified model name with a `provider/` at the front in the `.cecli.model.metadata.json` file. For example, use `deepseek/deepseek-chat`, not just `deepseek-chat`. That prefix should match the `litellm_provider` field.

### Contribute model metadata

Cecli ships its own bundled model metadata in `cecli/resources/model-metadata.json` (see the file in the [cecli repository](https://github.com/cecli-dev/cecli/blob/main/cecli/resources/model-metadata.json)). It is based on LiteLLM's configuration scheme [here](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json).

Consider submitting a PR to that file to add missing models.

## Model settings

Cecli has a number of settings that control how it works with different models. These model settings are pre-configured for most popular models. But it can sometimes be helpful to override them or add settings for a model that cecli doesn't know about.

### Configuration file locations

You can override or add settings for any model by creating a `.cecli.model.settings.yml` file in one of these locations:

- Your home directory.
- The root of your git repo.
- The current directory where you launch cecli.
- Or specify a specific file with the `--model-settings-file <filename>` switch.

If the files above exist, they will be loaded in that order. Files loaded last will take priority.

The YAML file should be a list of dictionary objects for each model.

### Passing extra params to model requests

The `extra_params` attribute of model settings is used to pass arbitrary extra parameters to cecli's completion dispatcher when sending data to the given model. These become request parameters sent to the provider API.

For example:

```yaml
- name: some-provider/my-special-model
  extra_params:
    extra_headers:
      Custom-Header: value
    max_tokens: 8192
```

You can use the special model name `cecli/extra_params` to define `extra_params` that will be passed to cecli's completion dispatcher for all models. Only the `extra_params` dict is used from this special model name.

For example:

```yaml
- name: cecli/extra_params
  extra_params:
    extra_headers:
      Custom-Header: value
    max_tokens: 8192
```

These settings will be merged with any model-specific settings, with the `cecli/extra_params` settings taking precedence for any direct conflicts.

### Default model settings

Below is an example settings entry to give a sense for how the configuration works.

You can also look at the `ModelSettings` class in [models.py](https://github.com/cecli-dev/cecli/blob/main/cecli/models.py) file for more details about all of the model setting that cecli supports.

The first entry shows all the settings, with their default values. For a real model, you just need to include whichever fields that you want to override the defaults.

```yaml
- name: (default values)
  edit_format: whole
  weak_model_name: null
  use_repo_map: false
  send_undo_reply: false
  lazy: false
  overeager: false
  reminder: user
  examples_as_sys_msg: false
  extra_params: null
  cache_control: false
  caches_by_default: false
  use_system_prompt: true
  use_temperature: true
  streaming: true
  editor_model_name: null
  editor_edit_format: null
  reasoning_tag: null
  remove_reasoning: null
  system_prompt_prefix: null
  accepts_settings: null
```
