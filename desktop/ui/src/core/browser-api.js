import { get_desktop_token } from './token.js';

/** HTTP, WebSocket and SSE helpers for the in-app browser panel. */

const JSON_HEADERS = { 'Content-Type': 'application/json' };

function post_json(path, body, timeout_ms = 10000) {
  return request_json(path, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body === undefined ? {} : body),
    timeout_ms,
  });
}

/** GET the browser backend state. */
export function get_browser_state() {
  return request_json('/api/browser/state', { headers: { Accept: 'application/json' } });
}

/** Start the local browser process. */
export function start_browser() {
  return post_json('/api/browser/start', {}, 45000);
}

/** Navigate the browser to a url. The backend resolves bare domains. */
export function open_browser_url(url) {
  return post_json('/api/browser/open', { url });
}

/** Run a history/navigation action: back, forward, reload or stop. */
export function send_browser_action(action) {
  return post_json('/api/browser/action', { action });
}

/** Open a new browser tab and make it the shared target. */
export function new_browser_tab(url = null) {
  return post_json('/api/browser/tab/new', url ? { url } : {});
}

/** Close one open browser tab. */
export function close_browser_tab(tab_id) {
  return post_json('/api/browser/tab/close', { tabId: tab_id });
}

/** Switch the shared screencast to another open tab. */
export function select_browser_tab(tab_id) {
  return post_json('/api/browser/tab', { tabId: tab_id });
}
/** Tell the backend the CSS viewport size used for input mapping. */
export function set_browser_viewport(width, height, dpr) {
  return post_json('/api/browser/viewport', { width, height, dpr });
}

/** Forward one synthetic input event (mouse, wheel, key or text). */
export function send_browser_input(event) {
  return post_json('/api/browser/input', { event });
}

/** Open the binary WebSocket frame/state stream. */
export function open_browser_stream() {
  const token = get_desktop_token();
  const protocols = ['cecli.browser.v1'];
  if (token) protocols.push(`token.${token}`);
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(
    `${scheme}://${window.location.host}/api/browser/ws`,
    protocols,
  );
  socket.binaryType = 'arraybuffer';
  return socket;
}

/** Open the legacy server-sent frame/state stream. */
export function open_browser_sse() {
  return new EventSource('/api/browser/stream');
}

/** Answer the open JavaScript dialog. */
export function answer_browser_dialog(accept, prompt_text = '') {
  return post_json('/api/browser/dialog', { accept, promptText: prompt_text });
}

/** Attach files to the intercepted file input. */
export function upload_browser_files(files) {
  return post_json('/api/browser/file-chooser', { files }, 30000);
}

/** Dismiss an intercepted file chooser. */
export function cancel_browser_file_chooser() {
  return post_json('/api/browser/file-chooser', { cancel: true });
}

/** Open a completed download. */
export function open_browser_download(id) {
  return post_json('/api/browser/download', { action: 'open', id });
}

/** Open the current page in the user's default browser. */
export function open_browser_external(url = null) {
  return post_json('/api/browser/external', url ? { url } : {});
}

/** Dispatch a dropped file or text selection onto the page. */
export function drop_browser_files(payload) {
  return post_json('/api/browser/drop', payload, 30000);
}

async function request_json(path, options) {
  let response;
  const { timeout_ms = 10000, ...request } = options;
  if (
    !request.signal &&
    typeof AbortSignal !== 'undefined' &&
    typeof AbortSignal.timeout === 'function'
  ) {
    request.signal = AbortSignal.timeout(timeout_ms);
  }

  try {
    response = await fetch(path, request);
  } catch (error) {
    const failure = new Error(`Network error: ${error.message}`);
    failure.status = 0;
    throw failure;
  }

  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }

  if (!response.ok || (data && data.ok === false)) {
    const error = new Error(
      (data && (data.error || data.message)) || `Request failed (${response.status})`,
    );
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}
