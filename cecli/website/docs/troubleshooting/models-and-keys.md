---
parent: Troubleshooting
nav_order: 28
---

# Models and API keys

cecli needs to know which LLM model you would like to work with and which keys
to provide when accessing it via API.

## Defaults

If you don't explicitly name a model, cecli will try to select a model
for you to work with.

First, cecli will check which 
[keys you have provided via the environment, config files, or command line arguments](https://cecli.dev/docs/config/api-keys.html).
Based on the available keys, cecli will select the best model to use.

## OpenRouter

If you have not provided any keys, cecli will offer to help you connect to 
[OpenRouter](http://openrouter.ai)
which provides both free and paid access to most popular LLMs.
Once connected, cecli will select the best model available on OpenRouter
based on whether you have a free or paid account there.

## Specifying model & key

You can also tell cecli which LLM to use and provide an API key.
The easiest way is to use the `--model` and `--api-key`
command line arguments, like this:

```
# Work with DeepSeek via DeepSeek's API
cecli --model deepseek --api-key deepseek=your-key-goes-here

# Work with Claude 3.7 Sonnet via Anthropic's API
cecli --model sonnet --api-key anthropic=your-key-goes-here

# Work with o3-mini via OpenAI's API
cecli --model o3-mini --api-key openai=your-key-goes-here

# Work with Sonnet via OpenRouter's API
cecli --model openrouter/anthropic/claude-3.7-sonnet --api-key openrouter=your-key-goes-here

# Work with DeepSeek Chat V3 via OpenRouter's API
cecli --model openrouter/deepseek/deepseek-chat --api-key openrouter=your-key-goes-here
```

For more information, see the documentation sections:

- [Connecting to LLMs](https://cecli.dev/docs/llms.html)
- [Configuring API keys](https://cecli.dev/docs/config/api-keys.html)
