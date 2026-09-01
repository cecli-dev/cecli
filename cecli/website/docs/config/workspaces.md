---
parent: Configuration
nav_order: 41
description: Workspaces turn multiple git repositories into agent-ready sub-agents you can spin up
---
# Workspaces

Workspaces let you manage several git repositories as one unit and, crucially, turn each repository into an agent you can delegate to. A workspace is defined by a `.cecli.workspaces.yml` file that lists its projects. Each project is either:

- **local** — an existing on-disk git root referenced by an absolute `path:` (used in-place, no cloning).
- **clone** — a remote `repo:` URL that is cloned into `~/.cecli/workspaces/{workspace}/{project}/main`.

## Workspace sub-agents

When a workspace is active, each project automatically becomes an **implicit `ws:{project}` sub-agent**. These agents are modelled on the built-in `worker` sub-agent but with two key differences:

- Their `root` is **overridden** to point at the project's git root (the
  in-place `path:` directory for local projects, or the cloned checkout for `repo:` projects), so the agent operates inside that repository.
- Their agent config sets `allow_nested_delegation: true`, so a `ws:*` agent can itself serve as a base for further delegations.

Because `ws:{name}` agents are registered with the sub-agent registry, they are available through the normal mechanisms:

- The `Delegate` tool (from a primary agent)
- `/spawn-agent ws:{name}` (interactively)
- `/open <name> <path>` (ad-hoc, no config file required)

You can find the agent name reported by `/workspace` (e.g. `ws:app`).

`/open app /path/to/app` opens a `ws:app` sub-agent rooted at the given path without needing a `.cecli.workspaces.yml` file. The path must be an existing git root; the agent is registered immediately and becomes the foreground agent.

Each project may carry a `metadata` block that configures its `ws:{name}` agent the same way a sub-agent `.md` front-matter does: `model`, `hooks` and `auto_reap` map to the config fields, and any other key (e.g. `agent-config`) is merged into the agent's metadata. `root`, `name` and `description` are always derived from the project definition and cannot be overridden by `metadata`.

## Configuration

`cecli` searches for workspace config in the following order:

1. **CLI argument** — a JSON/YAML string or file path passed to `--workspaces`.
2. **Local workspace file** — `.cecli.workspaces.yml` / `.cecli.workspaces.yaml`
   in the current directory, or at a common ancestor of the project
   directories (discovered by walking up from any project path).
3. **Global workspace file** — `~/.cecli/workspaces.yml` / `.cecli/workspaces.yaml`.

### Example Configuration

```yaml
workspaces:
  name: my-workspace
  projects:
    - name: app
      path: /abs/path/to/app
      primary: true        # At most one project can be primary
      metadata:            # Optional sub-agent front-matter
        model: <weak_model>
        agent-config:
          skills_paths: ["~/my-skills", "./project-skills"]
          skills_includelist: ["python-refactoring", "react-components"]
    - name: lib
      path: /abs/path/to/lib
    - name: docs
      repo: https://github.com/user/docs.git
      branch: main
      use_current_branch: false   # Force checkout of `branch` on init
      ignore: ~/.cecli/docs.ignore  # Optional custom ignore file
```

### Project Fields

| Field               | Required | Description |
|---------------------|----------|-------------|
| `name`              | Yes      | Unique project name; also names the `ws:{name}` sub-agent |
| `path`              | One of   | Absolute path to an existing local git root |
| `repo`              | One of   | Remote clone URL (cloned under `~/.cecli/workspaces/`) |
| `primary`           | No       | At most one project may set `primary: true` |
| `branch`            | No       | Branch to check out when cloning (`repo:` projects) |
| `use_current_branch`| No       | Default `true`; set `false` to force branch switching on init |
| `ignore`            | No       | Path to a custom ignore file for this project |
| `metadata`          | No       | Optional sub-agent front-matter for the `ws:{name}` agent |

**Validation rules:**

- Each project must have a `name` and **exactly one** of `path` or `repo`.
- At most one project may be marked `primary: true`.
- Project names must be unique (they become `ws:{name}` agent names).

### Path Layout

| Layout | Prefix | Example |
|--------|--------|--------|
| **clone** (repo-based) | `{project}/main/{file}` | `app/main/src/main.py` |
| **local** (path-based) | `{project}/{file}` | `app/src/main.py` |

### Multiple Workspaces

You can define a list of workspaces and mark one `active: true` (at most one):

```yaml
workspaces:
  - name: project-a
    active: true
    projects:
      - name: app
        path: /abs/path/to/app
  - name: project-b
    projects:
      - name: api
        repo: https://github.com/user/api.git
```

## Usage

```bash
cecli --workspace-name my-workspace
# OR if using a specific config file
cecli --workspaces path/to/workspaces.yml --workspace-name my-workspace
```

Activating a workspace registers a `ws:{name}` sub-agent for each resolvable project. The primary agent's root is **unchanged** — multi-project work happens by delegating to the `ws:{name}` sub-agents, each rooted at its own project.

- For **local** workspaces, the configured `path:` directories are used
  in-place — no cloning occurs.
- For **clone** workspaces, `cecli` creates `~/.cecli/workspaces/{workspace}/` and clones each `repo:` project into `{workspace}/{project}/main`.

Metadata is stored at the workspace root:

```
.cecli/
└── .workspace-meta.json
```

Clone workspaces materialise under `~/.cecli/workspaces/`:

```
~/.cecli/workspaces/
└── my-workspace/
    ├── .cecli/
    │   └── .workspace-meta.json
    └── app/
        └── main/        # git clone of `repo:`
```

## Arguments

- `--workspaces <file>`: Provide a JSON/YAML configuration or file path for
  workspace initialization.
- `--workspace-name <name>`: Specify the workspace name to activate.
