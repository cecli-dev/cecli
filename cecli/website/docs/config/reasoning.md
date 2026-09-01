---
parent: Configuration
nav_order: 110
description: How to configure reasoning model settings from secondary providers.
---

# Reasoning Models

## Basic usage

Cecli is configured to work with most popular reasoning models out of the box. You can use them like this:

```bash
# Sonnet uses a thinking token budget
cecli --model claude-sonnet-5 --thinking-tokens 8k

# o3-mini uses low/medium/high reasoning effort
cecli --model gpt-5.6-terra --reasoning-effort high

```

Inside the cecli chat, you can use `/thinking-tokens 4k` or `/reasoning-effort low` to change the amount of reasoning. Use `/thinking-tokens 0` to disable thinking tokens.

The rest of this document describes more advanced details which are mainly needed if you're configuring cecli to work with a lesser known reasoning model or one served via an unusual provider.

## Reasoning settings

Different models support different reasoning settings. cecli provides several ways to control reasoning behavior:

### Reasoning effort

You can use the `--reasoning-effort` switch to control the reasoning effort of models which support this setting. This switch is useful for OpenAI's reasoning models, which accept "low", "medium" and "high".

### Thinking tokens

You can use the `--thinking-tokens` switch to request the model use a certain number of thinking tokens. You can specify the token budget like "1024", "1k", "8k" or "0.01M". Use "0" to disable thinking tokens.

### Model compatibility and settings

Not all models support these two settings. cecli uses the [model's metadata](adv-model-settings.html) to determine which settings each model accepts:

```yaml
- name: gpt-5-mini
  ...
  accepts_settings: ["reasoning_effort"]
```

If you try to use a setting that a model doesn't explicitly support, cecli will warn you:

```
Warning: gpt-5-mini does not support 'thinking_tokens', ignoring.
Use --no-check-model-accepts-settings to force the 'thinking_tokens' setting.
```

The warning informs you that:
1. The setting won't be applied because the model doesn't list it in `accepts_settings`
2. You can use `--no-check-model-accepts-settings` to force the setting anyway

This functionality helps prevent API errors while still allowing you to experiment with settings when needed.

Each model has a predefined list of supported settings in its configuration. For example:

- OpenAI-compatible model APIs generally support `reasoning_effort`
- Anthropic-compatible model APIs generally support `thinking_tokens`
