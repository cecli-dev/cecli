# Session Management

Aider provides session management commands that allow you to save, load, and manage your chat sessions. This is particularly useful for:

- Continuing work on complex projects across multiple sessions
- Recreating specific development environments
- Archiving important conversations and file configurations

## Session Commands

### `/save-session <name>`
Save the current chat session to a named file in `.aider/sessions/`.

### Auto-Save and Auto-Load
Aider can automatically save and load sessions using command line options:

**Auto-save:**
```bash
aider --auto-save
```

**Auto-load:**
```bash
aider --auto-load
```

**In configuration files:**
```yaml
auto-save: true
auto-load: true
```

When `--auto-save` is enabled, aider will automatically save your session as 'auto-save' when you exit. When `--auto-load` is enabled, aider will automatically load the 'auto-save' session on startup if it exists.

**Usage:**
```
/save-session my-project-session
```

**What gets saved:**
- Chat history (both done and current messages)
- All files in the chat (editable, read-only, and read-only stubs)
- Current model and edit format settings
- Auto-commit, auto-lint, and auto-test settings
- Todo list content from `.aider.todo.txt`
- Session metadata (timestamp, version)

### `/load-session <name>`
Load a previously saved session by name or file path.

**Usage:**
```
/load-session my-project-session
```

**What gets loaded:**
- Restores chat history and file configurations
- Recreates the exact session state
- Preserves all settings and model configurations
- Restores the todo list content saved in the session

### `/list-sessions`
List all available saved sessions in `.aider/sessions/`.

**Usage:**
```
/list-sessions
```

**Shows:**
- Session names
- Model used
- Edit format
- Creation timestamp

## How Sessions Work

### Session Storage
Sessions are stored as JSON files in the `.aider/sessions/` directory within your project. Each session file contains:

```json
{
  "version": 1,
  "timestamp": 1700000000,
  "session_name": "my-session",
  "model": "gpt-4",
  "weak_model": "gpt-4o-mini",
  "editor_model": "gpt-4o",
  "editor_edit_format": "diff",
  "edit_format": "diff",
  "chat_history": {
    "done_messages": [...],
    "cur_messages": [...]
  },
  "files": {
    "editable": ["file1.py", "file2.js"],
    "read_only": ["docs/README.md"],
    "read_only_stubs": []
  },
  "settings": {
    "auto_commits": true,
    "auto_lint": false,
    "auto_test": false
  },
  "todo_list": "- plan feature A\n- write tests\n"
}
```

### Session File Location
- **Relative paths**: Files within your project are stored with relative paths
- **Absolute paths**: External files are stored with absolute paths

## Use Cases

### Project Continuation
```
# Start working on a project
/add src/main.py src/utils.py
# ... have a conversation ...
/save-session my-project

# Later, continue where you left off
/load-session my-project
```

### Multiple Contexts
```
# Work on frontend
/add src/components/*.jsx src/styles/*.css
/save-session frontend-work

# Switch to backend
/reset
/add server/*.py database/*.sql
/save-session backend-work

# Easily switch between contexts
/load-session frontend-work
```

## Best Practices

### Naming Conventions
- Use descriptive names: `feature-auth-session`, `bugfix-issue-123`
- Include dates if needed: `2024-01-project-setup`

### File Management
- Session files include all file paths, so they work best when project structure is stable
- External files (outside the project root) are stored with absolute paths
- Missing files are skipped with warnings during loading
- The todo list file (`.aider.todo.txt`) is cleared on startup; it is restored when you load a session or when you update it during a run

### Version Control
- Consider adding `.aider/sessions/` to your `.gitignore` if sessions contain sensitive information

## Troubleshooting

### Session Not Found
If `/load-session` reports "Session not found":
- Check that the session file exists in `.aider/sessions/`
- Verify the session name matches exactly
- Use `/list-sessions` to see available sessions

### Missing Files
If files are reported as missing during loading:
- The files may have been moved or deleted
- Session files store relative paths, so directory structure changes can affect this
- External files must exist at their original locations
- The todo list (`.aider.todo.txt`) is cleared on startup unless restored from a loaded session

### Corrupted Sessions
If a session fails to load:
- Check the session file is valid JSON
- Verify the session version is compatible
- Try creating a new session and compare file structures

### Deprecated Options
- `--preserve-todo-list` is deprecated. The todo list is cleared on startup and restored only when you load a session that contains it.

## Related Commands
- `/reset` - Clear chat history and drop files (useful before loading a session)

## Examples

### Complete Workflow
```
# Start a new project session
/add package.json src/main.js src/components/
# ... work on the project ...
/save-session react-project

# Later, continue working
/load-session react-project
# All files and chat history are restored
```

### Session with External Files
```
# Include documentation from outside the project
/read-only ~/docs/api-reference.md
/save-session project-with-docs
```

### Multiple Model Sessions
```
# Save session with specific model
/model gpt-5
/save-session gpt5-session

# Try different model
/model claude-sonnet-4.5
/save-session claude-session
```
