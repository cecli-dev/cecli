/**
 * Pure transcript reducers. Every function returns a new state object, or the
 * same object when the event changes nothing.
 */
import { extract_content_text, title_for_kind, tool_kind } from './format.js';


/** Add a user bubble to the transcript. */
export function append_user_message(state, text) {
  return {
    ...state,
    transcript: [...state.transcript, { id: next_id('user'), type: 'user', text }],
  };
}

/** Begin a fresh assistant turn (called after a prompt is accepted). */
export function begin_assistant_turn(state) {
  return {
    ...finalize_assistant(state),
    current_assistant_id: null,
    turn_sequence: state.turn_sequence + 1,
  };
}

/** Stream editable answer text into the current assistant turn. */
export function append_text_chunk(state, text) {
  if (!text) return state;

  const ensured = ensure_assistant(state);
  let assistant = collapse_thoughts({ ...ensured.assistant, had_text: true });
  const last = assistant.parts[assistant.parts.length - 1];

  if (last && last.type === 'text') {
    assistant = {
      ...assistant,
      parts: assistant.parts.map((part) =>
        part.id === last.id ? { ...part, text: part.text + text, streaming: true } : part,
      ),
    };
  } else {
    assistant = {
      ...assistant,
      parts: [
        ...stop_text(assistant.parts),
        { id: next_id('text'), type: 'text', text, streaming: true },
      ],
    };
  }

  return update_assistant(ensured.state, assistant);
}

/** Append reasoning text to the turn's collapsible thought block. */
export function append_thought_chunk(state, text) {
  if (!text) return state;

  const ensured = ensure_assistant(state);
  const existing = ensured.assistant.parts.find((part) => part.type === 'thought');
  let assistant;

  if (existing) {
    assistant = {
      ...ensured.assistant,
      parts: ensured.assistant.parts.map((part) =>
        part.id === existing.id ? { ...part, text: part.text + text } : part,
      ),
    };
  } else {
    const open = !ensured.assistant.had_text;
    assistant = {
      ...ensured.assistant,
      parts: [
        ...ensured.assistant.parts,
        { id: next_id('thought'), type: 'thought', text, open, auto_open: open },
      ],
    };
  }

  return update_assistant(ensured.state, assistant);
}

/** Create or update a tool card from tool_call or tool_call_update. */
export function upsert_tool(state, update, is_new) {
  const tool_id = String(update?.toolCallId);
  const ensured = ensure_assistant(state);
  const existing = ensured.assistant.parts.find(
    (part) => part.type === 'tool' && part.tool_id === tool_id,
  );

  if (existing) {
    return update_assistant(ensured.state, {
      ...ensured.assistant,
      parts: ensured.assistant.parts.map((part) =>
        part.id === existing.id ? merge_tool_part(part, update) : part,
      ),
    });
  }

  const base = is_new ? stop_text(ensured.assistant.parts) : ensured.assistant.parts;
  const created = merge_tool_part(create_tool_part(tool_id), update);

  return update_assistant(ensured.state, {
    ...ensured.assistant,
    parts: [...base, created],
  });
}

/** Append a streamed tool content chunk, creating the card when needed. */
export function append_tool_chunk(state, update) {
  const tool_id = String(update?.toolCallId);
  const ensured = ensure_assistant(state);
  const existing = ensured.assistant.parts.find(
    (part) => part.type === 'tool' && part.tool_id === tool_id,
  );
  const text = extract_content_text(update?.content);

  if (existing) {
    return update_assistant(ensured.state, {
      ...ensured.assistant,
      parts: ensured.assistant.parts.map((part) =>
        part.id === existing.id ? { ...part, content_text: part.content_text + text } : part,
      ),
    });
  }

  const created = { ...create_tool_part(tool_id), content_text: text };

  return update_assistant(ensured.state, {
    ...ensured.assistant,
    parts: [...ensured.assistant.parts, created],
  });
}

/** Replace the current turn's plan checklist. */
export function set_plan(state, entries) {
  const ensured = ensure_assistant(state);
  const items = Array.isArray(entries)
    ? entries.map((entry) => ({ content: entry?.content || '', status: entry?.status || 'pending' }))
    : [];
  const existing = ensured.assistant.parts.find((part) => part.type === 'plan');

  if (existing) {
    return update_assistant(ensured.state, {
      ...ensured.assistant,
      parts: ensured.assistant.parts.map((part) =>
        part.id === existing.id ? { ...part, entries: items } : part,
      ),
    });
  }

  return update_assistant(ensured.state, {
    ...ensured.assistant,
    parts: [
      ...stop_text(ensured.assistant.parts),
      { id: next_id('plan'), type: 'plan', entries: items },
    ],
  });
}

/** Toggle a thought block, preserving the auto-collapse flag. */
export function set_thought_open(state, part_id, open) {
  const assistant = current_assistant(state);
  if (!assistant) return state;

  const existing = assistant.parts.find((part) => part.id === part_id);
  if (!existing || existing.open === open) return state;

  return update_assistant(state, {
    ...assistant,
    parts: assistant.parts.map((part) => (part.id === part_id ? { ...part, open } : part)),
  });
}

/** Stop every streaming text block in the current turn. */
export function finalize_assistant(state) {
  const assistant = current_assistant(state);
  if (!assistant) return state;

  const next = update_assistant(state, {
    ...assistant,
    parts: stop_text(assistant.parts),
  });

  return { ...next, current_assistant_id: null };
}

/** Drop every transcript item and reset per-turn bookkeeping. */
export function reset_transcript(state, reset_usage = true) {
  return {
    ...state,
    transcript: [],
    permissions: [],
    current_assistant_id: null,
    turn_sequence: 0,
    auto_scroll: true,
    usage: reset_usage ? { used: 0, size: 0, cost: null } : state.usage,
  };
}

/** Add a pending permission request. Duplicate request ids are ignored. */
export function add_permission(state, payload) {
  const key = String(payload?.requestId);
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
function ensure_assistant(state) {
  const existing = current_assistant(state);
  if (existing) return { state, assistant: existing };

  const assistant = {
    id: next_id('turn'),
    type: 'assistant',
    turn: state.turn_sequence,
    parts: [],
    had_text: false,
  };

  return {
    state: {
      ...state,
      transcript: [...state.transcript, assistant],
      current_assistant_id: assistant.id,
    },
    assistant,
  };
}

function current_assistant(state) {
  if (!state.current_assistant_id) return null;
  return state.transcript.find((item) => item.id === state.current_assistant_id) || null;
}

function update_assistant(state, assistant) {
  return {
    ...state,
    transcript: state.transcript.map((item) =>
      item.id === assistant.id ? assistant : item,
    ),
  };
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
