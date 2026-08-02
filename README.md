## Why `cecli`?

`cecli` (probably pronounced like "Cecily") is yet another cli agent crafted for extensibility and customization. Originally a fork of the [Aider](https://cecli.dev/) AI pair programming tool, we aim to make agentic coding as maximally effective as it can be based on the incredible capabilities of large language models.


### Links

[Documentation](https://cecli.dev/docs/)
[Discord Chat](https://discord.gg/AX9ZEA7nJn)
[Issue Queue](https://github.com/cecli-dev/cecli/issues)


## Installation Instructions
All installation methods export a `cecli` command that can start the application. This project can be installed using several methods:

#### Linux & Mac

Use curl to download the script and execute it with sh:

```bash
curl -LsSf https://cecli.dev/install.sh | sh
```

If your system does not have curl, you can use wget:

```bash
wget -qO- https://cecli.dev/install.sh | sh
```

#### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://cecli.dev/install.ps1 | iex"
```

### Package Installation

```bash
uv pip install --native-tls cecli-dev
```

or

```bash
pip install cecli-dev
```

### Tool Installation
```bash
uv tool install --native-tls --python python3.12 cecli-dev
```

Use the tool installation so cecli doesn't interfere with your development environment.

## Prompt Queue Management

The `cecli` CLI includes a prompt queueing feature (`CLI-33`) that allows users to manage multiple prompts in a first-in-first-out (FIFO) in-memory queue. The queue is tied to the user's CLI session and does not persist across restarts.

### Queue Lifecycle

1. **Enqueue**: `/queue <prompt>` adds a prompt to the queue.
2. **List**: `/list-queue` displays all queued prompts with index numbers and timestamps.
3. **Remove**: `/remove-queue [index|*]` removes a specific item by index, clears the entire queue with `*`, or provides interactive selection when called with no arguments.
4. **Auto-Process**: After the current command completes and the system is idle (`cmd_running_event` is set), queued prompts are processed sequentially in FIFO order.

### Commands

- `/queue <prompt text>` — Adds a prompt to the queue. Confirms with the queue position.
- `/list-queue` — Displays a numbered list of queued prompts (`[index] text (timestamp)`). Shows "Queue is empty" when appropriate.
- `/remove-queue <index>` — Removes the prompt at the given 0-based index.
- `/remove-queue *` — Clears the entire queue.
- `/remove-queue` (no args) — Enters interactive selection mode.

### Queue Limits

- **Max Queue Size**: 100 items (hard limit). New prompts are rejected with a warning when the queue is full.
- **Max Prompt Length**: 10,000 characters per queued item. Prompts exceeding this limit are rejected.
- **In-Memory Only**: The queue is stored on the `Commands` instance (`cecli/commands/core.py`) and is lost when the CLI session restarts.

### Queue Processing Integration

Queue processing is triggered in the `finally` block of `Commands.execute()` after `cmd_running_event.set()`. Management commands (`queue`, `list-queue`, `remove-queue`) are excluded from triggering auto-processing to prevent unexpected behavior. A `_processing_queue` boolean flag prevents infinite recursion if a queued prompt itself queues another item.

### Example Workflow

```bash
# Queue multiple prompts
/queue "refactor database layer"
/queue "add unit tests for user service"

# View queued prompts
/list-queue
# Output: [1] refactor database layer (2026-08-01 10:30:00)
#         [2] add unit tests for user service (2026-08-01 10:30:05)

# Remove a specific queued prompt
/remove-queue 1

# Clear the entire queue
/remove-queue *

# Queued prompts process automatically after the current command completes
```

### Management Command Guard

The management commands (`/queue`, `/list-queue`, `/remove-queue`) must not trigger auto-processing of queued items. Their execution is isolated so that the current prompt continues uninterrupted. When any of these commands is entered while another prompt is being processed, they execute immediately without clearing `cmd_running_event` or steering the ongoing command.

### Thread Safety

The queue uses a single-threaded async event loop. List operations on `prompt_queue` are naturally safe within the async loop. An `asyncio.Lock` (`_queue_lock`) protects all read and write operations to ensure atomic updates.

The prompt queueing feature enhances the user experience by providing robust prompt management capabilities, increasing efficiency, and preventing interruptions during ongoing tasks.

The documentation above contains the full set of allowed configuration options
but I highly recommend using an `.cecli.conf.yml` file. A good place to get started is:

```yaml
model: <model of your choice>
agent: true
auto-commits: true
auto-save: true
cache-prompts: true
check-update: true
enable-context-compaction: true
context-compaction-max-tokens: 0.8
show-model-warnings: true

agent-config:
  large_file_token_threshold: 8192
  skip_cli_confirmations: false

mcp-servers:
  mcpServers:
    context7:
      transport: http
      url: https://mcp.context7.com/mcp
```

Use the adjacent .cecli.env file to store model api keys as environment variables, e.g:

```
ANTHROPIC_API_KEY="..."
GEMINI_API_KEY="..."
OPENAI_API_KEY="..."
OPENROUTER_API_KEY="..."
DEEPSEEK_API_KEY="..."
```

### Run Program

If you are in the directory with your .cecli.conf.yml file, then simply running `cecli` will start the agent with your configuration. For best results, since terminal emulators can be finicky, we highly suggest running:

```bash
cecli --terminal-setup
```

On first run to configure keybindings for the program (notably `shift+enter`). Support for terminals is ongoing so feel free to make a github issue or chat in the discord for us to figure out what's needed to support automatically setting up a given terminal.

If you want additional sandboxing, we publish a docker container that can be ran as follows:

```bash
docker pull dustinwashington/cecli
docker run \
  -it \
  --user $(id -u):$(id -g) \
  --volume $(pwd):/app \
  --volume $(pwd)/.cecli.conf.yml:/.cecli.conf.yml \
  --volume $(pwd)/.cecli.env:/.cecli.env \
  dustinwashington/cecli \
  --config /.cecli.conf.yml
  --env-file /.cecli.env
```

This command will make sure all commands ran by the coding agent happen in context of the docker container to protect the host file system from any infamous agentic mishap

## Documentation/Other Notes:

* [Agent Mode](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/agent-mode.md)
* [MCP Configuration](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/mcp.md)
* [TUI Configuration](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/tui.md)
* [Skills](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/skills.md)
* [Subagents](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/subagents.md)
* [Session Management](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/sessions.md)
* [Hooks](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/hooks.md)
* [Workspaces](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/workspaces.md)
* [Custom Commands](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/custom-commands.md)
* [Custom System Prompts](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/custom-system-prompts.md)
* [Custom Tools](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/agent-mode.md#creating-custom-tools)
* [Advanced Model Configuration](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/model-aliases.md#advanced-model-settings)
* [Additional Documentation](https://cecli.dev/)

* [Agent Mode](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/agent-mode.md)
* [MCP Configuration](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/mcp.md)
* [TUI Configuration](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/tui.md)
* [Skills](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/skills.md)
* [Subagents](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/subagents.md)
* [Session Management](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/sessions.md)
* [Hooks](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/hooks.md)
* [Workspaces](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/workspaces.md)
* [Custom Commands](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/custom-commands.md)
* [Custom System Prompts](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/custom-system-prompts.md)
* [Custom Tools](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/agent-mode.md#creating-custom-tools)
* [Advanced Model Configuration](https://github.com/cecli-dev/cecli/blob/main/cecli/website/docs/config/model-aliases.md#advanced-model-settings)
* [Additional Documentation](https://cecli.dev/)

## Project Roadmap/Goals

The current priorities are to improve core capabilities and user experience of the `cecli` project

1. **Base Asynchronicity (cecli coroutine-experiment branch)**
 * [x] Refactor codebase to have the main loop run asynchronously
 * [x] Update test harness to work with new asynchronous methods

2. **Repo Map Accuracy** - [Discussion](https://github.com/cecli-dev/cecli/issues/45)
 * [x] [Bias page ranking toward active/editable files in repo map parsing](https://github.com/Aider-AI/aider/issues/2405)
 * [x] [Include import information in repo map for richer context](https://github.com/Aider-AI/aider/issues/2688)
 * [x] [Handle non-unique symbols that break down in large codebases](https://github.com/Aider-AI/aider/issues/2341)

3. **Context Discovery** - [Discussion](https://github.com/cecli-dev/cecli/issues/46)
 * [ ] Develop AST-based search capabilities
 * [x] Enhance file search with ripgrep integration
 * [ ] Implement RAG (Retrieval-Augmented Generation) for better code retrieval
 * [ ] Build an explicit workflow and local tooling for internal discovery mechanisms

4. **Context Delivery** - [Discussion](https://github.com/cecli-dev/cecli/issues/47)
 * [x] Use workflow for internal discovery to better target file snippets needed for specific tasks (ExploreCode and ReadRange)
 * [x] Add support for partial files and code snippets in model completion messages
 * [x] Update message request structure for optimal caching

5. **TUI Experience** - [Discussion](https://github.com/cecli-dev/cecli/issues/48)
 * [x] Add a full TUI (probably using textual) to have a visual interface competitive with the other coding agent terminal programs
 * [x] Re-integrate pretty output formatting
 * [x] Implement a response area, a prompt area with current auto completion capabilities, and a helper area for managing utility commands

6. **Agent Mode** - [Discussion](https://github.com/cecli-dev/cecli/issues/111)
 * [x] Renaming "navigator mode" to "agent mode" for simplicity
 * [x] Add an explicit "finished" internal tool
 * [x] Add a configuration json setting for agent mode to specify allowed local tools to use, tool call limits, etc.
 * [ ] Add a RAG tool for the model to ask questions about the codebase
 * [x] Make the system prompts more aggressive about removing unneeded files/content from the context
 * [x] Add a plugin-like system for allowing agent mode to use user-defined tools in simple python files
 * [x] Add a dynamic tool discovery tool to allow the system to have only the tools it needs in context

7. **Sub Agents**
 * [x] Add `/invoke-agent` command to manually branch a sub agent and return a summary to the main context
 * [x] Add an instance-able view of the conversation system so sub agents get their own context and workspaces
 * [x] Modify coder classes to have discrete identifiers for themselves/management utilities for them to have their own slices of the world
 * [x] Refactor global files like todo lists to live inside instance folders to avoid state conflicts
 * [x] Add a `Delegate` tool that launches a sub agent as a background command that the parent model waits for to finish
 * [x] Add visibility into active sub agent calls in TUI

8. **Hooks**
 * [x] Add hooks base class for user defined python hooks with an execute method with type and priority settings
 * [x] Add hook manager that can accept user defined files and command line commands
 * [x] Integrate hook manager with coder classes with hooks for `start`, `end`, `on_message`, `end_message`, `pre_tool`, and `post_tool` 

9. **Efficient File Editing**
 * [x] Explore use of hashline file representation for more targeted file editing
 * [x] Assuming viability, update SEARCH part of SEARCH/REPLACE with hashline identification (Done with new edit format)
 * [x] Update agent mode edit tools to work with hashline identification
 * [x] Update internal file diff representation to support hashline propagation

10. **Dynamic Context Management** 
 * [x] Update compaction to use observational memory sub agent calls to generate decision records that are used as the compaction basis
 * [ ] Persist decision records to disk for sessions with some settings for managing lifetimes of such persistence
 * [ ] Integrate RLM to extract information from decision records on disk and other definable notes
 * [ ] Add a "describe" tool that launches a sub agent workflow that populates an RLM call's context with:
   * Current Conversation History
   * Past Decision Records
   * Repo Map Found Files

11. **Quality of Life**
 * [ ] Add hot keys support for running repeatable commands like switching between preferred models
 * [ ] Unified error message logging inside of `.cecli` directory

### All Contributors (Both Cecli and Aider main)

<table>
<tbody>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=paul-gauthier">@paul-gauthier</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=dwash96">@dwash96</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tekacs">@tekacs</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ErichBSchulz">@ErichBSchulz</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ei-grad">@ei-grad</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=joshuavial">@joshuavial</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=chrisnestrud">@chrisnestrud</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=chr15m">@chr15m</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=johbo">@johbo</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=fry69">@fry69</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=quinlanjager">@quinlanjager</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=caseymcc">@caseymcc</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=shladnik">@shladnik</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jamwil">@jamwil</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=itlackey">@itlackey</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tomjuggler">@tomjuggler</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=szmania">@szmania</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=vk4s">@vk4s</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=titusz">@titusz</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=bphd">@bphd</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=daniel-vainsencher">@daniel-vainsencher</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=1broseidon">@1broseidon</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=akaihola">@akaihola</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jalammar">@jalammar</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=schpet">@schpet</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=iamFIREcracker">@iamFIREcracker</a></td>
<td>JV</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=KennyDizi">@KennyDizi</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ivanfioravanti">@ivanfioravanti</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mdeweerd">@mdeweerd</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=itsmeknt">@itsmeknt</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=fahmad91">@fahmad91</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cheahjs">@cheahjs</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=youknow04">@youknow04</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=pjcreath">@pjcreath</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=pcamp">@pcamp</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=miradnanali">@miradnanali</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=o-nix">@o-nix</a></td>
<td>Jonathan Ellis</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=codeofdusk">@codeofdusk</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=claui">@claui</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jpshackelford">@jpshackelford</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Taik">@Taik</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Hambaobao">@Hambaobao</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=therealmarv">@therealmarv</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=muravvv">@muravvv</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=hypn4">@hypn4</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gmoz22">@gmoz22</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=contributor">@contributor</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ctoth">@ctoth</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=thehunmonkgroup">@thehunmonkgroup</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gcp">@gcp</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=sentienthouseplant">@sentienthouseplant</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ktakayama">@ktakayama</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=lreeves">@lreeves</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=nims11">@nims11</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=preynal">@preynal</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tgbender">@tgbender</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=apaz-cli">@apaz-cli</a></td>
<td>Alexander Kjeldaas</td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=zhyu">@zhyu</a></td>
<td>Yutaka Matsubara</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=burnettk">@burnettk</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cryptekbits">@cryptekbits</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=deansher">@deansher</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=kennyfrc">@kennyfrc</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=lentil32">@lentil32</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=malkoG">@malkoG</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mubashir1osmani">@mubashir1osmani</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=TimPut">@TimPut</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=zjy1412">@zjy1412</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=savioursho">@savioursho</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jayeshthk">@jayeshthk</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=susliko">@susliko</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=FeepingCreature">@FeepingCreature</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=misteral">@misteral</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=aelaguiz">@aelaguiz</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=DhirajBhakta">@DhirajBhakta</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gopar">@gopar</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=eltociear">@eltociear</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tao12345666333">@tao12345666333</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jpshack-at-palomar">@jpshack-at-palomar</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=smh">@smh</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=nhs000">@nhs000</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=sannysanoff">@sannysanoff</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ryanfreckleton">@ryanfreckleton</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mbokinala">@mbokinala</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=yamitzky">@yamitzky</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mobyvb">@mobyvb</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ozapinq">@ozapinq</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=nicolasperez19">@nicolasperez19</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=varchasgopalaswamy">@varchasgopalaswamy</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ffluk3">@ffluk3</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tanavamsikrishna">@tanavamsikrishna</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tylersatre">@tylersatre</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=pcgeek86">@pcgeek86</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tamirzb">@tamirzb</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=taha-yassine">@taha-yassine</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=strayer">@strayer</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=StevenTCramer">@StevenTCramer</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Skountz">@Skountz</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=sestrella">@sestrella</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=rnevius">@rnevius</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=holoskii">@holoskii</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Netzvamp">@Netzvamp</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=peterhadlaw">@peterhadlaw</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=pauldw">@pauldw</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=paulmaunders">@paulmaunders</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=omri123">@omri123</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=MatthewZMD">@MatthewZMD</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mbailey">@mbailey</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=golergka">@golergka</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=matfat55">@matfat55</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mtofano">@mtofano</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=maledorak">@maledorak</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mlang">@mlang</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=marcomayer">@marcomayer</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=you-n-g">@you-n-g</a></td>
<td>wangboxue</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=rti">@rti</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=prmbiy">@prmbiy</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=omarcinkonis">@omarcinkonis</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Oct4Pie">@Oct4Pie</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mark-asymbl">@mark-asymbl</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=yazgoo">@yazgoo</a></td>
<td>michal.sliwa</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mdklab">@mdklab</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mario7421">@mario7421</a></td>
</tr>
<tr>
<td>liam.liu</td>
<td>kwmiebach</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=kAIto47802">@kAIto47802</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jvmncs">@jvmncs</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=hydai">@hydai</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=hstoklosa">@hstoklosa</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gordonlukch">@gordonlukch</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=develmusa">@develmusa</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=coredevorg">@coredevorg</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cantalupo555">@cantalupo555</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=caetanominuzzo">@caetanominuzzo</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=yzx9">@yzx9</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=zackees">@zackees</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=wietsevenema">@wietsevenema</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=krewenki">@krewenki</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=vinnymac">@vinnymac</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=szepeviktor">@szepeviktor</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=lattwood">@lattwood</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=spdustin">@spdustin</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=henderkes">@henderkes</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=daysm">@daysm</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=devriesd">@devriesd</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=daniel-sc">@daniel-sc</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=damms005">@damms005</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=curran">@curran</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cclauss">@cclauss</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cjoach">@cjoach</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=csala">@csala</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=bexelbie">@bexelbie</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=branchv">@branchv</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=bkowalik">@bkowalik</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=h0x91b">@h0x91b</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=aroffe99">@aroffe99</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=banjo">@banjo</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=anjor">@anjor</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=andreypopp">@andreypopp</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ivnvxd">@ivnvxd</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=andreakeesys">@andreakeesys</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ameramayreh">@ameramayreh</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=a1ooha">@a1ooha</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=maliayas">@maliayas</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=akirak">@akirak</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=adrianlzt">@adrianlzt</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=codefromthecrypt">@codefromthecrypt</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=aweis89">@aweis89</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=aj47">@aj47</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=noitcudni">@noitcudni</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=solatis">@solatis</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=webkonstantin">@webkonstantin</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=khulnasoft-bot">@khulnasoft-bot</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=KebobZ">@KebobZ</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=acro5piano">@acro5piano</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=josx">@josx</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=joshvera">@joshvera</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jklina">@jklina</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jkeys089">@jkeys089</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=johanvts">@johanvts</a></td>
<td>Jim White</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gengjiawen">@gengjiawen</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jevon">@jevon</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jesstelford">@jesstelford</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=JeongJuhyeon">@JeongJuhyeon</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jackhallam">@jackhallam</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Mushoz">@Mushoz</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=zestysoft">@zestysoft</a></td>
<td>Henry Fraser</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gwpl">@gwpl</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=garrett-hopper">@garrett-hopper</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=filiptrplan">@filiptrplan</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=FelixLisczyk">@FelixLisczyk</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=evnoj">@evnoj</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=erykwieliczko">@erykwieliczko</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=elohmeier">@elohmeier</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=emmanuel-ferdman">@emmanuel-ferdman</a></td>
<td></td>
<td></td>
</tr>
</tbody>
</table>

The current priorities are to improve core capabilities and user experience of the `cecli` project

1. **Base Asynchronicity (cecli coroutine-experiment branch)**
  * [x] Refactor codebase to have the main loop run asynchronously
  * [x] Update test harness to work with new asynchronous methods

2. **Repo Map Accuracy** - [Discussion](https://github.com/cecli-dev/cecli/issues/45)
  * [x] [Bias page ranking toward active/editable files in repo map parsing](https://github.com/Aider-AI/aider/issues/2405)
  * [x] [Include import information in repo map for richer context](https://github.com/Aider-AI/aider/issues/2688)
  * [x] [Handle non-unique symbols that break down in large codebases](https://github.com/Aider-AI/aider/issues/2341)

3. **Context Discovery** - [Discussion](https://github.com/cecli-dev/cecli/issues/46)
  * [ ] Develop AST-based search capabilities
  * [x] Enhance file search with ripgrep integration
  * [ ] Implement RAG (Retrieval-Augmented Generation) for better code retrieval
  * [ ] Build an explicit workflow and local tooling for internal discovery mechanisms

4. **Context Delivery** - [Discussion](https://github.com/cecli-dev/cecli/issues/47)
  * [x] Use workflow for internal discovery to better target file snippets needed for specific tasks (ExploreCode and ReadRange)
  * [x] Add support for partial files and code snippets in model completion messages
  * [x] Update message request structure for optimal caching

5. **TUI Experience** - [Discussion](https://github.com/cecli-dev/cecli/issues/48)
  * [x] Add a full TUI (probably using textual) to have a visual interface competitive with the other coding agent terminal programs
  * [x] Re-integrate pretty output formatting
  * [x] Implement a response area, a prompt area with current auto completion capabilities, and a helper area for managing utility commands

6. **Agent Mode** - [Discussion](https://github.com/cecli-dev/cecli/issues/111)
  * [x] Renaming "navigator mode" to "agent mode" for simplicity
  * [x] Add an explicit "finished" internal tool
  * [x] Add a configuration json setting for agent mode to specify allowed local tools to use, tool call limits, etc.
  * [ ] Add a RAG tool for the model to ask questions about the codebase
  * [x] Make the system prompts more aggressive about removing unneeded files/content from the context
  * [x] Add a plugin-like system for allowing agent mode to use user-defined tools in simple python files
  * [x] Add a dynamic tool discovery tool to allow the system to have only the tools it needs in context

7. **Sub Agents**
  * [x] Add `/invoke-agent` command to manually branch a sub agent and return a summary to the main context
  * [x] Add an instance-able view of the conversation system so sub agents get their own context and workspaces
  * [x] Modify coder classes to have discrete identifiers for themselves/management utilities for them to have their own slices of the world
  * [x] Refactor global files like todo lists to live inside instance folders to avoid state conflicts
  * [x] Add a `Delegate` tool that launches a sub agent as a background command that the parent model waits for to finish
  * [x] Add visibility into active sub agent calls in TUI

8. **Hooks**
  * [x] Add hooks base class for user defined python hooks with an execute method with type and priority settings
  * [x] Add hook manager that can accept user defined files and command line commands
  * [x] Integrate hook manager with coder classes with hooks for `start`, `end`, `on_message`, `end_message`, `pre_tool`, and `post_tool` 

9. **Efficient File Editing**
  * [x] Explore use of hashline file representation for more targeted file editing
  * [x] Assuming viability, update SEARCH part of SEARCH/REPLACE with hashline identification (Done with new edit format)
  * [x] Update agent mode edit tools to work with hashline identification
  * [x] Update internal file diff representation to support hashline propagation

10. **Dynamic Context Management** 
  * [x] Update compaction to use observational memory sub agent calls to generate decision records that are used as the compaction basis
  * [ ] Persist decision records to disk for sessions with some settings for managing lifetimes of such persistence
  * [ ] Integrate RLM to extract information from decision records on disk and other definable notes
  * [ ] Add a "describe" tool that launches a sub agent workflow that populates an RLM call's context with:
    * Current Conversation History
    * Past Decision Records
    * Repo Map Found Files

11. **Quality of Life**
  * [ ] Add hot keys support for running repeatable commands like switching between preferred models
  * [ ] Unified error message logging inside of `.cecli` directory

### All Contributors (Both Cecli and Aider main)

<table>
<tbody>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=paul-gauthier">@paul-gauthier</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=dwash96">@dwash96</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tekacs">@tekacs</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ErichBSchulz">@ErichBSchulz</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ei-grad">@ei-grad</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=joshuavial">@joshuavial</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=chrisnestrud">@chrisnestrud</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=chr15m">@chr15m</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=johbo">@johbo</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=fry69">@fry69</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=quinlanjager">@quinlanjager</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=caseymcc">@caseymcc</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=shladnik">@shladnik</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jamwil">@jamwil</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=itlackey">@itlackey</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tomjuggler">@tomjuggler</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=szmania">@szmania</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=vk4s">@vk4s</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=titusz">@titusz</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=bphd">@bphd</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=daniel-vainsencher">@daniel-vainsencher</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=1broseidon">@1broseidon</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=akaihola">@akaihola</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jalammar">@jalammar</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=schpet">@schpet</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=iamFIREcracker">@iamFIREcracker</a></td>
<td>JV</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=KennyDizi">@KennyDizi</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ivanfioravanti">@ivanfioravanti</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mdeweerd">@mdeweerd</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=itsmeknt">@itsmeknt</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=fahmad91">@fahmad91</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cheahjs">@cheahjs</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=youknow04">@youknow04</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=pjcreath">@pjcreath</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=pcamp">@pcamp</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=miradnanali">@miradnanali</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=o-nix">@o-nix</a></td>
<td>Jonathan Ellis</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=codeofdusk">@codeofdusk</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=claui">@claui</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jpshackelford">@jpshackelford</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Taik">@Taik</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Hambaobao">@Hambaobao</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=therealmarv">@therealmarv</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=muravvv">@muravvv</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=hypn4">@hypn4</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gmoz22">@gmoz22</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=contributor">@contributor</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ctoth">@ctoth</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=thehunmonkgroup">@thehunmonkgroup</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gcp">@gcp</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=sentienthouseplant">@sentienthouseplant</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ktakayama">@ktakayama</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=lreeves">@lreeves</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=nims11">@nims11</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=preynal">@preynal</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tgbender">@tgbender</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=apaz-cli">@apaz-cli</a></td>
<td>Alexander Kjeldaas</td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=zhyu">@zhyu</a></td>
<td>Yutaka Matsubara</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=burnettk">@burnettk</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cryptekbits">@cryptekbits</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=deansher">@deansher</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=kennyfrc">@kennyfrc</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=lentil32">@lentil32</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=malkoG">@malkoG</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mubashir1osmani">@mubashir1osmani</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=TimPut">@TimPut</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=zjy1412">@zjy1412</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=savioursho">@savioursho</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jayeshthk">@jayeshthk</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=susliko">@susliko</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=FeepingCreature">@FeepingCreature</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=misteral">@misteral</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=aelaguiz">@aelaguiz</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=DhirajBhakta">@DhirajBhakta</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gopar">@gopar</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=eltociear">@eltociear</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tao12345666333">@tao12345666333</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jpshack-at-palomar">@jpshack-at-palomar</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=smh">@smh</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=nhs000">@nhs000</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=sannysanoff">@sannysanoff</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ryanfreckleton">@ryanfreckleton</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mbokinala">@mbokinala</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=yamitzky">@yamitzky</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mobyvb">@mobyvb</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ozapinq">@ozapinq</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=nicolasperez19">@nicolasperez19</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=varchasgopalaswamy">@varchasgopalaswamy</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ffluk3">@ffluk3</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tanavamsikrishna">@tanavamsikrishna</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tylersatre">@tylersatre</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=pcgeek86">@pcgeek86</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=tamirzb">@tamirzb</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=taha-yassine">@taha-yassine</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=strayer">@strayer</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=StevenTCramer">@StevenTCramer</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Skountz">@Skountz</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=sestrella">@sestrella</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=rnevius">@rnevius</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=holoskii">@holoskii</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Netzvamp">@Netzvamp</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=peterhadlaw">@peterhadlaw</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=pauldw">@pauldw</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=paulmaunders">@paulmaunders</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=omri123">@omri123</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=MatthewZMD">@MatthewZMD</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mbailey">@mbailey</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=golergka">@golergka</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=matfat55">@matfat55</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mtofano">@mtofano</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=maledorak">@maledorak</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mlang">@mlang</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=marcomayer">@marcomayer</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=you-n-g">@you-n-g</a></td>
<td>wangboxue</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=rti">@rti</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=prmbiy">@prmbiy</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=omarcinkonis">@omarcinkonis</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Oct4Pie">@Oct4Pie</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mark-asymbl">@mark-asymbl</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=yazgoo">@yazgoo</a></td>
<td>michal.sliwa</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mdklab">@mdklab</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=mario7421">@mario7421</a></td>
</tr>
<tr>
<td>liam.liu</td>
<td>kwmiebach</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=kAIto47802">@kAIto47802</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jvmncs">@jvmncs</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=hydai">@hydai</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=hstoklosa">@hstoklosa</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gordonlukch">@gordonlukch</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=develmusa">@develmusa</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=coredevorg">@coredevorg</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cantalupo555">@cantalupo555</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=caetanominuzzo">@caetanominuzzo</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=yzx9">@yzx9</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=zackees">@zackees</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=wietsevenema">@wietsevenema</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=krewenki">@krewenki</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=vinnymac">@vinnymac</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=szepeviktor">@szepeviktor</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=lattwood">@lattwood</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=spdustin">@spdustin</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=henderkes">@henderkes</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=daysm">@daysm</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=devriesd">@devriesd</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=daniel-sc">@daniel-sc</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=damms005">@damms005</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=curran">@curran</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cclauss">@cclauss</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=cjoach">@cjoach</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=csala">@csala</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=bexelbie">@bexelbie</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=branchv">@branchv</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=bkowalik">@bkowalik</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=h0x91b">@h0x91b</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=aroffe99">@aroffe99</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=banjo">@banjo</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=anjor">@anjor</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=andreypopp">@andreypopp</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ivnvxd">@ivnvxd</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=andreakeesys">@andreakeesys</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=ameramayreh">@ameramayreh</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=a1ooha">@a1ooha</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=maliayas">@maliayas</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=akirak">@akirak</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=adrianlzt">@adrianlzt</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=codefromthecrypt">@codefromthecrypt</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=aweis89">@aweis89</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=aj47">@aj47</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=noitcudni">@noitcudni</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=solatis">@solatis</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=webkonstantin">@webkonstantin</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=khulnasoft-bot">@khulnasoft-bot</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=KebobZ">@KebobZ</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=acro5piano">@acro5piano</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=josx">@josx</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=joshvera">@joshvera</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jklina">@jklina</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jkeys089">@jkeys089</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=johanvts">@johanvts</a></td>
<td>Jim White</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gengjiawen">@gengjiawen</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jevon">@jevon</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jesstelford">@jesstelford</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=JeongJuhyeon">@JeongJuhyeon</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=jackhallam">@jackhallam</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=Mushoz">@Mushoz</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=zestysoft">@zestysoft</a></td>
<td>Henry Fraser</td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=gwpl">@gwpl</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=garrett-hopper">@garrett-hopper</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=filiptrplan">@filiptrplan</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=FelixLisczyk">@FelixLisczyk</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=evnoj">@evnoj</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=erykwieliczko">@erykwieliczko</a></td>
</tr>
<tr>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=elohmeier">@elohmeier</a></td>
<td><a href="https://github.com/cecli-dev/cecli/commits/main?author=emmanuel-ferdman">@emmanuel-ferdman</a></td>
<td></td>
<td></td>
</tr>
</tbody>
</table>
