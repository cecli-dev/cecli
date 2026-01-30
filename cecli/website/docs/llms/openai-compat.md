---
parent: Connecting to LLMs
nav_order: 500
---

# OpenAI compatible APIs

cecli can connect to any LLM which is accessible via an OpenAI compatible API endpoint.

First, install cecli:

{% include install.md %}

Then configure your API key and endpoint:

```
# Mac/Linux:
export OPENAI_API_BASE=<endpoint>
export OPENAI_API_KEY=<key>

# Windows:
setx OPENAI_API_BASE <endpoint>
setx OPENAI_API_KEY <key>
# ... restart shell after setx commands
```

Start working with cecli and your OpenAI compatible API on your codebase:

```bash
# Change directory into your codebase
cd /to/your/project

# Prefix the model name with openai/
cecli --model openai/<model-name>
```

See the [model warnings](warnings.html)
section for information on warnings which will occur
when working with models that cecli is not familiar with.
