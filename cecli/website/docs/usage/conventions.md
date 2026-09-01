---
parent: Usage
nav_order: 800
description: Tell Cecli to follow your coding conventions when it works on your code.
---
# Convention Files

Sometimes you want LLMs to be aware of certain coding guidelines, like whether to provide type hints, which libraries or packages to prefer, etc.

The easiest way to do that with cecli is to simply create a small markdown file and include it in the chat.

For example, say we want our python code to:

```
- Prefer httpx over requests for making http requests.
- Use types everywhere possible.
```

We would simply create a file like `CONVENTIONS.md` with those lines and then we can add it to the cecli chat, along with the file(s) that we want to edit.

It's best to load the conventions file with `/rules CONVENTIONS.md` or `cecli --rules CONVENTIONS.md`.


## Always load conventions

You can also configure cecli to always load your conventions file in the [`.cecli.conf.yml` config file](../config/conf.html):


```yaml
# alone
rules: CONVENTIONS.md

# multiple files
rules: [CONVENTIONS.md, AGENTS.md]
```
