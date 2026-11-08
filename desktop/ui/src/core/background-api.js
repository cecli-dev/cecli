/** JSON helpers for the desktop background command API. */

const BACKGROUND_ENDPOINT = '/api/background';

export async function list_background_commands(bridge_id) {
  const data = await post_background(bridge_id, { action: 'list' });
  const commands = Array.isArray(data?.commands) ? data.commands : [];

  return commands.map(normalize_command).filter(Boolean);
}

export async function fetch_background_output(bridge_id, command_key) {
  const data = await post_background(bridge_id, { action: 'output', key: command_key });

  return {
    output: typeof data?.output === 'string' ? data.output : '',
    command: normalize_command(data?.command),
  };
}

function timeout_signal() {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    return AbortSignal.timeout(8000);
  }

  return undefined;
}

async function post_background(bridge_id, payload) {
  let response;

  try {
    response = await fetch(BACKGROUND_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: timeout_signal(),
      body: JSON.stringify({ bridgeId: bridge_id, ...payload }),
    });
  } catch (error) {
    throw background_error(error?.message || 'Background service unreachable', 0);
  }

  let data = null;

  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }

  if (!response.ok || data?.ok === false) {
    const message =
      data?.error || data?.message || `Background request failed (${response.status})`;

    throw background_error(message, response.status);
  }

  return data || {};
}

function background_error(message, status) {
  const error = new Error(message);

  error.status = status;
  error.unavailable = status === 0 || status === 404 || status === 409 || status === 503;

  return error;
}

function normalize_command(item) {
  if (!item || typeof item !== 'object') return null;

  const key = item.key ?? item.id;

  if (!key) return null;

  return {
    key: String(key),
    command: typeof item.command === 'string' ? item.command : '',
    running: Boolean(item.running),
    persist: Boolean(item.persist),
    continued_in_background: Boolean(
      item.continuedInBackground ?? item.continued_in_background,
    ),
    buffer_size: to_number(item.bufferSize ?? item.buffer_size),
    pages: to_number(item.pages),
    total_chars: to_optional_number(item.totalChars ?? item.total_chars),
    start_time: item.startTime ?? item.start_time ?? null,
    end_time: item.endTime ?? item.end_time ?? null,
    duration: typeof item.duration === 'number' ? item.duration : null,
  };
}

function to_number(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function to_optional_number(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}