/** Global fan-out for `type:"cli"` events. */

const listeners = new Set();

export function push_cli_event(payload) {
  if (!payload || typeof payload !== 'object') return;

  for (const listener of listeners) listener(payload);
}

export function subscribe_cli_event(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}