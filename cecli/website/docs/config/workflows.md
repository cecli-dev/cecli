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
hooks:                         # optional, same schema as Hooks
  start: [{ name: audit, command: "echo start >> ~/.cecli/workflows/audit.log" }]
skills: [gitlab-ci]            # optional -> preloaded as skills_init
servers: [gitlab]              # optional -> active MCP servers (lowercased)
on_failure: stop               # stop | continue
tasks:
  - name: attach-gitlab
    prompt: /load-mcp gitlab
  - name: triage
    prompt: >
      Monitor the gitlab test pipeline and recent builds; summarize any errors
      into .cecli/reports/pipeline.md
    save_to: pipeline_summary
```

Keys are `snake_case` or `hyphen-case`; both accepted. `${ENV_VAR}` / `$VAR` inside any string is interpolated from the environment (after `.env` files load).

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
| `hooks` | {} | Per-workflow hooks (start/end/pre_tool/…); run on the worker |
| `skills` | [] | Skills loaded into the worker's context at start |
| `servers` | [] | MCP servers made available to the worker |
| `on_failure` | `stop` | What to do after a task errors: `stop` drops the remaining tasks, `continue` runs them anyway |
| `catch_up` | scheduler default | Per-workflow override of the [scheduler's](scheduler.html) `catch_up` (replay of slots missed while cecli was closed) |

Task fields:

| field | default | meaning |
|-------|---------|---------|
| `prompt` | — | Required. A list entry may also be a bare string, which is taken as the prompt. Slash commands (`/load-mcp`, `/model`, …) work exactly as if typed |
| `name` | `task-N` | Label used in run logs and status output |
| `save_to` | none | On success, writes the run's final summary to a persistent per-run file under `~/.cecli/workflows/outputs/{workflow}/{run}/` (named after the key; the path is recorded in the run log) |

Run-time placeholders are expanded in task prompts in addition to load-time env interpolation: `{date}` (today as `YYYY-MM-DD`), `{workflow}` (the workflow name) and `{run_id}` (the scheduler run id, empty for manual runs). Other braces are left verbatim. A complete annotated sample is in the repository at `examples/workflows/check-pipeline.yml` — copy it to `~/.cecli/workflows/` or pass it via `--workflows` to try it.

## How a run works

1. The scheduler (or `/workflows run`) creates the `wf:{name}` worker sub-agent, configured with the workflow's model, hooks, skills and servers.
2. The task prompts are queued to that worker **in order**, using the same prompt queue as `/queue`. Each prompt is processed to completion before the next.
3. If a task errors, the remaining queued prompts are dropped according to `on_failure` (or the failing task's `continue_on_error`), then the worker is reaped. (Caveat: errors that abort the queue-drain chain behave like `stop` even under `continue_on_error`, since the remaining prompts never get a chance to drain; errors handled inside a prompt continue normally.)
4. The run is **detached**: a workflow worker never injects summaries or status into the parent's conversation (background operations stay out of its context). A finished `/workflows run` is announced once in the terminal only; the durable record lives in the run log and outputs.

Because a run is a sub-agent, it doesn't block the main conversation — watch it with `/agent-tree` or the TUI sub-agent pane. Every run also appends a JSON-lines audit log to `~/.cecli/workflows/runs/<YYYY-MM-DD>/<name>.<id>.jsonl`: a `start` line (with the definition hash), one `task` line per task, and a `finish` line. Before the worker is reaped, its full session is archived to `~/.cecli/workflows/outputs/<workflow>/<run>/session.json` using the standard session format (encrypted when session encryption is enabled) — so every run, including replayed or tool-less replies, is completely reviewable on disk without ever touching the parent's context.

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
  - prompt: /load-mcp github
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
