/** SSE transport and user actions for the bridge. */
import { get_state, post_json } from './api.js';
import { PERMISSION_CLEANUP_MS, RECONNECT_MAX_MS, RECONNECT_MIN_MS } from './constants.js';
import { handle_event, restore_turn_state } from './events.js';
import { push_log, push_toast } from './notices.js';
import { apply_snapshot } from './snapshot.js';
import { store } from './store.js';
import {
  append_user_message,
  begin_assistant_turn,
  mark_permission_resolved,
  remove_permission,
  reset_transcript,
  set_permission_resolving,
  set_thought_open,
} from './transcript.js';

export class Session {
  constructor(source) {
    this.store = source;
    this.event_source = null;
    this.reconnect_timer = null;
    this.reconnect_delay = RECONNECT_MIN_MS;
    this.permission_timers = new Map();
  }

  /** Open the SSE stream. */
  start() {
    this.connect();
  }

  /** Open the SSE stream and resync state whenever it (re)connects. */
  connect() {
    clearTimeout(this.reconnect_timer);
    this.reconnect_timer = null;
    if (this.event_source) this.event_source.close();

    const source = new EventSource('/api/events');
    this.event_source = source;

    source.onopen = () => {
      this.reconnect_delay = RECONNECT_MIN_MS;
      this.store.update((state) => ({
        ...state,
        connected: true,
        had_connection: true,
        disconnect_notified: false,
      }));
      this.refresh_state();
    };

    source.onmessage = (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        push_log(this.store, `malformed event: ${event.data}`, 'error');
        return;
      }

      handle_event(this.store, payload, {
        on_permission_resolved: (key) => this.schedule_permission_cleanup(key),
        on_prompt_done: () => this.clear_permission_cleanup(),
      });
    };

    source.onerror = () => {
      if (this.event_source !== source) return;

      source.close();
      this.event_source = null;
      this.store.update((state) => ({ ...state, connected: false }));

      if (this.store.state.had_connection && !this.store.state.disconnect_notified) {
        this.store.update((state) => ({ ...state, disconnect_notified: true }));
        push_toast(this.store, 'Connection lost — reconnecting…', 'error');
      }

      this.schedule_reconnect();
    };
  }

  /** Retry with capped exponential backoff (1s, 2s, 4s, 8s). */
  schedule_reconnect() {
    if (this.reconnect_timer) return;

    const wait = this.reconnect_delay;
    this.reconnect_timer = setTimeout(() => {
      this.reconnect_timer = null;
      this.reconnect_delay = Math.min(this.reconnect_delay * 2, RECONNECT_MAX_MS);
      this.connect();
    }, wait);
  }

  /** GET the authoritative snapshot; also called on every SSE open. */
  async refresh_state() {
    try {
      apply_snapshot(this.store, await get_state());
    } catch (error) {
      push_log(this.store, `state sync failed: ${error.message}`, 'error');
    }
  }

  /** Send composer text and optimistically start the turn. */
  async send_prompt(raw_text) {
    const text = String(raw_text || '').trim();
    if (!text || this.store.state.busy) return false;

    if (this.store.state.status !== 'ready') {
      push_toast(this.store, 'cecli is not ready yet', 'error');
      return false;
    }

    try {
      await post_json('/api/prompt', { text });
      this.store.update((state) => {
        const with_user = append_user_message(state, text);
        const begun = begin_assistant_turn(with_user);
        return {
          ...begun,
          last_prompt: text,
          retry_available: false,
          busy: true,
          stopping: false,
          busy_message: 'cecli is working…',
          turn_state: 'running',
        };
      });
      return true;
    } catch (error) {
      this.store.update((state) => ({
        ...state,
        last_prompt: text,
        retry_available: true,
      }));
      push_toast(this.store, error.message, 'error');
      return false;
    }
  }

  /** Request cancellation; the prompt response then reports cancelled. */
  async cancel_turn() {
    const state = this.store.state;
    if (!state.busy || state.stopping) return;

    this.store.update((current) => ({
      ...current,
      stopping: true,
      busy_message: 'Stopping…',
    }));

    try {
      await post_json('/api/cancel', {});
    } catch (error) {
      this.store.update((current) => ({ ...current, stopping: false }));
      push_toast(this.store, error.message, 'error');
    }
  }

  /** Start a fresh session and clear the transcript. */
  async new_chat() {
    if (this.store.state.busy) {
      push_toast(this.store, 'Finish or stop the current turn first', 'error');
      return;
    }

    this.clear_permission_cleanup();
    this.store.update((state) => ({ ...state, new_chat_pending: true }));
    const workspace = this.store.state.workspace;

    try {
      await post_json('/api/new_session', workspace ? { cwd: workspace } : {});
      this.store.update((state) => ({
        ...reset_transcript(state),
        session_id: null,
        busy: false,
        stopping: false,
        busy_message: '',
        turn_state: 'idle',
      }));
      push_toast(this.store, 'Started a new chat', 'info');
      this.refresh_state();
    } catch (error) {
      push_toast(this.store, error.message, 'error');
    } finally {
      this.store.update((state) => ({ ...state, new_chat_pending: false }));
    }
  }

  /** Restart the bridge child process. */
  async restart_server() {
    this.clear_permission_cleanup();
    this.store.update((state) => ({ ...state, restart_pending: true }));

    try {
      await post_json('/api/restart', {});
      this.store.update((state) => ({
        ...reset_transcript(state),
        session_id: null,
        busy: false,
        stopping: false,
        busy_message: '',
        status: 'starting',
        turn_state: 'idle',
      }));
      push_toast(this.store, 'Restarting cecli…', 'info');
    } catch (error) {
      push_toast(this.store, error.message, 'error');
    } finally {
      this.store.update((state) => ({ ...state, restart_pending: false }));
    }
  }

  /** POST a picker change; returns false so the picker can roll back. */
  async change_config(config_id, value) {
    try {
      await post_json('/api/config', { configId: config_id, value });
      this.store.update((state) => ({
        ...state,
        config_options: state.config_options.map((option) =>
          option.id === config_id ? { ...option, currentValue: value } : option,
        ),
      }));
      return true;
    } catch (error) {
      push_toast(this.store, error.message, 'error');
      return false;
    }
  }

  /** POST the selected permission option. */
  async resolve_permission(request_id, option_id) {
    const key = String(request_id);
    const entry = this.store.state.permissions.find((item) => item.key === key);
    if (!entry || entry.resolving || entry.resolved) return;

    this.store.update((state) => set_permission_resolving(state, key, true));

    try {
      await post_json('/api/permission', {
        requestId: entry.request_id,
        optionId: option_id,
      });
      this.store.update((state) => mark_permission_resolved(state, key, option_id));
      this.store.update((state) => restore_turn_state(state));
      this.schedule_permission_cleanup(key);
    } catch (error) {
      const current = this.store.state.permissions.find((item) => item.key === key);
      if (current && current.resolved) return;

      this.store.update((state) => set_permission_resolving(state, key, false));
      push_toast(this.store, error.message, 'error');
    }
  }

  /** Remove a resolved card after the legacy five-second delay. */
  schedule_permission_cleanup(key) {
    if (this.permission_timers.has(key)) return;

    const timer = setTimeout(() => {
      this.permission_timers.delete(key);
      this.store.update((state) => remove_permission(state, key));
    }, PERMISSION_CLEANUP_MS);

    this.permission_timers.set(key, timer);
  }

  /** Cancel every pending permission cleanup timer. */
  clear_permission_cleanup() {
    for (const timer of this.permission_timers.values()) clearTimeout(timer);
    this.permission_timers.clear();
  }

  /** Fill the composer from an example or retry action. */
  set_thought_open(part_id, open) {
    this.store.update((state) => set_thought_open(state, part_id, open));
  }

  set_auto_scroll(value) {
    const next = Boolean(value);
    this.store.update((state) =>
      state.auto_scroll === next ? state : { ...state, auto_scroll: next },
    );
  }

  jump_to_latest() {
    this.set_auto_scroll(true);
  }

  fill_composer(text) {
    this.store.update((state) => ({
      ...state,
      draft: String(text || ''),
      draft_revision: state.draft_revision + 1,
    }));
  }
}

export const session = new Session(store);
