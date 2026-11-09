/** Pure helpers for the Hooks tab of the registry modal. */

export const HOOK_SECTIONS = [
  { type: 'start', label: 'Start' },
  { type: 'on_message', label: 'On message' },
  { type: 'end_message', label: 'End message' },
  { type: 'pre_tool', label: 'Pre tool' },
  { type: 'post_tool', label: 'Post tool' },
  { type: 'end', label: 'End' },
];

/** Human heading for one hook type, falling back to a titleised slug. */
export function hook_section_label(type) {
  const known = HOOK_SECTIONS.find((section) => section.type === type);
  if (known) return known.label;

  const text = String(type || 'other').replace(/[_-]+/g, ' ').trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Other';
}

/** Group hooks by type in section order, sorting each section by priority. */
export function group_hooks(items) {
  const buckets = new Map();

  for (const item of Array.isArray(items) ? items : []) {
    if (!item || typeof item !== 'object') continue;
    const type = String(item.type || 'other');
    if (!buckets.has(type)) buckets.set(type, []);
    buckets.get(type).push(item);
  }

  const order = HOOK_SECTIONS.map((section) => section.type);
  const types = [...buckets.keys()].sort((left, right) => {
    const left_index = order.indexOf(left);
    const right_index = order.indexOf(right);
    if (left_index !== -1 || right_index !== -1) {
      if (left_index === -1) return 1;
      if (right_index === -1) return -1;
      return left_index - right_index;
    }
    return left.localeCompare(right);
  });

  return types.map((type) => ({
    type,
    label: hook_section_label(type),
    hooks: [...buckets.get(type)].sort((left, right) => {
      const by_priority = Number(left.priority ?? 10) - Number(right.priority ?? 10);
      if (by_priority !== 0) return by_priority;
      return String(left.name || '').localeCompare(String(right.name || ''));
    }),
  }));
}