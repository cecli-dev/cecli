---
parent: Usage
nav_order: 45
description: Drive native desktop apps like Excel, LibreOffice, and Notepad through the accessibility tree, with per-app recipes.
---

# App Harness

App Harness lets cecli drive a real desktop application the way a person would: read its accessibility tree, click and type into real controls, and verify the result. It works when an app has no usable API or file format - spreadsheets, native dialogs, line-of-business tools, and anything else that only exists as a window.

Use it when the work is GUI-only. For web pages use `browser-harness`; for HTTP APIs or files on disk use the normal tools.

## What it gives you

- **Cross-platform control** on Windows (UI Automation), macOS (AX), and Linux (AT-SPI).
- **Real input**, not simulated DOM events: invoke, click, type, send keys, drag, scroll, and handle native dialogs.
- **A verification loop** built for agents: `snapshot -> act -> verify`, with `delivered` and `verified` reported separately.
- **Per-app recipes** that can capture the selectors, key chords, and traps that make one application tractable - so the knowledge is shared instead of rediscovered.

## Quick start

```bash
app-harness state --json
app-harness windows --json
app-harness --window "Book1 - Excel" - <<'PY'
sheet = spreadsheet()
sheet.set_cell(1, 1, "Hello")
print(sheet.value(1, 1))
PY
```

From WSL, the agent can add `--host windows` (or `--interop`) so the call runs under a Windows Python that can see Windows windows:

```bash
app-harness --host windows --window "Book1 - Excel" snapshot --max-elements 40
```

## The agent loop

1. **Snapshot** the window (filter in the script, not in your context).
2. **Act** with the weakest action that works: `invoke`, `set_value`, `click`, then keystrokes.
3. **Verify** with a read-back. Keyboard actions return `verified=False`, so use `wait_for_value` or read the control again after a short pause.

```python
activate()
snap = snapshot(actionable=True, max_elements=80)

set_value(value="hello", name="Text editor")
wait_for_value("hello", name="Text editor", timeout_ms=3000)
emit({"ok": True})
```

## Keystrokes

`keys` takes a compact specification:

| Token | Meaning |
| --- | --- |
| `^` `!` `+` `~` | Control, Alt, Shift, Meta, bound to the *next* key (`^s`, `^+t`) |
| `{ENTER}` `{TAB}` `{ESC}` `{F5}` `{PGDN}` `{BACKSPACE}` | Named keys |
| `{+}` `{!}` `{^}` `{~}` | Those characters literally |
| anything else | Typed literally, in order |

```python
keys("^s")                    # save
keys("L1{ENTER}L2{ENTER}L3")  # typed in order, newline between rows
```

**Caveat: fast bursts can be dropped by the target.** Windows delivers synthetic input faster than some UI toolkits consume it, so a WinUI 3 / XAML editor (Notepad on Windows 11, Settings) may keep only the first character of a multi-key burst. The bridge sends every event; the target discards them. When you see this, send one step per call:

```python
for step in ["L", "1", "{ENTER}", "L", "2", "{ENTER}", "L", "3"]:
    keys(step)
    time.sleep(0.15)
```

`type_text` is not affected the same way: it prefers a direct `set_value`, and when it does type, it verifies the control value afterwards and re-sends once through the clipboard if the keystrokes were dropped.

## Recipes

A **recipe** tells App Harness how to drive one application. It names the controls you need, the key chords that work, and the traps that break a naive sequence. Recipes are data, not code: the bundled defaults and user recipes use the same YAML schema.

Why recipes matter:

- The same action can have different control names in different apps (`tab_item` vs `page_tab`, `edit` vs `push_button`).
- Real apps have workflow traps e.g. Excel's Paste Options overlay, Calc's Text Import dialog, editors that only expose a committed value.
- A recipe is a portable, reviewable artifact. Anyone can add support for an app without touching the driver.

### Where recipes live

Recipes are loaded from these directories, in order. Later files override earlier ones with the same `key`:

1. `~/.cecli/app-recipes/`
2. `~/.agents/app-recipes/`
3. `<project>/cecli/app-recipes/`
4. `<project>/.cecli/app-recipes/`
5. `<project>/.agents/app-recipes/`

Use `CECLI_APP_RECIPES_DIRS` to override the search path (`os.pathsep`-separated); an empty value disables external recipes.

Bundled recipes are `.yml` files under `cecli/helpers/app_harness/recipes/defaults/`. External recipes are read from `.yml` (preferred), `.yaml`, or `.json`.

### Recipe format

```yaml
key: notepad
display_name: Notepad
description: Plain-text editor on Windows
process_names: [notepad.exe]
title_markers: [notepad]
aliases: [notepad]

selectors:
  editor: "document[name='Text editor']"
  new_tab: "button[name='Add New Tab']"

keys:
  save: '^s'
  save_as: '^+s'
  select_all: '^a'

sections:
  Text entry:
    - Use set_value on the editor document.
    - Read the document back, or use wait_for_value after typing.

gotchas:
  - Save As opens a separate top-level dialog; dismiss it with cancel_dialog().
```

| Field | Required | Meaning |
|---|---|---|
| `key` | yes | Stable identifier used by `get_recipe`, `spreadsheet(app=...)`, and overrides. Defaults to the filename stem when omitted. |
| `display_name` | no | Human-readable app name shown in help. Defaults to `key`. |
| `description` | no | One-line summary shown at the top of rendered help. |
| `process_names` | yes* | Executable names used for detection, e.g. `excel.exe`, `soffice.bin`. |
| `title_markers` | yes* | Case-insensitive substrings matched against the window title. |
| `aliases` | no | Extra names accepted by `get_recipe`, e.g. `calc`, `lo`. |
| `selectors` | no | Map of selector names to selector expressions. |
| `keys` | no | Map of chord names to SendKeys syntax, e.g. `paste: '^v'`. |
| `sections` | no | Map of section title to a list of help lines. |
| `gotchas` | no | List of traps rendered under `Gotchas:`. |

\* At least one of `process_names` or `title_markers` is required.

### Read recipes from Python

```python
from cecli.helpers.app_harness import recipes

recipes.list_apps()              # ['excel', 'libreoffice', ...]
recipes.get_recipe("calc")       # alias -> LibreOffice Calc
recipes.detect_app(window)      # process/title -> recipe key
print(recipes.help_text("excel"))  # selectors, keys, sections, gotchas
```

Bundled defaults are importable per app:

```python
from cecli.helpers.app_harness.recipes.defaults import DEFAULT_RECIPES

excel = DEFAULT_RECIPES["excel"]
```

From the CLI:

```bash
app-harness help --list-apps
app-harness help --app excel
```

### Add a recipe with the creator

Ask the creator to add a recipe and it writes a `.yml` file into the selected scope:

```text
/creator add an app-harness recipe for Slack
```

That creates `.cecli/app-recipes/slack.yml` in the project (or `~/.cecli/app-recipes/slack.yml` for `scope: global`) using `ManageExtensions(type="app_recipe")`. The file is validated against the same schema before it is written, and the recipe registry reloads immediately.

### Contributing a default recipe

To ship support for an app with App Harness, add `cecli/helpers/app_harness/recipes/defaults/<app>.yml`. It is loaded automatically, included in the wheel through package data, and appears in `help --list-apps`. Keep it declarative: selectors and notes only.

## Tips for writing selectors

- Snapshot the real window and copy `element.selector()`; prefer `[automation_id="..."]` or role plus accessible name.
- Names are case-insensitive and may repeat; narrow with a role or a path.
- Prefer server-side capabilities when available; fall back to snapshot filtering.
- Record the trap that cost you time in `gotchas` - that is what makes a recipe valuable to the next person.
