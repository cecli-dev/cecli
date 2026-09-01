---
parent: Configuration
nav_order: 1000
description: Assign convenient short names to models.
---

# Model Aliases

Model aliases allow you to create shorthand names for models you frequently use. This is particularly useful for models with long names or when you want to standardize model usage across your team.

## Command Line Usage

You can define aliases when launching cecli using the `--alias` option:

```bash
cecli --alias "fast:gpt-5-mini" --alias "smart:anthropic/claude-opus-5"
```

Multiple aliases can be defined by using the `--alias` option multiple times. Each alias definition should be in the format `alias:model-name`.

## Configuration File

Of course, you can also define aliases in your [`.cecli.conf.yml` file](conf.html):

```yaml
alias:
  - "fast:gpt-5-mini"
  - "smart:anthropic/claude-opus-5"
  - "hacker:moonshotai/kimi-k3"
```

## Using Aliases

Once defined, you can use the alias instead of the full model name from the command line:

```bash
cecli --model fast  # Uses gpt-5-mini
cecli --model smart  # Uses anthropic/claude-opus-5
```

Or with the `/model` command in-chat:

```
cecli v1.0.0
Main model: moonshotai/kimi-k3 with diff edit format, prompt cache, infinite output
Weak model: gpt-5.6-luna
Git repo: .git with 406 files
Repo-map: using 4096 tokens, files refresh
─────────────────────────────────────────────────────────────────────────────────────────────────────
> /model fast

cecli v1.0.0
Main model: gpt-5-mini with diff edit format
─────────────────────────────────────────────────────────────────────────────────────────────────────
diff> /model smart

cecli v1.0.0
Main model: anthropic/claude-opus-5 with diff edit format
─────────────────────────────────────────────────────────────────────────────────────────────────────
>
```

## Priority

If the same alias is defined in multiple places, the priority is:

1. Command line aliases (highest priority)
2. Configuration file aliases
3. Built-in aliases (lowest priority)

This allows you to override built-in aliases with your own preferences.

Model overrides with suffixes provide an additional layer of configuration that works alongside aliases, giving you fine-grained control over model parameters for different use cases.
