/** Normalize terminal-state events so they stay scoped to one bridge. */

export function terminal_state_event(bridge_id, terminals) {
  return {
    bridge_id: String(bridge_id || ''),
    terminals: Array.isArray(terminals) ? terminals : [],
  };
}

export function resolve_terminal_state_event(detail, fallback_bridge_id = '') {
  if (Array.isArray(detail)) {
    const bridge_id = String(fallback_bridge_id || '');
    return bridge_id ? { bridge_id, terminals: detail } : null;
  }

  if (!detail || typeof detail !== 'object') return null;

  const bridge_id = String(detail.bridge_id || detail.bridgeId || '');
  if (!bridge_id || !Array.isArray(detail.terminals)) return null;

  return { bridge_id, terminals: detail.terminals };
}
