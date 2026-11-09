/** UI-side log ring for the CLI pane's Logs tab. */

const LIMIT = 2000;
const listeners = new Set();
let ring = [];
let sequence = 0;

export function push_terminal_log(entry) {
  sequence += 1;
  const line = {
    seq: sequence,
    level: entry.level || 'info',
    message: String(entry.message ?? ''),
    source: entry.source || entry.level || 'info',
    bridge_id: entry.bridge_id || entry.bridgeId || null,
    ts: entry.ts || Date.now(),
  };
  ring = [...ring, line];
  if (ring.length > LIMIT) ring = ring.slice(-LIMIT);
  for (const listener of listeners) listener(line);
}

export function get_terminal_logs(bridge_id = null) {
  if (!bridge_id) return ring;
  return ring.filter((entry) => !entry.bridge_id || entry.bridge_id === bridge_id);
}

export function subscribe_terminal_log(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function clear_terminal_logs() {
  ring = [];
}
