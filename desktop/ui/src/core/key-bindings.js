/** TUI-compatible key binding lookup for the desktop client. */

export const DEFAULT_KEY_BINDINGS = {
  newline: 'shift+enter',
  submit: 'enter',
  stop: 'escape',
  cancel: 'ctrl+c',
  paste: 'alt+v',
  next_agent: 'alt+ctrl+right',
  prev_agent: 'alt+ctrl+left',
  main_agent: 'alt+ctrl+home',
  panels: 'alt+p',
  panel_cycle: 'alt+o',
};

const MODIFIER_ORDER = ['alt', 'ctrl', 'shift', 'meta'];

// Textual reports shift+enter as ctrl+j, and the TUI accepts either spelling.
const KEY_ALIASES = { 'shift+enter': 'ctrl+j' };

const KEY_NAMES = {
  ' ': 'space',
  arrowdown: 'down',
  arrowleft: 'left',
  arrowright: 'right',
  arrowup: 'up',
  escape: 'escape',
  pagedown: 'pagedown',
  pageup: 'pageup',
  spacebar: 'space',
};

/** Merge user bindings over the desktop defaults. */
export function normalize_key_bindings(bindings) {
  const merged = { ...DEFAULT_KEY_BINDINGS };
  if (!bindings || typeof bindings !== 'object') return merged;

  for (const [name, value] of Object.entries(bindings)) {
    if (typeof value === 'string' && value.trim()) merged[name] = value.trim();
  }
  return merged;
}

/** One configured binding as a list of comma-separated keys. */
export function binding_keys(bindings, name) {
  const value = bindings?.[name] ?? DEFAULT_KEY_BINDINGS[name] ?? '';
  return String(value)
    .split(',')
    .map((key) => key.trim())
    .filter(Boolean);
}

/** Return the canonical key name for one keyboard event. */
export function event_key(event) {
  const modifiers = [];
  if (event.altKey) modifiers.push('alt');
  if (event.ctrlKey) modifiers.push('ctrl');
  if (event.shiftKey) modifiers.push('shift');
  if (event.metaKey) modifiers.push('meta');

  let name = String(event.key || '').toLowerCase();
  if (name === '\n' || name === '\r') name = 'enter';
  name = KEY_NAMES[name] || name;

  // macOS Option+letter reports the composed glyph in `key` (Option+P is "π").
  const code_letter = /^Key([A-Z])$/.exec(event.code || '');
  if (event.altKey && code_letter && !/^[a-z]$/.test(name)) {
    name = code_letter[1].toLowerCase();
  }
  if (!name) return '';
  return canonical_key([...modifiers, name].join('+'));
}

/** True when an event matches one of a named binding's configured keys. */
export function matches_key_binding(bindings, name, event) {
  if (!event || event.isComposing) return false;
  const pressed = event_key(event);
  if (!pressed) return false;
  return binding_keys(bindings, name).some((key) => canonical_key(key) === pressed);
}

/** Human-readable label shown beside the composer and in menus. */
export function binding_label(bindings, name) {
  const keys = binding_keys(bindings, name);
  if (!keys.length) return '';
  return label_for_key(keys[0]);
}

function canonical_key(key) {
  const parts = String(key)
    .toLowerCase()
    .split('+')
    .map((part) => part.trim())
    .filter(Boolean);
  if (!parts.length) return '';

  const raw_name = parts.pop();
  const name = KEY_NAMES[raw_name] || raw_name;
  const modifiers = [...new Set(parts)].sort(
    (left, right) => MODIFIER_ORDER.indexOf(left) - MODIFIER_ORDER.indexOf(right),
  );
  const normalized = [...modifiers, name].join('+');
  return KEY_ALIASES[normalized] || normalized;
}

function label_for_key(key) {
  if (canonical_key(key) === 'ctrl+j') return 'Shift+Enter';
  return String(key)
    .split('+')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('+');
}
