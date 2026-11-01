---
parent: Configuration
nav_order: 43
description: Use cecli as an agent inside editors that speak the Agent Client Protocol, such as Zed.
---

# Editor integration (ACP)

`cecli --acp` runs cecli as an [Agent Client Protocol](https://agentclientprotocol.com) agent.
The editor launches cecli as a subprocess and talks to it with JSON-RPC over stdin/stdout
(ACP v1), so cecli's chat, tool calls and confirmations show up in the editor's agent panel.

This is separate from the WebSocket server described in [ACP over WebSocket](api.html), which
streams events to custom dashboards.

## Zed

Add cecli to `agent_servers` in Zed's `settings.json`:

```json
{
  "agent_servers": {
    "cecli": {
      "type": "custom",
      "command": "cecli",
      "args": ["--acp"],
      "env": {}
    }
  }
}
```

Then start a new thread with cecli from the agent panel. cecli reads your usual configuration
(`~/.cecli/conf.yml`, `.cecli.conf.yml`, `.env`), so the model and API keys are the same as on
the command line. Any other flags can go in `args`, for example `["--acp", "--model", "sonnet"]`.
`--acp` itself has to be on the command line: it is ignored in config files and `CECLI_ACP`.

Use `dev: open acp logs` from the command palette to see the messages exchanged with cecli.
cecli's own diagnostics go to stderr.

## How cecli maps onto ACP

- **Prompts** are handled exactly like terminal input, so slash commands work (`/add`, `/ask`,
  `/model`, ...) and are offered as completions in the editor.
- **@-mentioned files** are added to the chat. Files outside the project are added read-only.
- **Model output** streams as messages; reasoning streams as thoughts.
- **Tool calls** in agent mode appear as tool cards with their output. The todo list is shown as
  the editor's plan, and the final `Yield` summary is shown as a message.
- **Confirmations** ("Run tools?", "Add file to the chat?", shell commands) become permission
  requests. "Yes to all" lasts for the rest of the session, just as in the terminal.
  `--yes-always` skips them.
- **Cancel** interrupts the running request.
- **MCP servers** configured in the editor (Zed's context servers) are passed to cecli, which
  connects them alongside its own MCP servers before the session starts. stdio, HTTP and SSE
  servers are supported. If cecli already has a server with the same name, cecli's wins.
- **Shell commands** run without a pager (`PAGER` and `GIT_PAGER` are set to `cat`), since no
  one can press a key to page through their output.
- cecli's own status lines (commits, lint results) appear in monospace blocks. The per-request
  token and cost line is left out, but it is still written to the chat history file.

## Mode, model and effort pickers

cecli offers three pickers next to the editor's prompt box. Choosing a value runs the matching
command, so it behaves exactly as if you had typed it, and typing the command updates the picker.

- **Mode**: code, ask, architect, context or agent (`/code`, `/ask`, ...), plus **Agent (YOLO)**:
  agent mode with what `--yolo` turns on, so tools and shell commands run without asking (the
  cost limit still asks). Choosing any other mode, or typing a command that leaves agent mode,
  brings the confirmations back. Launched with `--yolo`, agent mode shows as Agent (YOLO).
- **Model**: the model that answers in the current mode. In agent mode that is the agent model
  (`/agent-model`); otherwise it is the main model (`/model`). The list starts with the models
  you configured (the startup `--model`, your `alias` entries, model tag overrides, and models in
  `.cecli.model.settings.yml`), followed by the chat models of every provider whose API key is
  set, grouped by provider. Any other model can still be chosen by typing `/model`.
- **Effort**: reasoning effort (`/reasoning-effort`) or thinking budget (`/think-tokens`),
  whichever the current model accepts. It is hidden for models that accept neither.

A key for a large provider such as OpenRouter adds hundreds of models. To list only some of
them, set `acp-models` to patterns, matched the way `/models` matches its search: a plain word
matches anywhere in the name, and `*` and `?` work as wildcards. Your configured models are
always listed. Aliases give your favorite models short names at the top of the list. For
example, in `.cecli.conf.yml`:

```yaml
acp-models:
  - "claude-sonnet"
  - "gpt-5*"
alias:
  - "fast:gemini/gemini-2.5-flash"
  - "smart:anthropic/claude-sonnet-4-5"
```

## Sub-agents

When cecli delegates work to sub-agents (the `Delegate` tool, workspace and workflow agents),
editors that support ACP subagent sessions show each sub-agent as its own session under the
thread. Its messages, tool calls and permission requests appear there instead of in the main
thread, along with whether it is working, waiting for you or idle. The task it was given and the
result it sent back show as messages between the two sessions.

Each sub-agent can be stopped on its own, and the agent that delegated carries on with the
interrupted result. Cancelling the main thread also stops the sub-agents it is waiting for;
sub-agents working in the background keep going.

Subagent sessions are an unstable part of ACP, so this only happens with editors that advertise
the `subagents` client capability. With other editors, sub-agent output appears in the main
thread, and a sub-agent still working after the main thread's turn has ended can't ask for
permission: those confirmations are declined.

## Limitations

- One process serves one project: the directory of the first session. New threads on the same
  project reuse the process and start with a cleared chat; earlier threads can't be continued.
- Sessions can't be reloaded from the editor's history.
- A change to an editor MCP server's settings takes effect after restarting the agent.
- Questions that need free-form answers take their default, and confirmations asked during
  startup (before any prompt) are declined.
