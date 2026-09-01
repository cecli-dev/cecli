---
nav_order: 55
has_children: true
description: How to use cecli to pair program with AI and edit code in your local git repo.
---

# Usage

Cecli is a general terminal agent that can be used for coding, analysis, research and other workflows that can be expressed programmatically through scripting, file modification, and CLI commands.

## Adding files

To edit files, you need to "add them to the chat". You can use the in-chat `/add` command to add files. They can be existing files or the name of files you want cecli to create for you. With no arguments, `/add` will open a fuzzy finder that lets you select files from your repository. This feature is enabled if you have `fzf` installed. Otherwise, `/add` requires file paths as arguments.

Only add the files that need to be edited for your task. Don't add a bunch of extra files. If you add too many files, the LLM can get overwhelmed and confused (and it costs more tokens). cecli will automatically pull in content from related files so that it can [understand the rest of your code base](repomap.html).

You can use cecli without adding any files, and it will try to figure out which files need to be edited based on your requests.

### Adding files (CLI)

You can also add files directly from the CLI with:

```
cecli <file1> <file2> ...
```

At the cecli `>` prompt, ask for code changes and cecli will edit those files to accomplish your request.

```
$ cecli factorial.py

cecli v1.0.0
Models         deepseek-v4-flash (main)
Settings       diff (edit format) • prompt cache • infinite output
Environment    .git (258 files) • repo-map disabled
───────────────────────────────────────────────────────────────────
> Make a program that asks for a number and prints its factorial

...
```

> **Tip:** You'll get the best results if you think about which files need to be edited. Add **just** those files to the chat. cecli will include relevant context from the rest of your repo.

## Read-only files

You can also add files to the chat as "read-only" files. cecli can see these files for context, but can't edit them. This is useful for providing reference documentation, specifications, or examples of existing code that you don't want the AI to modify.

Use the `/read-only` command to add files in read-only mode. Like `/add`, running `/read-only` with no arguments will open a fuzzy finder to select files if `fzf` is installed.

If you run `/read-only` with no arguments and don't select any files, it will convert all editable files currently in the chat to read-only. This is a convenient way to protect a set of files from being modified after you've added them for context.

You can also move a file from read-only to editable by using `/add` on a file that is already in the chat as read-only.

## LLMs

Cecli can [connect to almost any LLM, including local models](https://cecli.chat/docs/llms.html).

```
$ cecli --model gemini/gemini-3.5-flash


$ cecli --model deepseek/deepseek-v4-flash
```

Or you can run `cecli --model XXX` to launch cecli with another model. During your chat you can switch models with the in-chat `/model` command.

## Making changes

Ask cecli to make changes to your code. It will show you some diffs of the changes it is making to complete you request. [cecli will git commit all of its changes](git.html), so they are easy to track and undo.

You can always use the `/undo` command to undo AI changes that you don't like.

> **Tip:**
> Use `/help <question>` to [ask for help about using cecli](troubleshooting/support.html), customizing settings, troubleshooting, using LLMs, etc.