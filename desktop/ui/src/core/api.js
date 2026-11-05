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
export async function get_state() {
  const response = await fetch('/api/state', { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`state request failed (${response.status})`);
  return response.json();
}
