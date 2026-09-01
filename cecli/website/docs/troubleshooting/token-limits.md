---
parent: Troubleshooting
nav_order: 25
---

# Token limits

Every LLM has limits on how many tokens it can process for each request:

- The model's **context window** limits how many total tokens of
*input and output* it can process.
- Each model has limit on how many **output tokens** it can
produce.

Cecli will report an error **if a model responds** indicating that it has exceeded a token limit. The error will include suggested actions to try and avoid hitting token limits.

Here's an example error: 

```
Model gpt-3.5-turbo has hit a token limit!

Input tokens: 768 of 16385
Output tokens: 4096 of 4096 -- exceeded output limit!
Total tokens: 4864 of 16385

To reduce output tokens:
- Ask for smaller changes in each request.
- Break your code into smaller source files.
- Try using a stronger model like DeepSeek V3 or Sonnet that can return diffs.

For more info: https://cecli.dev/docs/token-limits.html
```

> **Note:** cecli never *enforces* token limits, it only *reports* token limit errors from the API provider. The token counts that cecli reports are *estimates*.

## Input tokens & context window size

The most common problem is trying to send too much data to a model, overflowing its context window. Technically you can exhaust the context window if the input is too large or if the input plus output are too large.

Strong models like GPT-4o and Sonnet have quite large context windows, so this sort of error is typically only an issue when working with weaker models.

The easiest solution is to try and reduce the input tokens by removing files from the chat. It's best to only add the files that cecli will need to *edit* to complete your request.

- Use `/tokens` to see token usage.
- Use `/drop` to remove unneeded files from the chat session.
- Use `/clear` to clear the chat history.
- Break your code into smaller source files.

## Output token limits

Most models have quite small output limits, often as low as 4k tokens. If you ask cecli to make a large change that affects a lot of code, the LLM may hit output token limits as it tries to send back all the changes.

To avoid hitting output token limits:

- Ask for smaller changes in each request.
- Break your code into smaller source files.
- Use a strong model like gpt-4o, sonnet or DeepSeek V3 that can return diffs.
- Use a model that supports [infinite output](../more/infinite-output.html).

## Other causes

Sometimes token limit errors are caused by non-compliant API proxy servers or bugs in the API server you are using to host a local model. cecli has been well tested when directly connecting to major [LLM provider cloud APIs](../llms.html). For serving local models, [Ollama](../llms/ollama.html) is known to work well with cecli.

Try using cecli without an API proxy server or directly with one of the recommended cloud APIs and see if your token limit problems resolve.

## More help

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
