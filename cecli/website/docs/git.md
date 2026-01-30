---
parent: More info
nav_order: 100
description: cecli is tightly integrated with git.
---

# Git integration

cecli works best with code that is part of a git repo.
cecli is tightly integrated with git, which makes it easy to:

  - Use the `/undo` command to instantly undo any AI changes that you don't like.
  - Go back in the git history to review the changes that cecli made to your code
  - Manage a series of cecli's changes on a git branch

cecli uses git in these ways:

- It asks to create a git repo if you launch it in a directory without one.
- Whenever cecli edits a file, it commits those changes with a descriptive commit message. This makes it easy to undo or review cecli's changes. 
- cecli takes special care before editing files that already have uncommitted changes (dirty files). cecli will first commit any preexisting changes with a descriptive commit message. 
This keeps your edits separate from cecli's edits, and makes sure you never lose your work if cecli makes an inappropriate change.

## In-chat commands

cecli also allows you to use 
[in-chat commands](/docs/usage/commands.html)
to perform git operations:

- `/diff` will show all the file changes since the last message you sent.
- `/undo` will undo and discard the last change.
- `/commit` to commit all dirty changes with a sensible commit message.
- `/git` will let you run raw git commands to do more complex management of your git history.

You can also manage your git history outside of cecli with your preferred git tools.

## Disabling git integration

While it is not recommended, you can disable cecli's use of git in a few ways:

  - `--no-auto-commits` will stop cecli from git committing each of its changes.
  - `--no-dirty-commits` will stop cecli from committing dirty files before applying its edits.
  - `--no-git` will completely stop cecli from using git on your files. You should ensure you are keeping sensible backups of the files you are working with.
  - `--git-commit-verify` will run pre-commit hooks when making git commits. By default, cecli skips pre-commit hooks by using the `--no-verify` flag (`--git-commit-verify=False`).

## Commit messages

cecli sends the `--weak-model` a copy of the diffs and the chat history
and asks it to produce a commit message.
By default, cecli creates commit messages which follow
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

You can customize the
[commit prompt](https://github.com/dwash96/cecli/blob/main/cecli/prompts.py#L5)
with the `--commit-prompt` option.
You can place that on the command line, or 
[configure it via a config file or environment variables](https://cecli.dev/docs/config.html).


## Commit attribution

cecli marks commits that it either authored or committed.

- If cecli authored the changes in a commit, they will have "(cecli)" appended to the git author and git committer name metadata.
- If cecli simply committed changes (found in dirty files), the commit will have "(cecli)" appended to the git committer name metadata.

You can use `--no-attribute-author` and `--no-attribute-committer` to disable
modification of the git author and committer name fields.

Additionally, you can use the following options to prefix commit messages:

- `--attribute-commit-message-author`: Prefix commit messages with 'cecli: ' if cecli authored the changes.
- `--attribute-commit-message-committer`: Prefix all commit messages with 'cecli: ', regardless of whether cecli authored the changes or not.

Finally, you can use `--attribute-co-authored-by` to have cecli append a Co-authored-by trailer to the end of the commit string. 
This will disable appending `(cecli)` to the git author and git committer unless you have explicitly enabled those settings.

