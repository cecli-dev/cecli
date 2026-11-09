/** JSON helpers for the bridge API. */

/** POST JSON and surface bridge error bodies as thrown messages. */
import { get_desktop_token } from './token.js';
export async function post_json(path, body) {
  let response;

  try {
    response = await fetch(path, {
      method: 'POST',
      headers: post_headers(),
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
    const error = new Error(message);
    error.status = response.status;
    error.body = data;
    throw error;
  }

  return data;
}

function post_headers() {
  const headers = { 'Content-Type': 'application/json' };
  const token = get_desktop_token();
  if (token) headers['X-Cecli-Token'] = token;
  return headers;
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

/** GET JSON, surfacing bridge error bodies as thrown messages. */
export async function get_json(path) {
  let response;

  try {
    response = await fetch(path, { headers: { Accept: 'application/json' } });
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

/** DELETE JSON, surfacing bridge error bodies as thrown messages. */
export async function delete_json(path, body) {
  let response;

  try {
    response = await fetch(path, {
      method: 'DELETE',
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

/** GET configured workspaces and their live session ids. */
export async function get_workspaces() {
  return get_json('/api/workspaces');
}

/** GET directory suggestions for the workspace path input. */
export async function get_directory_suggestions(path) {
  const query = path ? `?path=${encodeURIComponent(path)}` : '';
  return get_json(`/api/fs/dirs${query}`);
}

/** GET onboarding status and provider options. */
export async function get_onboarding_status() {
  return get_json('/api/onboarding/status');
}

export async function get_onboarding_providers(slug = null) {
  const query = slug ? `?slug=${encodeURIComponent(slug)}` : '';
  return get_json(`/api/onboarding/providers${query}`);
}

export async function get_copilot_status() {
  return get_json('/api/onboarding/copilot');
}

/** POST composer text and return completion candidates. */
export async function post_complete(bridge_id, text) {
  return post_json('/api/complete', {
    ...(bridge_id ? { bridgeId: bridge_id } : {}),
    text,
  });
}
