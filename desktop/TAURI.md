# cecli desktop: Tauri v2 shell

A Tauri v2 wrapper that turns the local bridge into a normal desktop window.
The Rust shell starts `desktop/server.py` on a free loopback port, waits for it
to answer, and points a system-webview window at it. Everything above the
bridge (HTML, CSS, JS, JSON API, SSE) is unchanged; the shell adds process
lifecycle and a native window, nothing else.

The bridge itself is still usable on its own with `python3 desktop/server.py`.
See [README.md](README.md) for that workflow and [CONTRACT.md](CONTRACT.md) for
the HTTP/ACP contract.

## Why Tauri

- **Rust host.** The host process can spawn, supervise, and reliably tear down
the Python bridge, which a browser tab cannot do.
- **System webview.** Linux uses WebKitGTK, Windows uses WebView2, macOS uses
WKWebView. The app does not ship a browser engine, so binaries stay small and
start fast compared with an Electron bundle.
- **Real desktop behaviour.** A dedicated window, app icon, taskbar/dock entry,
   and an exit path that asks the bridge to stop before force-killing it. On
   Linux, the bridge, every ACP child, the spawned browser and terminal shells
   also ask the kernel to terminate them when their parent exits, so a crashed
   or SIGKILLed shell leaves no `cecli` processes or detached browsers behind.
   processes behind.
- **Cross-platform and mobile-capable.** The same Rust + web UI model runs on
all three desktop platforms, and Tauri v2 has mobile targets (see
[Mobile status](#mobile-status) for why this bridge is still desktop-first).

The tradeoff is a system dependency on the platform webview and its rendering
quirks. The UI is a Lit/Tailwind/daisyUI app compiled by Vite, so the shipped
page is still plain HTML/CSS/JS; WebKitGTK remains the least forgiving of the
three engines.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│ Tauri process (Rust, src-tauri/src/main.rs)                │
│                                                            │
│  1. choose a free port on 127.0.0.1                        │
│  2. spawn: <python> desktop/server.py --host 127.0.0.1 \   │
│            --port <port> --workspace <dir> --cecli <bin>   │
│  3. probe the loopback port until the bridge accepts       │
│  4. open the window at http://127.0.0.1:<port>/            │
│  5. kill and reap the Python child when the app exits      │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ system webview (WebKitGTK / WebView2 / WKWebView)     │  │
│  │ http://127.0.0.1:<port>/  — HTML, CSS, JS            │  │
│  └───────────────────────┬──────────────────────────────┘  │
└──────────────────────────┼─────────────────────────────────┘
                           │ HTTP + SSE over loopback
                 ┌─────────▼──────────┐
                 │ desktop/server.py  │  static assets, JSON API, SSE
                 │ Python 3.10+ stdlib│
                 └─────────┬──────────┘
                           │ ACP / newline-delimited JSON-RPC on stdio
                 ┌─────────▼──────────┐
                 │    cecli --acp     │
                 └────────────────────┘
```

The page, the API, and the event stream all share one origin
(`http://127.0.0.1:<port>`), so relative URLs, `EventSource`, and the bridge's
same-origin checks keep working without any CORS changes. The webview never
talks to Tauri: there is no `window.__TAURI__`, no `invoke` call in the page,
and no Tauri IPC endpoint reachable from the HTTP origin.

### Process ownership

Rust owns exactly one Python child. The child owns exactly one `cecli --acp`
child, as described in `CONTRACT.md`. On app exit the shell sends `SIGTERM` to
Python on Unix (or `kill()` on Windows), waits up to six seconds, then force
kills and reaps it. That lets the bridge terminate its own cecli child through
its normal shutdown path. If Python dies during startup, the shell reports the
early exit and aborts; after startup it does not restart the bridge, so closing
and relaunching is the only recovery.

### Startup and port selection

`server.py` accepts an ephemeral port (`--port 0`) and prints the URL it
actually bound:

```
cecli desktop bridge listening on http://127.0.0.1:54321/
```

The shell does not parse stdout. It binds `127.0.0.1:0` itself, reads the port
the OS assigned, drops the listener, and passes that port to Python explicitly;
the window URL is built from that value, never hardcoded. There is a small race
where another process can claim the port between the drop and Python's bind;
that surfaces as an early bridge exit and usually clears on a retry.

After spawning, the shell probes the loopback socket every 200 ms
(`TcpStream::connect_timeout`, 30-second deadline) and fails immediately if the
Python child exits during startup. It does not call `/api/health`: a successful
TCP connect only means the HTTP server is listening, so the agent session may
still be starting — which the UI already renders as an amber connection dot. A
failure is reported as a startup error with the bridge's stderr visible in the
terminal, rather than opening a blank window.

### Path resolution

| Context | `server.py` location |
|---------|----------------------|
| `tauri dev` / `cargo run` | `CARGO_MANIFEST_DIR/../server.py`, i.e. `desktop/server.py` |
| Packaged app | `resource_dir/server.py` or `resource_dir/_up_/server.py` |

The `_up_` directory is how Tauri preserves references to files outside
`src-tauri/` when bundling resources. The lookup order is
`CECLI_DESKTOP_SERVER`, the dev path, `resource_dir/server.py`, then
`resource_dir/_up_/server.py`. Because the dev path is compiled in, a packaged
build made on a development machine will prefer the checkout whenever it still
exists; that is convenient during development and surprising in a release
test. Static assets are resolved by `server.py` relative to its own file, so
`static/` must be bundled next to it (`resource_dir/_up_/static/`).

## Layout

```
desktop/
  package.json              npm scripts for Tauri, Vite and icons
  ui/                       Lit sources, split CSS and vite.config.js
  ui/vite.config.js         dev proxy for /api, build output ../static
  ui/build-hash.mjs         hashes ui/ sources for the freshness guard
  scripts/check_ui.mjs      fails when static/ is stale or incomplete
  scripts/gen_icons.py      renders the PNG/ICO/ICNS icons from the favicon SVG
  server.py                 the bridge the shell launches (unchanged)
  static/                   Vite build output served by the bridge
  tests/                    bridge tests with a fake ACP agent
  src-tauri/
    Cargo.toml              tauri 2, serde, serde_json; rust-version 1.77.2
    build.rs                tauri-build
    tauri.conf.json         app identity, bundle resources, security settings
    capabilities/default.json  permissions for the window (no remote IPC)
    src/main.rs             port selection, child process, window, shutdown
    icons/                  generated by `npm run gen:icons`
  TAURI.md                  this file
```

The UI is built with Lit, Tailwind CSS v4, daisyUI and Vite. `npm run
ui:build` writes `static/`; `npm run ui:dev` proxies `/api` to a running bridge
for live editing. The Tauri CLI adds the Rust shell.

## Prerequisites

### Fedora / WSL (Fedora Remix)

Tauri needs a C toolchain and the WebKitGTK development headers:

```bash
sudo dnf install webkit2gtk4.1-devel openssl-devel curl wget file \
  libappindicator-gtk3-devel librsvg2-devel libxdo-devel
sudo dnf group install c-development
```

On other distributions, follow the platform table in the official
[prerequisites](https://v2.tauri.app/start/prerequisites/) page; Debian/Ubuntu
use `libwebkit2gtk-4.1-dev`, `build-essential`, `libssl-dev`, `libayatana-appindicator3-dev`,
`librsvg2-dev`, and `libxdo-dev`.

Under WSL, a GUI needs WSLg (Windows 11, or Windows 10 with an X server).
Rendering issues in WSL are usually WebKit/DMA-BUF related; see
[Troubleshooting](#troubleshooting).

### Rust

Install with rustup if `rustc`/`cargo` are missing:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
rustc --version   # needs 1.77.2 or newer
```

### Node

Node 20.19+ or 22.12+ and npm, for Vite, Lit/daisyUI and the Tauri CLI. Vite 8
sets the floor; use a current LTS release (Node 22 or 24) if you can.

### cecli and Python

The bridge needs Python 3.10+ and a working `cecli` installation. For a
self-contained development build, `npm run runtime:install` creates
`desktop/.runtime/venv` and installs this checkout (including the `cecli`
console script) into it. The Rust shell prefers that interpreter, and
`server.py` prefers the sibling `cecli` executable, so no global cecli is
needed. The runtime is build-host state: it is gitignored and not bundled, so a
packaged app still falls back to system Python and `PATH` unless you ship a
frozen sidecar.

## Setup, build, run

```bash
cd desktop
npm install          # app, UI and Tauri CLI dependencies
npm run gen:icons    # writes src-tauri/icons/*
npm run runtime:install  # create .runtime/venv and install cecli
npm run ui:build     # optional: compile the frontend on its own
npm run dev          # tauri dev: rebuild UI, compile shell, open the window
npm run build        # tauri build: rebuild UI, release binary and bundles
```

`npm run gen:icons` renders `ui/public/cecli-temp-logo-favicon.svg` with CairoSVG
and writes PNGs (`32x32.png`, `128x128.png`, `128x128@2x.png`, `512x512.png`,
and the 1024px `icon.png`) plus `icon.ico` and `icon.icns`. The `tauri.conf.json`
bundle uses those outputs (512 px is available for manual use). If CairoSVG is
unavailable, the script falls back to a procedural icon. Rerun after changing
the SVG or script. `npm run tauri -- <args>` exposes the CLI directly (for
example `npm run tauri -- info`).

`beforeDevCommand` and `beforeBuildCommand` both run `npm run ui:build`, so
`npm run dev` and `npm run build` always refresh `static/` from `ui/`. This was
verified with `npm run dev` on the current toolchain; it builds, starts the
bridge, and opens the window. `npm run dev` also compiles the Rust shell on
first run, which takes several minutes and needs network access for crates.
Later runs are incremental. The first build also fails early if the WebKitGTK
development package is missing.

Point the app at a project and a cecli build with environment variables:

```bash
CECLI_DESKTOP_WORKSPACE=~/code/my-app \
CECLI_DESKTOP_CECLI=/home/dwash/cecli/venv/bin/cecli \
npm run dev
```

### Environment overrides

| Variable | Purpose | Default |
|----------|---------|---------|
| `CECLI_DESKTOP_WORKSPACE` | Project directory the agent edits (passed as `--workspace`) | First non-flag argument, then the current directory; debug builds under `src-tauri` walk up to the repo root |
| `CECLI_DESKTOP_PORT` | Pin the loopback port | An ephemeral `127.0.0.1` port, reserved at startup |
| `CECLI_DESKTOP_SERVER` | Explicit path to `server.py` | Dev path, then bundled resource path |
| `CECLI_DESKTOP_CECLI` | cecli executable (passed as `--cecli`) | Bridge falls back to `CECLI_BIN`, then `cecli` on `PATH` |
| `CECLI_PYTHON` | Python interpreter used to run the bridge | `desktop/.runtime/venv`, then `python3` on Unix; `python` then `python3` on Windows |
| `CECLI_DESKTOP_TERMINAL` | Enable the terminal panel | Enabled on loopback; `--no-terminal` or `0/false/no/off` disables; forced off for non-loopback binds |
| `CECLI_DESKTOP_TERMINAL_SHELL` | Shell used by the terminal panel | `$SHELL`/`/bin/sh` on POSIX; `%COMSPEC%`/`cmd.exe` on Windows |

Use `CECLI_DESKTOP_PORT=8765` when you want to inspect the running app from a
normal browser (`http://127.0.0.1:8765/`) or curl its API. Leave it unset in
normal use so two instances, or another dev server, cannot collide.

The workspace default is the process working directory, which is not always
the project you expect — a desktop launcher may start the app in `$HOME` — so
set `CECLI_DESKTOP_WORKSPACE` explicitly in a launcher or dev script. Tauri's
dev command runs the binary from `src-tauri`; debug builds detect that and use
the repository root instead, but an explicit override is still safer.

The Terminal panel (Logs and optional Shell tabs) is collapsed by default and
uses a WebSocket for raw terminal bytes. It is enabled by default on loopback
and can be disabled with `--no-terminal`; POSIX uses a real PTY, while Windows
falls back to a line-oriented pipe shell with stdin support but no TUI/resize.
Run the shell in the workspace the user expects, because it does not inherit the
agent's process group.

## Configuration notes

- **Window URL is runtime state.** The port is only known after the bridge
  starts, so the main window is created in Rust with
  [`WebviewWindowBuilder`](https://docs.rs/tauri/latest/tauri/webview/struct.WebviewWindowBuilder.html)
  and [`WebviewUrl::External`](https://docs.rs/tauri/latest/tauri/enum.WebviewUrl.html),
  not declared in `tauri.conf.json`. `app.windows` can stay empty.
- **`frontendDist` points at build output.** It is `../static`, which Vite
  writes from `ui/`; `beforeDevCommand`/`beforeBuildCommand` run
  `npm run ui:build` first. The window then loads the live loopback URL that
  Python serves, so rebuilding `static/` changes the running app; the embedded
  copy validates the config and is bundled but never served directly.
- **Resources.** Bundle `../server.py` and the static directory, for example
  `"resources": ["../server.py", "../static/**/*"]`. Tauri rewrites paths
  outside `src-tauri/` into `_up_/`, which is why the Rust lookup checks both
  `server.py` and `_up_/server.py`.
- **Capabilities.** The page is a remote HTTP origin and receives no Tauri
  permissions. Keep `capabilities/default.json` scoped to the `main` window
  with only the core permissions the shell itself needs. A capability entry
  applies to app-protocol pages; granting remote URLs IPC access is both
  unnecessary and contrary to this design. If a sidecar is added later, use
  the shell plugin's sidecar permission rather than a broad `shell:default`.
- **CSP.** `server.py` does not send a `Content-Security-Policy` header today.
  The page makes no external requests and loads only same-origin assets, so
  the practical exposure is small, but adding a CSP in the bridge is the right
  hardening step if the UI grows.
- **Devtools.** Release builds should keep devtools disabled. Use a debug
  build (`npm run dev`) when you need the web inspector.

## Security model

- **No Tauri IPC is reachable from the page.** The wrapped page is served over
  HTTP, not the `tauri://` custom protocol. Tauri injects its JS API only into
  app-origin pages, and no capability grants the loopback origin IPC access.
  The page can therefore only do what the HTTP API allows: prompt the agent,
  answer permissions, and read events.
- **The loopback bridge still has no authentication.** The `Host`/`Origin`
  checks in `server.py` block cross-site requests and DNS-rebinding reads from
  browsers; they do not authenticate. Any local process that can reach
  `127.0.0.1:<port>` can drive the agent.
- **Local-only assumption.** The bridge can execute shell commands in the
  workspace through cecli. Do not bind it to a non-loopback interface, do not
  put it behind a tunnel or reverse proxy, and do not load untrusted remote
  URLs in the app window.
- **Permissions are UX, not a sandbox.** The approval cards map to cecli's own
  permission flow; they do not constrain what the agent may do once approved.
  Treat the workspace and the user account as the security boundary.
- **Child process environment.** The bridge inherits the app's environment,
  including API keys. That is required for cecli to work, but it means the
  agent and anything it runs can read them.

## Packaging the Python side

Three options, from least to most work:

### 0. Build-time runtime install

`npm run runtime:install` creates `desktop/.runtime/venv` with `venv` and runs
`pip install -e <repo>`. The Rust shell looks for that interpreter before
falling back to `python3`. This is the lightest way to make the app run
internally in development: no system cecli on `PATH`, no hand-built sidecar.
The venv is build-host state (gitignored, not in `bundle.resources`) because
`pip install -e` and `bin/python` contain absolute paths and are not
relocatable. For distribution, use a frozen sidecar (option 2) or a native ACP
client (option 3).

### 1. Current: system Python + repo checkout

The bundle ships `server.py` and `static/`, and expects `python3`, a `cecli`
installation, and the user's API keys to exist on the machine. This is fine for
developers and for building from a checkout, and it is what the scaffold
targets. It is not a self-contained installer: the app fails to start the
bridge if Python 3.10+ or cecli is missing.

### 2. Recommended distribution: PyInstaller sidecar

Freeze the bridge into one executable and ship it as a Tauri sidecar, so the
app no longer depends on a system Python for the bridge:

```bash
pyinstaller --onefile --name cecli-desktop-bridge \
  --add-data "desktop/static:static" desktop/server.py
```

PyInstaller's one-file mode unpacks to a temporary directory and sets
`__file__` there, so `Path(__file__).resolve().parent / "static"` continues to
resolve when `static` is added beside `server.py`.

Tauri requires the sidecar filename to carry the Rust target triple, for
example `cecli-desktop-bridge-x86_64-unknown-linux-gnu`, placed under
`src-tauri/binaries/`. Then:

```json
{
  "bundle": {
    "externalBin": ["binaries/cecli-desktop-bridge"]
  }
}
```

`externalBin` paths are relative to `src-tauri/` and must not contain `..`.
Launch it from Rust with the shell plugin's sidecar API
(`app.shell().sidecar("cecli-desktop-bridge")`) and grant only the sidecar
execute/spawn permission needed, not unrestricted shell access. See the
[sidecar guide](https://v2.tauri.app/develop/sidecar/).

Important: this removes the Python requirement for the *bridge*, not for
`cecli`. cecli is itself a Python application. You still need to ship it (a
frozen cecli binary or a bundled virtualenv) or point `CECLI_DESKTOP_CECLI` at
an existing installation.

### 3. Future: native Rust bridge

Implement the ACP client in Rust over the `cecli --acp` child's stdio and drop
Python and HTTP entirely (or keep a thin local server for the web UI). That
yields one signed binary, no interpreter discovery, and a straightforward path
to mobile. It is a rewrite of `server.py`'s responsibilities, not a packaging
tweak, so it is out of scope for this scaffold.

## Mobile status

Tauri v2 supports iOS and Android, but this wrapper is desktop-first by design.
The shell's central job is spawning a Python child process and serving the UI
over loopback HTTP:

- **iOS** does not allow spawning arbitrary executables, and background process
  lifetime is tightly controlled. Embedding CPython is possible but heavy and
  does not give you a separate `cecli` process.
- **Android** can embed Python (for example via Chaquopy), but process and pipe
  management for an ACP child is fragile, and the loopback-server model fits the
  platform poorly.

A real mobile port would need an ACP client written in Rust (or another native
language) exposed through Tauri commands, plus UI changes to call IPC instead
of HTTP/SSE. The current page would need a transport shim. None of this is
implemented or attempted here.

## Troubleshooting

- **`cargo: command not found` / `rustc` missing.** Install rustup and restart
  the shell so `$HOME/.cargo/bin` is on `PATH`.
- **`webkit2gtk-4.1` not found, or `pkg-config` errors during build.** Install
  the development packages above. On Fedora, verify with
  `pkg-config --modversion webkit2gtk-4.1`.
- **Window opens but stays blank.** The bridge probably failed to start. Run
  `python3 desktop/server.py --workspace <dir>` by hand, then check
  `http://127.0.0.1:8765/api/health` (or the pinned port). The shell passes the
  child's stderr straight through, so the Python traceback appears in the
  terminal that launched `npm run dev` (or the app, if it has one).
- **`server.py not found`.** The dev path is baked in at compile time from
  `CARGO_MANIFEST_DIR`, so moving the checkout invalidates it; rebuild, or set
  `CECLI_DESKTOP_SERVER`. In a packaged app, verify the resource layout.
- **`Address already in use`.** `CECLI_DESKTOP_PORT` is pinned to a port another
  process owns. Unset it to go back to an ephemeral port.
- **Agent status stays amber or `cecli exited`.** The window only mirrors the
  bridge. Run `cecli --acp` in the workspace to see startup errors, and check
  that `CECLI_DESKTOP_CECLI`/`CECLI_BIN` point at a working executable.
- **`ModuleNotFoundError` or a Python stack trace on startup.** The shell picked
  the wrong interpreter. Set `CECLI_PYTHON` to the Python 3.10+ you use for
  cecli, or fix `PATH`.
- **Blank or flickering WebKit view under WSL.** Try
  `WEBKIT_DISABLE_COMPOSITING_MODE=1` or `WEBKIT_DISABLE_DMABUF_RENDERER=1` when
  launching; both are common WSL/GPU-driver workarounds. Confirm WSLg is
  available (`ls /mnt/wslg`) and that a simple GUI app can open a window.
- **Icons missing during `npm run build`.** Run `npm run gen:icons` first, or
  point the bundler at a generated icon set.
- **`npm install` cannot reach the registry.** The build needs the Tauri CLI
  plus Vite, Lit, Tailwind and daisyUI. On an offline machine, pre-populate the
  npm cache, vendor `node_modules`, or use a cargo-installed `tauri-cli`.
  dependency. On an offline machine, pre-install it or use a cargo-installed
  `tauri-cli` of the same major version.

## Verification status

The Rust shell compiles and launches in this environment (Fedora Remix 39 on
WSL2 with WSLg), using rustc/cargo 1.99.1, Tauri 2.12.5, and WebKitGTK 2.46.3.

What was verified in this tree:

- `cargo fmt --check` and `cargo check --manifest-path src-tauri/Cargo.toml`
- `cargo build --manifest-path src-tauri/Cargo.toml` produced
  `src-tauri/target/debug/cecli-desktop`
- a 15-second launch smoke test opened the window, started the Python bridge,
  and reached a real `cecli --acp` session
- `npm run ui:build` (Vite: 50 modules -> hashed `static/assets/index-*.js` and
  `index-*.css`) and `npm run ui:check` (source hash matches `static/.build-hash`)
- `python3 -m py_compile desktop/server.py`; `flake8` clean
- `python3 desktop/tests/test_bridge.py` (22 tests, fake ACP agent, no model
  calls, including a multi-permission turn, a cancelled-permission outcome, and
  SIGTERM with an open SSE client)
- `npm run test:ui` (20 `node:test` cases: transcript reducers, permissions,
  session filtering, multi-permission turns, snapshots, markdown escaping,
  send/failure/new-chat)
- a browser session against the built UI with the fake ACP agent: empty state
  with the cecli ASCII wordmark, control strip under the composer, prompt ->
  streamed turn, thought, tool card, plan, permission card -> resolve -> idle,
  working mode switch; 380 px and 1440 px viewports have no horizontal overflow
- `scripts/gen_icons.py` output: PNGs at 32, 128, 256, 512, and 1024 px plus
  `icon.ico` and `icon.icns`, matching the `bundle.icon` entries in
  `tauri.conf.json`
- `tauri.conf.json` validates against the installed Tauri CLI schema

Not verified: window-close cleanup inside a real Tauri session, release-mode
bundling (deb/rpm/AppImage), and non-Linux targets. On Linux the kernel
parent-death signal cleans up the bridge and its ACP children even after an
external SIGKILL; on Windows and macOS an external SIGKILL can still orphan
them.

## Research and sources

- Tauri v2 getting started: <https://v2.tauri.app/start/>
- Prerequisites per platform: <https://v2.tauri.app/start/prerequisites/>
- Embedding external binaries (sidecars): <https://v2.tauri.app/develop/sidecar/>
- Configuration reference: <https://v2.tauri.app/reference/config/>
- Capabilities and permissions: <https://v2.tauri.app/reference/acl/capability/>
- `WebviewUrl` API: <https://docs.rs/tauri/latest/tauri/enum.WebviewUrl.html>
- `WebviewWindowBuilder` API: <https://docs.rs/tauri/latest/tauri/webview/struct.WebviewWindowBuilder.html>