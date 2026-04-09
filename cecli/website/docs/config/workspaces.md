---
parent: Configuration
nav_order: 41
description: Workspaces allow you to work across multiple related repositories simultaneously
---
# Workspaces

Workspaces allow you to manage multiple independent git repositories within isolated environments. The system initializes workspaces with specified branches as git worktrees, enabling parallel development across multiple projects.

## Configuration

You can configure workspaces in multiple locations. `cecli` searches for configurations in the following order:

1. **CLI Argument**: Via a JSON/YAML configuration or file path passed to the `--workspaces` argument.
2. **Local Workspaces File**: `.cecli.workspaces.yml` or `.cecli.workspaces.yaml` in the current directory.
3. **Global Workspaces File**: `~/.cecli/workspaces.yml` or `~/.cecli/workspaces.yaml`.

### Example Configuration

```yaml
workspaces:
  name: "my-workspace"
  projects:
    - name: "frontend"
      repo: "https://github.com/user/frontend.git"
      branch: "main"
      worktrees:
        - name: "feature-auth"
          branch: "feature/auth"
    - name: "backend"
      repo: "https://github.com/user/backend.git"
      branch: "develop"
      use_current_branch: true  # Default: true. Set to false to force branch switching on init.
```

### Multiple Workspaces

You can define a list of workspaces. Use the `active: true` flag to specify which one should be used by default when running `cecli` without the `--workspace-name` argument. **Note: At most one workspace can be marked as active.**
```yaml
workspaces:
  - name: "project-a"
    active: true
    projects:
      - name: "app"
        repo: "https://github.com/user/app.git"
  - name: "project-b"
    projects:
      - name: "api"
        repo: "https://github.com/user/api.git"
```


## Usage

To use a workspace:

```bash
cecli --workspace-name my-workspace
# OR if using a specific config file
cecli --workspaces path/to/workspaces.yml --workspace-name my-workspace

If the workspace does not exist, `cecli` will create the directory structure at `~/.cecli/workspaces/my-workspace/` and clone the configured repositories.

### Workspace Structure

```
~/.cecli/workspaces/
└── workspace-name/
    ├── .cecli-workspace.json
    └── project-name/
        ├── main/        # Main repository clone
        └── worktrees/   # Additional worktrees
```

## Arguments

- `--workspaces <file>`: Provide a JSON/YAML configuration or file path for workspace initialization.
- `--workspace-name <name>`: Specify the workspace name to activate from the configuration.
