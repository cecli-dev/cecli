---
parent: Configuration
nav_order: 45
description: Agent Memory (a.k.a. persistent memory) is a SQLite-backed fact database that persists knowledge across sessions using a dedicated memorizer sub-agent.
---

# Agent Memory

Agent Memory — also referred to as *persistent memory* — gives cecli the ability to remember important facts about your project, preferences, and decisions **across sessions**. Rather than relying solely on the current conversation context, cecli can store structured facts in a local SQLite database and recall them when needed.

This is powered by a dedicated **memorizer** sub-agent that runs automatically in the background, extracting and maintaining a concise fact database about your project.

---

## What It Does

The memorizer sub-agent monitors activity during your cecli session and extracts **concrete, reusable facts** about:

- **preferences** — user preferences, coding style choices, conventions
- **structures** — project layout, key files, directory organisation
- **goals** — what the user is trying to accomplish, current objectives
- **relationships** — how modules / systems interact with each other
- **decisions** — architectural or design choices that were made and why
- **entities** — important classes, functions, or data structures
- **changes** — summaries of changes made and their intent

Each fact is stored with one or more **tags** for categorisation and is indexed using **FTS5 (Full-Text Search)** for fast retrieval.

### How Facts Are Stored

The database schema consists of three core tables:

| Table | Purpose |
|-------|---------|
| `Facts` | Stores the fact text with a timestamp |
| `Tags` | Stores unique tag names |
| `FactTags` | Many-to-many association between facts and tags |

A virtual FTS5 table (`facts_fts`) is kept in sync automatically via SQL triggers, enabling efficient full-text search queries with prefix matching.

---

## How to Enable

Agent Memory is **disabled by default** as it adds to overall system token usage. You can control it with the `--auto-memory` / `--no-auto-memory` flag:

```bash
# Enable
cecli --auto-memory

# Disable (default)
cecli --no-auto-memory
```

You can also set this in your [configuration file](options.html):

```yaml
# .cecli.yml or other config file
# To disable automatic fact memorization:
auto-memory: false
```

> **Note:** The memorizer only runs for the **primary agent** — it is automatically skipped for sub-agents to avoid redundant processing.

---

## When It Triggers

The memorizer is invoked **automatically** (fire-and-forget) at key points during a session:

| Trigger | Description |
|---------|-------------|
| **After context compaction** | When the conversation history is summarised to manage token limits, the memorizer extracts facts from the compaction summary |
| **After an agent/sub-agent yields** | When a sub-agent completes its task (via the `Yield` tool), the memorizer processes the yield summary |

It is **rate-limited to once every 120 seconds** (2 minutes) to avoid excessive LLM calls. This means rapid-fire interactions won't trigger the memorizer on every single message.

You can also spawn the agent manually with `/spawn-agent memorizer` and tell it what to do to keep the project database clean.

### What Context Is Sent

When the memorizer fires, it gathers:

1. **The latest user message** — what the user last asked or instructed
2. **Saved observations** — observations collected during the session (via `ObservationService`)
3. **Additional context** — compaction summaries or yield summaries that describe what happened

The memorizer sub-agent then:
1. Searches the database for existing related facts (to avoid duplicates)
2. Uses the `ReplaceFacts` tool to insert new facts and delete stale ones
3. Keeps the database clean and up-to-date

---

## Where the Database Is Stored

The fact database is stored in the project's `.cecli` directory:

```
{project_root}/.cecli/memory.v{version}/cache.db
```

For example, with the current schema version (v1):

```
/home/user/my-project/.cecli/memory.v1/cache.db
```

The version number in the path (e.g. `v1`) corresponds to the internal schema version (`SCHEMA_VERSION` in the code). If the schema changes in a future release, a new version directory is created, keeping old databases intact.

### Database Properties

| Property | Value |
|----------|-------|
| **Engine** | SQLite 3 |
| **Journal mode** | WAL (Write-Ahead Logging) — for multi-process safety |
| **Synchronisation** | `NORMAL` — balances durability with performance |
| **Transaction mode** | `BEGIN IMMEDIATE` — prevents deadlocks between concurrent processes |
| **Full-text search** | FTS5 with `porter` (stemming) and `unicode61` tokenizer |

The database is **thread-safe** using thread-local connections, so multiple threads within the same session can access it concurrently.

---

## Tools for the Memorizer

The memorizer sub-agent has access to two exclusive tools that no other agent can use:

### SearchFacts

Full-text search across the fact database:

- **Parameters:** `words` (array of search terms, required), `tags` (optional array of tag names for filtering)
- **Returns:** Matching facts with their IDs, text, date, and tags
- **Fallback:** If a tag-filtered search returns nothing, the tool retries without the tag filter

### ReplaceFacts

Atomically insert new facts and/or delete stale ones:

- **Parameters:** `inserts` (array of `{fact, tags?}` objects, required), `deletes` (optional array of fact IDs to remove)
- **Returns:** IDs of inserted facts and count of deleted facts

These tools are only registered during memorizer sub-agent sessions — they are unavailable to the primary agent or any other sub-agent.

---

## Managing Facts

While facts are managed automatically by the memorizer, you can also interact with them indirectly:

- **Clearing the session** (`/clear`) resets the observations that feed into the memorizer
- **Resetting the session** (`/reset`) clears observations and conversation history, starting fresh
- The fact database itself **persists across sessions** — facts survive `/clear` and `/reset`

If you need to manually inspect or clean the database, you can use any SQLite tool:

```bash
# Inspect all stored facts
sqlite3 .cecli/memory.v1/cache.db "SELECT * FROM Facts;"

# Remove the memory database entirely to start fresh
rm -rf .cecli/memory.v1/
```

Cecli will automatically recreate the database with an empty schema on the next invocation.

---

## Related

- [Sub-Agents](subagents.html) — Learn more about the sub-agent system that powers the memorizer
- [Options Reference](options.html) — All available CLI flags including `--auto-memory`
