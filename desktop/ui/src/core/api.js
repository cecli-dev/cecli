/** JSON helpers for the bridge API. */

/** POST JSON and surface bridge error bodies as thrown messages. */
export async function post_json(path, body) {
  let response;

  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body === undefined ? {} : body),
    });
  } catch (error) {
    throw new Error(`Network error: ${error.message}`);
  }

  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }

  if (!response.ok) {
    const message =
      data && (data.error || data.message)
        ? data.error || data.message
        : `Request failed (${response.status})`;
    throw new Error(message);
  }

  return data;
}

/** GET the authoritative /api/state snapshot. */
export async function get_state(bridge_id) {
  const query = bridge_id ? `?bridgeId=${encodeURIComponent(bridge_id)}` : '';
  const response = await fetch(`/api/state${query}`, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`state request failed (${response.status})`);
  return response.json();
}

/** GET the sidebar session summaries without loading a full bridge state. */
export async function get_sessions() {
  const response = await fetch('/api/sessions', { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`sessions request failed (${response.status})`);
  return response.json();
}

/** GET one bridge's replayed conversation stream. */
export async function get_history(bridge_id) {
  const query = bridge_id ? `?bridgeId=${encodeURIComponent(bridge_id)}` : '';
  const response = await fetch(`/api/history${query}`, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`history request failed (${response.status})`);
  return response.json();
}

/** POST composer text and return completion candidates. */
export async function post_complete(bridge_id, text) {
  return post_json('/api/complete', {
    ...(bridge_id ? { bridgeId: bridge_id } : {}),
    text,
  });
}
