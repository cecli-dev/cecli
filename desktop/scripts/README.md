# Desktop packaging scripts

## Which artifact contains the bridge?

The app-harness bridge is a **mode of the same signed `ce-underscore` binary**
that hosts the GUI. There is no second executable and no separate signed
artifact. The desktop installers and the cargo build ship it:

| Platform | Artifact | Bridge path |
|---|---|---|
| Windows | NSIS installer | `$INSTDIR\ce-underscore.exe` (current-user NSIS install, normally under `%LOCALAPPDATA%`) |
| macOS | `.dmg` / cask | `ce-underscore.app/Contents/MacOS/ce-underscore` |
| Linux | AppImage / deb / rpm | `/usr/bin/ce-underscore` |

A pip-only `cecli` install has the `app-harness` client but no bridge. It reports
`bridge_unavailable`; install the desktop artifact to get native app control.

Desktop builds prepend the provisioned runtime's scripts directory (`Scripts` on
Windows, `bin` elsewhere) and the install directory to `PATH` for the bridge
process. The embedded agent and its shells therefore find `app-harness`,
`browser-harness`, and `ce-underscore` without activating the runtime.

## Operator commands

```bash
ce-underscore --ensure-bridge     # start the bridge if absent, then exit
ce-underscore --bridge-status     # print bridge status as JSON
ce-underscore --stop-bridge       # stop the bridge; exit 0 when none runs
app-harness state                 # health, platform, version, capabilities
app-harness doctor                # permissions and backend diagnostics
```

`bridge.json` lives at `%LOCALAPPDATA%\cecli\bridge.json`,
`~/Library/Application Support/cecli/bridge.json`, or
`$XDG_RUNTIME_DIR/cecli/bridge.json` (fallback `~/.cache/cecli/bridge.json`).
`CECLI_BRIDGE_FILE` overrides it. A pip-only client must never auto-start the
bridge; only `--ensure-bridge` does.

## Update hooks

`stop_bridge_before_update.sh` / `.ps1` stop the bridge before files are
replaced and compare `bridge.json.version` with the installed binary's
`--version` afterwards. A missing bridge is success; a mismatch exits 3 with
both versions in the message.

- **Windows:** `nsis-hooks.nsh` is wired through
  `bundle.windows.nsis.installerHooks`. Post-install adds the install directory
to the **user** PATH only when `CECLI_ADD_TO_PATH=1` is set before running the
  installer. Uninstall removes it.
- **macOS:** the `.dmg` has no install hook. `brew-cask/ce-underscore.rb` calls
  `stop` in `preflight` and `verify` in `postflight`; a `.pkg` must do the same
  around replacing `ce-underscore.app`.
- **Linux:** `tauri.release.conf.json` passes the shell script as the deb/rpm
  maintainer script. dpkg/rpm run it as root, so it resolves `SUDO_USER`'s
  bridge file.

`check_linux_bundle.sh [bundle-dir]` asserts that the deb, AppImage, and rpm all
contain `/usr/bin/ce-underscore`; CI runs it after the Linux build.
