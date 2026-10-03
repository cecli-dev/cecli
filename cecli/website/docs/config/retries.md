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

Example usage in `.cecli.conf.yml`:

```yaml
retries:
  retry-timeout: 30
  retry-backoff-factor: 1.50
  retry-on-unavailable: true
```

This can also be set with the `--retries` command line switch, passing a JSON string:

```
$ cecli --retries '{"retry-timeout": 30, "retry-backoff-factor": 1.50, "retry-on-unavailable": true}'
```

Or by setting the `CECLI_RETRIES` environment variable:

```
export CECLI_RETRIES='{"retry-timeout": 30, "retry-backoff-factor": 1.50, "retry-on-unavailable": true}'
```

> **Tip:**
> See the
> [API key configuration docs](api-keys.html)
> for information on how to configure and store your API keys.
