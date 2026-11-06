---
parent: Configuration
nav_order: 16
description: Connect cecli to a real browser for automation and JavaScript-rendered pages.
---

# Browser

cecli can drive a real Chrome or Chromium browser through the
[browser-harness](https://github.com/browser-use/browser-harness) CLI. This is useful when a page
needs JavaScript, an existing login, or normal browser interaction. The `/web` command also uses it
to scrape JavaScript-rendered pages before falling back to plain HTTP.

browser-harness ships with cecli on Python 3.11 and newer. You only need a supported browser
installed on the machine. On older Python versions, `/web` falls back to plain HTTP.

## Quick start

Most users do not need to configure anything. When the agent runs a browser-harness command, cecli
connects to a browser that is already available for automation. If none is found, it launches a
dedicated Chrome profile at `~/.cecli/browser-profile`. Whenever a live browser is already running,
cecli exports `BU_CDP_URL` so shell commands and browser-harness can attach to it.

To connect to a browser you are already running, start Chrome with remote debugging enabled:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.cecli/browser-profile"
```

You can also open `chrome://inspect/#remote-debugging` and allow remote debugging for the current
browser instance.

Then tell cecli to use it without launching another browser:

```yaml
browser:
  cdp_url: http://127.0.0.1:9222
  launch: false
```

## Configuration

Set browser options with the `--browser` command-line option or the top-level `browser` key in a
config file. `--browser` accepts a JSON/YAML string or a path to a file:

```bash
cecli --browser '{"cdp_url": "http://127.0.0.1:9222", "launch": false}'
```

## Defaults

| Option | Default | Description |
|--------|---------|-------------|
| `cdp_url` | not set | Connect to this browser instead of searching for one. |
| `port` | `9222` | Port used when cecli launches a browser. |
| `user_data_dir` | `~/.cecli/browser-profile` | Profile directory used for launched browsers. |
| `launch_command` | auto-detected | Custom browser launch command. |
| `launch` | `true` | Launch a browser when a browser-harness command needs one. |
| `headless` | `false` | Run launched browsers without a visible window. The scraper always requests a headless launch. |
| `launch_timeout` | `10` | Seconds to wait for a launched browser to become ready. |
| `harness_timeout` | `30` | Seconds allowed for a browser-harness scrape. |

cecli looks for common Chrome, Chromium, Edge, Brave, and Vivaldi installations. It also checks the
usual local debugging ports when `cdp_url` is not set.

## Examples

### Use a dedicated profile on another port

```yaml
browser:
  port: 9333
  user_data_dir: ~/.cecli/browser-profile-work
```

### Run launched browsers headless

```yaml
browser:
  headless: true
```

### Use a custom launch command

```yaml
browser:
  launch_command: >-
    google-chrome --remote-debugging-port={port}
    --user-data-dir={user_data_dir} --headless=new
```

The launch command may use `{port}`, `{user_data_dir}` or `{profile_dir}`, `{headless}`, and
`{url}` placeholders.

### Never launch a browser automatically

```yaml
browser:
  launch: false
```

With `launch: false`, cecli only uses an existing browser. If none is available, browser-harness
commands fail instead of opening a new window.

## Scraping

`/web` uses browser-harness to render pages, then falls back to plain HTTP when browser-harness
cannot retrieve the page.