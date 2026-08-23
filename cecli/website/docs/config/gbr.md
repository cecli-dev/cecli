---
parent: Configuration
nav_order: 125
description: Pair a phone running Build Remote Agent to a cecli session (gbr/1).
---

# Pair a phone with Build Remote Agent

cecli can keep orchestrating in the terminal while a phone running
**Build Remote Agent** spectates the same desktop session through the
free MIT `gbr-agent`. Phone and PC never open ports to each other.

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
gbr-agent run              # leave running, then start cecli as usual
```

```powershell
# Windows
irm https://grokbuildremote.com/install.ps1 | iex
gbr-agent version
gbr-agent pair
gbr-agent run
```

Phone: open Build Remote Agent → **Scan QR from computer** (or type the
8-char code). **Unpair** in Settings before changing PCs. Force-close is
not enough.

## Attach

After `gbr-agent run`:

- HTTP Bot API: `http://127.0.0.1:8788`
- MCP stdio: see the `gbr` example in [MCP](mcp.md)

```bash
curl -sS http://127.0.0.1:8788/health
curl -sS http://127.0.0.1:8788/v1/sessions
```

Phone is spectator + veto. Orchestration stays in cecli.

Do not commit mailbox keys. Phone **Settings → Bot API** is the only
place the relay key is copied.

## Skill (optional)

cecli loads skills from directories in `skills_paths`. A `gbr/SKILL.md`
can teach agent mode the pair/run/attach loop. See [Skills](skills.md).
