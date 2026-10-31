---
parent: Usage
nav_order: 50
description: Control cecli with in-chat commands like /add, /model, etc.
---

# Slash Commands

Cecli supports commands from within the chat, which all start with `/`.

|Command|Description|
|:------|:----------|
| **/add** | Add files to the chat so cecli can edit them or review them in detail |
| **/architect** | Enter architect/editor mode using 2 different models. If no prompt provided, switches to architect/editor mode. |
| **/ask** | Ask questions about the code base without editing any files. If no prompt provided, switches to ask mode. |
| **/chat-mode** | Switch to a new chat mode |
| **/clear** | Clear the chat history |
| **/code** | Ask for changes to your code. If no prompt provided, switches to code mode. |
| **/commit** | Commit edits to the repo made outside the chat (commit message optional) |
| **/context** | Enter context mode to see surrounding code context. If no prompt provided, switches to context mode. |
| **/copy** | Copy the last assistant message to the clipboard |
| **/copy-context** | Copy the current chat context as markdown, suitable to paste into a web UI |
| **/creator** | Start creator mode to add skills, MCP servers, hooks, tools, commands, workflows, or settings |
| **/diff** | Display the diff of changes since the last message |
| **/drop** | Remove files from the chat session to free up context space |
| **/edit** | Alias for /editor: Open an editor to write a prompt |
| **/editor** | Open an editor to write a prompt |
| **/editor-model** | Switch the Editor Model to a new LLM |
| **/exit** | Exit the application |
| **/git** | Run a git command (output excluded from chat) |
| **/help** | Ask questions about cecli |
| **/history-search** | Fuzzy search your command history and paste the selected command into the chat. |
| **/hooks** | Manage hooks: `/hooks list`, `/hooks load <name>`, `/hooks remove <name>` |
| **/lint** | Lint and fix in-chat files or all dirty files if none in chat |
| **/load** | Load and execute commands from a file |
| **/ls** | List all known files and indicate which are included in the chat session |
| **/map** | Print out the current repository map |
| **/map-refresh** | Force a refresh of the repository map |
| **/mcp** | Manage MCP servers: `/mcp list`, `/mcp load <name>`, `/mcp remove <name>` |
| **/model** | Switch the Main Model to a new LLM |
| **/models** | Search the list of available models |
| **/multiline-mode** | Toggle multiline mode (swaps behavior of Enter and Meta+Enter) |
| **/paste** | Paste image/text from the clipboard into the chat.        Optionally provide a name for the image. |
| **/quit** | Exit the application |
| **/read-only** | Add files to the chat that are for reference only, or turn added files to read-only |
| **/reasoning-effort** | Set the reasoning effort level (values: number or low/medium/high depending on model) |
| **/report** | Report a problem by opening a GitHub Issue |
| **/reset** | Drop all files and clear the chat history |
| **/run** | Run a shell command and optionally add the output to the chat (alias: !) |
| **/save** | Save commands to a file that can reconstruct the current chat session's files |
| **/sessions** | Manage sessions: `/sessions list`, `/sessions load <name>`, `/sessions save <name>` |
| **/settings** | Print out the current settings |
| **/skills** | Manage skills: `/skills list`, `load`, `include`, `exclude`, `remove`, `import` |
| **/switch-agent** | Switch to a specific agent by name |
| **/test** | Run a shell command and add the output to the chat on non-zero exit code |
| **/think-tokens** | Set the thinking token budget, eg: 8096, 8k, 10.5k, 0.5M, or 0 to disable. |
| **/tokens** | Report on the number of tokens used by the current chat context |
| **/undo** | Undo the last git commit if it was done by cecli |
| **/voice** | Record and transcribe voice input |
| **/weak-model** | Switch the Weak Model to a new LLM |
| **/web** | Scrape a webpage, convert to markdown and send in a message |



## Prompt Queue Management

The prompt queue is a first-in-first-out (FIFO) queue of prompts attached to the active agent. Queued prompts run after the current response finishes. Starting a new prompt also drains the queue after that prompt completes; use `/queue run` to start it explicitly.

| Command | Description |
|---------|-------------|
| **/queue add** | Queue a prompt for processing after current tasks complete |
| **/queue insert** | Insert a prompt at a specific position in the queue |
| **/queue list** | List all prompts currently in the queue |
| **/queue remove** | Remove a prompt from the queue by index, or '*' to clear all |
| **/queue run** | Process queued prompts immediately |

If a response is interrupted (for example with Ctrl+C), the in-flight prompt is put back at the front of the queue. Use `/queue run` to resume processing.

### `/queue add` Command

**Usage:** `/queue add <prompt text>`, or the shorthand `/queue <prompt text>`

**Description:** Adds a prompt to the queue for processing after the current response completes.

**Examples:**
```bash
/queue add "refactor database layer"
/queue "add unit tests for user service"
```

### `/queue insert` Command

**Usage:** `/queue insert <index> <prompt text>`

**Description:** Inserts a prompt at a specific 1-based position in the queue. Existing items shift down, and the index is clamped to the queue bounds.

**Examples:**
```bash
/queue insert 1 "add tests for login"
/queue insert 3 "refactor database layer"
```

### `/queue list` Command

**Usage:** `/queue list`

**Description:** Lists all queued prompts with their position and queue time.

### `/queue remove` Command

**Usage:** `/queue remove <index>`, `/queue remove *`

**Description:** Removes the prompt at the given 1-based position, or clears the entire queue when `*` is used.

### `/queue run` Command

**Usage:** `/queue run`

**Description:** Processes every queued prompt immediately, in FIFO order. This is mainly useful to resume a queue that was paused by an interruption.

**Examples:**
```bash
/queue run
```


> **Tip:** You can easily re-send commands or messages. Use the up arrow ⬆ to scroll back or CONTROL-R to search your message history.


## Non-TUI Related Notes

### Multi-line Chat Messages

You can send long, multi-line messages in the chat in a few ways:
  - Paste a multi-line message directly into the chat.
  - Enter `{` alone on the first line to start a multiline message and `}` alone on the last line to end it.
    - Or, start with `{tag` (where "tag" is any sequence of letters/numbers) and end with `tag}`. This is useful when you need to include closing braces `}` in your message.
  - Use Meta-ENTER to start a new line without sending the message (Esc+ENTER in some environments).
  - Use `/paste` to paste text from the clipboard into the chat.
  - Use the `/editor` command (or press `Ctrl-X Ctrl-E` if your terminal allows) to open your editor to create the next chat message. See [editor configuration docs](../config/editor.html) for more info.
  - Use multiline-mode, which swaps the function of Meta-Enter and Enter, so that Enter inserts a newline, and Meta-Enter submits your command. To enable multiline mode:
    - Use the `/multiline-mode` command to toggle it during a session.
    - Use the `--multiline` switch.
  
Example with a tag:
```
{python
def hello():
    print("Hello}")  # Note: contains a brace
python}
```

### Key Bindings

The interactive prompt is built with [prompt-toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) which provides emacs and vi keybindings. 

#### Emacs

- `Up Arrow` : Move up one line in the current message.
- `Down Arrow` : Move down one line in the current message.
- `Ctrl-Up` : Scroll back through previously sent messages.
- `Ctrl-Down` : Scroll forward through previously sent messages.
- `Ctrl-A` : Move cursor to the start of the line.
- `Ctrl-B` : Move cursor back one character.
- `Ctrl-D` : Delete the character under the cursor.
- `Ctrl-E` : Move cursor to the end of the line.
- `Ctrl-F` : Move cursor forward one character.
- `Ctrl-K` : Delete from the cursor to the end of the line.
- `Ctrl-L` : Clear the screen.
- `Ctrl-N` : Move down to the next history entry.
- `Ctrl-P` : Move up to the previous history entry.
- `Ctrl-R` : Reverse search in command history.
- `Ctrl-X Ctrl-E` : Open the current input in an external editor
- `Ctrl-Y` : Paste (yank) text that was previously cut.

#### Vi

To use vi/vim keybindings, run cecli with the `--vim` switch.

- `Up Arrow` : Move up one line in the current message.
- `Down Arrow` : Move down one line in the current message.
- `Ctrl-Up` : Scroll back through previously sent messages.
- `Ctrl-Down` : Scroll forward through previously sent messages.
- `Esc` : Switch to command mode.
- `i` : Switch to insert mode.
- `a` : Move cursor one character to the right and switch to insert mode.
- `A` : Move cursor to the end of the line and switch to insert mode.
- `I` : Move cursor to the beginning of the line and switch to insert mode.
- `h` : Move cursor one character to the left.
- `j` : Move cursor down one line.
- `k` : Move cursor up one line.
- `l` : Move cursor one character to the right.
- `w` : Move cursor forward one word.
- `b` : Move cursor backward one word.
- `0` : Move cursor to the beginning of the line.
- `$` : Move cursor to the end of the line.
- `x` : Delete the character under the cursor.
- `dd` : Delete the current line.
- `u` : Undo the last change.
- `Ctrl-R` : Redo the last undone change.
