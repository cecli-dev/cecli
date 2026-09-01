---
parent: Troubleshooting
excerpt: Use "/help <question>" to ask for help about using cecli, customizing settings, troubleshooting, using LLMs, etc.
nav_order: 30
---

# Using /help

Type `/help <question>` and cecli will respond with helpful information. You can ask questions about using cecli, customizing settings, troubleshooting, using LLMs, etc.

Behind the scenes, cecli has indexed all of its [documentation](../index.html). It uses the question to find relevant docs and share them with the LLM to do retrieval augmented generation (RAG) The LLM also has the full context of your ongoing cecli chat, so it can help with the exact issue you might be facing.


> cecli v0.42.1-dev  
> Models: claude-3-5-sonnet with diff edit format  
> Repo-map: using 1024 tokens  
> Use /help \<question\> to ask for help, run with --help to see cmd line args  

#### /help is the .env file global or for a git repo?

Based on the provided documentation, here's the answer to your question about the .env file in cecli:

The .env file in cecli can be both global and specific to a git repository. cecli looks for .env files in multiple locations, with the following priority order:

1. Your home directory (global)
2. The root of your git repo (repo-specific)
3. The current directory
4. A file specified with the `--env-file <filename>` parameter

If multiple .env files exist in these locations, they are loaded in the order listed above, with files loaded last taking priority. This means you can have a global .env file in your home directory with general settings, and then override or add to those settings with a repo-specific .env file in your git repository root.

Here are some relevant documentation links that you might find helpful:

- https://cecli.dev/docs/config/
- https://cecli.dev/docs/config/dotenv/

The ability to use both global and repo-specific .env files allows for flexible configuration, where you can set default values globally and override them on a per-project basis as needed.


#### /help can i use local LLMs?

Yes, you can use local LLMs with cecli. Here's a summary of the options:

1. Ollama: cecli supports using local models through Ollama.

2. OpenAI-compatible API: cecli can access local models that provide an OpenAI-compatible API.

3. Other local models: cecli connects directly to many LLM providers, including local and OpenAI-compatible endpoints (Ollama, LM Studio, etc.).

However, it's important to note that cecli works best with more capable models. Less capable models may have difficulty properly returning code edits, which could result in cecli not being able to edit your files and commit changes effectively.

For more detailed information on using local LLMs and connecting to various models, you might want to check out these relevant documentation pages:

- https://cecli.dev/docs/llms/
- https://cecli.dev/docs/llms/ollama/
- https://cecli.dev/docs/llms/openai-compat/

Keep in mind that the performance and capabilities of local LLMs may vary depending on the specific model and your hardware resources.


## Getting more help

If you need more help, please check our
[GitHub issues](https://github.com/cecli-dev/cecli/issues)
and file a new issue if your problem isn't discussed.
Or drop into our
[Discord](https://discord.gg/g4bF53fSWF)
to chat with us.

When reporting problems, it is very helpful if you can provide:

- cecli version
- LLM model you are using

Including the "announcement" lines that
aider prints at startup
is an easy way to share this helpful info.

```
Aider v0.37.1-dev
Models: gpt-4o with diff edit format, weak model gpt-3.5-turbo
Git repo: .git with 243 files
Repo-map: using 1024 tokens
```

> **Tip:**
> Use `/help <question>` to 
> [ask for help about using cecli](support.html),
> customizing settings, troubleshooting, using LLMs, etc.
