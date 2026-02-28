# Handoff: cecli Task Management — Invisible Persistence

## Session Context
- Date: 2026-02-27
- Branch: `feat/cecli-tasks-brainfile`
- Previous approach: Two-layer architecture with explicit opt-in board (see git history)

## Design Philosophy

**The agent and user should never know brainfile exists.** The existing `UpdateTodoList` tool and todo UX remain identical on the surface. The only difference: todos are now backed by structured task files instead of a flat text file, giving users persistence, history, and session memory for free.

No new LLM tools. No board creation ceremony. No mode-switch. No "WTF is a kanban board" moment.

## Architecture

### What the agent sees (unchanged)
- `UpdateTodoList` — the only tool. Same schema, same behavior, same prompt.
- `get_todo_list()` — returns the same `<context name="todo_list">` block it always did.
- `agent.yml` — no mention of boards, tasks, brainfile, or structured data.

### What happens underneath (new)
- `UpdateTodoList` writes to `.cecli/tasks/board/task-{N}.md` instead of `.cecli/todo.txt`.
- Each call creates or updates a **single session task** — the "current task" for this session.
- Todo items become subtasks in that task file's YAML frontmatter.
- `.cecli/tasks/brainfile.md` (board config) is auto-created on first write. No explicit init.
- `todo.txt` is no longer the primary storage.

### What the user gets (for free, without doing anything)
- **Persistence across sessions**: Incomplete todos survive session restarts. The task file persists.
- **History**: Completed tasks move to `.cecli/tasks/logs/`. Git tracks everything.
- **Searchable past work**: `/task list logs` shows what was done across previous sessions.
- **Optional power-user access**: `/task list`, `/task show`, `/task open` for humans who want control.

## The Session-Task Mapping

```
Session starts →
  find or create a "current session task" in .cecli/tasks/board/
  (reuse the last incomplete task, or create a new one)

UpdateTodoList called →
  always write to the current session task's subtasks

Session ends (or user starts new work) →
  incomplete task persists in board/
  completed task can be moved to logs/ via /task complete
```

### How the "current task" is determined
1. On session start, check `.cecli/tasks/board/` for the most recently updated task.
2. If it has incomplete subtasks → resume it (set as `active_task_id`).
3. If all subtasks are complete or no tasks exist → create a new task on next `UpdateTodoList` call.
4. The user can override with `/task open <id>` to switch to a different task.
5. The user can force a fresh task with `/task new [title]`.

### Key difference from previous approach
- **Before**: Two separate systems (todo.txt vs board) with a mode-switch and `/task promote` bridge.
- **Now**: One system. `UpdateTodoList` always writes structured files. The agent doesn't know. The user doesn't have to care. Power features are there when you want them.

## Changes from Previous Implementation

### Kill
- **Two-layer routing** in `UpdateTodoList` (the `active_task_id` branch to todo.txt vs board). There is now only one write path — always through the store.
- **`_execute_todo_txt`** method — the flat-file write path. All writes go through `CecliTaskStore`.
- **`/task promote`** — unnecessary. Todos are already structured from the first `UpdateTodoList` call.
- **Board tool gating** in `ToolRegistry` — no conditional registration of Task* LLM tools.
- **`BOARD_TOOL_MODULES` split** in `tools/__init__.py` — no separate module list needed.
- **`todo.txt` as primary storage** — replaced by task files.
- **Task* LLM tools** (`TaskCreate`, `TaskList`, `TaskShow`, `TaskUpdate`, `TaskComplete`, `TaskDrop`) — the agent should never call these. They were board-mode tools for a mode that no longer exists. All agent interaction goes through `UpdateTodoList`. Human interaction goes through `/task` slash commands.

### Keep
- **`CecliTaskStore`** in `cecli/brainfile/store.py` — the adapter is solid. Add `get_or_create_session_task()` method.
- **`/task` command** — all subcommands remain for human power-users: `list`, `show`, `open`, `complete`, `drop`, `delete`, `update`.
- **`UpdateTodoList` tool schema** — identical. `tasks` array, `append`, `done`, `current` flags.
- **`get_todo_list()` context block** — same `<context name="todo_list">` format, now always reads from the current session task's subtasks.
- **`render_task_todo_block()`** — already does what we need.
- **`brainfile` Python library dependency** — unchanged.
- **Completion flow** — `completeTaskFile` moves to `logs/`.
- **`format_output()`** in UpdateTodoList — renders the same ✓/○/→ display.

### Add
- **Auto-init**: `CecliTaskStore.ensure_initialized()` called lazily on first `UpdateTodoList` write, not on explicit `/task add`.
- **`get_or_create_session_task()`**: New method on `CecliTaskStore`. Finds latest incomplete task or creates a new one.
- **Auto-titling**: New tasks get a title from the first todo item, or a timestamp fallback.
- **`/task new [title]`**: New subcommand — explicitly start a fresh task for users who want to segment work.
- **Session persistence**: Save/restore `active_task_id` in session data.

## File Changes Required

### `cecli/tools/update_todo_list.py`
- Remove `_execute_todo_txt` method entirely.
- Remove the `active_task_id` routing branch in `execute()`.
- `execute()` becomes:
  1. Get store: `CecliTaskStore(coder.root)`
  2. Get or create current task: `store.get_or_create_session_task(coder)`
  3. Write subtasks: `store.update_task_subtasks(task_id, tasks, append)`
  4. Track change, return result.
- Keep `format_output()` unchanged.

### `cecli/coders/agent_coder.py`
- `get_todo_list()`: Remove the `todo.txt` fallback path. Always render from the store via `render_task_todo_block(active_task_id)`. If no active task or no subtasks, return the existing "Todo list does not exist" prompt.
- On init or session resume: call `store.get_or_create_session_task(coder)` to resolve and set `active_task_id`.
- Remove any board-tool registry rebuilding logic (no conditional tool registration).

### `cecli/brainfile/store.py`
- Add `get_or_create_session_task(coder) -> dict`:
  - Calls `ensure_initialized()`.
  - Scans `board/` for most recently updated task file.
  - If found with incomplete subtasks → sets `active_task_id` on coder, returns it.
  - If all complete or none exist → creates new task (column `in-progress`, auto-title), sets `active_task_id`, returns it.
- Add `auto_title(items: list[dict] | None) -> str`:
  - First non-done item text, truncated to 80 chars.
  - Fallback: `"Session {date}"`.
- Rest of adapter unchanged.

### `cecli/tools/__init__.py`
- Remove `BOARD_TOOL_MODULES` list.
- Remove `task_create.py`, `task_list.py`, `task_show.py`, `task_update.py`, `task_complete.py`, `task_drop.py`, `open_task.py` from LLM tool registration.
- These files can stay on disk for now (the `/task` command imports from the store directly, not from these tool modules), or be deleted if they're only wired into the LLM tool schema.

### `cecli/tools/utils/registry.py`
- Remove conditional board-existence check for tool registration.
- Simplify to always register the same tool set.

### `cecli/prompts/agent.yml`
- **No changes.** Agent prompt stays exactly as it is on main. `UpdateTodoList` is the only tool mentioned.

### `cecli/commands/task.py`
- Remove `/task promote` subcommand.
- Add `/task new [title]` — creates a fresh task, sets it as active, future `UpdateTodoList` calls write to it.
- Keep everything else: `list`, `add`, `show`, `open`, `update`, `delete`, `complete`, `drop`.

### `cecli/sessions.py`
- On session save: include `active_task_id` in session JSON.
- On session load: restore `active_task_id`, verify the task file still exists in `board/`. If deleted, clear it.

## Default Board Config

Auto-created at `.cecli/tasks/brainfile.md` on first `UpdateTodoList` write:

```yaml
---
title: cecli tasks
schema: https://brainfile.md/v2/board.json
strict: false
columns:
  - id: in-progress
    title: In Progress
---
```

One column. No ceremony. The user who never types `/task` will never see this file.

## Agent Prompt (unchanged from main)

```
## Todo List Management
- **Track Progress**: Use the `UpdateTodoList` tool to add or modify items.
- **Plan Steps**: Create a todo list at the start of complex tasks...
- **Stay Organized**: Update the todo list as you complete steps...
```

Zero mention of boards, tasks, brainfile, structured data, or any underlying infrastructure.

## Example Flows

### Basic user (never touches /task)
```
User: "Add authentication to this app"

Agent: [calls UpdateTodoList with 5 items]
  → store.get_or_create_session_task() creates task-1.md
  → 5 subtasks written to task-1.md frontmatter
  → User sees the same ✓/○/→ display they always saw

Agent: [completes 3 items, calls UpdateTodoList]
  → task-1.md updated, 3 subtasks marked done

User: closes session, opens new one next day
  → agent_coder init finds task-1 with 2 incomplete subtasks
  → sets active_task_id = task-1
  → get_todo_list() shows remaining work automatically

Agent: [finishes remaining items]
  → task-1 subtasks all complete
  → next UpdateTodoList call creates task-2 (fresh task)
```

### Power user (uses /task)
```
User: /task list
  → task-1 (in-progress, 3/5 done)

User: /task complete task-1
  → Moved to logs/

User: /task new "Refactor database layer"
  → Creates task-2, sets as active
  → Agent's next UpdateTodoList writes to task-2

User: /task list logs
  → task-1: "Add authentication" (completed)
```

### Session restore
```
User: /session save "auth-work"
  → Saves session JSON with active_task_id: "task-1"

User: /session load "auth-work"
  → Restores active_task_id, verifies task-1.md exists
  → get_todo_list() renders task-1's remaining subtasks
```

## Tests
```bash
uv run pytest tests/basic/test_cecli_task_store.py -q
uv run pytest tests/basic/test_task_management.py -q
uv run pytest tests/basic/test_sessions.py -q
```

### Test cases to add/update
- `UpdateTodoList` with no prior board → auto-creates board config + task file
- `UpdateTodoList` with existing incomplete task → updates subtasks in place
- `UpdateTodoList` after all subtasks complete → creates new task on next call
- `get_or_create_session_task` finds latest incomplete → returns it
- `get_or_create_session_task` with no tasks → creates new
- `get_or_create_session_task` with all complete → creates new
- Session save includes `active_task_id`
- Session restore with valid `active_task_id` → resumes
- Session restore with missing task file → clears and creates new
- `/task new` mid-session → switches active task, next UpdateTodoList uses it
- `/task complete` → moves to logs, clears active, next UpdateTodoList creates fresh

## Open Questions
1. **`todo.txt` write-through**: Should we also write `todo.txt` on each update for backward compat with external scripts? Leaning no — clean break, `todo.txt` is a cecli internal.
2. **Auto-title strategy**: First subtask item (truncated) vs session timestamp vs something else. First item is probably most useful for `/task list` display.
3. **Stale task cleanup**: Should old incomplete tasks auto-archive after N days? Or leave entirely to the user? Leaning leave it — auto-archiving risks losing work.
4. **`/task add` vs `/task new`**: Should `/task add` still exist (creates a task but doesn't switch to it) vs `/task new` (creates and switches)? Probably keep both — `add` for queueing future work, `new` for "start fresh now."
