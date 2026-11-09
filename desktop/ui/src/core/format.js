/** Formatting and ACP payload helpers shared by reducers and components. */

/** Compact token counts: 950, 12.3k, 128k, 1.2m. */
export function format_tokens(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return '—';
  if (number < 1000) return String(Math.round(number));

  if (number < 1000000) {
    const thousands = number / 1000;
    return `${thousands >= 100 ? Math.round(thousands) : trim_zero(thousands.toFixed(1))}k`;
  }

  return `${trim_zero((number / 1000000).toFixed(1))}m`;
}

/** Format a usage cost object. */
export function format_cost(cost) {
  if (!cost || typeof cost.amount !== 'number') return '';

  const currency = typeof cost.currency === 'string' ? cost.currency.toUpperCase() : '';

  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits: 4,
    }).format(cost.amount);
  } catch (error) {
    return `${currency} ${cost.amount.toFixed(4)}`.trim();
  }
}

/** Drop a trailing .0 from formatted numbers. */
export function trim_zero(value) {
  return String(value).replace(/\.0$/, '');
}

export function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

/** Normalise the ACP update discriminator. */
export function update_kind(update) {
  if (typeof update.sessionUpdate === 'string') return update.sessionUpdate;
  if (typeof update.type === 'string') return update.type;
  if (update.toolCallId && typeof update.status === 'string') return 'tool_call_update';
  if (update.toolCallId) return 'tool_call';
  return '';
}

/** Pull displayable text out of ACP content entries. */
export function extract_content_text(content) {
  if (!content) return '';
  if (typeof content === 'string') return content;

  if (Array.isArray(content)) {
    return content.map(extract_content_text).filter(Boolean).join('\n');
  }

  if (typeof content === 'object') {
    if (typeof content.text === 'string') return content.text;
    if (content.content) return extract_content_text(content.content);
  }

  return '';
}

/** Remove one pair of surrounding ``` fences, if the whole text is fenced. */
/** Extract display text and source metadata from a context envelope. */
export function parse_message_text(text) {
  const value = typeof text === 'string' ? text : String(text || '');
  const opening = /<context\b([^>]*)>/i.exec(value);
  const attributes = opening ? opening[1] : '';
  const name = /\bname=["']([^"']+)["']/i.exec(attributes)?.[1] || '';
  const from = /\bfrom=["']([^"']+)["']/i.exec(attributes)?.[1] || '';
  const stripped = value
    .replace(/<context\b[^>]*?\/?>/gi, '')
    .replace(/<\/context\s*>/gi, '')
    .trim();

  return { text: stripped, is_user: name === 'user_input', context_name: name, from };
}

/** Backwards-compatible name for the user-input subset of the parser. */
export function unwrap_user_input(text) {
  return parse_message_text(text);
}

export function strip_surrounding_fences(text) {
  const value = typeof text === 'string' ? text : String(text || '');
  const trimmed = value.trim();
  const match = /^```[^\n]*\n([\s\S]*?)\n?```$/.exec(trimmed);
  return match ? match[1] : value;
}

/** Tool output text exactly as the legacy client displayed it. */
export function tool_output_text(content_text) {
  return strip_surrounding_fences(content_text).replace(/\n{3,}/g, '\n\n').trimEnd();
}

/** Map an ACP tool kind to one of the six supported icon buckets. */
export function tool_kind(kind) {
  const value = String(kind || '').toLowerCase();

  if (value === 'read' || value === 'delete' || value === 'move') return 'read';
  if (value === 'edit') return 'edit';
  if (value === 'execute') return 'execute';
  if (value === 'search') return 'search';
  if (value === 'think') return 'think';
  if (value === 'fetch') return 'fetch';
  return 'other';
}

/** Human title fallback when a tool call has no title. */
export function title_for_kind(kind) {
  const titles = {
    read: 'Reading files',
    edit: 'Editing files',
    execute: 'Running command',
    search: 'Searching',
    think: 'Thinking',
    fetch: 'Fetching',
    other: 'Tool call',
  };

  return titles[kind] || titles.other;
}

/** Chip label for a tool status. */
export function status_label(status) {
  if (status === 'in_progress') return 'In progress';
  if (status === 'completed') return 'Completed';
  if (status === 'failed') return 'Failed';
  return 'Pending';
}

/** CSS class for a permission option kind. */
export function option_class(kind) {
  const value = String(kind || '');

  if (value.startsWith('allow')) return 'perm-option--allow';
  if (value.startsWith('reject')) return 'perm-option--reject';
  return '';
}

/** Basename of an absolute or relative path. */
export function basename(path) {
  const parts = String(path || '').split(/[\\/]/);
  return parts[parts.length - 1] || String(path || '');
}

/** Extract a numeric line from an ACP location. */
export function location_line(location) {
  if (!location) return null;
  if (typeof location.line === 'number') return location.line;
  if (location.line && typeof location.line.start === 'number') return location.line.start;
  return null;
}

/** Location chip label. */
export function location_label(location) {
  if (!location || !location.path) return '';
  const line = location_line(location);
  return line ? `${basename(location.path)}:${line}` : basename(location.path);
}

/** Replace a leading home directory with `~`, guessing common Unix layouts. */
export function shorten_home_path(path, home = '') {
  const value = String(path || '');
  if (!value) return '';

  const home_dir = String(home || '');
  if (home_dir) {
    return value === home_dir || value.startsWith(`${home_dir}/`)
      ? `~${value.slice(home_dir.length)}`
      : value;
  }

  const match = value.match(/^(?:\/home\/[^/]+|\/Users\/[^/]+|\/root)(?=\/|$)/);
  return match ? `~${value.slice(match[0].length)}` : value;
}

/** Directory + branch label for the active sub-agent, or the main workspace. */
export function active_agent_location(state, home = '') {
  const active_id = state?.active_agent_session_id;
  const subagents = Array.isArray(state?.subagents) ? state.subagents : [];
  const agent = active_id ? subagents.find((entry) => entry.sessionId === active_id) : null;
  const cwd = (agent && agent.cwd) || state?.cwd || '';
  const branch = (agent && agent.gitBranch) || state?.git_branch || '';

  return [shorten_home_path(cwd, home), branch]
    .map((part) => String(part || '').trim())
    .filter(Boolean)
    .join(' • ');
}

/** Whether a turn part renders as an expandable pill. */
export function is_pill_part(part) {
  return Boolean(part) && ['thought', 'tool', 'diff'].includes(part.type);
}

/** Split a unified diff into display lines classified for the panel. */
export function diff_lines(diff) {
  return String(diff || '')
    .split('\n')
    .map((line) => {
      if (
        line.startsWith('+++') ||
        line.startsWith('---') ||
        line.startsWith('diff ') ||
        line.startsWith('@@') ||
        line.startsWith('index ')
      ) {
        return { kind: 'hunk', text: line };
      }
      if (line.startsWith('+')) return { kind: 'add', text: line };
      if (line.startsWith('-')) return { kind: 'del', text: line };
      return { kind: 'ctx', text: line };
    });
}
