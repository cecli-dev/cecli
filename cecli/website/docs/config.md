---
nav_order: 40
has_children: true
description: Information on all of cecli's settings and how to use them.
---

# Configuration

cecli has many options which can be set with
command line switches.
Most options can also be set in an `.cecli.conf.yml` file
which can be placed in your home directory or at the root of
your git repo. 
Or by setting environment variables like `CECLI_xxx`
either in your shell or a `.env` file.

Here are 4 equivalent ways of setting an option. 

With a command line switch:

```
$ cecli --dark-mode
```

Using a `.cecli.conf.yml` file:

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


## Default `~/.cecli/` Locations

cecli also checks several default locations inside `~/.cecli/` for
configuration, environment variables, and agent resources.
These are always included with lower precedence than project-level equivalents,
so a setting in a project `.cecli.conf.yml` or `.env` file will override the
`~/.cecli/` default.

### `~/.cecli/conf.yml`

A YAML configuration file read after all other config file sources,
making it the lowest-precedence config option. Useful for setting
machine-wide defaults that individual projects can override.
See the [configuration section](/docs/config/conf.html) above for supported options.

### `~/.cecli/.env`

An environment file loaded before any other `.env` file, so project-level
`.env` files can override its values. A convenient place to store
API keys or other environment variables used across multiple projects.

### `~/.cecli/skills/`

A directory containing skill packages (each a sub-directory with a
`SKILL.md` file). Skills here are discoverable alongside those in any
user-configured skills paths.

### `~/.cecli/subagents/`

A directory containing sub-agent definition files (`.md` files with
YAML front matter). Sub-agents here are registered alongside those in
any user-configured sub-agent paths.


## Prompt Queue Configuration

- `max_queue_size`: Maximum number of prompts that can be queued in a single session (default: 100, range: 1-1000). Environment variable: `CECLI_MAX_QUEUE_SIZE`.
- `max_prompt_length`: Maximum length of a single queued prompt (default: 10,000, range: 100-50,000). Environment variable: `CECLI_MAX_PROMPT_LENGTH`.

## Prompt Queue Configuration

- `max_queue_size`: Maximum number of prompts that can be queued in a single session (default: 100, range: 1-1000). Environment variable: `CECLI_MAX_QUEUE_SIZE`.
- `max_prompt_length`: Maximum length of a single queued prompt (default: 10,000, range: 100-50,000). Environment variable: `CECLI_MAX_PROMPT_LENGTH`.

{% include keys.md %}
