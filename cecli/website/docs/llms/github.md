---
parent: Connecting to LLMs
nav_order: 510
---

# GitHub Copilot

Cecli can connect to GitHub Copilot’s LLMs because Copilot exposes a standard **OpenAI-style** endpoint at:

```
https://api.githubcopilot.com
```

First, install cecli:

```bash
uv tool install cecli-dev
```

---

When you specify a GitHub Copilot model on start up (e.g. `github_copilot/gpt-5-mini`), cecli will enter a GitHub auth workflow natively, wherein you will connect to your GitHub account with the provided auth code to grant the system access.