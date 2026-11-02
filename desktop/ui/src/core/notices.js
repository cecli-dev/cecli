import { MAX_LOG_LINES, TOAST_FADE_MS, TOAST_VISIBLE_MS } from './constants.js';

let toast_sequence = 0;

/** Append a timestamped line to the capped log drawer. */
export function push_log(store, message, level = 'info') {
  const text = typeof message === 'string' ? message : String(message);
  const stamp = new Date().toLocaleTimeString([], { hour12: false });
  const line = `[${stamp}] ${String(level || 'info').padEnd(5)} ${text}`;

  store.update((state) => {
    const logs = [...state.logs, line];
    return { ...state, logs: logs.length > MAX_LOG_LINES ? logs.slice(-MAX_LOG_LINES) : logs };
  });
}

/** Transient notice with the legacy 4.6 s lifetime and 260 ms fade. */
export function push_toast(store, message, kind = 'info') {
  toast_sequence += 1;
  const id = toast_sequence;

  store.update((state) => ({
    ...state,
    toasts: [...state.toasts, { id, message: String(message), kind: kind || 'info', visible: false }],
  }));

  requestAnimationFrame(() => {
    store.update((state) => ({
      ...state,
      toasts: state.toasts.map((toast) =>
        toast.id === id ? { ...toast, visible: true } : toast,
      ),
    }));
  });

  setTimeout(() => {
    store.update((state) => ({
      ...state,
      toasts: state.toasts.map((toast) =>
        toast.id === id ? { ...toast, visible: false } : toast,
      ),
    }));

    setTimeout(() => {
      store.update((state) => ({
        ...state,
        toasts: state.toasts.filter((toast) => toast.id !== id),
      }));
    }, TOAST_FADE_MS);
  }, TOAST_VISIBLE_MS);
}
