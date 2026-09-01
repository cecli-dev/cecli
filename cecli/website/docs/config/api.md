---
parent: Configuration
nav_order: 42
description: Pseudo-ACP (Agent Client Protocol) WebSocket API for connecting external tools and UIs to cecli's event stream.
---

# Agent Client Protocol (ACP)

Cecli includes an optional WebSocket server that broadcasts real-time events and accepts input from external clients. This enables custom UIs, dashboards, and integrations to observe and interact with cecli sessions programmatically.

The server implements a **pseudo-ACP (Agent Client Protocol)** JSON-RPC 2.0 interface. All events (tool calls, streaming, state changes, usage, etc.) are broadcast as `session/update` notifications matching the ACP v2 spec.

> **Reference:** [ACP v2 — Tool Invocation & Status Reporting](
>   https://agentclientprotocol.com/protocol/v2/prompt-lifecycle#5-tool-invocation-and-status-reporting
> )
> The cecli implementation is pseudo-ACP: it follows the general shape of ACP session/update notifications but may not cover every edge case of the formal specification.

## Activation

The server is controlled by the `--server-config` flag, which accepts a JSON or YAML string with the following fields:

```
cecli --server-config '{"host": "127.0.0.1", "port": 23254}'
```

| Field | Default | Description |
|-------|---------|-------------|
| `port` | `23254` | Port to listen on. Set to `0` to disable the server. |
| `host` | `127.0.0.1` | Host interface to bind to. |
| `headless` | `false` | Run TUI in headless mode (no terminal UI, server mode). |

You can also set it via your config file:

```yaml
# ~/.cecli/config.yml
server-config:
  port: 23254
  host: "127.0.0.1"
  headless: false
```


## Connecting

Point any WebSocket client to `ws://{host}:{port}`:

```bash
# Example with websocat
websocat ws://127.0.0.1:23254
```

## Server → Client Notifications (ACP JSON-RPC)

Core agent lifecycle events are broadcast as **JSON-RPC 2.0 notifications** with method `session/update`. The envelope looks like:

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "<coder-uuid>",
    "update": { ... }
  }
}
```

The `update` object contains a `sessionUpdate` discriminator field that identifies the specific update type:

### State Updates

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "<coder-uuid>",
    "update": {
      "sessionUpdate": "state_update",
      "state": "running"
    }
  }
}
```

| `state` value | Trigger |
|---------------|--------|
| `"running"` | Agent starts responding (`start_response` signal) |
| `"idle"` | Error occurs (`error` signal), with `stopReason: "refusal"` |

### Streaming Agent Messages

**Thought chunks** (reasoning / thinking content):

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "<coder-uuid>",
    "update": {
      "sessionUpdate": "agent_thought_chunk",
      "messageId": "<xxhash>",
      "content": {
        "type": "text",
        "text": "..."
      }
    }
  }
}
```

**Message chunks** (final assistant response text):

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "<coder-uuid>",
    "update": {
      "sessionUpdate": "agent_message_chunk",
      "messageId": "<xxhash>",
      "content": {
        "type": "text",
        "text": "..."
      }
    }
  }
}
```

The bridge classifies each `stream_chunk` signal as "thought", "message", or "mixed" by detecting `---------` (REASONING_START) / `----` (REASONING_END) markers in the text.

### Tool Call Updates

**Tool call started** (status `"in_progress"`):

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "<coder-uuid>",
    "update": {
      "sessionUpdate": "tool_call_update",
      "toolCallId": "<xxhash>",
      "status": "in_progress",
      "title": "ReadFile(api.md)",
      "kind": "read"
    }
  }
}
```

| `kind` value | Detected from |
|--------------|--------------|
| `"read"` | Tool call contains `read`, `view`, `list`, `grep`, `search` |
| `"write"` | Tool call contains `write`, `edit`, `create`, `replace`, `delete` |
| `"command"` | Tool call contains `bash`, `run`, `execute`, `command` |
| `"other"` | Fallback |

**Tool call content streaming** (one or more chunks):

```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "<coder-uuid>",
    "update": {
      "sessionUpdate": "tool_call_content_chunk",
      "toolCallId": "<xxhash>",
      "content": {
        "type": "text",
        "text": "..."
      }
    }
  }
}
```

> **Note:** The ACP bridge currently sends `content_chunk` updates for every
> tool result signal, but does **not** send a terminal `completed` status.
> Completion detection is left to the client (e.g., when a new tool call or
> message chunk arrives).



## Client → Server Messages (ACP JSON-RPC)

Clients send **JSON-RPC 2.0 requests** for session lifecycle operations. Each request expects a JSON-RPC response from the server.

### Initialize

Before using the session, clients should send an `initialize` request:

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": 2,
    "capabilities": {
      "session": {}
    },
    "info": {
      "name": "cecli",
      "title": "CECLI Coding Agent",
      "version": "2.0.0"
    },
    "authMethods": []
  }
}
```

### Session Lifecycle

**Create a new session** (or reuse an existing coder UUID):

```json
{"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {}}
```

Response:

```json
{"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "<coder-uuid>"}}
```

**List active sessions:**

```json
{"jsonrpc": "2.0", "id": 3, "method": "session/list", "params": {}}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "sessions": [
      {
        "sessionId": "<uuid>",
        "cwd": "/path",
        "status": "active",
        "_meta": {}
      }
    ],
    "_meta": {}
  }
}
```

**Send a prompt (chat message):**

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "session/prompt",
  "params": {
    "sessionId": "<coder-uuid>",
    "prompt": [
      {
        "type": "text",
        "text": "your message"
      }
    ]
  }
}
```

Response (immediate acknowledgment):

```json
{"jsonrpc": "2.0", "id": 4, "result": {}}
```

The server then:
1. Echoes a `user_message` notification (see Server → Client Notifications above)
2. Routes the text to the coder input queue for processing

**Cancel a session:**

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "session/cancel",
  "params": {
    "sessionId": "<coder-uuid>"
  }
}
```

Returns a `state_update(idle, stopReason=cancelled)` notification.

**Close a session:**

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "session/close",
  "params": {
    "sessionId": "<coder-uuid>"
  }
}
```

Response: `{"jsonrpc": "2.0", "id": 6, "result": {}}`



## Example

Using a simple Python script to listen for JSON-RPC notifications and send prompts:

```python
import asyncio
import json
from websockets.asyncio.client import connect

async def listen():
    async with connect("ws://127.0.0.1:23254") as ws:
        # Initialize the session
        init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        await ws.send(json.dumps(init_req))
        resp = json.loads(await ws.recv())
        print(f"Initialized: {resp['result']['info']['title']}")

        # Create a new session
        new_req = {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {}}
        await ws.send(json.dumps(new_req))
        resp = json.loads(await ws.recv())
        session_id = resp["result"]["sessionId"]
        print(f"Session: {session_id}")

        # Listen for events (notifications won't have an "id" field)
        async for msg in ws:
            data = json.loads(msg)
            if "method" in data and data["method"] == "session/update":
                update = data["params"]["update"]
                update_type = update["sessionUpdate"]
                if update_type == "agent_message_chunk":
                    print(update["content"]["text"], end="", flush=True)
                elif update_type == "agent_thought_chunk":
                    print(f"[THOUGHT] {update['content']['text']}")
                elif update_type == "tool_call_update":
                    print(f"\n[TOOL] {update['title']} ({update['status']})")
                elif update_type == "tool_call_content_chunk":
                    print(update["content"]["text"], end="", flush=True)
                elif update_type == "state_update":
                    print(f"\n[STATE] {update['state']}")

asyncio.run(listen())
```
