/** JSON and socket helpers for the desktop terminal panel. */

import { post_json } from './api.js';
import { get_desktop_token } from './token.js';

export async function get_terminal_state(bridge_id) {
  const query = bridge_id ? `?bridgeId=${encodeURIComponent(bridge_id)}` : '';
  const response = await fetch(`/api/terminal/state${query}`, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`terminal state failed (${response.status})`);
  return response.json();
}

export function start_terminal(bridge_id, terminal_id = '') {
  const body = { bridgeId: bridge_id };
  if (terminal_id) body.terminalId = terminal_id;

  return post_json('/api/terminal/start', body);
}

export function create_terminal(bridge_id) {
  return post_json('/api/terminal/new', { bridgeId: bridge_id });
}

export function close_terminal(bridge_id, terminal_id) {
  return post_json('/api/terminal/close', { bridgeId: bridge_id, terminalId: terminal_id });
}

export function stop_terminal(bridge_id, terminal_id = '') {
  const body = { bridgeId: bridge_id };
  if (terminal_id) body.terminalId = terminal_id;

  return post_json('/api/terminal/stop', body);
}

export function post_terminal_input(bridge_id, data) {
  return post_json('/api/terminal/input', { bridgeId: bridge_id, data });
}

export function post_terminal_resize(bridge_id, cols, rows) {
  return post_json('/api/terminal/resize', { bridgeId: bridge_id, cols, rows });
}

export function open_terminal_socket(bridge_id, since = 0, terminal_id = '') {
  const token = get_desktop_token();
  const protocols = ['cecli.desktop.v1', `terminal.${bridge_id}`];
  if (token) protocols.push(`token.${token}`);
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const params = `bridgeId=${encodeURIComponent(bridge_id)}&since=${encodeURIComponent(since)}`;
  const terminal = terminal_id ? `&terminalId=${encodeURIComponent(terminal_id)}` : '';
  return new WebSocket(
    `${scheme}://${window.location.host}/api/terminal/ws?${params}${terminal}`,
    protocols,
  );
}
