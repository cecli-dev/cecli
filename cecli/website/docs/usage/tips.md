---
parent: Usage
nav_order: 25
description: Tips for AI pair programming with cecli.
---

# Tips

## Just add the files that need to be changed to the chat

Take a moment and think about which files will need to be changed.
cecli can often figure out which files to edit all by itself, but the most efficient approach is for you to add the files to the chat.

## Don't add lots of files to the chat

Just add the files you think need to be edited.
Too much irrelevant code will distract and confuse the LLM.
cecli uses a [map of your entire git repo](https://cecli.dev/docs/repomap.html)
so is usually aware of relevant classes/functions/methods elsewhere in your code base.
It's ok to add 1-2 highly relevant files that don't need to be edited,
but be selective.

## Break your goal down into bite sized steps

Do them one at a time. 
Adjust the files added to the chat as you go: `/drop` files that don't need any more changes, `/add` files that need changes for the next step.

## For complex changes, discuss a plan first

Use the [`/ask` command](modes.html) to make a plan with cecli.
Once you are happy with the approach, just say "go ahead" without the `/ask` prefix.

## If cecli gets stuck

- Use `/clear` to discard the chat history and make a fresh start.
- Can you `/drop` any extra files?
- Use `/ask` to discuss a plan before cecli starts editing code.
- Use the [`/model` command](commands.html) to switch to a different model and try again. Switching between GPT-4o and Sonnet will often get past problems.
- If cecli is hopelessly stuck,
just code the next step yourself and try having cecli code some more after that.
Take turns and pair program with cecli.

## Creating new files

If you want cecli to create a new file, add it to the repository first with `/add <file>`.
This way cecli knows this file exists and will write to it. 
Otherwise, cecli might write the changes to an existing file.
This can happen even if you ask for a new file, as LLMs tend to focus a lot
on the existing information in their contexts.

## Fixing bugs and errors

If your code is throwing an error, 
use the [`/run` command](commands.html)
to share the error output with the cecli.
Or just paste the errors into the chat. Let the cecli figure out how to fix the bug.

If test are failing, use the [`/test` command](lint-test.html)
to run tests and
share the error output with the cecli.

## Providing docs

LLMs know about a lot of standard tools and libraries, but may get some of the fine details wrong about API versions and function arguments.

You can provide up-to-date documentation in a few ways:

- Paste doc snippets into the chat.
- Include a URL to docs in your chat message
and cecli will scrape and read it. For example: `Add a submit button like this https://ui.shadcn.com/docs/components/button`. 
- Use the [`/read` command](commands.html) to read doc files into the chat from anywhere on your filesystem.
- If you have coding conventions or standing instructions you want cecli to follow, consider using a [conventions file](conventions.html).

## Interrupting & inputting

Use Control-C to interrupt cecli if it isn't providing a useful response. The partial response remains in the conversation, so you can refer to it when you reply with more information or direction.

{% include multi-line.md %}

