---
parent: Configuration
nav_order: 600
description: How to configure cecli retry behavior for failed API calls.
---

# Retries

Cecli can be configured to retry failed API calls. This is useful for handling intermittent network issues or other transient errors. The `retries` option is a JSON object that can be configured with the following keys:

- `retry-timeout`: The timeout in seconds for each retry.
- `retry-backoff-factor`: The backoff factor to use between retries.
- `retry-on-unavailable`: Whether to retry on 503 Service Unavailable errors.
- `retry-on-empty`: Whether to retry when the model returns an empty response. A response is considered empty when it has no content, no tool calls, and no *meaningful* reasoning. Reasoning that contains no alphanumeric characters (for example a `reasoning_content` of `"!!!!"`) does not count as a response, so it is retried like any other empty response.
- `retry-on-unauthorized`: Whether to retry on 401 Unauthorized (and 403 Forbidden) errors. Default: false.
- `min-switch-reset-seconds`: When a rate limit names its reset time and that
  reset is sooner than this many seconds, wait it out on the same model instead
  of switching to a fallback. Default: 0 (always prefer switching).
- `fallbacks`: Failover configuration, applied after the same-model retry
  budget is exhausted (or, after at least one quick retry, on a rate limit
  with a long declared reset window).

## Fallback models and credential pools

The `fallbacks` block configures two independent layers of resilience, tried
in order:

1. **Credential pools** (`fallbacks.keys`): on a 429 or auth failure, the next
   available API key is tried *for the same provider* before anything else.
   Entries are environment-variable names; unset ones are skipped. Providers
   with dedicated auth flows (GitHub Copilot, Bedrock, Ollama) ignore pools.
2. **Model chains** (`fallbacks.models`): when credentials cannot serve the
   request, cecli switches mid-request to the next model in the chain for the
   model's role (`model`, `agent`, `weak`, `editor`). A model is never skipped
   over without at least one retry against it, so the retry timeout is always
   honored on the current model before a switch (rate-limit waits are capped
   at 1s when a fallback is pending, rather than sleeping out the full reset).
   On activation the failed model is *benched* for the duration of its reset
   window (or `retry-timeout` when none is declared); later requests skip
   benched models and return to the primary once its bench expires. Every
   activation is announced in the chat.

Chain entries accept the same names as `--model` (aliases included). A bare
list under `fallbacks:` is treated as the main chain. Candidate models are
used exactly as configured: cecli does not validate that a fallback matches
the primary's context window or tool-calling ability, so curate chains
yourself.

```yaml
retries:
  retry-timeout: 30
  min-switch-reset-seconds: 120
  fallbacks:
    models:
      model:
        - openrouter/anthropic/claude-sonnet-4
        - gemini/gemini-2.5-pro
      agent:
        - haiku
      weak:
        - gemini/gemini-2.5-flash-lite
    keys:
      openai:
        - OPENAI_API_KEY
        - OPENAI_API_KEY_2
```

Example usage in `.cecli.conf.yml`:

```yaml
retries:
  retry-timeout: 30
  retry-backoff-factor: 1.50
  retry-on-unavailable: true
  retry-on-unauthorized: false
```

This can also be set with the `--retries` command line switch, passing a JSON string:

```
$ cecli --retries '{"retry-timeout": 30, "retry-backoff-factor": 1.50, "retry-on-unavailable": true, "retry-on-unauthorized": false}'
```

Or by setting the `CECLI_RETRIES` environment variable:

```
export CECLI_RETRIES='{"retry-timeout": 30, "retry-backoff-factor": 1.50, "retry-on-unavailable": true, "retry-on-unauthorized": false}'
```

> **Tip:**
> See the
> [API key configuration docs](api-keys.html)
> for information on how to configure and store your API keys.
