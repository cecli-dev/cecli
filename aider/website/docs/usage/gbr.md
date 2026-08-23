---
title: Pair a phone with Build Remote Agent
parent: Usage
nav_order: 850
description: Spectate an aider session from a phone using Build Remote Agent (gbr/1). Not a replacement for aider --browser.
---

# Pair a phone with Build Remote Agent

Aider can keep running in your terminal (or with `--browser`) while a
phone running **Build Remote Agent** spectates the same desktop
session. Pairing uses the free MIT `gbr-agent`. The phone and PC never
open ports to each other.

This is **not** a replacement for [aider `--browser`](browser.md).
It is a pairing device for a phone you already have in your pocket.

Website: https://grokbuildremote.com/  
Agent: https://github.com/LinespottingOrg/GrokBuildRemote-Agents (MIT)  
Protocol: `gbr/1` · need agent **v0.6.0+**

Independent product by Linespotting AB. Not affiliated with xAI or SpaceX.

## Install + pair

```bash
# macOS / Linux
curl -fsSL https://grokbuildremote.com/install.sh | bash
gbr-agent version          # must print v0.6.0 or newer
gbr-agent pair             # QR in browser + printed 8-char code
gbr-agent run              # leave running, then start aider as usual
```

```powershell
# Windows
irm https://grokbuildremote.com/install.ps1 | iex
gbr-agent version
gbr-agent pair
gbr-agent run
```

Phone: open Build Remote Agent → **Scan QR from computer** (or type the
8-char code). Sessions appear in the app. **Unpair** in Settings before
changing PCs. Force-close is not enough.

## Attach

After `gbr-agent run`:

- HTTP Bot API: `http://127.0.0.1:8788`
- MCP stdio: clone the agent repo and run `node mcp/gbr-mcp/bin/gbr-mcp.js`

```bash
curl -sS http://127.0.0.1:8788/health
curl -sS http://127.0.0.1:8788/v1/sessions
```

Keep aider as the orchestrator. The phone is spectator + veto.

Do not commit mailbox keys. Phone **Settings → Bot API** is the only
place the relay key is copied.
