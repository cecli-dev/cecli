---
parent: Connecting to LLMs
nav_order: 400
---

# GROQ

Groq currently offers *free* API access to the models they host.
The Llama 3 70B model works
well with cecli and is comparable to GPT-3.5 in code editing performance.
You'll need a [Groq API key](https://console.groq.com/keys).

First, install cecli:

{% include install.md %}

Then configure your API keys:

```
export GROQ_API_KEY=<key> # Mac/Linux
setx   GROQ_API_KEY <key> # Windows, restart shell after setx
```

Start working with cecli and Groq on your codebase:

```bash
# Change directory into your codebase
cd /to/your/project

cecli --model groq/llama3-70b-8192

# List models available from Groq
cecli --list-models groq/
```


