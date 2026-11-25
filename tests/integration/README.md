# app-harness integration suite

This directory is the cross-platform acceptance gate for the app-harness bridge
(`T15`). It has two layers:

1. **Hermetic protocol and CLI-contract tests.** They start an isolated fake
   bridge and never touch a real desktop. They run by default on any machine.
2. **Platform acceptance tests.** Windows UIA and Linux AT-SPI checks need real
   applications, a real bridge, and an interactive session. They skip cleanly
   when any component is missing.

Every test is designed to report *why* it skipped, so a green run on a machine
without a desktop is not mistaken for acceptance.

## Running locally

```bash
# Hermetic layer only; starts its own fake bridge.
venv/bin/python -m pytest tests/integration -q

# Collect without running anything.
venv/bin/python -m pytest tests/integration --collect-only -q
```

The fake bridge is chosen in this order:

1. `target/debug/examples/fake_bridge` (or the same path under `desktop/`),
2. `ce-underscore --app-harness` with `CECLI_BRIDGE_BACKEND=fake`,
3. the in-process Python fake from `tests/app_harness/conftest.py`.

The chosen bridge always gets its own temporary `bridge.json`, so the tests
never read or rewrite the operator's real bridge file.

## Running against a real bridge

Set `CECLI_INTEGRATION=1` and point `CECLI_BRIDGE_FILE` at the `bridge.json`
written by a running bridge. Start the bridge in the **same logged-in desktop
session** that owns the applications under test:

```bash
# Linux / macOS
export CECLI_INTEGRATION=1
export CECLI_BRIDGE_FILE="$HOME/.cache/cecli/bridge.json"
/path/to/ce-underscore --app-harness &
venv/bin/python -m pytest tests/integration -q
```

```powershell
# Windows PowerShell
$env:CECLI_INTEGRATION = "1"
$env:CECLI_BRIDGE_FILE = "$env:LOCALAPPDATA\cecli\bridge.json"
& "$env:LOCALAPPDATA\Programs\ce-underscore\ce-underscore.exe" --app-harness
venv\Scripts\python -m pytest tests\integration -q
```

`CECLI_CE_UNDERSCORE` can override the binary path when testing an unpacked or
CI build. Do not set `CECLI_BRIDGE_VERSION_SKIP` for acceptance runs; a version
mismatch must fail with exit code 4.

## Windows QEMU guest

Acceptance tests must run inside the guest's interactive desktop, not over a
non-interactive service session:

1. Boot the QEMU Windows image and log in through the console or RDP.
2. Install or stage `ce-underscore` and the `cecli` virtualenv in the guest.
3. Start `ce-underscore --app-harness` from that logged-in session so it writes
   `%LOCALAPPDATA%\cecli\bridge.json` and can reach the desktop.
4. In the same session:

   ```powershell
   $env:CECLI_INTEGRATION = "1"
   $env:CECLI_BRIDGE_FILE = "$env:LOCALAPPDATA\cecli\bridge.json"
   C:\cecli\venv\Scripts\python -m pytest tests\integration -q
   ```

   With `--ensure-bridge`, pass `CECLI_CE_UNDERSCORE` to the staged binary.

Why the interactive session matters: UIA and `SendInput` operate on the window
station and desktop of the caller. A service or SSH session has a different
window station, so `EnumWindows` sees no user windows, focus cannot be set, and
`PrintWindow` captures a blank surface. The suite will skip with
`CECLI_INTEGRATION is not set` or fail window discovery rather than pretend
the desktop is testable.

The tests start `tests/integration/fixtures/fixture_app.ps1` automatically. It
is a dependency-free .NET Framework WinForms app titled
`cecli Harness Fixture` with the controls the acceptance checks expect. Set
`CECLI_FIXTURE_LOG` manually only when you want Save clicks written to a file;
the tests set it for their own temporary log.

## Linux AT-SPI

```bash
export CECLI_INTEGRATION=1
export CECLI_BRIDGE_FILE="$XDG_RUNTIME_DIR/cecli/bridge.json"
export DISPLAY=:0            # or WAYLAND_DISPLAY
venv/bin/python -m pytest tests/integration/test_linux_atspi.py -q
```

The suite skips when there is no session bus, no `org.a11y.Bus`, or no
`PyGObject`/GTK3. `gtk_fixture.py` creates the GTK3 window used by
`test_gtk_fixture_is_snapshotted`; run it manually to debug:

```bash
venv/bin/python tests/integration/gtk_fixture.py
```

Wayland sessions report AT-SPI structure but may refuse synthetic X11 input.
Treat input failures on Wayland as capability gaps, not protocol failures.

## Environment variables

| Variable | Purpose |
|---|---|
| `CECLI_INTEGRATION=1` | Enables host-desktop acceptance tests. |
| `CECLI_BRIDGE_FILE` | Discovery override; points at the bridge's `bridge.json`. |
| `CECLI_CE_UNDERSCORE` | Binary used by `--ensure-bridge` and the fake-server fallback. |
| `CECLI_BRIDGE_BACKEND=fake` | Forces the compiled fake backend in the bridge. |
| `CECLI_APP_TIMEOUT_MS` | Client read timeout; unset by the fixtures so tests control it. |
| `CECLI_FIXTURE_LOG` | Optional Save-click log for the PowerShell fixture. |

## Acceptance matrix

The table maps section 15 of `IMPLEMENTATION-PLAN.md` to the tests that cover
it. "Gap" means the check needs packaging, a different application, or a
platform this repository cannot host in WSL.

| Phase | Plan check | Test |
|---|---|---|
| 0 | `ce-underscore --app-harness` writes `bridge.json`; `/api/app/state` serves | `test_protocol.py::test_state_reports_identity`; `test_bridge_file_override_is_honoured` |
| 0 | `app-harness state` succeeds; no bridge exits 4 | `test_cli_contract.py::test_exit_zero_for_successful_commands`; `test_exit_four_without_a_bridge` |
| 0 | `--ensure-bridge` is idempotent, starts exactly one process | Gap: covered by T1/T3 unit tests; this suite only consumes a running bridge |
| 0 | Fake tests: protocol, token rejection, truncation, timeouts | `test_protocol.py::test_token_rejection_returns_401`; `test_truncation_flags_are_explicit`; `test_transport_timeout_maps_to_uncertain` |
| 1 | Notepad: snapshot finds the edit; `set_value` reads back; `keys` types | `test_windows_acceptance.py::test_snapshot_finds_edit_and_button`; `test_set_value_reads_back`; `test_keys_types_into_edit` |
| 1 | Excel: snapshot finds a cell/formula bar; `set_value` verifies; Save works | Gap: the deterministic fixture replaces Excel so the suite is repeatable |
| 1 | Password field: value never returned | `test_windows_acceptance.py::test_password_value_is_never_returned` |
| 1 | Disabled control: refused before sending | `test_windows_acceptance.py::test_disabled_control_is_refused` |
| 1 | Stale handle: refused; nothing sent | `test_windows_acceptance.py::test_stale_element_ref_is_refused` |
| 1 | Hung target: returns uncertain, no automatic retry | `test_protocol.py::test_transport_timeout_maps_to_uncertain` (transport-level) |
| 1 | Screenshot produces a non-empty PNG | `test_protocol.py::test_screenshot_returns_png_bytes`; `test_windows_acceptance.py::test_screenshot_is_nonempty_png` |
| 1 | 10 consecutive runs: no state leakage or orphan processes | Partial: `test_cli_contract.py::test_repeated_runs_share_no_client_state`; orphan-process counting is a gap |
| 2 | One installer installs the GUI and bridge mode | Gap: packaging workflow, not this suite |
| 2 | A pip-only `cecli` reports `bridge_unavailable` | `test_cli_contract.py::test_exit_four_without_a_bridge` |
| 2 | `CECLI_BRIDGE_FILE` and token checks work | `test_protocol.py::test_bridge_file_override_is_honoured`; `test_token_rejection_returns_401` |
| 2 | No new signed artifact on Windows or macOS | Gap: release and signing audit |
| 3 | macOS Accessibility grant covers GUI and bridge launches | Gap: no macOS host |
| 3 | `CGEventPostToPid` sends keys and pointer actions | Gap: no macOS host |
| 3 | Screen Recording prompt appears only when needed | Gap: no macOS host |
| 3 | Notarized bundle passes `spctl --assess` | Gap: release audit |
| 4 | AT-SPI snapshot and actions on a GTK fixture | `test_linux_atspi.py::test_snapshot_of_any_window_is_structurally_valid`; `test_gtk_fixture_is_snapshotted` (snapshot only; actions are a gap) |
| 4 | XTEST input while focused | Gap: not covered here |
| 4 | Wayland reports unsupported per capability | Gap: needs a Wayland session matrix |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Everything skipped: `CECLI_INTEGRATION is not set` | Acceptance layer is gated | Export `CECLI_INTEGRATION=1`. |
| `no real bridge: set CECLI_BRIDGE_FILE` | No `bridge.json`, or it does not answer `/api/app/state` | Start `ce-underscore --app-harness` in the same session. |
| Windows window never appears | PowerShell session is non-interactive, or the script is blocked by execution policy | Run in the console/RDP session; the fixture is launched with `-ExecutionPolicy Bypass`. |
| Snapshot is empty on Windows | The bridge runs in a different session or integrity level | Run the bridge in the logged-in session at the same integrity level. |
| AT-SPI module skips: `org.a11y.Bus is not on the session bus` | Accessibility is disabled | Enable `org.a11y` (GNOME: `gsettings set org.gnome.desktop.interface toolkit-accessibility true`) and restart the app. |
| `PyGObject/GTK3 unavailable` | The venv lacks `gi` or the GTK typelib | Install `python3-gi`/`gir1.2-gtk-3.0` or run the fixture with a system interpreter. |

Timed-out actions are reported as `uncertain` and are never retried. If a test
fails after a timeout, inspect the target application before rerunning; do not
add retries to the suite.
