---
parent: Usage
nav_order: 850
description: Session management utilities to save and load work across multiple application runs
---

# Session Management

Cecli provides session management commands that allow you to save, load, and manage your chat sessions. This is particularly useful for:

- Continuing work on complex projects across multiple sessions
- Recreating specific development environments
- Archiving important conversations and file configurations

## Session Commands

### `/sessions save <name>`
Save the current chat session to a named file in `.cecli/sessions/`.

**Usage:**
```
/sessions save my-project-session
```

**What gets saved:**
- Chat history (both done and current messages)
- All files in the chat (editable, read-only, and read-only stubs)
- Current model and edit format settings
- Auto-commit, auto-lint, and auto-test settings
- Todo list content from `.cecli/run/{date}/{agent id}/todo.txt`
- Session metadata (timestamp, version)

### Auto-Save and Auto-Load
Cecli can automatically save and load sessions using command line options:

**Auto-save:**
```bash
cecli --auto-save
```

**Auto-load:**
```bash
cecli --auto-load
```

**In configuration files:**
```yaml
auto-save: true
auto-load: true
```

When `--auto-save` is enabled, cecli will automatically save your session as 'auto-save' when you exit. When `--auto-load` is enabled, cecli will automatically load the 'auto-save' session on startup if it exists.

### `/sessions load <name>`
Load a previously saved session by name or file path.

**Usage:**
```
/sessions load my-project-session
```

**What gets loaded:**
- Restores chat history and file configurations
- Recreates the exact session state
- Preserves all settings and model configurations
- Restores the todo list content saved in the session

### `/sessions list`
List all available saved sessions in `.cecli/sessions/`.

**Usage:**
```
/sessions list
```

**Shows:**
- Session names
- Model used
- Edit format
- Creation timestamp

## How Sessions Work

### Session Storage
Sessions are stored as JSON files in the `.cecli/sessions/` directory within your project. Each session file contains:

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
/sessions save my-project

# Later, continue where you left off
/sessions load my-project
```

### Multiple Contexts
```
# Work on frontend
/add src/components/*.jsx src/styles/*.css
/sessions save frontend-work

# Switch to backend
/reset
/add server/*.py database/*.sql
/sessions save backend-work

# Easily switch between contexts
/sessions load frontend-work
```

## Best Practices

### Naming Conventions
- Use descriptive names: `feature-auth-session`, `bugfix-issue-123`
- Include dates if needed: `2024-01-project-setup`

### File Management
- Session files include all file paths, so they work best when project structure is stable
- External files (outside the project root) are stored with absolute paths
- Missing files are skipped with warnings during loading

### Version Control
- Consider adding `.cecli/sessions/` to your `.gitignore` if sessions contain sensitive information

### Optional encryption (AES-256-GCM)

When enabled, session files on disk are encrypted (plaintext JSON is unchanged when disabled).

```bash
export CECLI_SESSION_KEY="$(python -c 'import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
cecli --session-encrypt --auto-save
```

Or use `--session-key-file` pointing at a file with the same urlsafe-base64 32-byte key.

## Troubleshooting

### Session Not Found
If `/sessions load` reports "Session not found":
- Check that the session file exists in `.cecli/sessions/`
- Verify the session name matches exactly
- Use `/sessions list` to see available sessions

### Missing Files
If files are reported as missing during loading:
- The files may have been moved or deleted
- Session files store relative paths, so directory structure changes can affect this
- External files must exist at their original locations

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
/sessions save react-project

# Later, continue working
/sessions load react-project
# All files and chat history are restored
```

### Session with External Files
```
# Include documentation from outside the project
/read-only ~/docs/api-reference.md
/sessions save project-with-docs
```

### Multiple Model Sessions
```
# Save session with specific model
/model gpt-5
/sessions save gpt5-session

# Try different model
/model claude-sonnet-4.5
/sessions save claude-session
```
