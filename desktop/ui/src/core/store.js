import { create_initial_state } from './state.js';

export class Store {
  constructor(initial_state) {
    this._views = new Map([['', this._strip(initial_state)]]);
    this._active_bridge_id = null;
    this._sessions = [];
    this._workspaces = [];
    this._max_sessions = initial_state.max_sessions || 8;
    this._revisions = new Map();
    this._listeners = new Set();
    this._connection = {
      connected: initial_state.connected,
      had_connection: initial_state.had_connection,
      disconnect_notified: initial_state.disconnect_notified,
    };
  }

  get state() {
    return this._project(this._active_bridge_id || '');
  }

  get active_bridge_id() {
    return this._active_bridge_id;
  }

  get sessions() {
    return this._sessions;
  }

  get workspaces() {
    return this._workspaces;
  }

  /** Monotonic per-bridge revision used to reject stale snapshots. */
  revision(bridge_id) {
    return this._revisions.get(bridge_id || '') || 0;
  }

  subscribe(listener) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  update(mutator) {
    this._write(this._active_bridge_id || '', mutator);
  }

  /** Apply an event to a background bridge without disturbing the active view. */
  update_for(bridge_id, mutator) {
    const key = bridge_id || this._active_bridge_id || '';
    this._write(key, mutator);
  }

  /** A stable view adapter for one bridge, used by the event reducers. */
  scoped(bridge_id) {
    const owner = this;
    return {
      bridge_id,
      get state() {
        return owner.state_for(bridge_id);
      },
      update: (mutator) => owner.update_for(bridge_id, mutator),
      patch_session: (first, second) =>
        second === undefined
          ? owner.patch_session(bridge_id, first)
          : owner.patch_session(first, second),
    };
  }

  state_for(bridge_id) {
    const key = bridge_id || '';
    if (!this._active_bridge_id || key === this._active_bridge_id) return this.state;
    return this._project(key);
  }
  set_active(bridge_id) {
    const next_id = bridge_id || null;
    if (next_id === this._active_bridge_id) return;

    const previous = this.state;
    this._views.set(this._active_bridge_id || '', this._strip(previous));
    this._active_bridge_id = next_id;
    if (next_id && !this._views.has(next_id)) {
      const summary = this._sessions.find((item) => item.bridgeId === next_id);
      const blank = create_initial_state();
      blank.connected = previous.connected;
      blank.had_connection = previous.had_connection;
      blank.disconnect_notified = previous.disconnect_notified;
      blank.bridge_id = next_id;
      blank.title = summary?.title || '';
      blank.workspace = summary?.workspace || '';
      blank.status = summary?.status || 'starting';
      blank.session_id = summary?.sessionId || null;
      blank.busy = Boolean(summary?.busy);
      blank.activity = summary?.activity || 'idle';
      blank.activity_detail = summary?.activityDetail || '';
      this._views.set(next_id, this._strip(blank));
    }

    this.emit();
  }

  /** Replace the sidebar list, upserting by bridgeId so races never duplicate. */
  set_sessions(sessions, max_sessions) {
    if (Array.isArray(sessions)) {
      this._sessions = [...sessions];
    }
    if (Number.isFinite(max_sessions)) this._max_sessions = max_sessions;

    if (!this._active_bridge_id && this._sessions.length) {
      this.set_active(this._sessions[0].bridgeId);
      return;
    }

    this.emit();
  }

  /** Replace the configured workspace list; sessions stay the live subset. */
  set_workspaces(workspaces) {
    if (!Array.isArray(workspaces)) return;
    this._workspaces = [...workspaces];
    this.emit();
  }

  remove_session(bridge_id) {
    this._views.delete(bridge_id);
    this._sessions = this._sessions.filter((item) => item.bridgeId !== bridge_id);
    if (this._active_bridge_id === bridge_id) {
      this._active_bridge_id = this._sessions[0]?.bridgeId || null;
    }
    this.emit();
  }

  /** Merge live activity into one sidebar summary without resetting it. */
  patch_session(bridge_id, patch) {
    if (typeof bridge_id === 'object' && bridge_id !== null && patch === undefined) {
      patch = bridge_id;
      bridge_id = this._active_bridge_id;
    }
    if (!bridge_id || !patch) return;

    let changed = false;
    const values = Object.fromEntries(
      Object.entries(patch).filter(([, value]) => value !== undefined),
    );
    this._sessions = this._sessions.map((item) => {
      if (item.bridgeId !== bridge_id) return item;
      changed = true;
      return { ...item, ...values };
    });
    if (changed) this.emit();
  }

  emit() {
    if (this._emit_scheduled) return;
    this._emit_scheduled = true;
    queueMicrotask(() => {
      this._emit_scheduled = false;
      for (const listener of this._listeners) listener(this.state);
    });
  }

  _project(key) {
    let view = this._views.get(key);
    if (!view) {
      view = key ? create_initial_state() : this._views.get('') || create_initial_state();
    }
    return {
      ...view,
      sessions: this._sessions,
      workspaces: this._workspaces,
      active_bridge_id: this._active_bridge_id,
      max_sessions: this._max_sessions,
      ...this._connection,
    };
  }

  _write(key, mutator) {
    const before = this._views.get(key) || create_initial_state();
    const next = mutator(this._project(key));
    if (!next) return;

    const connection = {
      connected: next.connected,
      had_connection: next.had_connection,
      disconnect_notified: next.disconnect_notified,
    };
    const connection_changed =
      connection.connected !== this._connection.connected ||
      connection.had_connection !== this._connection.had_connection ||
      connection.disconnect_notified !== this._connection.disconnect_notified;
    this._connection = connection;

    const clean = this._strip(next);
    const view_changed = !this._same_view(before, clean);

    if (view_changed) {
      this._views.set(key, clean);
      this._revisions.set(key, this.revision(key) + 1);
    }

    if (view_changed || connection_changed) this.emit();
  }

  _same_view(left, right) {
    const keys = Object.keys(left);
    if (keys.length !== Object.keys(right).length) return false;
    return keys.every((key) => left[key] === right[key]);
  }

  _strip(view) {
    const next = { ...view };
    delete next.sessions;
    delete next.workspaces;
    delete next.active_bridge_id;
    delete next.max_sessions;
    delete next.connected;
    delete next.had_connection;
    delete next.disconnect_notified;
    return next;
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

  active_agent(state) {
    if (!state.active_agent_session_id) return null;
    return (
      (state.subagents || []).find(
        (agent) => agent.sessionId === state.active_agent_session_id,
      ) || null
    );
  },

  visible_transcript(state) {
    if (!state.active_agent_session_id) return state.transcript;
    return state.subagent_transcripts?.[state.active_agent_session_id] || [];
  },

  visible_busy(state) {
    if (!state.active_agent_session_id) return state.busy;
    const agent = selectors.active_agent(state);
    return Boolean(agent?.running);
  },

  has_transcript(state) {
    return selectors.visible_transcript(state).length > 0;
  },
};

export const store = new Store(create_initial_state());
