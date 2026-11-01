---
parent: Configuration
nav_order: 24
description: Use creator mode to add skills, MCP servers, hooks, tools, commands, workflows, and settings that persist across sessions.
---

# Creator Mode

Creator mode is a built-in helper agent that builds and configures cecli for you. Instead of hand-editing YAML or dropping files into the right directory, describe what you want and the creator writes the backing files, records the configuration in `creator.yml`, and reloads the change so it works immediately and in future sessions.

Use creator mode when the request is about extending cecli itself — not when you want help editing your project's code:

- add a skill (`SKILL.md` package)
- connect an MCP server
- add a hook
- create a custom tool or slash command
- define a workflow
- change persistent settings

## Starting Creator Mode

Start it like any other chat mode:

```text
/creator
/creator add a skill that reviews Python diffs for risky patterns
```

With a prompt, the creator starts working immediately. Without one, it waits for your next message. In the TUI, the creator opens as its own agent; use the next-agent key to switch back and forth. You can also ask the primary agent to delegate a task to the creator.

The creator is a separate agent, so it does not automatically see your current conversation. Briefly include the goal and any constraints in your request.

The creator looks up documentation on demand with its `SearchDocs` tool. `SearchDocs(query=...)` returns ranked, feed-back-able addresses of the form `path#heading-slug`, at most one per file; pass an address straight back as `SearchDocs(path=...)` to read it. `path` also accepts a whole file (`config/hooks.md`), one section (`config/hooks.md#configuration-options`), one config key from a sample block (`config/conf.md#dark-mode`), a directory or glob (`config/`, `config/*.md`), `/` for the docs root, and `file.md#` for that file's table of contents. `SearchDocs(query=..., mode="content")` returns chunk text instead of addresses; each chunk carries its docs path, heading, and line range, and navigation hints include copy-paste addresses. cecli does not inject documentation into the creator's context automatically.

When building custom tools or commands, the creator sees a `creator_requirements` context block listing the top-level modules installed in the Python environment running cecli (whether managed by pip, uv, or another installer). It uses that list to decide what can be imported; if a dependency is missing, it should tell you what to install instead of generating an extension that cannot import.

## What You Can Ask For

| Goal | Example request | What you get |
|------|-----------------|--------------|
| Add a skill | `/creator make a skill for reviewing Python diffs` | `.cecli/skills/<name>/SKILL.md`, recorded so agents can load it |
| Connect an MCP server | `/creator connect the github MCP server` | `mcp-servers.github` in `creator.yml`, connected on reload |
| Add a hook | `/creator block edits to generated files with a hook` | A hook source file plus its `hooks:` entry |
| Create a custom tool | `/creator add a tool that summarizes long logs` | `.cecli/tools/<name>.py`, registered on reload |
| Create a slash command | `/creator add a /deploy command` | `.cecli/commands/<name>.py` plus `custom.command-paths` |
| Define a workflow | `/creator triage open issues every morning` | `.cecli/workflows/<name>.yml` with an optional schedule |
| Change settings | `/creator make model X the default locally` | The setting deep-merged into `creator.yml` |

Examples of what changes:

```text
You:   /creator add a skill that reviews Python diffs for risky patterns
Creator: Wrote .cecli/skills/python-diff-review/SKILL.md
         Merged agent-config.skills_paths into .cecli/creator.yml
         Skills reloaded

You:   /creator connect the github MCP server locally
Creator: Added mcp-servers.github to .cecli/creator.yml
         MCP servers added: github
```

The practical benefit is always the same: the change survives restarts, takes effect in the current session without manual reloads or config editing, and can be committed or copied to another machine as part of your project.

## Local vs Global

Creator mode writes to one of two files:

| Choice | Where it lives | Who it affects |
|--------|----------------|----------------|
| **Local** (default) | `<project>/.cecli/creator.yml` and `<project>/.cecli/<type>/...` | Just this project; easy to commit and review |
| **Global** | `~/.cecli/creator.yml` and `~/.cecli/<type>/...` | Every project on this machine |

When you ask for a change, say whether you want it enabled **locally** (just this project) or **globally** (every project on this machine) — for example, "add this skill locally" or "enable this hook globally". If you do not say, creator mode uses local, which is the safer default: it keeps behavior reproducible and version-controlled with the project.

## Targeting Specific Agents

By default an entry goes into the shared config, which reaches the primary agent and agents that inherit from it. If you want an extension only for particular sub-agents, say so in plain language:

```text
/creator add the pdf-review skill, but only for the reviewer agent
/creator give every workflow agent access to the github MCP server
/creator add the release-notes skill for the release writer only
```

Supported targets are agent names (`reviewer`), patterns (`wf:*` for workflow workers, `ws:*` for workspace agents), or `*` for all sub-agents. The creator resolves and validates the names, then records per-agent entries under `agents:` in `creator.yml`.

> **Scoping is config-level, not physical isolation.** The skill file, hook source, or server definition is still written once in the shared `.cecli` location. `apply_to` controls which agents' configuration references or whitelists the entry; unfiltered agents may still discover file-backed artifacts. Use the exclude lists or an agent-specific directory when you need hard isolation. The exact rules are in the Advanced Reference section below.

## Seeing and Undoing Changes

Ask the creator to show its work:

```text
/creator list everything you have created
```

This prints both `creator.yml` files. To undo a change, ask the creator to remove it:

```text
/creator remove the pdf-review skill
/creator remove it for the reviewer agent only
/creator remove it and delete the files too
```

Backing files are left on disk by default so you can inspect them; say "delete the files" to remove them as well. The two config files are at `~/.cecli/creator.yml` and `<project>/.cecli/creator.yml`; backing files use the matching `.cecli/skills`, `hooks`, `tools`, `commands`, or `workflows` directory.

## Safety Notes

- The creator never hand-edits `.cecli.conf.yml`, `conf.yml`, or `creator.yml`. All writes go through its ManageExtensions tool, which merges rather than replaces existing content.
- It inspects existing files before changing them, but it is designed to run unattended, so review its summary and use `list` when you want to confirm what was persisted.
- Removing an entry prunes references but keeps backing files unless you ask to delete them.
- Settings that only apply at startup (for example some model/provider options) may need `/hot-reload` or a restart; the creator tells you when that is the case.

## Advanced Reference

Everything below describes the underlying ManageExtensions tool. You normally do not need it — ask the creator instead.

### ManageExtensions tool

The ManageExtensions tool is scoped to the creator sub-agent (`creator_mode: true`). The primary agent and other sub-agents cannot call it directly; delegate the request to the creator. One action runs per call.

| Action | Behavior |
|--------|----------|
| `add` | Build the entry and deep-merge its fragment into `creator.yml`. |
| `update` | Alias for `add`; existing keys are preserved. |
| `remove` | Remove the entry and prune references to it. |
| `list` | Print the parsed contents of both `creator.yml` files. |

| Argument | Required | Description |
|----------|----------|-------------|
| `action` | Yes | One of `add`, `update`, `remove`, `list`. |
| `type` | Yes | One of `mcp_server`, `hook`, `skill`, `custom_tool`, `custom_command`, `workflow`, `config`. |
| `scope` | No | `local` (default) or `global`. |
| `name` | Yes unless listing | Entry name. For `config`, a dotted key path such as `models.default`. |
| `config` | No | Payload deep-merged for the entry, or the value for a dotted `config` path. |
| `content` | No | Full file content for file-backed types (a `SKILL.md` body, a tool or hook `.py` source, a workflow YAML document). |
| `apply_to` | No | Agent names or patterns to scope the entry to, for example `["reviewer"]`, `["wf:*"]`, or `["*"]`. Omit for the shared config. Supported for `skill`, `mcp_server`, `hook`, and `config`. |

`creator.yml` is deep-merged **last** among config files, so its values take precedence over `.cecli/conf.yml` and `.cecli.conf.yml`; command-line switches still win. See [YAML Config File](conf.html) for the full precedence rules.

### Persistence by type

| Type | Default recording (shared) | With `apply_to` | Backing file |
|------|----------------------------|-----------------|--------------|
| `mcp_server` | `mcp-servers.<name>` plus a conditional `agent-config.servers_includelist` entry | Shared `mcp-servers.<name>`; each target that already filters gets the name in `agents.<target>.agent-config.servers_includelist` | None |
| `hook` | `hooks.<name>` | Shared `hooks.<name>`; each target gets the name in `agents.<target>.hooks` | Optional `<scope>/hooks/<name>.py` |
| `skill` | `agent-config.skills_paths` plus a conditional `agent-config.skills_includelist` entry | `agents.<target>.agent-config.skills_paths` (deduplicated on merge), plus `skills_includelist` only for targets that already filter | `<scope>/skills/<name>/SKILL.md` |
| `custom_tool` | `agent-config.tools_paths` (the default `~/.cecli/tools` and `<root>/.cecli/tools` dirs are also scanned) | Not supported | `<scope>/tools/<name>.py` |
| `custom_command` | `custom.command-paths` | Not supported | `<scope>/commands/<name>.py` |
| `workflow` | No fragment; discovered from `<scope>/workflows/` | Not supported | `<scope>/workflows/<name>.yml` |
| `config` | The dotted key path, nested as a mapping | Allowed only for `agent-config.*` or `hooks.*` paths with one exact agent name; written under `agents.<name>` | None |

#### `mcp_server`

Merges the server definition under `mcp-servers.<name>`. When a live coder already runs with a non-empty `servers_includelist`, the new server is also added to that whitelist so the reload does not leave it hidden.

```yaml
mcp-servers:
  demo:
    command: run-demo
    args:
      - --stdio
agent-config:
  servers_includelist:
    - demo
```

With `apply_to`, the `mcp-servers.<name>` definition stays shared and only filtering targets get an include-list entry. Removing an `mcp_server` with `apply_to` therefore leaves the shared definition in place; remove it without `apply_to`, or use `type: config` with `name: mcp-servers.<name>`. See [Model Context Protocol](mcp.html) for the server schema.

#### `hook`

Merges the hook definition under `hooks.<name>`. When `content` is supplied, it is written to `<scope>/hooks/<name>.py` and that path is recorded as the hook's `path` unless the payload already sets one.

```yaml
hooks:
  audit:
    path: /home/me/repo/.cecli/hooks/audit.py
```

See [Hooks](hooks.html) for the hook payload schema.

#### `skill`

Writes `<scope>/skills/<name>/SKILL.md` from `content`. If `content` is omitted and the file does not exist, ManageExtensions scaffolds a minimal `SKILL.md` with `name` and `description` front matter for the author to fill in. The skill directory is recorded in `agent-config.skills_paths`; when a live coder already runs with a non-empty `skills_includelist`, the new name is added there as well.

```yaml
agent-config:
  skills_paths:
    - /home/me/repo/.cecli/skills
  skills_includelist:
    - release-notes
```

After an `add`, the creator activates the skill for the targeted coders (or every live coder for a shared write): `include_skill` when a whitelist is active, then `load_skill`. A `remove` unloads it from those coders and, when its directory is left on disk, adds it to their live exclude list so it does not filter back in. See [Skills](skills.html) for the package format.

#### `custom_tool`

Writes `<scope>/tools/<name>.py` from `content` and records the scope's tools directory in `agent-config.tools_paths`. `~/.cecli/tools` and `<root>/.cecli/tools` are scanned by default, but recording the path keeps the directory explicit. If a live coder's `tools_excludelist` names the tool, ManageExtensions notes that the tool stays hidden there.

```yaml
agent-config:
  tools_paths:
    - /home/me/repo/.cecli/tools
```

#### `custom_command`

Writes `<scope>/commands/<name>.py` from `content` and records the file in `custom.command-paths`. See [Custom Commands](custom-commands.html) for the `CustomCommand` class format.

```yaml
custom:
  command-paths:
    - /home/me/repo/.cecli/commands/deploy.py
```

#### `workflow`

Writes `<scope>/workflows/<name>.yml` from `content` or from a dict `config` (a `name` is added when missing). Workflows are discovered by scanning the workflows directories, so ManageExtensions records **no fragment** in `creator.yml`. If the workflow has `enabled: false`, ManageExtensions warns that no `wf:<name>` sub-agent will register.

> **Important:** Workflows are never recorded as a top-level list of dicts in `creator.yml`. A `workflows:` list in that file would bypass the normal workflow file discovery and precedence rules.

See [Workflows](workflows.html) for the definition format.

#### `config`

Deep-merges an arbitrary value at a dotted key path. `config` supplies the value; if it is absent, `content` is parsed as YAML/JSON, falling back to the raw string. For example, `name: models.default` with `config: gpt-test` produces:

```yaml
models:
  default: gpt-test
```

### Agent targeting internals

By default every entry lands in the shared config. `apply_to` writes the entry under the top-level `agents:` map instead:

```yaml
agents:
  reviewer:
    agent-config:
      skills_paths:
        - /home/me/repo/.cecli/skills
      skills_includelist:
        - release-notes
    hooks:
      audit:
        path: /home/me/repo/.cecli/hooks/audit.py
  "wf:*":
    agent-config:
      servers_includelist:
        - github
```

`agents:` is read **only** from `creator.yml` (global then project-local); entries in `.cecli.conf.yml` or `.cecli/conf.yml` are ignored. ManageExtensions refreshes the index after every successful change, so sub-agents spawned later in the same session pick up the override without a restart.

**Names and patterns.** Targets are exact registry names or `fnmatch` patterns (`"*"`, `"wf:*"`, `"ws:*"`). When a sub-agent spawns, matching overrides merge most-specific-last:

```text
"*"  <  "wf:*" | "ws:*"  <  exact agent name
```

Override values merge on top of the agent's own front matter and inherited config. Each target must match at least one registered agent (`primary`/`main` are rejected because the shared config is theirs); unknown names raise an error listing available agents. Patterns are stored verbatim, so they also apply to matching agents created later.

**Whitelist gating.** Recording a name in `skills_includelist` or `servers_includelist` turns an unfiltered agent into a filtered one. Include-list entries are therefore recorded only for targets that already filter:

- **Skills**: the target's live `skills_manager.include_list` is non-empty. An empty set means "no filter".
- **MCP servers**: the target's config-authored `agent-config.servers_includelist` is non-empty. Runtime `registered_servers["included"]` is ignored because it is automatically populated for unfiltered users.

Mixed exact-name target sets are recorded per target. For a pattern, the include-list entry is written only when every agent the pattern currently matches already filters; otherwise the pattern is stored without it.

**Update and remove.** `update` behaves like `add`; `agents.<name>` deep-merges. `remove` with `apply_to` prunes only the matching `agents.<target>` entries and deletes entries that become empty; shared sections stay untouched. Without `apply_to`, removal performs the shared cleanup and also prunes the name from every `agents.*` override. `apply_to: ["*"]` prunes every override. For `mcp_server`, a scoped removal only edits `servers_includelist`; delete the shared definition by removing without `apply_to` or using `type: config` with `name: mcp-servers.<name>`.

**Defining agents.** An `agents:` entry whose name is not registered defines a new agent, registered as `creator:<name>` at startup:

```yaml
agents:
  writer:
    description: Release note writer
    prompt: |
      You write release notes.
    model: <weak_model>
    auto_reap: true
    agent-config:
      skills_includelist:
        - release-notes
```

The bare name `writer` does not resolve; delegate to `creator:writer`.

**Inheritance caveat.** A custom `.md` agent that declares its own `agent-config` does not inherit the shared config. Use `apply_to` to give that agent specific entries.

**Config-level isolation.** `apply_to` scopes the per-agent config records (`skills_paths`, `skills_includelist`, `hooks`, `servers_includelist`), not the backing artifacts. A scoped skill still lives under `<scope>/skills/<name>` (an implicit scan directory), a scoped hook still lands in the shared `hooks:` section (loaded session-wide), and a scoped MCP server still defines `mcp-servers.<name>` once. Unfiltered agents can therefore still discover or load these artifacts. Use `skills_excludelist` / `servers_excludelist` / `tools_excludelist` or an agent-specific directory for strict isolation.

### Removing entries and reload behavior

`remove` drops the matching entry from `creator.yml`:

- `mcp_server` and `hook` remove the `<name>` key from `mcp-servers` and `hooks`; `mcp_server` also drops the name from `agent-config.servers_includelist`.
- `config` removes the leaf at the dotted key path.
- `skill` and `custom_tool` prune path references from `skills_paths` / `tools_paths`; skills also prune `skills_includelist` and `skills_init`, and custom tools prune `tools_includelist` and `tools_excludelist`.
- `custom_command` prunes `custom.command-paths` and `custom.command_paths`.
- `workflow` prunes entries in a legacy `workflows` list that name the workflow.

For file-backed types (`hook`, `skill`, `custom_tool`, `custom_command`, `workflow`) the backing file is the entry: removal succeeds when that file exists even if `creator.yml` holds no reference, which covers skills and tools living in the implicit `.cecli/skills` or `.cecli/tools` directories.

Backing files are left on disk by default. Pass `config: {delete_files: true}` to a `remove` call to delete the skill directory or the tool, hook, command, or workflow file as well.

`action: list` prints both `creator.yml` files. Every `add`, `update`, and `remove` runs the reload helper for that type, so the change is visible immediately; skill additions and removals also activate or deactivate the skill for the relevant live coders. Tool output names the resolved targets for `apply_to` calls and explicitly marks shared-config writes.