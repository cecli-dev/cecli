---
parent: Connecting to LLMs
nav_order: 800
---

# Other LLMs

Cecli connects directly to hundreds of models through their providers' APIs, so there is no extra model-routing package to install. You can use `cecli --model <model-name>` to use any supported model.

To explore the list of supported models you can run `cecli --list-models <model-name>` with a partial model name. If the supplied name is not an exact match for a known model, cecli will return a list of possible matching models. For example:

```
$ cecli --list-models turbo

cecli v0.29.3-dev
Models which match "turbo":
- gpt-4-turbo-preview (openai/gpt-4-turbo-preview)
- gpt-4-turbo (openai/gpt-4-turbo)
- gpt-4-turbo-2024-04-09 (openai/gpt-4-turbo-2024-04-09)
- gpt-3.5-turbo (openai/gpt-3.5-turbo)
- ...
```

See the [model warnings](warnings.html) section for information on warnings which will occur when working with models that cecli is not familiar with.

## Connecting to other providers

Cecli connects to each provider through its own request dispatcher (`cecli/helpers/llms/`): when you specify a model, cecli resolves the provider's base URL, API-key environment variable and API family (OpenAI-compatible chat, Anthropic Messages, Responses, Gemini, or Bedrock) and handles authentication and headers itself.

## Other API key variables

The authoritative list of provider base URLs and API-key environment variables is cecli's own provider configuration (`cecli/resources/providers.json`, which covers 61 providers) plus built-in defaults for the major providers. Each provider page in this section lists the variables you need to set, and `cecli --list-models <partial-name>` shows the model names cecli knows about.

Here are some of the most commonly used API key environment variables:

- OPENAI_API_KEY
- ANTHROPIC_API_KEY
- DEEPSEEK_API_KEY
- OPENROUTER_API_KEY
- GEMINI_API_KEY
- META_API_KEY
- GROQ_API_KEY
- XAI_API_KEY
- MISTRAL_API_KEY
- OLLAMA_API_KEY
- AZURE_API_KEY
