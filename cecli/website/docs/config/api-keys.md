---
parent: Configuration
nav_order: 5
description: Setting API keys for API providers.
---

# API Keys

Cecli lets you specify API keys in a few ways:

- On the command line
- As environment variables
- In a `.env` file
- In your `.cecli.conf.yml` config file
- Interactively with the provider setup wizard

---

## Interactive setup

Run `cecli --configure-provider` to launch the interactive provider setup wizard. It lets you choose a provider, enter its API key(s), and pick a default model. The keys are saved to `~/.cecli/.env` and the model to `~/.cecli/conf.yml`, so they are loaded automatically in future sessions.

This is useful for (re)configuring a provider even when a model or API key is already set.


## Command line

Use `--api-key provider=<key>` which has the effect of setting the environment variable `PROVIDER_API_KEY=<key>`. So `--api-key gemini=xxx` would set `GEMINI_API_KEY=xxx`.

## Environment variables or .env file

You can set API keys in environment variables. The [.env file](dotenv.html) is a great place to store your API keys and other provider API environment variables:

```bash
OPENAI_API_KEY=<key>
ANTHROPIC_API_KEY=<key>
GEMINI_API_KEY=foo
OPENROUTER_API_KEY=bar
DEEPSEEK_API_KEY=baz
```

## YAML config file


You can also set API keys in the [`.cecli.conf.yml` file](conf.html) via the `api-key` entry:

```
api-key:
- gemini=foo      # Sets env var GEMINI_API_KEY=foo
- openrouter=bar  # Sets env var OPENROUTER_API_KEY=bar
- deepseek=baz    # Sets env var DEEPSEEK_API_KEY=baz
```
