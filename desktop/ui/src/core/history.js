/** Replay a coder's conversation stream into an empty transcript. */
import { parse_message_text } from './format.js';

/**
 * Merge historical messages into a bridge view, keeping live items that arrived
 * before the fetch completed.
 */
export function apply_history(store, payload, bridge_id = null) {
  if (!payload || typeof payload !== 'object') return;

  const target = bridge_id || store.active_bridge_id;
  if (!target) return;

  store.update_for(target, (state) => {
    let next = state;
    const messages = Array.isArray(payload.messages) ? payload.messages : [];

    if (messages.length && !has_conversation(next.transcript)) {
      next = {
        ...next,
        transcript: [...messages_to_items(messages, 'main'), ...next.transcript],
        current_assistant_id: null,
      };
    }

    const entries = Array.isArray(payload.subagents) ? payload.subagents : [];
    if (!entries.length) return next;

    let transcripts = next.subagent_transcripts || {};
    let currents = next.subagent_current_assistant_ids || {};
    let changed = false;

    for (const entry of entries) {
      const session_id = entry?.sessionId;
      const history = Array.isArray(entry?.messages) ? entry.messages : [];
      if (!session_id || !history.length) continue;

      const existing = transcripts[session_id] || [];
      if (has_conversation(existing)) continue;

      transcripts = {
        ...transcripts,
        [session_id]: [...messages_to_items(history, session_id), ...existing],
      };
      currents = { ...currents, [session_id]: null };
      changed = true;
    }

    if (!changed) return next;
    return {
      ...next,
      subagent_transcripts: transcripts,
      subagent_current_assistant_ids: currents,
    };
  });
}

/** Whether a transcript already renders a real user or assistant turn. */
export function has_conversation(items) {
  return (items || []).some(
    (item) => item && (item.type === 'user' || item.type === 'assistant'),
  );
}

/** Convert provider message dicts into transcript items. */
function messages_to_items(messages, scope) {
  const items = [];
  const tool_parts = new Map();
  let turn = 0;

  messages.forEach((message, index) => {
    const role = String(message?.role || '');
    const text = parse_message_text(message?.content).text;

    if (role === 'user') {
      if (text) items.push({ id: `${scope}-user-${index}`, type: 'user', text });
      return;
    }

    if (role === 'assistant') {
      const parts = [];
      const reasoning = parse_message_text(message?.reasoning).text;

      if (reasoning) {
        parts.push({
          id: `${scope}-thought-${index}`,
          type: 'thought',
          text: reasoning,
          open: false,
          auto_open: false,
        });
      }
      if (text) {
        parts.push({ id: `${scope}-text-${index}`, type: 'text', text, streaming: false });
      }
      const tool_calls = Array.isArray(message?.toolCalls) ? message.toolCalls : [];
      for (const [call_index, call] of tool_calls.entries()) {
        const part = tool_part(`${scope}-tool-${index}-${call_index}`, call);
        tool_parts.set(String(part.tool_id), part);
        parts.push(part);
      }
      if (!parts.length) return;

      items.push({
        id: `${scope}-turn-${index}`,
        type: 'assistant',
        turn: turn++,
        parts,
        had_text: Boolean(text),
      });
      return;
    }

    if (role === 'tool') {
      const part = tool_parts.get(String(message?.toolCallId || ''));
      if (part) {
        if (text) part.content_text = part.content_text ? `${part.content_text}\n${text}` : text;
        return;
      }
      if (!text) return;

      items.push({
        id: `${scope}-tool-turn-${index}`,
        type: 'assistant',
        turn: turn++,
        parts: [
          {
            id: `${scope}-tool-out-${index}`,
            type: 'tool',
            tool_id: String(message?.toolCallId || `tool-${index}`),
            kind: 'other',
            title: 'Tool result',
            status: 'completed',
            locations: [],
            content_text: text,
          },
        ],
        had_text: false,
      });
    }
  });

  return items;
}

function tool_part(id, call) {
  const arguments_text =
    typeof call?.arguments === 'string' ? call.arguments : JSON.stringify(call?.arguments ?? '');

  return {
    id,
    type: 'tool',
    tool_id: String(call?.id || id),
    kind: 'other',
    title: String(call?.name || 'Tool call'),
    status: 'completed',
    locations: [],
    content_text: arguments_text,
  };
}