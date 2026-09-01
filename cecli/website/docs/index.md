---
title: Documentation
---

# Documentation

It's a terminal agent! LLMs yap enough and I won't belabor the point.

## Getting Started

```bash
uv pip install cecli-dev

# Change directory into your codebase
cd /to/your/project

# Claude 5 Sonnet
cecli --model claude-sonnet-5 --api-key anthropic=<key>

# Gemini 3.5 Flash
cecli --model gemini/gemini-3.5-flash-preview --api-key gemini=<key>

# GPT-5.6 Luna
cecli --model openai/gpt-5.6-luna --api-key openai=<key>

# DeepSeek V4 Flash
cecli --model deepseek/deepseek-v4-flash --api-key deepseek=<key>
```

## More Information

### Documentation

Everything you need to get started and make the most of cecli.

- [Installation Guide](install.html)
- [Usage Guide](usage.html)
- [Connecting to LLMs](llms.html)
- [Configuration Options](config.html)
- [Troubleshooting](troubleshooting.html)

### Community & Resources

Connect with other users and find additional resources.

- [GitHub Repository](https://github.com/cecli-dev/cecli)
- [Discord Community](https://discord.gg/AX9ZEA7nJn)
- [Release notes](https://github.com/cecli-dev/cecli/releases)
- [LLM Leaderboards](leaderboards/index.html)

## Reference

- [In-chat commands](usage/commands.html)
- [Options reference](config/options.html)
