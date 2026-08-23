# PR: Local `path:` projects for cecli workspaces

## Summary

Extends cecli’s existing **clone** workspace mode (`repo:` URLs under `~/.cecli/workspaces/`, paths like `project/main/file.py`) with **local** layout: multiple git roots on disk referenced by absolute `path:` in a repo-local config file.

## Motivation

IDE clients (e.g. desktop agents with a primary git root) open a **primary git repo** but need agent context across **sibling repos** without cloning into `~/.cecli/workspaces/`. Submodule-only setups are a different layout; this PR adds an explicit, reviewable config surface.

## Config

Place at the workspace root (walked up from any listed project path):

```yaml
# .cecli.workspaces.yml
name: my-workspace
projects:
  - name: app
    path: /abs/path/to/app
    primary: true
  - name: lib
    path: /abs/path/to/lib
    readonly: true
```

Rules (enforced in `validate_config`):

- Each project: `name` + **exactly one** of `path` or `repo`
- At most one `primary: true`

## Path layout

| Layout | Prefix | Example |
|--------|--------|---------|
| **local** (this PR) | `{project}/{file}` | `app/src/main.py` |
| **clone** (existing) | `{project}/main/{file}` | `app/main/src/main.py` |

## Behavior changes

| Area | Change |
|------|--------|
| `GitRepo.__init__` | Multiple git roots allowed when `.cecli.workspaces.yml` is found on a common ancestor |
| `get_workspace_files` | Local layout unions `git ls-files` from each `path:` root |
| `commit` | Local layout commits per underlying repo (`_commit_local_workspace`) |
| `abs_root_path` | Resolves prefixed paths to the correct project root |

Clone workspaces and `.cecli-workspace.json` metadata are unchanged.

## Tests

- `tests/helpers/monorepo/test_config.py` — validation (`path` / `repo` XOR)
- `tests/helpers/monorepo/test_local_workspace.py` — helpers + `GitRepo` integration
- Existing `test_repomap_workspace.py`, `test_workspace.py`, etc. — still pass (clone layout)

Run:

```bash
pytest tests/helpers/monorepo -q
```

## Non-goals (follow-up PRs)

- Auto-registering git submodules into the workspace registry
- Combining submodule `RepoSet` with local YAML in one facade
- New global config file formats (reuse `.cecli.workspaces.yml` only)
