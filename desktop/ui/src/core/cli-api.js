/** Canonical /api/cli client. Background uses SSE + POST input; shell stays on /api/terminal. */

import { get_desktop_token } from './token.js';

export async function get_cli_state(bridge_id) {
  const query = bridge_id ? `?bridgeId=${encodeURIComponent(bridge_id)}` : '';
  const response = await fetch(`/api/cli/state${query}`, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw await response_error(response, 'CLI state failed');

  const data = await response.json();
  return {
    ready: Boolean(data?.ok ?? true),
    bridge_id: data?.bridgeId || bridge_id || null,
    workspace: data?.workspace || '',
    terminals: Array.isArray(data?.terminals) ? data.terminals : [],
    background: (Array.isArray(data?.background) ? data.background : []).map(normalize_background).filter(Boolean),
  };
}

export function open_cli_stream(bridge_id, cli_id, since = 0) {
  const params = new URLSearchParams({
    bridgeId: bridge_id || '',
    cliId: cli_id || '',
    since: String(Math.max(0, Number(since) || 0)),
  });

  return new EventSource(`/api/cli/stream?${params.toString()}`);
}

export function send_cli_input(payload) {
  return post_cli('/api/cli/input', payload);
}

export function stop_cli(bridge_id, cli_id) {
  return post_cli('/api/cli/stop', { bridgeId: bridge_id, cliId: cli_id });
}

export function close_cli(bridge_id, cli_id) {
  return post_cli('/api/cli/close', { bridgeId: bridge_id, cliId: cli_id });
}

export function resize_cli(bridge_id, cli_id, cols, rows) {
  return post_cli('/api/cli/resize', { bridgeId: bridge_id, cliId: cli_id, cols, rows });
}

export function normalize_background(item) {
  if (!item || typeof item !== 'object') return null;

  const key = item.key ?? item.commandKey ?? item.command_key;
  if (!key) return null;

  return {
    key: String(key),
    cli_id: item.cliId || item.cli_id || `bg:${item.bridgeId || item.bridge_id || 'unknown'}:${key}`,
    bridge_id: item.bridgeId || item.bridge_id || null,
    command: typeof item.command === 'string' ? item.command : '',
    running: Boolean(item.running),
    state: item.state || (item.running ? 'running' : 'exited'),
    persist: Boolean(item.persist),
    continued_in_background: Boolean(item.continuedInBackground ?? item.continued_in_background),
    started_at: item.startedAt ?? item.started_at ?? null,
    ended_at: item.endedAt ?? item.ended_at ?? null,
    exit_code: item.exitCode ?? item.exit_code ?? null,
    signal: item.signal ?? null,
    total_chars: Number(item.totalChars ?? item.total_chars ?? 0) || 0,
    needs_input: Boolean(item.needsInput ?? item.needs_input),
    last_prompt: item.lastPrompt ?? item.last_prompt ?? '',
    cols: Number(item.cols ?? 0) || 0,
    rows: Number(item.rows ?? 0) || 0,
    input_owner: item.inputOwner ?? item.input_owner ?? null,
    seq: Number(item.seq ?? 0) || 0,
    start_seq: Number(item.startSeq ?? item.start_seq ?? 0) || 0,
    consumed_at: item.consumedAt ?? item.consumed_at ?? null,
    pty: Boolean(item.pty),
  };
}

async function post_cli(path, payload) {
  const token = get_desktop_token();
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['X-Cecli-Token'] = token;

  let response;

  try {
    response = await fetch(path, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload === undefined ? {} : payload),
    });
  } catch (error) {
    throw request_error(error?.message || 'CLI request failed', 0);
  }

  let data = null;

  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }

  if (!response.ok || data?.ok === false) {
    const message = data?.error || data?.message || `CLI request failed (${response.status})`;
    const failure = request_error(message, response.status);
    failure.body = data;
    failure.code = data?.error || '';
    throw failure;
  }

  return data || {};
}

async function response_error(response, fallback) {
  let data = null;

  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }

  return request_error(data?.error || data?.message || `${fallback} (${response.status})`, response.status);
}

function request_error(message, status) {
  const error = new Error(message);
  error.status = status;
  error.unavailable = status === 0 || status === 404 || status === 501 || status === 503;
  return error;
}