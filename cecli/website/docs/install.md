---
title: Installation
has_children: true
nav_order: 20
description: How to install and get started pair programming with cecli.
---

# Installation

## One-liners

These one-liners will install cecli, along with python 3.12 if needed (cecli supports Python 3.10-3.14). They are based on the [uv installers](https://docs.astral.sh/uv/getting-started/installation/).

#### Linux & Mac

Use curl to download the script and execute it with sh:

```bash
curl -LsSf https://cecli.dev/install.sh | sh
```

If your system doesn't have curl, you can use wget:

```bash
wget -qO- https://cecli.dev/install.sh | sh
```

#### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://cecli.dev/install.ps1 | iex"
```

## Install with uv

You can install cecli with uv:

```bash
uv tool install --native-tls --python python3.12 cecli-dev
```

This will install cecli in its own isolated environment. If needed, uv will automatically install a separate python 3.12 to use with cecli (cecli supports Python 3.10-3.14).

Also see the [docs on other methods for installing uv itself](https://docs.astral.sh/uv/getting-started/installation/).

## Install with pipx

You can install cecli with pipx:

```bash
python -m pip install pipx  # If you need to install pipx
pipx install cecli-dev
```

You can use pipx to install cecli with python versions 3.10-3.14.

Also see the [docs on other methods for installing pipx itself](https://pipx.pypa.io/stable/installation/).

## Other install methods

You can install cecli with the methods described below, but one of the above methods is usually safer.

#### Install with pip

If you install with pip, you should consider using a [virtual environment](https://docs.python.org/3/library/venv.html) to keep cecli's dependencies separated.

You can use pip to install cecli with python versions 3.10-3.14.

```bash
pip install cecli-dev
```

or

```bash
uv pip install --native-tls cecli-dev
```

## Basic Configuration

We highly recommend using an `.cecli.conf.yml` file in your project directories. A good place to get started is:

```yaml
model: <model of your choice>
agent: true
auto-commits: true
auto-save: true
cache-prompts: true
check-update: true
enable-context-compaction: true
context-compaction-max-tokens: 0.8
show-model-warnings: true

agent-config:
  large_file_token_threshold: 8192
  skip_cli_confirmations: false

mcp-servers:
  mcpServers:
    context7:
      transport: http
      url: https://mcp.context7.com/mcp
```

### Run Program

If you are in the directory with your .cecli.conf.yml file, then simply running `cecli` will start the agent with your configuration. For best results, since terminal emulators can be finicky, we highly suggest running:

```bash
cecli --terminal-setup
```

On first run to configure keybindings for the program (notably `shift+enter`). Support for terminals is ongoing so feel free to make a github issue or chat in the discord for us to figure out what's needed to support automatically setting up a given terminal.

## Next steps...

See the [usage instructions](usage.html) to start coding with cecli.
