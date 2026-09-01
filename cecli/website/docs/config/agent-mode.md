---
parent: Configuration
nav_order: 5
description: Agent Mode enables autonomous codebase exploration and modification using local tools.
---
# Agent Mode

Agent Mode is an operational mode in cecli that enables autonomous codebase exploration and modification using local tools. Instead of relying on traditional edit formats, Agent Mode uses a tool-based approach where the LLM can discover, analyze, and modify files through a series of tool calls.

Agent Mode can be activated in the following ways

In the interface:

```
/agent
```

In the command line:

```
cecli ... --agent
```

In the configuration files:

```
agent: true
```

## How Agent Mode Works

### Core Architecture

Agent Mode operates through a continuous loop where the LLM:

1. **Receives a user request** and analyzes the current context
2. **Uses discovery tools** to find relevant files and information
3. **Executes editing tools** to make changes
4. **Processes results** and continues exploration and editing until the task is complete

This loop continues automatically until the `Yield` tool is called, or the maximum number of iterations is reached.

### Key Components

#### Tool Registry System

Agent Mode uses a centralized local tool registry. The standard tools include:

- **Discovery and inspection**: `ExploreCode`, `Ls`, `Grep`, `ReadFile`, and `Thinking`
- **Context and editing**: `ResourceManager`, `EditFile`, `UndoChange`, and `UpdateTodoList`
- **Execution and orchestration**: `Command` and `Orchestrate`
- **Sub-agent coordination**: `Delegate` and `Yield`
- **Optional memory tools**: `SearchFacts` and `ReplaceFacts`

#### Enhanced Context Management

Agent Mode includes some useful context management features:

- **Automatic file tracking**: Files added during exploration are tracked separately
- **Configurable context blocks**: Environment, todo, skills, server, sub-agent, orchestration, and other blocks can be included or excluded
- **Token management**: Context token counts are calculated when enabled; detailed limit warnings are shown by the `context_summary` block
- **Tool usage history**: Tracks repetitive tool usage to prevent exploration loops

### Key Features

#### Autonomous Context Management

- **Proactive file discovery**: LLM can find relevant files without user guidance
- **Smart file removal**: Large files can be removed from context to save tokens
- **Dynamic context updates**: Context blocks provide real-time project information

#### Safety and Recovery

- **Undo capability**: `UndoChange` tool for immediate recovery from mistakes
- **Dry run support**: Tools can be tested with `dry_run=True`
- **Virtual content IDs**: `ReadFile` returns virtual line identifiers that `EditFile` uses to target complete logical blocks safely
- **Tool usage monitoring**: Prevents infinite loops by tracking repetitive patterns

### Workflow Process

#### 1. Exploration Phase

The LLM uses discovery tools to gather information:

```text
Tool Call: ExploreCode
Arguments: {"queries": [{"symbol": "Config", "action": "search"}]}

Tool Call: ReadFile
Arguments: {"read": [{"file_path": "main.py", "range_start": "@000", "range_end": "000@"}]}

Tool Call: Grep
Arguments: {"searches": [{"pattern": "function_name", "directory": "."}]}
```

`ExploreCode` uses a codebase index when available. `ReadFile` returns content with virtual identifiers for precise follow-up edits. Files discovered through agent tools can be added as read-only context by using `ResourceManager` to change context membership.

#### 2. Planning Phase

The LLM uses the `UpdateTodoList` tool to track progress and plan complex changes:

```
Tool Call: UpdateTodoList
Arguments: {"content": "## Task: Add new feature\n- [ ] Analyze existing code\n- [ ] Implement new function\n- [ ] Add tests\n- [ ] Update documentation"}
```

#### 3. Execution Phase

Files are added to context and made editable with `ResourceManager`, then modifications are applied with `EditFile`:

```text
Tool Call: ResourceManager
Arguments: {"add": ["main.py"]}

Tool Call: EditFile
Arguments: {"edits": [{"file_path": "main.py", "operation": "replace", "start_line": "——def old_function():", "end_line": "——    return old_value", "text": "def new_function():\n    return new_value"}]}
```

`EditFile` accepts an `edits` array containing `replace`  or `delete` operations. Its line targets come from the latest `ReadFile` result. `ResourceManager` can add files as editable or read-only and remove them from context.

#### 4. Verification Phase

Changes are verified with the available tools:

```text
Tool Call: GitDiff
Arguments: {}

Tool Call: ReadFile
Arguments: {"read": [{"file_path": "main.py", "range_start": "@000", "range_end": "000@"}]}

Tool Call: UndoChange
Arguments: {"change_id": "..."}
```

`GitDiff` is available when enabled in the configuration; it is excluded by default.

#### 5. Completion Phase

The agent continues until the task is complete and then calls `Yield`:

```text
Tool Call: Yield
Arguments: {}
```

`Yield` is the registry's essential tool. When sub-agents are active, it waits for their outstanding tasks; completed summaries and errors are injected into the parent conversation before completion.

### Agent Configuration

Agent Mode can be configured using the `--agent-config` command line argument, which accepts a JSON string for fine-grained control over tool availability and behavior.

Agent Mode can also be configured directly in your configuration file. See the [Complete Configuration Example](#agent-mode-how-agent-mode-works-agent-configuration-complete-configuration-example) below for a full reference.

#### Configuration Options

- **`large_file_token_threshold`**: Maximum token threshold for large file warnings (default: `8192`)
- **`skip_cli_confirmations`**: YOLO mode; `yolo` is accepted as an alias (default: `false`)
- **`allowed_commands`**: Array of glob patterns for commands that can be executed without prompting. Example: `["wc -l*"]` (default: `[]`)
- **`tools_includelist`**: Array of tool names to allow. When non-empty, only these tools are available; `yield` is automatically retained.
- **`tools_excludelist`**: Array of tool names to exclude
- **`tools_paths`**: Array of directories or Python files containing custom tools. `tool_paths` is accepted as an alias.
- **`servers_includelist`**: Array of MCP server names to allow. `servers_whitelist` is accepted as an alias.
- **`servers_excludelist`**: Array of MCP server names to exclude. `servers_blacklist` is accepted as an alias.
- **`show_lint_errors`**: When enabled, linting errors found during editing are displayed in tool output (default: `false`)
- **`subagent_paths`**: Array of directories to search for sub-agent definition `.md` files. `~/.cecli/subagents` and the built-in defaults directory are also scanned.
- **`max_sub_agents`**: Maximum number of active sub-agents (default: `30`; `-1` means effectively unlimited)
- **`allow_nested_delegation`**: Allow sub-agents to delegate tasks to further sub-agents (default: `false`)
- **`include_context_blocks`**: Array of context block names to include, replacing the default set
- **`exclude_context_blocks`**: Array of context block names to exclude from the selected set
- **`hot_reload`**: When enabled, skills configuration is hot-reloaded automatically (default: `false`)
- **`command_timeout`**: Seconds used when waiting for background command completion (default: `30`)
- **`diff_colors`**: When enabled, edit diffs use color-coded removed, added, and context lines (default: `true`)
- **`allow_orchestration`**: Enables the `Orchestrate` tool and its context block (default: `true`)

- **`orchestration`**: A nested configuration object for the Orchestrate tool's Python sandbox. When absent or empty, the sandbox runs with default restrictions. See [Orchestration Configuration](#agent-mode-how-agent-mode-works-agent-configuration-orchestration-configuration) below for details.

#### Orchestration Configuration

The `Orchestrate` tool runs user code in a secure Python sandbox with the following restrictions:
- **No imports** — only pre-imported modules (`re`, `math`, `itertools`, `collections`,
  `datetime`, `traceback`, `json`, `pathlib`) are available
- **No private/dunder access** — attributes starting with `_` are blocked
- **No dangerous builtins** — `eval`, `exec`, `open`, `compile`, `breakpoint`,
  `__import__`, `globals`, `locals`, `setattr`, `delattr` are blocked
- **No global/nonlocal statements**
- **Loop protection** — `while`/`for` loops yield cooperatively to prevent hangs

These restrictions can be selectively relaxed via the `orchestration` config block:

- **`allowed_imports`**: Array of module names to allow importing. Example:
  `["os", "typing"]`. Only standard library modules should be allowed; third-party
  modules may execute arbitrary code at import time.

- **`allowed_builtins`**: Array of builtin function names to add to the sandbox.
  Example: `["setattr", "property"]`. Dangerous builtins (`eval`, `exec`, `open`, etc.)
  cannot be added.

- **`allow_classes`**: Boolean (default: `false`). When `true`, class definitions are
  permitted and dunder methods (`__init__`, `__str__`, `__repr__`, `__iter__`, etc.)
  are allowed inside class bodies.

- **`disable_security`**: Boolean (default: `false`). When `true`, the AST-level security
  filter is skipped entirely. ⚠ Use with extreme caution — this disables all import
  blocking, dunder blocking, and dangerous builtin blocking.

- **`disable_loop_protection`**: Boolean (default: `false`). When `true`, the cooperative
  yield injection is skipped. Use only if you are certain the orchestration code has no
  unbounded loops.

Example:

```yaml
agent-config:
  orchestration:
    allowed_imports:
      - os
      - typing
    allow_classes: true
```

#### Essential Tools

Only `Yield` is protected as an essential registry tool. Other tools, including `ResourceManager` and `ReadFile`, can be restricted by includelist/excludelist settings.

- `ResourceManager` - Add, drop, and make files editable in context
- `ReadFile` - Read file contents with virtual content IDs
- `Yield` - Complete the task and wait for active child agents

The registry also supports **Custom Tools** that can be loaded from specified directories or files using the `tools_paths` configuration option. Custom tools must be Python files containing a `Tool` class that inherits from `BaseTool` and defines a `NORM_NAME` attribute.

##### Creating Custom Tools

Custom tools can be created by writing Python files that follow this structure:

```python
from cecli.tools.utils.base_tool import BaseTool

class Tool(BaseTool):
    NORM_NAME = "mycustomtool"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "MyCustomTool",
            "description": "Description of what the tool does",
            "parameters": {
                "type": "object",
                "properties": {
                    "parameter_name": {
                        "type": "string",
                        "description": "Description of the parameter"
                    }
                },
                "required": ["parameter_name"],
            },
        },
    }

    @classmethod
    def execute(cls, coder, parameter_name):
        """
        Execute the custom tool.
        
        Args:
            coder: The coder instance
            parameter_name: The parameter value
        
        Returns:
            A string result message
        """
        # Tool implementation here
        return f"Tool executed with parameter: {parameter_name}"
```

To load custom tools, specify the `tools_paths` configuration option in your agent config:

```yaml
agent-config:
  tools_paths: ["./custom-tools", "~/my-tools"]
```

The `tools_paths` can include:
- **Directories**: All `.py` files in the directory will be scanned for `Tool` classes
- **Individual Python files**: Specific tool files can be loaded directly

Tools are loaded automatically when the registry is built and will be available alongside the built-in tools.

#### Sub-agent Behavior

`Delegate` accepts one or more delegation objects. Each delegation includes a registered sub-agent `name`, a `prompt`, and optional `async` and `persist` flags. Asynchronous delegations run in the background; synchronous delegations wait for the sub-agent result. The system uses `Yield` to wait for outstanding child tasks when finishing the parent task.

Sub-agent results are reported back to the parent conversation as summaries or errors. Sub-agents use `auto_reap: true` by default, so completed agents can be removed automatically after their work and descendants finish. Independent agents may be cleaned up shortly after completion, while the service also reaps completed agents when the configured limit requires space. Set `max_sub_agents` to `-1` to remove the limit on simultaneous sub agents.

Sub-agent definition files may specify a `model` using one of these runtime-resolved values: `<weak_model>`, `<agent_model>`, `<main_model>`, or `<current>`. Nested delegation is disabled by default; enable `allow_nested_delegation` to expose `Delegate` to sub-agents and allow nested child-agent context.

#### Context Blocks

The following context blocks are available and can be customized using `include_context_blocks` and `exclude_context_blocks`:

**Included by default:**

- **`environment_info`**: Working directory, platform, date, language, and repository details
- **`todo_list`**: Current tasks managed through `UpdateTodoList`
- **`skills`**: Available skills and their configuration
- **`servers`**: Connected, filtered, and disconnected MCP servers
- **`sub_agents`**: Registered sub-agents (shown to the primary agent; nested agents require nested delegation to see child-agent context)
- **`orchestration`**: Orchestrate guidance when `allow_orchestration` is enabled

**Available when explicitly included:**

- **`context_summary`**: Current file and context-block token usage and limits
- **`directory_structure`**: Project file structure
- **`git_status`**: Current git branch, status, and recent commits
- **`symbol_outline`**: Classes, functions, and methods in current context


When `include_context_blocks` is specified, it replaces the default set. `exclude_context_blocks` then removes named blocks from that set.

- `use-enhanced-map` - Use enhanced repo map that takes into account import relationships between files

```yaml
use-enhanced-map: true
```

#### Complete Configuration Example

Complete configuration example in YAML configuration file (`.cecli.conf.yml` or `~/.cecli.conf.yml`):

```yaml
# Enable Agent Mode
agent: true

# Agent Mode configuration
agent-config:
  # Tool configuration
  tools_includelist: ["resourcemanager", "readfile", "yield"]
  tools_excludelist: ["command"]
  tools_paths: ["./custom-tools", "~/my-tools"]

  # Server configuration
  servers_includelist: ["local"]
  servers_excludelist: []

  # Sub-agent configuration
  subagent_paths: [".cecli/subagents"]
  max_sub_agents: 30  # -1 means effectively unlimited
  allow_nested_delegation: false

  # Context blocks configuration
  include_context_blocks: ["todo_list", "git_status"]
  exclude_context_blocks: ["symbol_outline", "directory_structure"]

  # Performance and behavior settings
  large_file_token_threshold: 8192
  command_timeout: 30
  skip_cli_confirmations: false
  allowed_commands: ["wc -l*"]
  show_lint_errors: false
  hot_reload: false
  diff_colors: true
  allow_orchestration: true

  # Orchestration sandbox configuration
  orchestration:
    allowed_imports: []
    allowed_builtins: []
    allow_classes: false
    disable_security: false
    disable_loop_protection: false

  # Skills configuration
  skills_paths: ["~/my-skills", "./project-skills"]
  skills_includelist: ["python-refactoring", "react-components"]
  skills_excludelist: ["legacy-tools"]
  skills_init: ["python-refactoring"]


```

This configuration system allows for fine-grained control over which tools are available in Agent Mode, enabling security-conscious deployments and specialized workflows while maintaining essential functionality.

### Skills

Agent Mode includes a powerful skills system that allows you to extend the AI's capabilities with custom instructions, reference materials, scripts, and assets. Skills are configured through the `agent-config` parameter in the YAML configuration file.

Skills can be configured to load automatically on startup using the `skills_init` option, which accepts a list of skill names that will be both loaded (included in context) and whitelisted (made discoverable) when the agent starts:

```yaml
agent-config:
  skills_init: ["python-refactoring"]
```

For complete documentation on creating and using skills, including skill directory structure, SKILL.md format, and best practices, see the [Skills documentation](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/skills.md).

### Benefits
- **Autonomous operation**: Reduces need for manual file management
- **Context awareness**: Real-time project information improves decision making
- **Precision editing**: Granular tools reduce errors compared to SEARCH/REPLACE
- **Scalable exploration**: Can handle large codebases through strategic context management
- **Recovery mechanisms**: Built-in undo and safety features

Agent Mode represents a significant evolution in cecli's capabilities, enabling more sophisticated and autonomous codebase manipulation while maintaining safety and control through the tool-based architecture.
