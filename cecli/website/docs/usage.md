---
nav_order: 30
has_children: true
description: How to use cecli to pair program with AI and edit code in your local git repo.
---

# Usage

Run `cecli` with the source code files you want to edit.
These files will be "added to the chat session", so that
cecli can see their
contents and edit them for you.
They can be existing files or the name of files you want
cecli to create for you.

```
cecli <file1> <file2> ...
```

At the cecli `>` prompt, ask for code changes and cecli
will edit those files to accomplish your request.


```
$ cecli factorial.py

cecli v0.37.1-dev
Models: gpt-4o with diff edit format, weak model gpt-3.5-turbo
Git repo: .git with 258 files
Repo-map: using 1024 tokens
Use /help to see in-chat commands, run with --help to see cmd line args
───────────────────────────────────────────────────────────────────────
> Make a program that asks for a number and prints its factorial

...
```

{% include help-tip.md %}

## Adding files

To edit files, you need to "add them to the chat".
Do this
by naming them on the cecli command line.
Or, you can use the in-chat
`/add` command to add files. With no arguments, `/add` will open a fuzzy finder that lets you select files from your repository. This feature is enabled if you have `fzf` installed. Otherwise, `/add` requires file paths as arguments.


Only add the files that need to be edited for your task.
Don't add a bunch of extra files.
If you add too many files, the LLM can get overwhelmed
and confused (and it costs more tokens).
cecli will automatically
pull in content from related files so that it can
[understand the rest of your code base](https://cecli.dev/docs/repomap.html).

You can use cecli without adding any files,
and it will try to figure out which files need to be edited based
on your requests.

{: .tip }
You'll get the best results if you think about which files need to be
edited. Add **just** those files to the chat. cecli will include
relevant context from the rest of your repo.

## Read-only files

You can also add files to the chat as "read-only" files. cecli can see these files for context, but can't edit them. This is useful for providing reference documentation, specifications, or examples of existing code that you don't want the AI to modify.

Use the `/read-only` command to add files in read-only mode. Like `/add`, running `/read-only` with no arguments will open a fuzzy finder to select files if `fzf` is installed.

If you run `/read-only` with no arguments and don't select any files, it will convert all editable files currently in the chat to read-only. This is a convenient way to protect a set of files from being modified after you've added them for context.

You can also move a file from read-only to editable by using `/add` on a file that is already in the chat as read-only.

## LLMs

{% include works-best.md %}

```
# o3-mini
$ cecli --model o3-mini --api-key openai=<key>

# Claude 3.7 Sonnet
$ cecli --model sonnet --api-key anthropic=<key>
```

Or you can run `cecli --model XXX` to launch cecli with
another model.
During your chat you can switch models with the in-chat
`/model` command.

## Making changes

Ask cecli to make changes to your code.
It will show you some diffs of the changes it is making to
complete you request.
[cecli will git commit all of its changes](/docs/git.html),
so they are easy to track and undo.

You can always use the `/undo` command to undo AI changes that you don't
like.
