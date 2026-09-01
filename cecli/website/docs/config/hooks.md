---
parent: Configuration
nav_order: 35
description: Create and use custom commands to extend cecli's functionality.
---

# Hooks

Hooks allow you to extend `cecli` by defining custom actions that trigger at specific points in the agent's workflow. You can use hooks to automate tasks, integrate with external systems, or add custom validation logic.

## Per-Agent Architecture

Hooks in `cecli` use a **per-agent** architecture. Each coder instance (primary agent and sub-agents) has its own isolated `HookManager` with its own set of registered hooks and enabled/disabled states.

Key design points:

- **Isolated hook state**: Each agent gets its own `HookManager`. Enabling or disabling a hook on one agent does not affect others.
- **No inheritance**: Sub-agents do **not** inherit hooks from their parent. Each sub-agent defines its own hooks (if any) in its definition file.
- **Independent lifecycle**: Hooks are created when their owning coder is created and cleaned up when the coder is destroyed.
- **Global configuration**: The `--hooks` CLI flag and `.cecli.conf.yml` hooks configuration only affect the **primary agent**.
- **Per-agent hooks**: Sub-agents can define their own hooks via the `hooks` field in their YAML front matter definition.

Hooks are configured in your `.cecli.conf.yml` file under the `hooks` section. You can define two types of hooks:
1. **Command Hooks**: Execute shell commands or scripts.
2. **Python Hooks**: Execute custom Python code by providing a path to a Python file.

### Basic Configuration

```yaml
hooks:
  start:
    - name: log_session_start
      command: "echo 'Session started at {timestamp}' >> .cecli/hooks_log.txt"
      priority: 10
      enabled: true
      description: "Logs session start to file"
```

## Hook Types

The following hook types are available:

| Hook Type | Trigger Point |
|-----------|---------------|
| `start` | When the agent session begins. |
| `on_message` | When a new user message is received. |
| `end_message` | When message processing completes. |
| `pre_tool` | Before a tool is executed. |
| `post_tool` | After a tool execution completes. |
| `end` | When the agent session ends. |

## Configuration Options

Each hook entry supports the following options:

- `name`: (Required) A unique name for the hook.
- `command`: The shell command to execute (for Command Hooks).
- `file`: The path to a Python file (for Python Hooks).
- `priority`: (Optional) Execution order (lower numbers run first). Default is 10.
- `enabled`: (Optional) Whether the hook is active. Default is true.
- `description`: (Optional) A brief description of what the hook does.

## Command Hooks

Command hooks are simple shell commands. You can use placeholders in the command string that will be replaced with metadata from the hook event.

### Available Metadata

| Hook Type | Available Placeholders |
|-----------|------------------------|
| `start`, `end` | `{timestamp}` `{coder_type}` |
| `on_message` `end_message` | `{timestamp}` `{message}` `{message_length}` |
| `pre_tool` | `{timestamp}` `{tool_name}` `{arg_string}` |
| `post_tool` | `{timestamp}` `{tool_name}` `{arg_string}` `{output}` |

### Example: Aborting Tool Execution
If a `pre_tool` command hook returns a non-zero exit code, the tool execution will be aborted.

```yaml
hooks:
  pre_tool:
    - name: check_dangerous_command
      command: "python3 scripts/check_safety.py --args '{arg_string}'"
```

## Python Hooks

Python hooks allow for more complex logic. To create a Python hook, create a `.py` file and define a class that inherits from `BaseHook`.

### Example Python Hook

**File**: `.cecli/hooks/my_hook.py`
```python
from cecli.hooks import BaseHook, HookHelpers
from cecli.hooks.types import HookType

class MyCustomHook(BaseHook):
    type = HookType.PRE_TOOL

    async def execute(self, coder, metadata):
        # Access coder instance or metadata
        tool_name = metadata.get("tool_name")

        if tool_name == "delete_file":
            print("Warning: Deleting a file!")

            # Fetch recent messages for context
            recent = HookHelpers.get_messages(coder, last_n=3)

        # Return False to abort operation (for pre_tool/post_tool)
        return True
```

**Configuration**:
```yaml
hooks:
  pre_tool:
    - name: my_custom_python_hook
      file: .cecli/hooks/my_hook.py
```

## Hook Helpers

The ``HookHelpers`` class provides a higher-level API for writing Python hooks. All helpers are accessed through a single import — ``from cecli.hooks import HookHelpers`` — giving you convenient access to conversation history, model calls, and sub-agent invocation from within any hook's ``execute()`` method.

```python
from cecli.hooks import BaseHook, HookHelpers
from cecli.hooks.types import HookType

class MyHook(BaseHook):
    type = HookType.POST_TOOL

    async def execute(self, coder, metadata):
        # Fetch recent conversation messages
        recent = HookHelpers.get_messages(coder, last_n=5)

        # Make an LLM call
        reply = await HookHelpers.call(coder, prompt="Summarize the last message.")

        # Append a message to the conversation
        HookHelpers.append_message(coder, {"role": "user", "content": reply})

        # Invoke a sub-agent
        summary = await HookHelpers.call_subagent(
            coder, "reviewer", "Review these changes"
        )
        return True
```

### get_messages(coder, last_n=None, tag=None, reload=False)

Retrieve messages from the agent's conversation history as a list of message dicts (``{"role": …, "content": …}``).

| Parameter | Description |
|-----------|-------------|
| ``coder`` | The coder instance passed to ``execute()``. |
| ``last_n`` | If set, return only the *last_n* messages (most recent). |
| ``tag`` | Optional tag to filter by (e.g. ``"cur"``, ``"done"``). |
| ``reload`` | If ``True``, bypass the internal cache. |

### append_message(coder, message_dict, tag="cur", **kwargs)

Append a message to the agent's conversation history. The message will be visible to the LLM on the next turn. Returns the ``BaseMessage`` instance.

| Parameter | Description |
|-----------|-------------|
| ``coder`` | The coder instance passed to ``execute()``. |
| ``message_dict`` | The message content dict, e.g. ``{"role": "user", "content": "..."}``. |
| ``tag`` | Message tag (default ``"cur"``). |
| ``**kwargs`` | Extra arguments like ``hash_key``, ``force``, ``priority``. |

### call(coder, messages=None, prompt=None, system=None, model_name=None, max_tokens=None, **kwargs)

Make a language model generation call (async). You can either pass a pre-built ``messages`` list, or use ``prompt`` with an optional ``system`` preamble.

| Parameter | Description |
|-----------|-------------|
| ``coder`` | The coder instance passed to ``execute()``. |
| ``messages`` | Full message list (overrides ``prompt``/``system``). |
| ``prompt`` | A simple user-prompt string. |
| ``system`` | Optional system message prepended to ``prompt``. |
| ``model_name`` | Override model (e.g. ``"gpt-4o"``). Defaults to ``coder.main_model``. |
| ``max_tokens`` | Maximum response tokens. |
| ``**kwargs`` | Extra arguments passed to the underlying ``simple_send_with_retries()``. |

### call_subagent(coder, name, prompt, **kwargs)

Invoke a registered sub-agent by name (async, blocking by default). Returns the sub-agent's summary string, or ``None`` on failure.

| Parameter | Description |
|-----------|-------------|
| ``coder`` | The coder instance passed to ``execute()``. |
| ``name`` | The registered sub-agent name (e.g. ``"reviewer"``, ``"tester"``). |
| ``prompt`` | The user message to send to the sub-agent. |
| ``**kwargs`` | Extra arguments like ``blocking``, ``parent``, ``auto_reap``. |

## Managing Hooks

You can manage hooks during an active session using the following slash commands:

- `/hooks`: List all registered hooks and their status.
- `/load-hook <name>`: Enable a specific hook.
- `/remove-hook <name>`: Disable a specific hook.

## Best Practices

- **Security**: Hooks run with the same permissions as `cecli`. Be careful when running scripts from untrusted sources.
- **Performance**: Avoid long-running tasks in hooks, as they can block the agent's loop.
- **Error Handling**: If a hook fails, `cecli` will generally log the error and continue, except for `pre_tool` hooks which can abort execution.
