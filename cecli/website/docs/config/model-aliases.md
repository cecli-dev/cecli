---
parent: Configuration
nav_order: 1000
description: Assign convenient short names to models.
---

# Model Aliases

Model aliases allow you to create shorthand names for models you frequently use. This is particularly useful for models with long names or when you want to standardize model usage across your team.

## Command Line Usage

You can define aliases when launching aider using the `--alias` option:

```bash
aider --alias "fast:gpt-5-mini" --alias "smart:o3-mini"
```

Multiple aliases can be defined by using the `--alias` option multiple times. Each alias definition should be in the format `alias:model-name`.

## Configuration File

Of course,
you can also define aliases in your [`.aider.conf.yml` file](https://aider.chat/docs/config/aider_conf.html):

```yaml
alias:
  - "fast:gpt-5-mini"
  - "smart:o3-mini"
  - "hacker:claude-3-sonnet-20240229"
```

## Using Aliases

Once defined, you can use the alias instead of the full model name from the command line:

```bash
aider --model fast  # Uses gpt-5-mini
aider --model smart  # Uses o3-mini
```

Or with the `/model` command in-chat:

```
Aider v0.75.3
Main model: anthropic/claude-3-7-sonnet-20250219 with diff edit format, prompt cache, infinite output
Weak model: claude-3-5-sonnet-20241022
Git repo: .git with 406 files
Repo-map: using 4096 tokens, files refresh
─────────────────────────────────────────────────────────────────────────────────────────────────────
> /model fast

Aider v0.75.3
Main model: gpt-5-mini with diff edit format
─────────────────────────────────────────────────────────────────────────────────────────────────────
diff> /model smart

Aider v0.75.3
Main model: o3-mini with diff edit format
─────────────────────────────────────────────────────────────────────────────────────────────────────
>
```

## Built-in Aliases

Aider includes some built-in aliases for convenience:

<!--[[[cog
import cog
from aider.models import MODEL_ALIASES

for alias, model in sorted(MODEL_ALIASES.items()):
    cog.outl(f"- `{alias}`: {model}")
]]]-->
- `3`: gpt-3.5-turbo
- `35-turbo`: gpt-3.5-turbo
- `35turbo`: gpt-3.5-turbo
- `4`: gpt-4-0613
- `4-turbo`: gpt-4-1106-preview
- `4o`: gpt-4o
- `5`: gpt-5
- `deepseek`: deepseek/deepseek-chat
- `flash`: gemini/gemini-2.5-flash
- `flash-lite`: gemini/gemini-2.5-flash-lite
- `gemini`: gemini/gemini-3-pro-preview
- `gemini-2.5-pro`: gemini/gemini-2.5-pro
- `gemini-3-pro-preview`: gemini/gemini-3-pro-preview
- `gemini-exp`: gemini/gemini-2.5-pro-exp-03-25
- `grok3`: xai/grok-3-beta
- `haiku`: claude-3-5-haiku-20241022
- `optimus`: openrouter/openrouter/optimus-alpha
- `opus`: claude-opus-4-20250514
- `quasar`: openrouter/openrouter/quasar-alpha
- `r1`: deepseek/deepseek-reasoner
- `sonnet`: anthropic/claude-sonnet-4-20250514
<!--[[[end]]]-->

## Advanced Model Settings

CECLI/Cecli supports model names with colon-separated suffixes (e.g., `gpt-5:high`) that map to additional configuration parameters defined in the relevant config.yml file. This allows you to create named configurations for different use cases. These configurations map precisely to the LiteLLM `completion()` method parameters [here](https://docs.litellm.ai/docs/completion/input), though more are supported for specific models and providers.

### Configuration File

Add a structure like the following to your config.yml file or create a `.aider.model.overrides.yml` file (or specify a different file with `--model-overrides-file` if there are global defaults you want):

```yaml
model-overrides:
  gpt-5:
    high:  # Use with: --model gpt-5:high
      temperature: 0.8
      top_p: 0.9
      extra_body:
        reasoning_effort: high
    low:   # Use with: --model gpt-5:low
      temperature: 0.2
      top_p: 0.5
    creative:  # Use with: --model gpt-5:creative
      temperature: 0.9
      top_p: 0.95
      frequency_penalty: 0.5

  claude-4-5-sonnet:
    fast:    # Use with: --model claude-3-5-sonnet:fast
      temperature: 0.3
    detailed: # Use with: --model claude-3-5-sonnet:detailed
      temperature: 0.7
      thinking_tokens: 4096
```

### Usage

You can use these suffixes with any model argument:

```bash
# Main model with high reasoning effort (using file)
aider --model gpt-5:high --model-overrides-file .aider.model.overrides.yml

# Main model with high reasoning effort (using direct JSON/YAML)
aider --model gpt-5:high --model-overrides '{"gpt-5": {"high": {"temperature": 0.8, "top_p": 0.9, "extra_body": {"reasoning_effort": "high"}}}}'

# Different configurations for main and weak models
aider --model claude-3-5-sonnet:detailed --weak-model claude-3-5-sonnet:fast

# Editor model with creative settings
aider --model gpt-5 --editor-model gpt-5:creative
```

### How It Works

1. When you specify a model with a suffix (e.g., `gpt-5:high`), Aider splits it into the base model name (`gpt-5`) and suffix (`high`).
2. It looks up the suffix in the overrides file for that model.
3. The corresponding configuration parameters are applied to the model's API calls.
4. The parameters are deep-merged into the model's existing settings, with overrides taking precedence.

### Priority

Model overrides work alongside aliases. For example, you can use:
- `aider --model fast:high` (if `fast` is an alias for `gpt-5-mini`)
- `aider --model sonnet:detailed` (if `sonnet` is an alias for `anthropic/claude-sonnet-4-20250514`)

The suffix is applied after alias resolution.

## Priority

If the same alias is defined in multiple places, the priority is:

1. Command line aliases (highest priority)
2. Configuration file aliases
3. Built-in aliases (lowest priority)

This allows you to override built-in aliases with your own preferences.

Model overrides with suffixes provide an additional layer of configuration that works alongside aliases, giving you fine-grained control over model parameters for different use cases.
