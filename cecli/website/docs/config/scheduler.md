---
parent: Configuration
nav_order: 48
description: The scheduler turns workflow schedule entries into runs, coordinating any number of cecli instances through a shared SQLite database.
---
# Scheduler

The [scheduler](workflows.html) is the component that turns a [workflow](workflows.html) `schedule:` key into actual runs. It lives inside a running cecli session — there is no separate process to install or start.

## Running it

The scheduler starts automatically in any interactive cecli session that has at least one enabled, scheduled workflow. It is configured as an object in `.cecli.conf.yml`:

```yaml
scheduler:
  enabled: true               # true | false; omit the key for 'auto'
  tick_seconds: 60            # resolution of the due-check loop
  catch_up: true              # replay slots missed while cecli was closed (default)
  max_catchup: 1              # how many missed slots to replay before skipping ahead
```

`--scheduler <json>` overrides it for a single session with the same object, e.g. `cecli --scheduler '{"enabled": false}'`. Disabling is always expressed through the object's `enabled` key — there is no separate off switch — and workflows remain usable manually via `/workflows run`.

Resolution order for whether it runs: `enabled` (from the CLI `--scheduler <json>` deep-merged over the `scheduler:` config key) decides on/off; when `enabled` is omitted the mode is auto — on when any enabled workflow has a `schedule:`, off otherwise. Nothing touches the coordination database when no scheduled workflow exists, and one-shot (`--message`) runs return before the scheduler can tick.

The `catch_up` pair controls what happens after downtime (e.g. a sleeping laptop):

- `catch_up: true` (default): overdue slots are replayed one at a time, so a job that was due while cecli was closed still runs. If the backlog behind "now" is deeper than `max_catchup`, the scheduler skips ahead to the next future slot rather than queueing hundreds of stale runs.
- `catch_up: false`: if machine time jumped past several slots, only the most-recent slot fires — the schedule advances straight to the next future slot.

An individual workflow may override the global setting with its own top-level `catch_up: true|false` key (see [Workflows](workflows.html)); unset means "follow the scheduler".

## Multi-instance coordination

You can safely run **many** cecli instances at once (same machine, or one shared `~/.cecli` on a network filesystem — see caveats). They cooperate through a global SQLite database:

```
~/.cecli/scheduler/scheduler.v1/scheduler.db
```

The database (`jobs`, `runs` and `task_log` tables) records, per workflow, its `next_run` slot and a time-limited **lease**. Claiming a due slot is an atomic insert guarded by a `UNIQUE(name, slot, attempts)` constraint, so:

- only the instance that wins the claim dispatches the workflow,
- everyone else sees the slot as taken and moves on,
- while a run is in flight its lease is renewed; if the winner crashes anyway, the lease expires after the workflow's `lease_timeout` minutes and any instance may steal the slot and retry (one extra attempt row per steal — a deterministically crashing job therefore retries at most once per lease timeout per slot). Only crashed or expired attempts are steal-retryable — a slot that already reached a terminal status (`ok`, `error` or `skipped`) is never re-run.

This guarantees "at most one run per scheduled slot" across all instances without any central coordinator process. Advancing a job is monotonic: a slow instance finishing an old slot can never drag `next_run` backwards and re-arm slots that already ran. A crashed-but-leased run is only ever picked up after the timeout, so set `lease_timeout` longer than your longest expected run.

## Notes and caveats

- The DB is the arbiter, **not** the definition store. YAML remains the source of truth: deleting a workflow file disables it on the next tick (its run history is kept), even if its DB row lingers.
- All timestamps are stored in UTC; the `timezone:` key on a workflow controls how its cron expression is interpreted.
- On a shared network filesystem, SQLite WAL locking can be unreliable; prefer a local `~/.cecli` or per-host schedulers.
- The lease protects against *duplicate scheduling*, not against a workflow that itself takes a long external action; make workflow tasks idempotent where the side effects matter.

## Inspecting it

Scheduler state is visible from any session with the [workflow commands](workflows.html#commands) — `/workflows status` shows each job's last/next run, status and active lease holder, `/workflows last <name>` the summary of the most recent run. Per-run JSON-lines audit logs are written to `~/.cecli/workflows/runs/<YYYY-MM-DD>/`.

## Arguments

- `--scheduler <json>`: Override scheduler configuration for this session (same object as the `scheduler:` config key).
- `--workflows <json|yaml>`: Workflow definitions the scheduler will consider (see [Workflows](workflows.html)).
- To disable the scheduler, pass `--scheduler '{"enabled": false}'` (or set `enabled: false` under the `scheduler:` config key).
