---
parent: Configuration
nav_order: 900
description: Configure model overrides, alias-based suffixes, and structured override groups.
---

# Model Configuration

## Model Configuration & Overrides

Cecli allows you to customize and override LLM configurations to fine-tune their behavior, API parameters, and metadata. You can organize these overrides into three logical configuration groups, and apply them either as **defaults** (by model name) or via **suffixes** (e.g., `gpt-5:high`).

---

## Core Configuration Groups

For advanced configurations, you can organize override parameters into three logical groups: `api`, `llm`, and `agent`.
### 1. `api`
Values under `api` are request-level parameters that cecli passes to the provider API. This is useful for configuring provider-specific API options, temperature, or custom headers. For more details, see the [advanced model settings](../config/adv-model-settings.html) page.

**Common parameters**: `temperature`, `top_p`, `max_tokens`, `parallel_tool_calls`, `extra_body` (e.g., `thinking: true` or `reasoning_effort: "high"`).

### 2. `llm`
Values under `llm` are merged into the model's info dictionary (`self.info`). This allows you to override or augment model metadata and capabilities. For a comprehensive list of available model metadata fields, see cecli's bundled metadata in [cecli/resources/model-metadata.json](https://github.com/cecli-dev/cecli/blob/main/cecli/resources/model-metadata.json).

**Common parameters**: `supports_vision`, `supports_function_calling`, token limits, or pricing information.

### 3. `agent`
Values under `agent` modify CECLI's internal `ModelSettings` fields. This controls how CECLI interacts with the model and manages the workspace. For all supported fields, the `ModelSettings` class in [models.py](https://github.com/cecli-dev/cecli/blob/main/cecli/models.py) contains the most comprehensive list.

**Common parameters**: `edit_format`, `use_repo_map`, `cache_control`, `caches_by_default`.

---

## Application Methods

You can apply these configuration groups in two ways:

### 1. Default Overrides
Default overrides apply automatically to a model by name without requiring any suffix. Use the special `defaults` key within your `model-overrides` configuration.

When you run `cecli --model gpt-5`, any default overrides specified under `defaults` for `gpt-5` are applied automatically.

### 2. Suffix-Based Overrides
Suffix-based overrides allow you to define named configurations for different use cases using a colon-separated suffix (e.g., `gpt-5:high` or `claude-3-5-sonnet:fast`).

When you specify a model with a suffix, CECLI splits it into the base model name and the suffix, looks up the suffix configuration, and merges it on top of any default settings.

---

## Configuration File Example

You can define these overrides in your `config.yml` file, a `.cecli.model.overrides.yml` file, or a custom file specified via `--model-overrides-file`.

```yaml
model-overrides:
  # 1. Default overrides (applied automatically by model name)
  defaults:
    openai/gpt-5.5:
      api:
        temperature: 0.7
        top_p: 0.9
    anthropic.claude-sonnet-4-6:
      api:
        temperature: 1.0
      llm:
        supports_vision: true
        supports_function_calling: true
      agent:
        cache_control: true

  # 2. Suffix-based overrides (applied when using model:suffix)
  openai/gpt-5.5:
    high:
      api:
        temperature: 0.8
        top_p: 0.9
        extra_body:
          reasoning_effort: high
    low:
      api:
        temperature: 0.2
        top_p: 0.5
    creative:
      api:
        temperature: 0.9
        top_p: 0.95
        frequency_penalty: 0.5

  anthropic.claude-sonnet-4-6:
    fast:
      api:
        temperature: 0.3
    detailed:
      api:
        temperature: 0.7
        thinking_tokens: 4096
```

---

## Usage & CLI Examples

You can reference these configurations in any model argument on the command line:

```bash
# Applies default overrides for gpt-5
cecli --model gpt-5

# Applies suffix-based overrides for gpt-5:high, merged on top of defaults
cecli --model gpt-5:high --model-overrides-file .cecli.model.overrides.yml

# Different configurations for main and weak models
cecli --model claude-3-5-sonnet:detailed --weak-model claude-3-5-sonnet:fast

# Editor model with creative settings
cecli --model gpt-5 --editor-model gpt-5:creative

# Direct JSON/YAML overrides via CLI
cecli --model gpt-5:high --model-overrides '{"gpt-5": {"high": {"api": {"temperature": 0.8}}}}'
```

---

## Resolution & Priority

When resolving model configurations, CECLI applies overrides in the following order of precedence (highest priority first):

1. **Suffix-Based Overrides**: Specific suffix configurations (e.g., `:high`) override default settings.
2. **Default Overrides**: Settings defined under the `defaults` key for the model.
3. **Base Model Settings**: The model's built-in or system-defined parameters.

### Alias Resolution
If you use a model alias (e.g., `fast` as an alias for `gpt-5-mini`), the alias is resolved to the base model name **before** any suffixes or overrides are applied.

For example, `cecli --model fast:high` resolves `fast` to `gpt-5-mini`, then applies the `high` suffix overrides defined for `gpt-5-mini`.
