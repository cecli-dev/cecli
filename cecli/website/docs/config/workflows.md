---
parent: Configuration
nav_order: 47
description: Workflows are named, optionally scheduled sequences of prompts that run unattended on a dedicated worker sub-agent.
---
# Workflows

A **workflow** is a named, optionally scheduled sequence of prompts that run unattended on a dedicated `wf:{name}` worker sub-agent — the same mechanism as [`ws:` workspace](workspaces.html) agents. Use workflows for recurring or batch jobs: "check the CI pipeline every 30 minutes", "triage open issues each morning", "run this 3-step refactor once, now". Workflows with a `schedule:` key are executed by the [scheduler](scheduler.html).

## Where to define them

Preferred: one YAML file per workflow in `~/.cecli/workflows/` (with `~/.agents/workflows/` also discovered):

```
~/.cecli/workflows/
    check-pipeline.yml
    morning-triage.yml
```

Also supported: a repo-local `.cecli/workflows/` or `.agents/workflows/` directory (one YAML file per workflow), inline under a `workflows:` key in `.cecli.conf.yml`, or a repo-local `.cecli.workflows.yml`. Each source may hold a single workflow mapping, a `workflows: [...]` list, or a plain list of mappings. Resolution precedence (highest first):

1. **CLI argument** — an inline JSON/YAML string or a file path passed to `--workflows`.
2. **Local file** — `.cecli.workflows.yml` / `.cecli.workflows.yaml` in the git root (or working directory).
3. **Local directory** — `.cecli/workflows/*.yml` / `*.yaml` in the git root (or working directory), loaded in sorted order.
4. **Standard local directory** — `.agents/workflows/*.yml` / `*.yaml` in the git root (or working directory), loaded in sorted order.
5. **Merged config** — the `workflows:` key in `.cecli.conf.yml`.
6. **Global files** — `~/.cecli/workflows/*.yml` / `*.yaml`, loaded in sorted order.
7. **Standard global directory** — `~/.agents/workflows/*.yml` / `*.yaml`, loaded in sorted order.

On a duplicate `name`, the higher-precedence definition wins and the loser is skipped with a warning. A source that fails to parse is skipped with a warning as well — a malformed workflows file never crashes startup.

## Reference format

```yaml
name: check-pipeline           # required, unique, no ':'
description: Poll CI, summarize failures
schedule: "*/30 * * * *"        # optional cron / @preset / '@every 30m'; omit for manual-only
timezone: UTC                  # optional IANA name (default: local, interpreted as UTC)
enabled: true                  # optional (default: true)
lease_timeout: 30              # optional minutes (default: 30)
model: <model-name>            # optional model override for the worker
root: ~/repos/my-project       # optional working directory
repo: /repos/app               # optional worktree source (local path or remote URL)
worktree: true                 # optional isolated git worktree; or {branch: main}
hooks:                         # optional, same schema as Hooks
  start: [{ name: audit, command: "echo start >> ~/.cecli/workflows/audit.log" }]
skills: [gitlab-ci]            # optional -> preloaded as skills_init
servers: [gitlab]              # optional -> active MCP servers (lowercased)
on_failure: stop               # stop | continue
persist: true                  # keep the worker in the TUI and reuse it next run
metadata:                      # optional sub-agent overrides (see below)
  agent-config:
    allow_nested_delegation: false
tasks:
  - name: attach-gitlab
    prompt: /mcp load gitlab
  - name: triage
    prompt: >
      Monitor the gitlab test pipeline and recent builds; summarize any errors
      into .cecli/reports/pipeline.md
    save_to: pipeline_summary
```

Keys are `snake_case` or `hyphen-case`; both accepted. `${ENV_VAR}` / `$VAR` inside any string is interpolated from the environment (after `.env` files load).

Validation notes: `repo` must be a string. `worktree` must be a boolean or a mapping; a mapping currently supports only `branch`, which must be a string (unknown keys warn and are ignored). When `worktree` is enabled, the source repository is inferred from `repo`, then `root`, then the git top-level containing the workflow file; if none can be found a warning is logged and the dispatching agent's root is used at run time.

Field meanings:

| field | default | meaning |
|-------|---------|---------|
| `name` | — | Identity; the worker agent is `wf:{name}`. Must match `[A-Za-z0-9_.-]+` (no `:`) |
| `tasks` | — | Ordered prompt list; at least one task is required |
| `description` | `""` | Shown in `/workflows list` |
| `schedule` | none | 5-field cron expression, a preset (`@hourly`, `@daily`, `@weekly`, `@monthly`, `@yearly`) or an interval (`@every 30m`). Without one the workflow runs only via `/workflows run` |
| `timezone` | `local` | IANA zone the cron expression is interpreted in; `local` — like any unknown zone, which falls back with a warning — is treated as UTC |
| `enabled` | true | Disabled workflows never tick and register no worker |
| `lease_timeout` | 30 | Minutes a scheduler instance holds the job lock before peers may steal an abandoned run |
| `model` | inherited | Model (or sentinel) for the worker sub-agent |
| `root` | session root | Working directory the worker operates in |
| `repo` | — | Source repository for the optional worktree: a local path or remote URL. When the worktree is enabled, the run's root becomes the generated worktree checkout |
| `worktree` | disabled | Set `true` to run the worker in an isolated git worktree, or `{branch: <ref>}` to choose the base ref to start from. See [Worktrees](worktrees.html) |
| `hooks` | {} | Per-workflow hooks (start/end/pre_tool/…); run on the worker |
| `skills` | [] | Skills loaded into the worker's context at start |
| `servers` | [] | MCP servers made available to the worker |
| `metadata` | {} | Sub-agent overrides, matching workspace project metadata: `model`, `hooks` and `auto_reap` map to the sub-agent config fields, an `agent-config` mapping is merged on top of the declarative `skills`/`servers`, and any other key is merged into the sub-agent metadata. `name`, `description` and `root` always come from the workflow definition |
| `persist` | false | Keep the worker sub-agent (and its TUI container) after the run finishes. The next run reuses the same worker after clearing its conversation, file context and prompt queue. Persistent workers are never auto-reaped |
| `on_failure` | `stop` | What to do after a task errors: `stop` drops the remaining tasks, `continue` runs them anyway |
| `catch_up` | scheduler default | Per-workflow override of the [scheduler's](scheduler.html) `catch_up` (replay of slots missed while cecli was closed) |

Task fields:

| field | default | meaning |
|-------|---------|---------|
| `prompt` | — | Required. A list entry may also be a bare string, which is taken as the prompt. Slash commands (`/mcp load`, `/model`, …) work exactly as if typed |
| `name` | `task-N` | Label used in run logs and status output |
| `save_to` | none | On success, writes the run's final summary to a persistent per-run file under `~/.cecli/workflows/outputs/{workflow}/{run}/` (named after the key; the path is recorded in the run log) |
| `post_run` | none | One async `post_run(coder, context)` hook: a callable, a `.py` file, inline Python (a whole `async def post_run(...)` or just its body), or a `module:function` reference. It can continue, stop, or jump to another step |

Run-time placeholders are expanded in task prompts in addition to load-time env interpolation: `{date}` (today as `YYYY-MM-DD`), `{workflow}` (the workflow name) and `{run_id}` (the scheduler run id, empty for manual runs). Other braces are left verbatim. A complete annotated sample is in the repository at `examples/workflows/check-pipeline.yml` — copy it to `~/.cecli/workflows/` or pass it via `--workflows` to try it.

## How a run works

1. The scheduler (or `/workflows run`) creates the `wf:{name}` worker sub-agent, configured with the workflow's model, hooks, skills and servers.
2. The task prompts are staged in the worker's prompt queue **in order**, using the same queue as `/queue`. The runner processes one prompt at a time and runs that step's `post_run` hook before choosing the next queued action.
3. If a task errors, its `post_run` hook still runs with `context.status == "error"`. Without a jump, the remaining prompts are dropped or kept according to `on_failure` (or the failing task's `continue_on_error`). A hook can therefore recover by jumping to a fix step, or stop the run explicitly.
4. The run is **detached**: a workflow worker never injects summaries or status into the parent's conversation (background operations stay out of its context). A finished `/workflows run` is announced once in the terminal only; the durable record lives in the run log and outputs.
5. With `persist: true`, the worker is not reaped when the run finishes: it stays in the TUI and the next run of the same workflow reuses it. Before staging the new tasks, the runner waits for any in-flight run, clears the worker's conversation (re-adding its system prompt) and file context, resets the prompt queue and per-run status, and then runs the new task list on the same agent.

Because a run is a sub-agent, it doesn't block the main conversation — watch it with `/agent-tree` or the TUI sub-agent pane. Every run also appends a JSON-lines audit log to `~/.cecli/workflows/runs/<YYYY-MM-DD>/<name>.<id>.jsonl`: a `start` line (with the definition hash), one `task` line per task, and a `finish` line. Before the worker is reaped, its full session is archived to `~/.cecli/workflows/outputs/<workflow>/<run>/session.json` using the standard session format (encrypted when session encryption is enabled) — so every run, including replayed or tool-less replies, is completely reviewable on disk without ever touching the parent's context.

## Dynamic task flow

Every task is a named step. Set a task-level `post_run` to a Python callable or a string reference (`module:function` or `path.py:function`). The hook runs after the step and chooses what happens next:

- `True` continues with the queue.
- `False` stops the run.
- `context.jump(step, prompt=None)` (or a returned `(step, prompt)` tuple) makes *step* the next action. The optional `prompt` replaces that step's prompt completely; omit it to use the original definition.

```yaml
tasks:
  - name: run-tests
    prompt: Run the test suite and report failures.
    post_run: ".cecli/workflows/hooks.py:route_failure"
  - name: fix-failures
    prompt: Fix the reported failures.
  - name: publish
    prompt: Publish the release.
```

Example `.cecli/workflows/hooks.py`:

```python
def route_failure(coder, context):
    if context.status == "error":
        return context.jump("fix-failures", "Fix only the first failure.")

    return True
```

A failed `run-tests` queues `fix-failures` next; a successful `fix-failures` then continues to `publish`. `context.steps` is the original `{name: prompt}` map and is never mutated or duplicated: forward jumps drop the queued steps before the target, and backward jumps queue the target again (retry loops, branches). A hook that returns a jump or `False` redirects control flow; returning `True` keeps the queue moving.

The hook context exposes `coder`, `workflow`, `step_name`, `prompt`, `status` (`ok`/`error`), `error`, `steps` (the original `{name: prompt}` map) and `available_steps` (a copy). A hook may be async and may take `(coder, context)` or just `(context)`.

More routing patterns:

```python
# Stop the whole run when a step fails.
def stop_on_error(coder, context):
    if context.status == "error":
        return context.stop()

    return True


# Retry the same step with a sharper prompt (at most twice).
attempts = {}

def retry_tests(coder, context):
    attempts[context.step_name] = attempts.get(context.step_name, 0) + 1
    if context.status == "error" and attempts[context.step_name] <= 2:
        return context.jump(
            context.step_name,
            f"{context.prompt}\n\nFix the failures from the last attempt.",
        )

    return True


# Branch on the worker's result: tuple form instead of context.jump().
def review_or_publish(coder, context):
    if "risk" in (context.error or "").lower():
        return ("manual-review", "Explain the risk and stop before publishing.")

    return True
```

A forward jump drops every queued step before the target, so `run-tests -> fix-failures` skips unrelated steps in between. A backward jump queues the target (and everything after it) again, which is how retries and loops are expressed. Because the step map is the original definition, the override prompt lasts for that one jump only; the next visit starts from the original prompt again.

### Python file hooks

Point `post_run` at a `.py` file and define `async def post_run(coder, context)` inside it. Relative paths resolve against the worker root, then against the workflow file's directory:

```yaml
tasks:
  - name: run-tests
    prompt: Run the test suite and report failures.
    post_run: ".cecli/workflows/hooks.py"
```

```python
# .cecli/workflows/hooks.py
async def post_run(coder, context):
    if context.status == "error":
        return context.jump("fix-failures", "Fix only the first failure.")

    return True
```

### Inline Python

For one-off logic, put Python directly in the workflow. A complete `async def post_run(coder, context)` works as-is:

```yaml
tasks:
  - name: run-tests
    prompt: Run the test suite and report failures.
    post_run: |
      async def post_run(coder, context):
          if context.status == "error":
              return context.jump("fix-failures")

          return True
```

Or write only the function body; it is wrapped in an `async def post_run(coder, context)`. The hook must be async in every form:

```yaml
tasks:
  - name: run-tests
    prompt: Run the test suite and report failures.
    post_run: |
      if context.status == "error":
          return context.jump("fix-failures", "Fix only the first failure.")

      return True
```

Inline hooks are compiled into a cached temporary module, so module-level state (counters, retry attempts) persists for the life of the process — including between runs on a `persist: true` worker. Use `context`/`coder` attributes if you want state scoped to one run.

## Isolated worktrees

Set `worktree: true` to give the run its own git worktree instead of operating directly in `root`. The worker starts on a generated branch `cecli/<agent>-<uuid>` (for example `cecli/wf-nightly-tidy-<uuid>`) based on `branch` (the starting base ref) or the source repository's default branch. `repo` selects the source repository; if it is omitted, `root` (or the workflow file's git root) is used. The agent's actual root is the generated worktree checkout.

When the run finishes, a dirty worktree is committed with the subject `Unfinished Dirty Worktree from agent <uuid>` before the worktree is released. Branches with unmerged commits are kept for review; empty or already-merged branches are deleted. The worktree checkout under `~/.cecli/worktrees/` is removed after the commit/release step. See [Worktrees](worktrees.html) for the full lifecycle and on-disk layout.

## Commands

```
/workflows                     # List loaded workflows (same as 'list')
/workflows list                # Show loaded workflows
/workflows run <name>          # Trigger now, in the background
/workflows show <name>         # Dump the resolved definition (YAML)
/workflows status [name]       # Scheduler job state and active leases (config view if the scheduler isn't running)
/workflows last <name>         # Summary of the most recent run
/workflows enable <name>       # Enable for this session (synced to the scheduler DB)
/workflows disable <name>      # Disable for this session (synced to the scheduler DB)
/workflows reload              # Re-resolve all sources: --workflows value + files
```

## Examples

**Nightly repo tidy (manual + scheduled):**

```yaml
name: nightly-tidy
schedule: "0 3 * * *"
timezone: America/New_York
repo: /repos/app
worktree:
  branch: main
skills: [code-review]
tasks:
  - prompt: "Run the linter over the repo and fix obvious issues."
  - prompt: "Summarize what changed into CHANGELOG-Unreleased.md."
```

**Dependabot-style review, gated on an MCP server:**

```yaml
name: pr-review
schedule: "@every 20m"
servers: [github]
on_failure: continue
tasks:
  - prompt: /mcp load github
    continue_on_error: true
  - prompt: "List open PRs I haven't reviewed; for each, summarize the diff and flag risky changes."
    save_to: pr_review_notes
```

**One-shot pipeline (no schedule), run via `/workflows run build-doctor`:**

```yaml
name: build-doctor
tasks:
  - prompt: "Run the full test suite and report failures."
  - prompt: "For each failure, propose a minimal fix as a diff."
```

## Compatibility

- Workflows are additive: nothing changes until you create a `workflows:` key or a file in `~/.cecli/workflows/` or `~/.agents/workflows/`.
- `wf:` agents show up in `/agent-tree` alongside `ws:` agents; a workflow can itself delegate sub-agents (nested delegation enabled).
- Existing `/queue` semantics are unchanged; workflows reuse the same queue.

## Arguments

- `--workflows <json|yaml>`: Provide an inline workflows configuration or a path to a workflows file, overriding all file-based sources.
- `--scheduler <json>`: Override [scheduler](scheduler.html) configuration for this session (same object as the `scheduler:` config key).
