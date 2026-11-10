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

On Linux the bridge exits when the process that launched it exits, so closing
the shell or desktop app does not leave orphaned `cecli --acp` children behind.
Set `CECLI_DESKTOP_KEEP_ON_PARENT_EXIT=1` to keep a deliberately detached
bridge alive.
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
npm run runtime:install  # optional: create desktop/.runtime/venv with cecli
npm run dev        # or: npm run build (both rebuild the UI first)
```

The workspace defaults to the app's working directory (Tauri dev uses the repo
root); set
`CECLI_DESKTOP_WORKSPACE` to choose a project, and `CECLI_DESKTOP_CECLI` to
pick a specific cecli executable.

On Node 22.15+, 23.9+, or 24+, the dev and build scripts run Node with the
system certificate store. On Linux the app also forces the WebKit rendering
workarounds described in [TAURI.md](TAURI.md).

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

- A left sidebar with one tree per parent cecli session and its sub-agents.
- Per-session activity badges, permission counts, context files, and loaded
  skills/MCP servers/workflows.
- Add/close parent sessions; switch sessions without losing the in-memory
  transcript; message or cancel a sub-agent.
- A right-hand workbench with a live Chrome/Chromium page preview above the
  active background-command panel. The preview has a tab strip for every open
  browser tab (including tabs opened by browser-harness), a new-tab button,
  hover-close controls, and a horizontally scrollable strip without a visible
  scrollbar. Client-side zoom controls do not change the emulated page viewport,
  and wheel scrolling hands off from the page into the zoomed canvas at page
  scroll boundaries. The browser, background, and workflows headers collapse
  their sections when clicked. Chat and the workbench split the remaining width,
  header toggles collapse the sidebar, chat, or workbench, and the emulated page
  fills the pane up to a 1920x1080 viewport.
- The browser preview handles JavaScript dialogs, file pickers, downloads,
  promptable permissions, IME composition, cursor feedback, clipboard copy, and
  file/text drops. Frames stream over a binary WebSocket (with the SSE endpoint
  as a fallback), and an "Open in default browser" action provides the
  screen-reader-accessible escape hatch from the canvas preview.
- A registry panel at the bottom of the sidebar for toggling skills and MCP
  servers and running workflows.

`GET /api/sessions` lists the tree, `GET /api/state?bridgeId=...` returns one
session view, and `GET /ws` is a command-only WebSocket (`sessions.*`,
`session.*`, `subagents.*`, `skills.*`, `mcp.*`, `workflows.*`, `context.*`).
SSE remains the only server-to-client event stream, so commands cannot race and
duplicate state updates.

## Requirements

- Python 3.10+ on the machine running the bridge. Only the standard library is
  used (`asyncio`, `http`, `json`, `subprocess`), so there is nothing to install.
- Chrome, Chromium, Edge or Brave for the browser preview. A dedicated profile
  is kept under `~/.cecli/desktop/browser-profile`; set `CECLI_BROWSER_BIN` if
  the browser is installed in a nonstandard location.
  The preview window opens off-screen on macOS and Windows, minimized on other
  Linux desktops, and hidden under WSL when X11 is available (WSLg cannot
  position or minimize windows, so the browser window is unmapped instead);
  without an X11 display it falls back to headless. Override this with
  `CECLI_BROWSER_WINDOW_MODE=offscreen|minimized|headless|hidden|visible`.
  On WSL, use a Chrome/Chromium installation inside the Linux distribution. A
  Windows `chrome.exe` found under `/mnt/c` only works with mirrored WSL
  networking; default NAT cannot reach its loopback debug port.
- A working `cecli` installation and whatever API keys your normal `cecli`
  session uses.
- Node 20.19+ or 22.12+ and npm only when rebuilding the UI or the Tauri app.
  The Python bridge and the committed `static/` output need no Node at runtime.
- The optional terminal panel runs a shell in the workspace. POSIX hosts use a
  PTY (`$SHELL -i`), so sudo prompts and interactive commands work; Windows and
  no resize or TUI support. It is enabled by default on loopback; disable it
  with `--no-terminal` or `CECLI_DESKTOP_TERMINAL=0`, and set `--terminal-shell`
  to override the shell. It is forced off for non-loopback binds, and the Logs
  tab works regardless.
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
python3 desktop/tests/test_bridge.py -v   # 22 tests, fake ACP agent, no model calls
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
