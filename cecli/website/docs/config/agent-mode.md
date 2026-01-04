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

This loop continues automatically until the `Finished` tool is called, or the maximum number of iterations is reached.

### Key Components

#### Tool Registry System

Agent Mode uses a centralized local tool registry that manages all available tools:

- **File Discovery Tools**: `ViewFilesMatching`, `ViewFilesWithSymbol`, `Ls`, `Grep`
- **Editing Tools**: `ReplaceText`, `InsertBlock`, `DeleteBlock`, `ReplaceLines`, `DeleteLines`
- **Context Management Tools**: `ContextManager`
- **Git Tools**: `GitDiff`, `GitLog`, `GitShow`, `GitStatus`
- **Utility Tools**: `UpdateTodoList`, `ListChanges`, `UndoChange`, `Finished`
- **Skill Management**: `LoadSkill`, `RemoveSkill`

#### Enhanced Context Management

Agent Mode includes some useful context management features:

- **Automatic file tracking**: Files added during exploration are tracked separately
- **Context blocks**: Directory structure, git status, symbol outlines, and environment info
- **Token management**: Automatic calculation of context usage and warnings when approaching limits
- **Tool usage history**: Tracks repetitive tool usage to prevent exploration loops

### Key Features

#### Autonomous Context Management

- **Proactive file discovery**: LLM can find relevant files without user guidance
- **Smart file removal**: Large files can be removed from context to save tokens
- **Dynamic context updates**: Context blocks provide real-time project information

#### Granular Editing Capabilities

Agent Mode prioritizes granular tools over SEARCH/REPLACE:

- **Precision editing**: `ReplaceText` for targeted changes
- **Block operations**: `InsertBlock`, `DeleteBlock` for larger modifications
- **Line-based editing**: `ReplaceLines`, `DeleteLines` with safety protocols
- **Refactoring support**: `ExtractLines` for code reorganization

#### Safety and Recovery

- **Undo capability**: `UndoChange` tool for immediate recovery from mistakes
- **Dry run support**: Tools can be tested with `dry_run=True`
- **Line number verification**: Two-step process for line-based edits to prevents errors
- **Tool usage monitoring**: Prevents infinite loops by tracking repetitive patterns

### Workflow Process

#### 1. Exploration Phase

The LLM uses discovery tools to gather information:

```
Tool Call: ViewFilesMatching
Arguments: {"pattern": "config", "file_pattern": "*.py"}

Tool Call: View
Arguments: {"file_path": "main.py"}

Tool Call: Grep
Arguments: {"pattern": "function_name"}
```

Files found during exploration are added to context as read-only, allowing the LLM to analyze them without immediate editing.

#### 2. Planning Phase

The LLM uses the `UpdateTodoList` tool to track progress and plan complex changes:

```
Tool Call: UpdateTodoList
Arguments: {"content": "## Task: Add new feature\n- [ ] Analyze existing code\n- [ ] Implement new function\n- [ ] Add tests\n- [ ] Update documentation"}
```

#### 3. Execution Phase

Files are made editable and modifications are applied:

```
Tool Call: MakeEditable
Arguments: {"file_path": "main.py"}

Tool Call: ReplaceText
Arguments: {"file_path": "main.py", "find_text": "old_function", "replace_text": "new_function"}

Tool Call: InsertBlock
Arguments: {"file_path": "main.py", "after_pattern": "import statements", "content": "new_imports"}
```

#### 4. Verification Phase

Changes are verified and the process continues:

```
Tool Call: GitDiff
Arguments: {}

Tool Call: ListChanges
Arguments: {}
```

#### 5. Completion Phase

The above continues over and over until:

```
Tool Call: Finished
Arguments: {}
```

### Agent Configuration
Agent Mode can be configured using the `--agent-config` command line argument, which accepts a JSON string for fine-grained control over tool availability and behavior.

Agent Mode can also be configured directly in the relevant config.yml file:

```yaml
agent: true
agent-config:
  # Tool configuration
  tools_includelist: [contextmanager", "replacetext", "finished"]  # Optional: Whitelist of tools
  tools_excludelist: ["command", "commandinteractive"]  # Optional: Blacklist of tools
  tool_paths: ["./custom-tools", "~/my-tools"]  # Optional: Directories or files containing custom tools
  
  # Context blocks configuration
  include_context_blocks: ["todo_list", "git_status"]  # Optional: Context blocks to include
  exclude_context_blocks: ["symbol_outline", "directory_structure"]  # Optional: Context blocks to exclude
  
  # Performance and behavior settings
  large_file_token_threshold: 12500  # Token threshold for large file warnings
  skip_cli_confirmations: false  # YOLO mode - be brave and let the LLM cook
  
  # Skills configuration (see Skills documentation for details)
  skills_paths: ["~/my-skills", "./project-skills"]  # Directories to search for skills
  skills_includelist: ["python-refactoring", "react-components"]  # Optional: Whitelist of skills to include
  skills_excludelist: ["legacy-tools"]  # Optional: Blacklist of skills to exclude
```

#### Configuration Options

- **`large_file_token_threshold`**: Maximum token threshold for large file warnings (default: 25000)
- **`skip_cli_confirmations`**: YOLO mode, be brave and let the LLM cook, can also use the option `yolo` (default: False)
- **`tools_includelist`**: Array of tool names to allow (only these tools will be available)
- **`tools_excludelist`**: Array of tool names to exclude (these tools will be disabled)
- **`tool_paths`**: Array of directories or Python files containing custom tools to load
- **`include_context_blocks`**: Array of context block names to include (overrides default set)
- **`exclude_context_blocks`**: Array of context block names to exclude from default set

#### Essential Tools

Certain tools are always available regardless of includelist/excludelist settings:

- `ContextManager` - Add, drop, and make files editable in the context
- `replacetext` - Basic text replacement
- `finished` - Complete the task

The registry also supports **Custom Tools** that can be loaded from specified directories or files using the `tool_paths` configuration option. Custom tools must be Python files containing a `Tool` class that inherits from `BaseTool` and defines a `NORM_NAME` attribute.

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

To load custom tools, specify the `tool_paths` configuration option in your agent config:

```yaml
agent-config:
  tool_paths: ["./custom-tools", "~/my-tools"]
```

The `tool_paths` can include:
- **Directories**: All `.py` files in the directory will be scanned for `Tool` classes
- **Individual Python files**: Specific tool files can be loaded directly

Tools are loaded automatically when the registry is built and will be available alongside the built-in tools.

#### Context Blocks

The following context blocks are available by default and can be customized using `include_context_blocks` and `exclude_context_blocks`:

- **`context_summary`**: Shows current context usage and token limits
- **`directory_structure`**: Displays the project's file structure
- **`git_status`**: Shows current git branch, status, and recent commits
- **`symbol_outline`**: Lists classes, functions, and methods in current context
- **`todo_list`**: Shows the current todo list managed via `UpdateTodoList` tool
- **`skills`**: Include skills content in the conversation

When `include_context_blocks` is specified, only the listed blocks will be included. When `exclude_context_blocks` is specified, the listed blocks will be removed from the default set.

#### Other Cecli Config Options for Agent Mode

- `use-enhanced-map` - Use enhanced repo map that takes into account import relationships between files

```yaml
use-enhanced-map: true
```

#### Complete Configuration Example

Complete configuration example in YAML configuration file (`.aider.conf.yml` or `~/.aider.conf.yml`):

```yaml
# Enable Agent Mode
agent: true

# Agent Mode configuration
agent-config:
  # Tool configuration
  tools_includelist: ["contextmanager", "replacetext", "finished"]  # Optional: Whitelist of tools
  tools_excludelist: ["command", "commandinteractive"]  # Optional: Blacklist of tools
  tool_paths: ["./custom-tools", "~/my-tools"]  # Optional: Directories or files containing custom tools
  
  # Context blocks configuration
  include_context_blocks: ["todo_list", "git_status"]  # Optional: Context blocks to include
  exclude_context_blocks: ["symbol_outline", "directory_structure"]  # Optional: Context blocks to exclude
  
  # Performance and behavior settings
  large_file_token_threshold: 12500  # Token threshold for large file warnings
  skip_cli_confirmations: false  # YOLO mode - be brave and let the LLM cook
  
  # Skills configuration (see Skills documentation for details)
  skills_paths: ["~/my-skills", "./project-skills"]  # Directories to search for skills
  skills_includelist: ["python-refactoring", "react-components"]  # Optional: Whitelist of skills to include
  skills_excludelist: ["legacy-tools"]  # Optional: Blacklist of skills to exclude

# Other Agent Mode options
use-enhanced-map: true  # Use enhanced repo map with import relationships
```

This configuration system allows for fine-grained control over which tools are available in Agent Mode, enabling security-conscious deployments and specialized workflows while maintaining essential functionality.

### Skills

Agent Mode includes a powerful skills system that allows you to extend the AI's capabilities with custom instructions, reference materials, scripts, and assets. Skills are configured through the `agent-config` parameter in the YAML configuration file.

For complete documentation on creating and using skills, including skill directory structure, SKILL.md format, and best practices, see the [Skills documentation](https://github.com/dwash96/cecli/blob/main/aider/website/docs/config/skills.md).

### Benefits

- **Autonomous operation**: Reduces need for manual file management
- **Context awareness**: Real-time project information improves decision making
- **Precision editing**: Granular tools reduce errors compared to SEARCH/REPLACE
- **Scalable exploration**: Can handle large codebases through strategic context management
- **Recovery mechanisms**: Built-in undo and safety features

Agent Mode represents a significant evolution in aider's capabilities, enabling more sophisticated and autonomous codebase manipulation while maintaining safety and control through the tool-based architecture.
