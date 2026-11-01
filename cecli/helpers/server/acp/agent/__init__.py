"""``cecli --acp``: cecli as an Agent Client Protocol (ACP) v1 agent.

ACP clients such as Zed launch cecli as a subprocess and drive it with
newline-delimited JSON-RPC 2.0 on stdin/stdout:
https://agentclientprotocol.com/protocol/v1/schema

- ``agent``: AcpAgent, which answers the client and runs each prompt as a turn
- ``transport``: the channel to the client (stdio)
- ``io``: AcpInputOutput, which routes cecli's input and output through the agent
- ``updates``: cecli's output as ``session/update`` notifications
- ``config``: the mode, model and effort pickers
- ``mcp``: MCP servers passed by the client

The WebSocket bridge in the parent package is a separate feature, which streams
cecli's events to dashboards.
"""

from __future__ import annotations

from cecli.helpers.server.acp.agent.agent import AcpAgent
from cecli.helpers.server.acp.agent.transport import StdioTransport

_agent: AcpAgent | None = None


def get_agent() -> AcpAgent:
    global _agent
    if _agent is None:
        _agent = AcpAgent(StdioTransport())
    return _agent
