---
parent: Connecting to LLMs
nav_order: 700
---

# OpenCode Go

Cecli can connect to [OpenCode Go](https://opencode.ai/go), a subscription that provides access to many coding models. You'll need an OpenCode Go API key.

First, install cecli:

```bash
uv tool install cecli-dev
```

Then configure your API key:

```
export OPENCODE_GO_API_KEY=<key> # Mac/Linux
setx   OPENCODE_GO_API_KEY <key> # Windows, restart shell after setx
```

Start working with cecli and OpenCode Go on your codebase:

```bash
# Change directory into your codebase
cd /to/your/project

# Use the DeepSeek V4 Flash model
cecli --model opencode-go/deepseek-v4-flash

# List models available from OpenCode Go
cecli --list-models opencode-go/
```

