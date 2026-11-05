# cecli desktop

A local, clean chat interface for [cecli](../README.md). The browser
talks to a tiny Python bridge on localhost, and the bridge talks to a real
`cecli --acp` process over newline-delimited JSON-RPC on stdio. No model SDKs,
and no external assets at runtime. The UI is a Lit single-page app built from
`ui/` with Vite, Tailwind CSS and daisyUI.

```
 browser  <-- HTTP + SSE -->  desktop/server.py  <-- ACP / stdio -->  cecli --acp
```

## Run it

From the repository root:

```bash
python3 desktop/server.py --workspace /path/to/your/project
```

Then open <http://127.0.0.1:8765>. The workspace defaults to the current
directory, and that directory is the project the agent edits. A built UI ships
in `static/`; after changing `ui/`, rebuild it with `cd desktop && npm install &&
npm run ui:build`.

Useful flags:

```bash
python3 desktop/server.py \
  --workspace ~/code/my-app \
  --port 8765 \
  --cecli /home/dwash/cecli/venv/bin/cecli \
  --open
```

`--cecli` falls back to `$CECLI_BIN`, then `cecli` on `PATH`. Anything after
`--` is forwarded to cecli, for example `-- --model gpt-5 --yes`.

> The server binds loopback only unless you pass `--host`. Treat it as a local
> tool: it can run shell commands through the agent in the chosen workspace.
> API calls must be JSON with a trusted `Host`/`Origin`, which blocks cross-site
> and DNS-rebinding requests, but there is still no authentication on the port.

## Tauri desktop app (optional)

`src-tauri/` wraps the same bridge in a Tauri v2 window: the Rust shell starts
`server.py` on a free loopback port, waits for it to answer, loads it in the
system webview, and kills the Python child on exit. The UI, JSON API, and SSE
stream are unchanged, and the page gets no Tauri IPC access.

Prerequisites (Rust, WebKitGTK development headers, Node 20.19+ or 22.12+), environment
overrides, and packaging notes are in [TAURI.md](TAURI.md).

```bash
cd desktop
npm install
npm run gen:icons
npm run dev        # or: npm run build (both rebuild the UI first)
```

The workspace defaults to the app's working directory (Tauri dev uses the repo
root); set
`CECLI_DESKTOP_WORKSPACE` to choose a project, and `CECLI_DESKTOP_CECLI` to
pick a specific cecli executable.

## What the UI gives you

- Streaming assistant text and collapsible reasoning, rendered as safe markdown.
- Live tool cards (read, edit, execute, search, think) with status and output.
- Plan checklists from the agent's todo updates.
- Inline permission prompts for commands and edits, with the same options the
  terminal UI offers (yes / yes to all / skip / no).
- The cecli ASCII wordmark, centred before the first turn.
- A control strip under the composer: mode/model/thinking-effort chips from the
  ACP config options, a compact context-usage badge, and icon actions for logs,
  new chat, and restart.
- Stop / cancel; send becomes a stop button while a turn runs.

## Requirements

- Python 3.10+ on the machine running the bridge. Only the standard library is
  used (`asyncio`, `http`, `json`, `subprocess`), so there is nothing to install.
- A working `cecli` installation and whatever API keys your normal `cecli`
  session uses.
- Node 20.19+ or 22.12+ and npm only when rebuilding the UI or the Tauri app.
  The Python bridge and the committed `static/` output need no Node at runtime.

## Troubleshooting

- **Connection dot stays amber.** The agent is still starting or configuring the
  project. Watch the logs drawer in the header; cecli's stderr is mirrored there.
- **`cecli exited` status.** Restart from the header or rerun the server. Run
  `cecli --acp` in the workspace by hand to see its startup errors.
- **Nothing renders.** Check the browser console and <http://127.0.0.1:8765/api/state>.
- **Permissions never appear.** The agent only asks when it needs approval; if
  you launched cecli with `--yes`, it will not prompt at all.

## Development

```bash
cd desktop
npm install
npm run ui:build        # Vite -> desktop/static
npm run ui:dev          # optional: Vite dev server, proxies /api to :8765
npm run ui:check        # fail if static/ does not match ui/ sources
npm run test:ui         # node:test reducers, snapshots, session actions
cd ..
python3 -m py_compile desktop/server.py
python3 desktop/tests/test_bridge.py -v   # 20 tests, fake ACP agent, no model calls
```

`npm run ui:dev` serves `ui/` on Vite's port and proxies `/api` to an already
running bridge at <http://127.0.0.1:8765>; production always uses the Vite
build in `static/`. Run `npm run ui:check` before committing UI changes: it
compares the source hash recorded by the last build and exits non-zero if
`static/` is stale.

`ui/` is the only hand-edited frontend source; `static/index.html` and the
content-hashed `static/assets/` bundles are build output. The build records a
hash of `ui/` plus `package.json` in `static/.build-hash`, so `npm run ui:check`
catches a forgotten rebuild. The bridge denies dotfiles, so that hash file is
never served.

Before release, walk the built UI against the fake agent
(`desktop/tests/fake_acp_agent.py`): send a prompt, watch text, thoughts, a tool
card and a plan stream in, approve and reject a permission, cancel a turn, reload
during a permission prompt, and resize to 380 px. All of that exercises the SSE
replay, reducer and responsive paths without model calls.

The wire protocol and API are documented in [CONTRACT.md](CONTRACT.md).
