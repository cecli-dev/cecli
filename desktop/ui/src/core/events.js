/** Map decoded SSE payloads and ACP updates onto store transitions. */
import { extract_content_text, update_kind } from './format.js';
import { push_log, push_toast } from './notices.js';
import {
  add_permission,
  append_text_chunk,
  append_thought_chunk,
  append_tool_chunk,
  clear_permissions,
  finalize_assistant,
  has_pending_permissions,
  mark_permission_resolved,
  reset_transcript,
  set_plan,
  upsert_tool,
} from './transcript.js';

/** Route one decoded SSE payload. */
export function handle_event(store, payload, hooks = {}) {
  if (!payload || typeof payload !== 'object') return;

  switch (payload.type) {
    case 'status':
      handle_status_event(store, payload);
      break;
    case 'session':
      handle_session_event(store, payload);
      break;
    case 'update':
      if (!update_matches_session(store, payload)) break;
      handle_update(store, payload.update || {});
      break;
    case 'permission':
      if (!permission_matches_session(store, payload)) break;
      store.update((state) => show_permission(state, payload));
      break;
    case 'permission_resolved':
      handle_permission_resolved(store, payload, hooks);
      break;
    case 'prompt_done':
      handle_prompt_done(store, payload, hooks);
      break;
    case 'log':
      push_log(store, payload.message, payload.level || 'info');
      break;
    case 'error':
      handle_error_event(store, payload);
      break;
    default:
      break;
  }
}

/** Add a permission request and put the turn into requires_action. */
function show_permission(state, payload) {
  const next = add_permission(state, payload);
  if (next === state) return state;

  return {
    ...next,
    busy: true,
    turn_state: 'requires_action',
    busy_message: 'Waiting for your approval',
  };
}

/** Status transitions from the bridge. */
function handle_status_event(store, payload) {
  if (payload.agent) store.update((state) => apply_agent(state, payload.agent));
  if (payload.detail) push_log(store, String(payload.detail), 'info');

  if (payload.status === 'exited') {
    store.update((state) => {
      const finalized = finalize_assistant(state);
      return {
        ...clear_permissions(finalized),
        busy: false,
        stopping: false,
        busy_message: '',
        turn_state: 'idle',
        retry_available: Boolean(state.last_prompt),
      };
    });
    push_toast(store, 'cecli exited', 'error');
  }

  apply_status(store, payload.status);
}

/** Session creation/replacement resets stale transcript contents. */
function handle_session_event(store, payload) {
  adopt_session(store, payload.sessionId);
  if (payload.modes) store.update((state) => ({ ...state, modes: payload.modes }));
  if (Array.isArray(payload.configOptions)) {
    replace_config_options(store, payload.configOptions);
  }
}

/** One ACP update, passed through by the bridge. */
function handle_update(store, update) {
  if (!update || typeof update !== 'object') return;

  switch (update_kind(update)) {
    case 'agent_message_chunk':
      store.update((state) => append_text_chunk(state, extract_content_text(update.content)));
      break;
    case 'agent_thought_chunk':
      store.update((state) => append_thought_chunk(state, extract_content_text(update.content)));
      break;
    case 'tool_call':
      store.update((state) => upsert_tool(state, update, true));
      break;
    case 'tool_call_update':
      store.update((state) => upsert_tool(state, update, false));
      break;
    case 'tool_call_content_chunk':
      store.update((state) => append_tool_chunk(state, update));
      break;
    case 'plan':
      store.update((state) => set_plan(state, update.entries));
      break;
    case 'usage_update':
      store.update((state) => apply_usage(state, update));
      break;
    case 'config_option_update':
      replace_config_options(store, update.configOptions);
      break;
    case 'current_mode_update':
      store.update((state) => set_mode(state, update.currentModeId));
      break;
    case 'state_update':
      handle_state_update(store, update);
      break;
    default:
      break;
  }
}

/** Mirror state_update into the composer status line. */
function handle_state_update(store, update) {
  const next = update.state;

  if (next === 'requires_action') {
    store.update((state) => ({
      ...state,
      busy: true,
      turn_state: 'requires_action',
      busy_message: 'Waiting for your approval',
    }));
  } else if (next === 'running') {
    store.update((state) => ({
      ...state,
      busy: true,
      turn_state: 'running',
      busy_message: 'cecli is working…',
    }));
  } else if (next === 'idle') {
    store.update((state) => {
      const finalized = finalize_assistant(state);
      return {
        ...finalized,
        busy: false,
        stopping: false,
        turn_state: 'idle',
        busy_message: '',
      };
    });
  }
}

/** Finish a turn after prompt_done. */
function handle_prompt_done(store, payload, hooks) {
  store.update((state) => {
    const finalized = clear_permissions(finalize_assistant(state));
    return {
      ...finalized,
      busy: false,
      stopping: false,
      turn_state: 'idle',
      busy_message: '',
      retry_available:
        payload && payload.stopReason === 'cancelled'
          ? Boolean(state.last_prompt)
          : state.retry_available,
    };
  });

  if (payload && payload.stopReason === 'cancelled') push_log(store, 'turn cancelled', 'info');
  if (typeof hooks.on_prompt_done === 'function') hooks.on_prompt_done();
}

/** React to permission_resolved: keep the chosen card and other pending ones. */
function handle_permission_resolved(store, payload, hooks) {
  const key = String(payload.requestId);

  store.update((state) => restore_turn_state(mark_permission_resolved(state, key, payload.optionId)));

  if (typeof hooks.on_permission_resolved === 'function') hooks.on_permission_resolved(key);
}

/** Report bridge errors as toasts, never transcript spam. */
function handle_error_event(store, payload) {
  const message = payload.message || 'Unknown bridge error';
  store.update((state) => ({ ...state, retry_available: Boolean(state.last_prompt) }));
  push_log(store, message, 'error');
  push_toast(store, message, 'error');
}

/** Adopt a session id, clearing stale transcript when it changes. */
export function adopt_session(store, session_id) {
  if (!session_id) return;

  let restarted = false;

  store.update((state) => {
    if (state.session_id && state.session_id !== session_id) {
      restarted = true;
      return { ...reset_transcript(state, false), session_id };
    }

    if (state.session_id === session_id) return state;
    return { ...state, session_id };
  });

  if (restarted) push_toast(store, 'Session restarted', 'info');
}

/** Set the visible bridge status, collapsing the turn when the child exits. */
export function apply_status(store, status) {
  store.update((state) => {
    const next_status = status || state.status;
    const exited = next_status === 'exited';

    if (state.status === next_status && (!exited || !state.busy)) return state;

    return {
      ...state,
      status: next_status,
      busy: exited ? false : state.busy,
      stopping: exited ? false : state.stopping,
      busy_message: exited ? '' : state.busy_message,
    };
  });
}

/** Update agent name/version. */
export function apply_agent(state, agent) {
  if (!agent) return state;

  const name = agent.name || state.agent.name;
  const version = agent.version || '';

  if (state.agent.name === name && state.agent.version === version) return state;
  return { ...state, agent: { name, version } };
}

/** Update the workspace path display. */
export function set_workspace(state, path) {
  if (typeof path !== 'string' || !path || state.workspace === path) return state;
  return { ...state, workspace: path };
}

/** Merge a usage_update payload. */
export function apply_usage(state, update) {
  const used = Number(update.used);
  const size = Number(update.size);
  const usage = { ...state.usage };

  if (Number.isFinite(used)) usage.used = used;
  if (Number.isFinite(size)) usage.size = size;
  if (update.cost) usage.cost = update.cost;

  if (
    usage.used === state.usage.used &&
    usage.size === state.usage.size &&
    usage.cost === state.usage.cost
  ) {
    return state;
  }

  return { ...state, usage };
}

/** Replace the config option list. */
export function replace_config_options(store, options) {
  if (!Array.isArray(options)) return;
  store.update((state) =>
    state.config_options === options ? state : { ...state, config_options: options },
  );
}

/** Reflect current_mode_update into the mode option. */
export function set_mode(state, current_mode_id) {
  if (current_mode_id === undefined || current_mode_id === null) return state;

  const value = String(current_mode_id);
  let changed = false;
  const config_options = state.config_options.map((option) => {
    if (option.id !== 'mode') return option;
    if (String(option.currentValue) === value) return option;
    changed = true;
    return { ...option, currentValue: current_mode_id };
  });

  if (!changed) return state;
  return { ...state, config_options };
}

/** Whether an update belongs to the session currently on screen. */
function update_matches_session(store, payload) {
  const session_id = store.state.session_id;
  if (!session_id) return false;

  return !payload.sessionId || payload.sessionId === session_id;
}

/** Whether a permission request belongs to the session on screen. */
function permission_matches_session(store, payload) {
  const session_id = store.state.session_id;
  if (!session_id || !payload.sessionId) return true;

  return payload.sessionId === session_id;
}

/** Return to running/idle once no permission cards remain. */
export function restore_turn_state(state) {
  if (has_pending_permissions(state)) return state;

  const turn_state = state.busy ? 'running' : 'idle';
  const busy_message = state.busy ? 'cecli is working…' : '';

  if (state.turn_state === turn_state && state.busy_message === busy_message) return state;
  return { ...state, turn_state, busy_message };
}
