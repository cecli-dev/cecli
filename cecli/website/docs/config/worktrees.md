---
parent: Configuration
nav_order: 49
description: Isolated git worktrees give each agent or workflow run its own checkout and branch.
---
# Worktrees

Worktrees let an agent or workflow run modify a repository without touching the main checkout. cecli creates a linked git worktree, runs the agent inside it, and releases it afterwards — committing unfinished changes so nothing is lost.

## Enabling

Workflows opt in with `worktree: true` (or `worktree: {branch: <ref>}`); see [Workflows](workflows.html). A workflow's `repo` is the source repository; `root` selects the base working directory. When a worktree is enabled, the agent's actual root is the generated worktree checkout. `branch` selects the starting base ref; when omitted the source repository's default branch is used.

## Branch namespace

Every worktree gets a generated branch named `cecli/<agent>-<uuid>`. Agent names are sanitized for git, so `wf:nightly-tidy` becomes `cecli/wf-nightly-tidy-<uuid>`. Generated branches live alongside your normal branches and can be inspected, pushed, or merged like any other branch.

## Lifecycle

1. **Create** — a worktree is created from the source repository on the generated branch. Remote sources are cached as bare repositories first.
2. **Run** — the agent works inside the worktree; its `root` points at the checkout.
3. **Release** — on cleanup, a dirty worktree is committed with the subject `Unfinished Dirty Worktree from agent <uuid>` so uncommitted work survives. Branches with unmerged commits are kept; empty or already-merged branches are deleted.
4. **Remove** — the worktree checkout under `~/.cecli/worktrees/` is removed after the commit/release step. Kept branches remain in the source repository.

## Session restore

A workflow or delegated agent restored from a saved session keeps its worktree record (`branch`, `path` and related metadata). On restore, cecli recreates or re-attaches the worktree from that record when possible; if the checkout is gone but the branch still contains work, the branch is the durable artifact to recover.

## Disk layout

`CECLI_WORKTREES_DIR` overrides the base directory; the default is `~/.cecli/worktrees/`.

```
~/.cecli/worktrees/
  _sources/<repo-slug>-<sha8>/       # cached bare clones for remote sources
  <repo-slug>/
    <agent-slug>-<uuid>/             # one linked worktree checkout per run
```

Local `repo:` paths are used in place as the source repository; the checkout itself still lives under the worktrees base directory. Removing a checkout or the whole base directory is safe once a run has finished: commits are on the kept branch, and empty branches are disposable.