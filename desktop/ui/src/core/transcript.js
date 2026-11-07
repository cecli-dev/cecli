/**
 * Pure transcript reducers. Every function returns a new state object, or the
 * same object when the event changes nothing.
 */
import { extract_content_text, title_for_kind, tool_kind } from './format.js';


/** Add a user bubble to the transcript. */
export function append_user_message(state, text, agent_id = null) {
  const view = transcript_view(state, agent_id);
  const transcript = [
    ...stop_current(view),
    { id: next_id('user'), type: 'user', text },
  ];
  return commit_view(state, agent_id, transcript, null);
}

/** Add a collapsible message for injected context or agent-to-agent traffic. */
export function append_context_message(state, text, agent_id = null, title = 'Agent message', source = '') {
  const view = transcript_view(state, agent_id);
  const transcript = [
    ...stop_current(view),
    { id: next_id('context'), type: 'context', text, title, source },
  ];

  return commit_view(state, agent_id, transcript, null);
}
/** Begin a fresh assistant turn (called after a prompt is accepted). */
export function begin_assistant_turn(state, agent_id = null) {
  const finalized = finalize_assistant(state, agent_id);
  const view = transcript_view(finalized, agent_id);
  return commit_view(finalized, agent_id, view.transcript, null, {
    turn_sequence: finalized.turn_sequence + 1,
  });
}

/** Stream editable answer text into the current assistant turn. */
export function append_text_chunk(state, text, agent_id = null) {
  if (!text) return state;

  const current = current_assistant(state, agent_id);
  const last = current?.parts[current.parts.length - 1];

  if (current && last && last.type === 'text') {
    const assistant = {
      ...current,
      had_text: true,
      parts: current.parts.map((part) =>
        part.id === last.id ? { ...part, text: part.text + text, streaming: true } : part,
      ),
    };
    return update_assistant(state, assistant, agent_id);
  }

  const base =
    current && last && last.type === 'thought'
      ? { state, assistant: current }
      : start_assistant(state, agent_id);
  const assistant = collapse_thoughts({
    ...base.assistant,
    had_text: true,
    parts: [
      ...stop_text(base.assistant.parts),
      { id: next_id('text'), type: 'text', text, streaming: true },
    ],
  });

  return update_assistant(base.state, assistant, agent_id);
}

/** Append reasoning text, starting a new message when the block already moved on. */
export function append_thought_chunk(state, text, agent_id = null) {
  if (!text) return state;

  const current = current_assistant(state, agent_id);
  const last = current?.parts[current.parts.length - 1];
  const continuing = Boolean(current && last && last.type === 'thought');
  const base = continuing ? { state, assistant: current } : start_assistant(state, agent_id);

  const assistant = continuing
    ? {
        ...base.assistant,
        parts: base.assistant.parts.map((part) =>
          part.id === last.id ? { ...part, text: part.text + text } : part,
        ),
      }
    : {
        ...base.assistant,
        parts: [
          ...base.assistant.parts,
          { id: next_id('thought'), type: 'thought', text, open: false, auto_open: false },
        ],
      };

  return update_assistant(base.state, assistant, agent_id);
}
export function upsert_tool(state, update, is_new, agent_id = null) {
  const tool_id = String(update?.toolCallId);

  if (!is_new) {
    const found = find_tool(state, agent_id, tool_id);
    if (found) {
      return update_assistant(
        state,
        {
          ...found.assistant,
          parts: found.assistant.parts.map((part) =>
            part.id === found.part.id ? merge_tool_part(part, update) : part,
          ),
        },
        agent_id,
      );
    }
  }

  const ensured = ensure_assistant(state, agent_id);
  const existing = ensured.assistant.parts.find(
    (part) => part.type === 'tool' && part.tool_id === tool_id,
  );

  if (existing) {
    return update_assistant(
      ensured.state,
      {
        ...ensured.assistant,
        parts: ensured.assistant.parts.map((part) =>
          part.id === existing.id ? merge_tool_part(part, update) : part,
        ),
      },
      agent_id,
    );
  }

  const base = is_new ? stop_text(ensured.assistant.parts) : ensured.assistant.parts;
  const created = merge_tool_part(create_tool_part(tool_id), update);

  return update_assistant(
    ensured.state,
    { ...ensured.assistant, parts: [...base, created] },
    agent_id,
  );
}

/** Append a streamed tool content chunk, creating the card when needed. */
export function append_tool_chunk(state, update, agent_id = null) {
  const tool_id = String(update?.toolCallId);
  const text = extract_content_text(update?.content);
  const found = find_tool(state, agent_id, tool_id);

  if (found) {
    return update_assistant(
      state,
      {
        ...found.assistant,
        parts: found.assistant.parts.map((part) =>
          part.id === found.part.id ? { ...part, content_text: part.content_text + text } : part,
        ),
      },
      agent_id,
    );
  }

  const ensured = ensure_assistant(state, agent_id);
  const created = { ...create_tool_part(tool_id), content_text: text };

  return update_assistant(
    ensured.state,
    { ...ensured.assistant, parts: [...ensured.assistant.parts, created] },
    agent_id,
  );
}

/** Replace the current turn's plan checklist. */
export function set_plan(state, entries, agent_id = null) {
  const ensured = ensure_assistant(state, agent_id);
  const items = Array.isArray(entries)
    ? entries.map((entry) => ({ content: entry?.content || '', status: entry?.status || 'pending' }))
    : [];
  const existing = ensured.assistant.parts.find((part) => part.type === 'plan');

  if (existing) {
    return update_assistant(
      ensured.state,
      {
        ...ensured.assistant,
        parts: ensured.assistant.parts.map((part) =>
          part.id === existing.id ? { ...part, entries: items } : part,
        ),
      },
      agent_id,
    );
  }

  return update_assistant(
    ensured.state,
    {
      ...ensured.assistant,
      parts: [
        ...stop_text(ensured.assistant.parts),
        { id: next_id('plan'), type: 'plan', entries: items },
      ],
    },
    agent_id,
  );
}

/** Toggle a thought block, preserving the auto-collapse flag. */
export function set_thought_open(state, part_id, open, agent_id = null) {
  const assistant = current_assistant(state, agent_id);
  if (!assistant) return state;

  const existing = assistant.parts.find((part) => part.id === part_id);
  if (!existing || existing.open === open) return state;

  return update_assistant(
    state,
    {
      ...assistant,
      parts: assistant.parts.map((part) => (part.id === part_id ? { ...part, open } : part)),
    },
    agent_id,
  );
}

/** Stop every streaming text block in the current turn. */
export function finalize_assistant(state, agent_id = null) {
  const assistant = current_assistant(state, agent_id);
  if (!assistant) return state;

  const next = update_assistant(
    state,
    { ...assistant, parts: stop_text(assistant.parts) },
    agent_id,
  );

  return commit_view(next, agent_id, transcript_view(next, agent_id).transcript, null);
}

/** Drop every transcript item and reset per-turn bookkeeping. */
export function reset_transcript(state, reset_usage = true) {
  return {
    ...state,
    transcript: [],
    subagent_transcripts: {},
    subagent_current_assistant_ids: {},
    active_agent_session_id: null,
    permissions: [],
    current_assistant_id: null,
    turn_sequence: 0,
    auto_scroll: true,
    usage: reset_usage ? { used: 0, size: 0, cost: null } : state.usage,
  };
}

/** Add a pending permission request. Duplicate request ids are ignored. */
export function add_permission(state, payload) {
  const bridge_id = payload?.bridgeId || state.bridge_id || '';
  const key = bridge_id ? `${bridge_id}:${payload?.requestId}` : String(payload?.requestId);
  if (state.permissions.some((entry) => entry.key === key)) return state;

  const tool_call = payload?.toolCall || {};
  const detail = extract_content_text(tool_call.content).trim();

  return {
    ...state,
    permissions: [
      ...state.permissions,
      {
        key,
        request_id: payload?.requestId,
        tool_call,
        options: Array.isArray(payload?.options) ? payload.options : [],
        detail,
        resolved: false,
        resolving: false,
        chosen: null,
        status_kind: '',
        status_text: '',
      },
    ],
  };
}

/** Mark a permission request as submitting. */
export function set_permission_resolving(state, key, resolving) {
  const entry = state.permissions.find((item) => item.key === key);
  if (!entry || entry.resolving === resolving) return state;

  return {
    ...state,
    permissions: state.permissions.map((item) =>
      item.key === key ? { ...item, resolving } : item,
    ),
  };
}

/** Lock a permission card with the chosen option. */
export function mark_permission_resolved(state, key, option_id) {
  const entry = state.permissions.find((item) => item.key === key);
  if (!entry || entry.resolved) return state;

  const chosen = option_id === null || option_id === undefined ? null : String(option_id);
  const option = entry.options.find((item) => String(item.optionId) === chosen) || null;

  return {
    ...state,
    permissions: state.permissions.map((item) =>
      item.key === key
        ? {
            ...item,
            resolved: true,
            resolving: false,
            chosen,
            status_kind: option ? String(option.kind || '') : 'dismissed',
            status_text: chosen === null ? 'Dismissed' : option ? option.name : 'Selected',
          }
        : item,
    ),
  };
}

/** Remove one card after its cleanup delay. */
export function remove_permission(state, key) {
  if (!state.permissions.some((item) => item.key === key)) return state;
  return { ...state, permissions: state.permissions.filter((item) => item.key !== key) };
}

/** Remove every permission card. */
export function clear_permissions(state) {
  if (!state.permissions.length) return state;
  return { ...state, permissions: [] };
}

/** True while at least one card awaits a choice. */
export function has_pending_permissions(state) {
  return state.permissions.some((entry) => !entry.resolved);
}

/** Ensure the current assistant turn exists, returning state and item. */
function ensure_assistant(state, agent_id = null) {
  const existing = current_assistant(state, agent_id);
  if (existing) return { state, assistant: existing };

  const view = transcript_view(state, agent_id);
  const assistant = {
    id: next_id('turn'),
    type: 'assistant',
    turn: state.turn_sequence,
    parts: [],
    had_text: false,
  };

  const next_state = commit_view(state, agent_id, [...view.transcript, assistant], assistant.id);
  return { state: next_state, assistant };
}

function current_assistant(state, agent_id = null) {
  const view = transcript_view(state, agent_id);
  if (!view.current_id) return null;
  return view.transcript.find((item) => item.id === view.current_id) || null;
}

/** Append a fresh assistant message block and make it current. */
function start_assistant(state, agent_id = null) {
  const view = transcript_view(state, agent_id);
  const assistant = {
    id: next_id('turn'),
    type: 'assistant',
    turn: state.turn_sequence,
    parts: [],
    had_text: false,
  };

  const next_state = commit_view(
    state,
    agent_id,
    [...stop_current(view), assistant],
    assistant.id,
  );
  return { state: next_state, assistant };
}

/** Stop streaming text on the block that is about to be closed. */
function stop_current(view) {
  if (!view.current_id) return view.transcript;

  return view.transcript.map((item) =>
    item.id === view.current_id && item.type === 'assistant'
      ? { ...item, parts: stop_text(item.parts) }
      : item,
  );
}

function update_assistant(state, assistant, agent_id = null) {
  const view = transcript_view(state, agent_id);
  const transcript = view.transcript.map((item) =>
    item.id === assistant.id ? assistant : item,
  );
  return commit_view(state, agent_id, transcript, view.current_id);
}

/** Locate a tool card anywhere in the transcript so late updates stay in its block. */
function find_tool(state, agent_id, tool_id) {
  const view = transcript_view(state, agent_id);

  for (let index = view.transcript.length - 1; index >= 0; index -= 1) {
    const assistant = view.transcript[index];
    if (assistant.type !== 'assistant') continue;

    const part = assistant.parts.find(
      (candidate) => candidate.type === 'tool' && candidate.tool_id === tool_id,
    );
    if (part) return { assistant, part };
  }

  return null;
}

/** Auto-collapse reasoning once visible answer text begins. */
function collapse_thoughts(assistant) {
  const thought = assistant.parts.find((part) => part.type === 'thought');
  if (!thought) return assistant;

  const open = thought.auto_open && thought.open ? false : thought.open;

  return {
    ...assistant,
    parts: assistant.parts.map((part) =>
      part.id === thought.id ? { ...part, open, auto_open: false } : part,
    ),
  };
}

function stop_text(parts) {
  return parts.map((part) =>
    part.type === 'text' && part.streaming ? { ...part, streaming: false } : part,
  );
}

function create_tool_part(tool_id) {
  return {
    id: next_id('tool'),
    type: 'tool',
    tool_id,
    kind: 'other',
    title: 'Tool call',
    status: 'pending',
    locations: [],
    content_text: '',
  };
}

function merge_tool_part(part, update) {
  const next = { ...part };

  if (update.kind) next.kind = tool_kind(update.kind);
  if (update.title) next.title = update.title;
  else if (!next.title || next.title === 'Tool call') next.title = title_for_kind(next.kind);

  if (update.status) next.status = update.status;
  if (Array.isArray(update.locations)) next.locations = update.locations;

  if (update.content !== undefined) {
    const content = extract_content_text(update.content);
    if (content) next.content_text = content;
  }

  return next;
}

function next_id(prefix) {
  const uuid = globalThis.crypto?.randomUUID?.();
  const suffix = uuid || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${suffix}`;
}

function transcript_view(state, agent_id) {
  if (!agent_id) {
    return { transcript: state.transcript, current_id: state.current_assistant_id };
  }

  return {
    transcript: state.subagent_transcripts?.[agent_id] || [],
    current_id: state.subagent_current_assistant_ids?.[agent_id] || null,
  };
}

function commit_view(state, agent_id, transcript, current_id, extra = {}) {
  if (!agent_id) {
    return { ...state, ...extra, transcript, current_assistant_id: current_id };
  }

  return {
    ...state,
    ...extra,
    subagent_transcripts: {
      ...(state.subagent_transcripts || {}),
      [agent_id]: transcript,
    },
    subagent_current_assistant_ids: {
      ...(state.subagent_current_assistant_ids || {}),
      [agent_id]: current_id,
    },
  };
}
