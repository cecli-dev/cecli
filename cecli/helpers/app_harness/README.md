# app-harness

Drive native desktop applications through the `ce-underscore` accessibility
bridge. The client snapshots the OS accessibility tree, locates controls, sends
real input, and reads the result back.

## Usage

Run one Python script against one bridge connection:

```bash
app-harness --window "Book1 - Excel" - <<'PY'
sheet = spreadsheet(window="Book1 - Excel")
sheet.set_cell(1, 1, "Hello")
print(sheet.value(1, 1))
PY
```

From WSL, add `--host windows` (or `--interop`) to forward the call to a Windows
Python that can see Windows windows.

`app-harness help`, `app-harness help --list-apps`, and
`app-harness help --app excel` document the bridge endpoints, selectors, and
application recipes.

## Script helpers

`windows`, `snapshot`, `find`, `locator`, `wait_for`, `cell_at`, `click`,
`double_click`, `right_click`, `hover`, `drag`, `select`, `scroll_into_view`,
`type_text`, `edit_text`, `wait_for_value`, `dialogs`, `accept_dialog`,
`cancel_dialog`, `dismiss_dialogs`, `spreadsheet`, `paste_tsv`,
`set_clipboard`, `get_clipboard`, `keys`, `focus`, `scroll`, `scroll_to`,
`activate`, `screenshot`, `emit`, `expect`, and `refresh`.

Every action returns an `ActionResult` with `delivered`, `verified`, `outcome`,
`message`, and `value`. Synthetic keystrokes cannot be verified
server-side; call `wait_for_value` or read the control back after a short pause.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Script completed |
| 1 | Script raised, or `expect` failed |
| 2 | An action was refused |
| 3 | An action was delivered but not verified |
| 4 | No bridge is running |

## App recipes

Recipes capture the selectors, key chords, and traps for one application. They are
YAML files; bundled defaults live in `cecli/helpers/app_harness/recipes/defaults/`
(`excel.yml`, `libreoffice.yml`), and users or projects can drop `.yml` files into:

1. `~/.cecli/app-recipes/`
2. `~/.agents/app-recipes/`
3. `<project>/cecli/app-recipes/`
4. `<project>/.cecli/app-recipes/`
5. `<project>/.agents/app-recipes/`

Later files override earlier ones with the same `key`. `.yaml` and `.json` are also
accepted; `.yml` is the preferred and creator-generated format.

```python
from cecli.helpers.app_harness import recipes

print(recipes.list_apps())
print(recipes.help_text("excel"))
```

See the App Harness documentation section for the full recipe schema and examples.

## Version coupling

`EXPECTED_BRIDGE_VERSION` in `client.py` must match the Cargo workspace
version in the repository root (`Cargo.toml`). The client rejects a bridge whose
version differs, so bump both together; `tests/app_harness/test_client.py`
checks the two values stay in sync.
