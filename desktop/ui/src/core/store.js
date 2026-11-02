import { create_initial_state } from './state.js';

/** Minimal reactive store; reducers return a new state object or the same one. */
export class Store {
  constructor(initial_state) {
    this._state = initial_state;
    this._listeners = new Set();
  }

  get state() {
    return this._state;
  }

  subscribe(listener) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  update(mutator) {
    const next = mutator(this._state);
    if (!next || next === this._state) return;
    this._state = next;
    this.emit();
  }

  emit() {
    for (const listener of this._listeners) listener(this._state);
  }
}

/** Lit ReactiveController that re-renders its host on every store change. */
export class StoreController {
  constructor(host, source) {
    this.host = host;
    this.store = source;
    this._unsubscribe = null;
    host.addController(this);
  }

  get state() {
    return this.store.state;
  }

  hostConnected() {
    this._unsubscribe = this.store.subscribe(() => this.host.requestUpdate());
  }

  hostDisconnected() {
    if (this._unsubscribe) this._unsubscribe();
    this._unsubscribe = null;
  }
}

export const selectors = {
  connection_label(state) {
    let label = state.status || 'starting';
    if (label === 'ready' && state.busy) label = 'busy';
    if (!state.connected && state.had_connection) label = 'reconnecting';
    return label;
  },

  turn_label(state) {
    return (state.turn_state || 'idle').replace(/_/g, ' ');
  },

  busy_text(state) {
    return state.busy_message || 'cecli is working…';
  },

  retry_visible(state) {
    return Boolean(state.retry_available && state.last_prompt && !state.busy && !state.stopping);
  },

  usage_percent(state) {
    const { used, size } = state.usage;
    if (!(size > 0)) return 0;
    return Math.min(Math.max((used / size) * 100, 0), 100);
  },

  usage_level(state) {
    const percent = selectors.usage_percent(state);
    if (percent > 90) return 'high';
    if (percent > 70) return 'warn';
    return 'normal';
  },

  has_transcript(state) {
    return state.transcript.length > 0;
  },
};

export const store = new Store(create_initial_state());
