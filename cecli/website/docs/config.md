---
nav_order: 55
has_children: true
description: Information on all of cecli's settings and how to use them.
---

# Configuration

cecli has many options which can be set with
command line switches.
Most options can also be set in an `.aider.conf.yml` file
which can be placed in your home directory or at the root of
your git repo. 
Or by setting environment variables like `CECLI_xxx`
either in your shell or a `.env` file.

Here are 4 equivalent ways of setting an option. 

With a command line switch:

```
$ cecli --dark-mode
```

Using a `.aider.conf.yml` file:

```yaml
dark-mode: true
```

By setting an environment variable:

```
export CECLI_DARK_MODE=true
```

Using an `.env` file:

```
CECLI_DARK_MODE=true
```


## Retries

cecli can be configured to retry failed API calls.
This is useful for handling intermittent network issues or other transient errors.
The `retries` option is a JSON object that can be configured with the following keys:

- `retry-timeout`: The timeout in seconds for each retry.
- `retry-backoff-factor`: The backoff factor to use between retries.
- `retry-on-unavailable`: Whether to retry on 503 Service Unavailable errors.

Example usage in `.aider.conf.yml`:

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
{% include keys.md %}
