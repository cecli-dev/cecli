/** Map decoded SSE payloads and ACP updates onto store transitions. */
import { extract_content_text, parse_message_text, update_kind } from './format.js';
import { push_log, push_toast } from './notices.js';
import {
  add_permission,
  append_text_chunk,
  append_context_message,
  append_user_message,
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
      handle_update(store, payload.update || {}, payload.sessionId, payload.bridgeId);
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
    case 'details':
      apply_details(store, payload);
      break;
    case 'subagents':
      apply_subagents(store, payload);
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
  if (store.patch_session) {
    store.patch_session({
      status: payload.status,
      activity: payload.activity,
      activityDetail: payload.detail,
    });
  }
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
function handle_update(store, update, session_id = null, bridge_id = null) {
  if (!update || typeof update !== 'object') return;

  if (update_kind(update) === 'subagent_update') {
    apply_subagent_update(store, update, bridge_id);
    return;
  }

  const agent_id = agent_for_session(store.state, session_id);

  if (update_kind(update) === 'session_message') {
    const recipient = update.recipientSessionId || session_id;
    const target_session = update.userMessage ? recipient : session_id;
    apply_session_message(store, update, agent_for_session(store.state, target_session));
    return;
  }

  switch (update_kind(update)) {
    case 'agent_message_chunk':
      store.update((state) =>
        append_text_chunk(state, extract_content_text(update.content), agent_id),
      );
      break;
    case 'agent_thought_chunk':
      store.update((state) =>
        append_thought_chunk(state, extract_content_text(update.content), agent_id),
      );
      break;
    case 'tool_call':
      store.update((state) => upsert_tool(state, update, true, agent_id));
      break;
    case 'tool_call_update':
      store.update((state) => upsert_tool(state, update, false, agent_id));
      break;
    case 'tool_call_content_chunk':
      store.update((state) => append_tool_chunk(state, update, agent_id));
      break;
    case 'plan':
      store.update((state) => set_plan(state, update.entries, agent_id));
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
      handle_state_update(store, update, agent_id);
      break;
    default:
      break;
  }
}

/** Mirror state_update into the composer status line. */
function handle_state_update(store, update, agent_id = null) {
  const next = update.state;

  if (agent_id) {
    store.update((state) => upsert_subagent_state(state, agent_id, next));
    if (next === 'idle') {
      store.update((state) => finalize_assistant(state, agent_id));
    }
    return;
  }

  if (next === 'requires_action') {
    store.update((state) => ({
      ...state,
      activity: 'requires_action',
      busy: true,
      turn_state: 'requires_action',
      busy_message: 'Waiting for your approval',
    }));
  } else if (next === 'running') {
    store.update((state) => ({
      ...state,
      activity: 'running',
      busy: true,
      turn_state: 'running',
      busy_message: 'cecli is working\u2026',
    }));
  } else if (next === 'idle') {
    store.update((state) => {
      const finalized = finalize_assistant(state);
      return {
        ...finalized,
        activity: 'idle',
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
      activity: 'idle',
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
  const bridge_id = payload.bridgeId || store.state.bridge_id || '';
  const key = bridge_id ? `${bridge_id}:${payload.requestId}` : String(payload.requestId);
  store.update((state) => restore_turn_state(mark_permission_resolved(state, key, payload.optionId)));

  if (typeof hooks.on_permission_resolved === 'function') hooks.on_permission_resolved(key);
}

/** Report bridge errors as toasts, never transcript spam. */
/** Replace registry/details state from one authoritative server snapshot. */
function apply_details(store, payload) {
  const details = payload.details || {};
  if (Array.isArray(payload.subagents)) apply_subagents(store, payload);
  store.update((state) => ({
    ...state,
    skills: Array.isArray(details.skills) ? details.skills : state.skills,
    mcp_servers: Array.isArray(details.mcpServers) ? details.mcpServers : state.mcp_servers,
    workflows: Array.isArray(details.workflows) ? details.workflows : state.workflows,
    context_files: Array.isArray(details.contextFiles)
      ? details.contextFiles
      : state.context_files,
  }));
}

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

/** The sub-agent session id an update belongs to, or null for the primary. */
function agent_for_session(state, session_id) {
  if (!session_id) return null;
  if (state.session_id && session_id === state.session_id) return null;
  return (state.subagents || []).some((agent) => agent.sessionId === session_id)
    ? session_id
    : null;
}

/** Merge one subagent announcement, state change or removal into the tree. */
function apply_subagent_update(store, update, bridge_id = null) {
  const session_id = update.sessionId;
  if (!session_id) return;

  store.update((state) => {
    const agents = state.subagents || [];
    const existing = agents.find((agent) => agent.sessionId === session_id) || {
      sessionId: session_id,
    };

    if (update.capabilities === null) {
      return {
        ...state,
        active_agent_session_id:
          state.active_agent_session_id === session_id ? null : state.active_agent_session_id,
        subagents: agents.map((agent) =>
          agent.sessionId === session_id
            ? { ...agent, removed: true, running: false, state: 'idle' }
            : agent,
        ),
      };
    }

    const next_agent = { ...existing, removed: false };
    if (update.title) next_agent.title = update.title;
    if (update.description) next_agent.description = update.description;
    if (update.capabilities) next_agent.announced = true;
    if (update.state && typeof update.state === 'object') {
      next_agent.state = update.state.state || 'idle';
      next_agent.running = next_agent.state === 'running';
      if (update.state.stopReason) next_agent.stopReason = update.state.stopReason;
      if (update.state.error) next_agent.error = update.state.error;
    }

    const next_agents = agents.some((agent) => agent.sessionId === session_id)
      ? agents.map((agent) => (agent.sessionId === session_id ? next_agent : agent))
      : [...agents, next_agent];

    return {
      ...state,
      subagents: next_agents,
      subagent_transcripts: state.subagent_transcripts[session_id]
        ? state.subagent_transcripts
        : { ...state.subagent_transcripts, [session_id]: [] },
    };
  });

  if (bridge_id && store.patch_session) {
    store.patch_session(bridge_id, {
      subagents: store.state.subagents,
    });
  }
}

/** Replace the sub-agent tree from a server snapshot/event. */
function apply_subagents(store, payload) {
  const incoming = Array.isArray(payload.subagents) ? payload.subagents : [];
  store.update((state) => {
    const by_id = new Map((state.subagents || []).map((agent) => [agent.sessionId, agent]));
    for (const agent of incoming) {
      if (!agent?.sessionId) continue;
      by_id.set(agent.sessionId, { ...by_id.get(agent.sessionId), ...agent, removed: false });
    }

    const subagent_transcripts = { ...state.subagent_transcripts };
    for (const agent of incoming) {
      if (agent?.sessionId && !subagent_transcripts[agent.sessionId]) {
        subagent_transcripts[agent.sessionId] = [];
      }
    }

    const active_agent_session_id =
      state.active_agent_session_id && by_id.has(state.active_agent_session_id)
        ? state.active_agent_session_id
        : null;

    return {
      ...state,
      active_agent_session_id,
      subagents: [...by_id.values()],
      subagent_transcripts,
    };
  });

  if (payload.bridgeId && store.patch_session) {
    store.patch_session(payload.bridgeId, { subagents: incoming });
  }
}

function upsert_subagent_state(state, session_id, next_state) {
  return {
    ...state,
    subagents: (state.subagents || []).map((agent) =>
      agent.sessionId === session_id
        ? { ...agent, state: next_state, running: next_state === 'running' }
        : agent,
    ),
  };
}

/** A message between agents, rendered in the receiving transcript. */
function apply_session_message(store, update, agent_id) {
  const raw = extract_content_text(update.content);
  const parsed = parse_message_text(raw);
  if (!parsed.text) return;

  const is_user = Boolean(update.userMessage) || parsed.is_user;
  const title = context_title(parsed.context_name);

  store.update((state) =>
    is_user
      ? append_user_message(state, parsed.text, agent_id)
      : append_context_message(
          state,
          parsed.text,
          agent_id,
          title,
          sender_label(state, update.senderSessionId) || parsed.from,
        ),
  );
}

/** Human title for a context envelope name such as ``sub_agent_result``. */
function context_title(name) {
  const value = String(name || '').trim();
  if (!value) return 'Agent message';

  const label = value.replace(/[_-]+/g, ' ').trim();
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/** Human label for the session that sent an inter-agent message. */
function sender_label(state, sender_session_id) {
  if (!sender_session_id) return '';
  if (state.session_id && sender_session_id === state.session_id) return 'Main';

  const agent = (state.subagents || []).find(
    (item) => item.sessionId === sender_session_id,
  );
  return agent?.title || agent?.name || String(sender_session_id);
}

/** Whether an update belongs to the session currently on screen. */
function update_matches_session(store, payload) {
  if (!payload || !payload.update) return false;
  if (!payload.sessionId) return true;

  const state = store.state;
  if (!state.session_id) return false;
  if (payload.sessionId === state.session_id) return true;
  return state.subagents.some((agent) => agent.sessionId === payload.sessionId);
}

/** Whether a permission request belongs to the session currently on screen. */
function permission_matches_session(store, payload) {
  if (!payload || payload.requestId === undefined) return false;
  if (!payload.sessionId) return true;

  const state = store.state;
  if (!state.session_id || payload.sessionId === state.session_id) return true;
  return state.subagents.some((agent) => agent.sessionId === payload.sessionId);
}

/** Return to running/idle once no permission cards remain. */
export function restore_turn_state(state) {
  if (has_pending_permissions(state)) return state;

  const turn_state = state.busy ? 'running' : 'idle';
  const busy_message = state.busy ? 'cecli is working…' : '';

  if (state.turn_state === turn_state && state.busy_message === busy_message) return state;
  return { ...state, turn_state, busy_message };
}
