/** Pure tab model and reconciliation for the CLI pane. */


export const MAX_BACKGROUND_TABS = 8;
export const MAX_INPUT_BYTES = 64 * 1024;
export const AUTO_CLOSE_MS = 30 * 1000;

export const LIVE_STATES = new Set(['starting', 'running', 'needs_input', 'stopping']);
export const FINISHED_STATES = new Set(['exited', 'failed', 'closed', 'lost']);

const INTERPRETERS = new Set([
  'bash', 'sh', 'zsh', 'fish', 'dash', 'node', 'nodejs', 'deno', 'bun',
  'python', 'python3', 'py', 'ruby', 'perl', 'php', 'uv', 'npx', 'npm',
  'pnpm', 'yarn', 'cargo', 'go', 'java', 'dotnet', 'poetry', 'pipenv',
]);

export function workspace_key(state) {
  const workspace = String(state?.workspace || '').trim().replace(/\\/g, '/').replace(/\/+$/, '');
  const bridge = String(state?.bridge_id || '').trim();
  return workspace || bridge || 'unassigned';
}

export function logs_key(workspace) {
  return `logs:${workspace}`;
}

export function shell_key(workspace) {
  return `shell:${workspace}`;
}

export function bg_key(bridge_id, command_key) {
  return `bg:${bridge_id || 'unknown'}:${command_key}`;
}

export function command_label(command, max_chars = 20) {
  const tokens = String(command || '').trim().split(/\s+/).filter(Boolean);
  let value = tokens[0] || 'command';

  if (INTERPRETERS.has(basename(value)) && tokens[1] && !tokens[1].startsWith('-')) {
    value = tokens[1];
  }

  const label = basename(value) || 'command';
  return label.length > max_chars ? `${label.slice(0, max_chars - 1)}\u2026` : label;
}

export function create_default_tabs(workspace, terminal_enabled = true) {
  const tabs = [
    {
      key: logs_key(workspace), kind: 'logs', workspace_key: workspace,
      bridge_id: null, cli_id: null, command_key: null, label: 'Logs',
      closeable: false, status: 'running', exit_code: null,
      started_at: null, finished_at: null, total_chars: 0, unread: 0,
      input_hint: false, pinned: false, input_owner: null,
    },
  ];

  if (terminal_enabled) {
    tabs.push({
      key: shell_key(workspace), kind: 'shell', workspace_key: workspace,
      bridge_id: null, cli_id: null, command_key: null, label: 'Shell',
      closeable: false, status: 'idle', exit_code: null,
      started_at: null, finished_at: null, total_chars: 0, unread: 0,
      input_hint: false, pinned: false, input_owner: null,
    });
  }

  return tabs;
}

export function monitor_state(state) {
  return !state || state === 'none' ? null : String(state);
}

export function normalize_input_owner(value) {
  if (value === null || value === undefined) return null;
  const owner = String(value);
  return owner === 'none' || owner === '' ? null : owner;
}

export function command_status(command) {
  const value = command?.state || command?.status;
  if (value) return String(value);
  if (command?.running) return 'running';
  if (command?.endedAt ?? command?.ended_at ?? command?.exitCode ?? command?.exit_code) return 'exited';
  return 'starting';
}

export function is_live_status(status) {
  return LIVE_STATES.has(status);
}

export function is_eligible_command(command) {
  if (!command || typeof command !== 'object') return false;
  if (command.persist && !(command.continuedInBackground ?? command.continued_in_background)) {
    return false;
  }
  return true;
}

export function command_to_tab(command, { bridge_id, workspace_key: workspace, now = Date.now() } = {}) {
  const command_key = String(command.key ?? command.commandKey ?? command.id ?? '');
  if (!command_key) return null;

  const cli_id = command.cliId || command.cli_id || `bg:${bridge_id || 'unknown'}:${command_key}`;
  const status = command_status(command);
  const ended_at = command.endedAt ?? command.ended_at ?? null;
  const started_at = command.startedAt ?? command.started_at ?? command.startTime ?? command.start_time ?? null;

  return {
    key: bg_key(bridge_id, command_key),
    kind: 'bg',
    workspace_key: workspace || 'unassigned',
    bridge_id: bridge_id || null,
    cli_id,
    command_key,
    label: command_label(command.command || command_key),
    closeable: true,
    status,
    exit_code: command.exitCode ?? command.exit_code ?? null,
    signal: command.signal ?? null,
    started_at: to_number_or_null(started_at),
    finished_at: to_number_or_null(ended_at) ?? (is_live_status(status) ? null : now),
    total_chars: Number(command.totalChars ?? command.total_chars ?? 0) || 0,
    unread: 0,
    input_hint: Boolean(command.needsInput ?? command.needs_input),
    last_prompt: command.lastPrompt ?? command.last_prompt ?? '',
    pinned: Boolean(command.pinned),
    input_owner: normalize_input_owner(command.inputOwner ?? command.input_owner),
    seq: Number(command.seq ?? 0) || 0,
    start_seq: Number(command.startSeq ?? command.start_seq ?? 0) || 0,
  };
}

export function reconcile_tabs(tabs, commands, options = {}) {
  const {
    workspace_key: workspace = 'unassigned',
    bridge_id = null,
    terminal_enabled = true,
    baseline = false,
    active_key = null,
    now = Date.now(),
  } = options;

  const defaults = create_default_tabs(workspace, terminal_enabled);
  const existing = new Map((tabs || []).filter((tab) => tab.kind === 'bg').map((tab) => [tab.key, tab]));
  let next = [
    ...defaults.map((tab) => {
      const prior = (tabs || []).find((item) => item.key === tab.key);
      return prior ? { ...prior, ...tab, unread: prior.unread || 0, status: prior.status } : tab;
    }),
    ...(tabs || []).filter((tab) => tab.kind === 'bg'),
  ];

  const seen = new Set();
  const archived = [];

  for (const command of commands || []) {
    if (!is_eligible_command(command)) continue;

    const tab = command_to_tab(command, { bridge_id, workspace_key: workspace, now });
    if (!tab) continue;

    seen.add(tab.key);
    const prior = existing.get(tab.key);

    if (prior) {
      const unread = tab.key === active_key
        ? 0
        : prior.unread + (should_count_unread(prior, tab) ? 1 : 0);
      next = next.map((item) =>
        item.key === tab.key
          ? { ...prior, ...tab, unread, pinned: prior.pinned || tab.pinned }
          : item,
      );
      continue;
    }

    if (baseline && !is_live_status(tab.status)) continue;
    next.push(tab);
  }

  next = next.map((tab) => {
    if (tab.kind !== 'bg' || seen.has(tab.key)) return tab;
    if (!is_live_status(tab.status) || tab.status === 'lost') return tab;

    return { ...tab, status: 'lost', finished_at: tab.finished_at || now };
  });

  next = enforce_pressure(next, archived, now);
  return { tabs: next, archived };
}
export function apply_cli_event(tabs, payload, options = {}) {
  const {
    workspace_key: workspace = 'unassigned',
    bridge_id = null,
    active_key = null,
    now = Date.now(),
  } = options;
  const event = String(payload?.event || payload?.type || '');
  const command_key = payload?.key ?? payload?.commandKey;
  if (!command_key) return tabs;

  const key = bg_key(bridge_id, command_key);
  const existing = (tabs || []).find((tab) => tab.key === key);

  if (event === 'closed') return (tabs || []).filter((tab) => tab.key !== key);

  const command = payload.entry || payload.command || payload;
  const base = existing || command_to_tab({ ...command, key: command_key }, { bridge_id, workspace_key: workspace, now });
  if (!base) return tabs;

  let next = { ...base, updated_at: now };

  if (event === 'started') next.status = is_live_status(next.status) ? next.status : 'running';
  if (event === 'needs_input') {
    next.status = 'needs_input';
    next.input_hint = true;
    next.last_prompt = payload.lastPrompt ?? payload.last_prompt ?? next.last_prompt;
  }
  if (event === 'state') {
    const state = payload.state || command.state;
    if (state) next.status = String(state);
  }
  if (event === 'exited') {
    next.status = 'exited';
    next.exit_code = payload.exitCode ?? payload.exit_code ?? payload.code ?? next.exit_code ?? null;
    next.signal = payload.signal ?? next.signal ?? null;
    next.finished_at = payload.endedAt ?? payload.ended_at ?? now;
    next.input_hint = false;
  }
  if (event === 'error') {
    next.status = 'error';
    next.error = payload.message || payload.error || '';
  }

  const unread = key === active_key
    ? 0
    : existing && should_count_unread(existing, next)
      ? (existing.unread || 0) + 1
      : existing?.unread || 0;
  next = { ...next, unread };

  const output = (tabs || []).filter((tab) => tab.key !== key);
  output.push(next);
  return output;
}

export function set_tab_status(tabs, key, status, patch = {}) {
  return (tabs || []).map((tab) => (tab.key === key ? { ...tab, ...patch, status } : tab));
}

export function mark_tab_lost(tabs, key, now = Date.now()) {
  return (tabs || []).map((tab) =>
    tab.key === key && tab.kind === 'bg'
      ? { ...tab, status: 'lost', finished_at: tab.finished_at || now }
      : tab,
  );
}

export function activate_tab(tabs, key) {
  return (tabs || []).map((tab) => (tab.key === key ? { ...tab, unread: 0 } : tab));
}

export function count_unread(tabs) {
  return (tabs || []).reduce((sum, tab) => sum + (Number(tab.unread) || 0), 0);
}

export function close_tab(tabs, key, active_key) {
  const index = (tabs || []).findIndex((tab) => tab.key === key);
  if (index < 0) return { tabs, active_key };

  const tab = tabs[index];

  const next = tabs.filter((item) => item.key !== key);
  let next_active = active_key;

  if (active_key === key) {
    const previous = next[index - 1] || next[0] || null;
    next_active = previous?.key || null;
  }

  return { tabs: next, active_key: next_active };
}

export function archive_tab(tabs, key) {
  const tab = (tabs || []).find((item) => item.key === key) || null;
  return { tabs: (tabs || []).filter((item) => item.key !== key), archived: tab };
}

export function auto_close_due(tabs, { enabled = false, now = Date.now(), active_key = null } = {}) {
  if (!enabled) return [];

  return (tabs || [])
    .filter((tab) =>
      tab.kind === 'bg'
      && FINISHED_STATES.has(tab.status)
      && tab.key !== active_key
      && !tab.pinned
      && tab.finished_at !== null
      && now - tab.finished_at >= AUTO_CLOSE_MS,
    )
    .map((tab) => tab.key);
}

export function input_payload({
  bridge_id, cli_id, input_seq, text = '', newline = true, release = false, owner = 'ui',
}) {
  if (release) return { bridgeId: bridge_id, cliId: cli_id, owner, release: true };

  return {
    bridgeId: bridge_id,
    cliId: cli_id,
    inputSeq: input_seq,
    owner,
    data: `${text}${newline ? '\n' : ''}`,
  };
}

export function release_payload({ bridge_id, cli_id, owner = 'ui' }) {
  return { bridgeId: bridge_id, cliId: cli_id, owner, release: true };
}

export function input_byte_length(text) {
  if (typeof TextEncoder === 'function') return new TextEncoder().encode(String(text || '')).byteLength;
  return String(text || '').length;
}

export function classify_input_error(status, response = null) {
  const code = response?.error || response?.code || '';

  if (status === 404 || code === 'not_found') {
    return { action: 'lost', notice: 'This background command no longer exists.' };
  }
  if (status === 409 || code === 'not_running') {
    return { action: 'exited', notice: 'The command is no longer running.' };
  }
  if (status === 423 || code === 'input_locked') {
    return { action: 'locked', notice: 'Another controller owns this prompt.' };
  }
  if (status === 429 || code === 'queue_full') {
    return { action: 'busy', notice: 'Input queue is full; wait for output.' };
  }
  if (status === 413 || code === 'too_large') {
    return { action: 'too_large', notice: 'Input exceeds the 64 KiB limit.' };
  }
  if (status === 400 || status === 501) {
    return { action: 'unsupported', notice: 'This bridge does not support background input.' };
  }

  return { action: 'error', notice: response?.message || 'Input failed.' };
}

function should_count_unread(prior, next) {
  if (!prior) return false;
  if (prior.status === next.status && prior.total_chars === next.total_chars) return false;
  if (next.status === 'needs_input' && prior.status !== 'needs_input') return true;
  return next.status !== 'lost' && (next.total_chars || 0) > (prior.total_chars || 0);
}

function enforce_pressure(tabs, archived, now) {
  let background = tabs.filter((tab) => tab.kind === 'bg');
  if (background.length <= MAX_BACKGROUND_TABS) return tabs;

  const removable = background
    .filter((tab) => FINISHED_STATES.has(tab.status) || tab.status === 'error')
    .sort((left, right) => (left.finished_at || 0) - (right.finished_at || 0));

  const drop = new Set();
  for (const tab of removable) {
    if (background.length - drop.size <= MAX_BACKGROUND_TABS) break;
    drop.add(tab.key);
    archived.push({ ...tab, archived_at: now });
  }

  if (!drop.size) return tabs;
  return tabs.filter((tab) => !drop.has(tab.key));
}

function basename(value) {
  const trimmed = String(value).replace(/[\\/]+$/, '');
  const parts = trimmed.split(/[\\/]/);
  return parts[parts.length - 1] || trimmed;
}

function to_number_or_null(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}