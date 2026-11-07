/** SSE transport and user actions for the bridge. */
import { get_history, get_sessions, get_state, post_complete, post_json } from './api.js';
import { PERMISSION_CLEANUP_MS, RECONNECT_MAX_MS, RECONNECT_MIN_MS } from './constants.js';
import { handle_event, restore_turn_state } from './events.js';
import { apply_history, has_conversation } from './history.js';
import { push_log, push_toast } from './notices.js';
import { apply_snapshot } from './snapshot.js';
import { store } from './store.js';
import { bridge_socket } from './ws.js';
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
    this.state_generations = new Map();
    this.permission_timers = new Map();
    this.history_loaded = new Set();
    this.reconnect_timer = null;
    this.reconnect_delay = RECONNECT_MIN_MS;
  }

  /** Open the SSE stream. */
  start() {
    this.connect();
    this.sync_timer = setInterval(() => this.sync_now(), 5000);
  }

  /** Keep the agent tree and registries fresh when SSE is quiet. */
  sync_now() {
    if (!this.store.state.connected) return;
    this.refresh_sessions();
    if (!this.store.state.busy) this.refresh_state(this.store.active_bridge_id);
    this.hydrate_history(this.store.active_bridge_id);
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
      this.refresh_sessions();
      this.refresh_state(this.store.active_bridge_id);
    };

    source.onmessage = (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        push_log(this.store, `malformed event: ${event.data}`, 'error');
        return;
      }

      if (payload.type === 'sessions') {
        this.store.set_sessions(payload.sessions, payload.maxSessions);
        this._sync_active_summary();
        return;
      }


      const bridge_id = payload.bridgeId || this.store.active_bridge_id;
      const target = bridge_id ? this.store.scoped(bridge_id) : this.store;
      handle_event(target, payload, {
        on_permission_resolved: (key) => this.schedule_permission_cleanup(key, bridge_id),
        on_prompt_done: () => this.clear_permission_cleanup(bridge_id),
      });
      this._track_session_event(target, payload);
      if (payload.type === 'status' && payload.status === 'ready') {
        this.hydrate_history(bridge_id);
      }
      if (payload.type === 'subagents') this.hydrate_history(bridge_id);
      if (payload.type === 'session' && bridge_id) {
        for (const key of this.history_loaded) {
          if (key.startsWith(`${bridge_id}:`)) this.history_loaded.delete(key);
        }
        this.hydrate_history(bridge_id);
      }
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
  async refresh_sessions() {
    try {
      const payload = await get_sessions();
      this.store.set_sessions(payload.sessions, payload.maxSessions);
      this._sync_active_summary();
    } catch (error) {
      push_log(this.store, `session list failed: ${error.message}`, 'error');
    }
  }

  /** Fold the active session summary's sub-agents and registries into its view. */
  _sync_active_summary() {
    const bridge_id = this.store.active_bridge_id;
    if (!bridge_id) return;
    const summary = this.store.sessions.find((item) => item.bridgeId === bridge_id);
    if (!summary) return;

    this.store.update_for(bridge_id, (state) => {
      const subagents = Array.isArray(summary.subagents) ? summary.subagents : state.subagents;
      const subagent_transcripts = { ...state.subagent_transcripts };
      for (const agent of subagents) {
        if (agent?.sessionId && !subagent_transcripts[agent.sessionId]) {
          subagent_transcripts[agent.sessionId] = [];
        }
      }

      return {
        ...state,
        subagents,
        subagent_transcripts,
        skills: Array.isArray(summary.skills) ? summary.skills : state.skills,
        mcp_servers: Array.isArray(summary.mcpServers)
          ? summary.mcpServers
          : state.mcp_servers,
        workflows: Array.isArray(summary.workflows) ? summary.workflows : state.workflows,
        context_files: Array.isArray(summary.contextFiles)
          ? summary.contextFiles
          : state.context_files,
      };
    });
  }

  async refresh_state(bridge_id = this.store.active_bridge_id, attempt = 0) {
    if (!bridge_id) {
      await this.refresh_sessions();
      bridge_id = this.store.active_bridge_id;
      if (!bridge_id) return;
    }

    const generation = (this.state_generations.get(bridge_id) || 0) + 1;
    this.state_generations.set(bridge_id, generation);
    const revision = this.store.revision(bridge_id);
    const prune_keys = new Set(
      this.store.state_for(bridge_id).permissions.map((entry) => entry.key),
    );

    try {
      const snapshot = await get_state(bridge_id);
      if (this.state_generations.get(bridge_id) !== generation) return;

      if (this.store.revision(bridge_id) !== revision) {
        const current = this.store.state_for(bridge_id);
        if (current.session_id && attempt < 1) {
          await this.refresh_state(bridge_id, attempt + 1);
          return;
        }
      }

      apply_snapshot(this.store, snapshot, bridge_id, prune_keys);
      this.hydrate_history(bridge_id);
    } catch (error) {
      push_log(this.store, `state sync failed: ${error.message}`, 'error');
    }
  }

  /** Replay each coder's stored conversation while a transcript is still empty. */
  async hydrate_history(bridge_id = this.store.active_bridge_id) {
    const target = bridge_id || this.store.active_bridge_id;
    if (!target) return;

    const state = this.store.state_for(target);
    if (state.status !== 'ready') return;

    const keys = ['main'];
    for (const agent of state.subagents || []) {
      if (agent?.sessionId && !agent.removed) keys.push(agent.sessionId);
    }

    const pending = keys.filter((key) => {
      const transcript = key === 'main' ? state.transcript : state.subagent_transcripts?.[key] || [];
      return !has_conversation(transcript) && !this.history_loaded.has(`${target}:${key}`);
    });
    if (!pending.length) return;

    for (const key of pending) this.history_loaded.add(`${target}:${key}`);

    let payload = null;
    try {
      payload = await bridge_socket.request('history.get', { bridgeId: target });
    } catch (error) {
      try {
        payload = await get_history(target);
      } catch (fallback_error) {
        for (const key of pending) this.history_loaded.delete(`${target}:${key}`);
        return;
      }
    }

    apply_history(this.store, payload, target);
  }

  async switch_session(bridge_id) {
    if (!bridge_id) return;
    this.store.update((state) => ({ ...state, active_agent_session_id: null }));
    if (bridge_id === this.store.active_bridge_id) return;
    this.store.set_active(bridge_id);
    await this.refresh_state(bridge_id);
  }

  async create_session(cwd = null, title = null) {
    const body = { ...(cwd ? { cwd } : {}), ...(title ? { title } : {}) };
    let bridge_id = null;

    try {
      const result = await bridge_socket.request('sessions.create', body);
      bridge_id = result?.bridgeId || null;
    } catch (error) {
      const result = await post_json('/api/sessions', body);
      bridge_id = result?.bridgeId || null;
    }

    await this.refresh_sessions();
    if (bridge_id) await this.switch_session(bridge_id);
    return bridge_id;
  }

  async close_session(bridge_id) {
    try {
      await bridge_socket.request('sessions.close', { bridgeId: bridge_id });
    } catch (error) {
      await post_json('/api/sessions/close', { bridgeId: bridge_id });
    }

    this.store.remove_session(bridge_id);
    await this.refresh_sessions();
    await this.refresh_state(this.store.active_bridge_id);
  }

  /** Select a sub-agent transcript, switching bridge sessions when needed. */
  async select_agent(bridge_id, session_id = null) {
    if (bridge_id && bridge_id !== this.store.active_bridge_id) {
      await this.switch_session(bridge_id);
    }
    this.store.update((state) => ({
      ...state,
      active_agent_session_id: session_id || null,
      auto_scroll: true,
    }));
    this.hydrate_history(bridge_id || this.store.active_bridge_id);
  }

  async message_subagent(session_id, text) {
    const bridge_id = this.store.active_bridge_id;
    if (!bridge_id) return;
    await post_json('/api/subagent/message', {
      bridgeId: bridge_id,
      sessionId: session_id,
      text,
    });
    this.store.update((state) => ({
      ...state,
      subagents: (state.subagents || []).map((agent) =>
        agent.sessionId === session_id
          ? { ...agent, running: true, state: 'running' }
          : agent,
      ),
    }));
  }

  async registry_action(kind, action, name) {
    const bridge_id = this.store.active_bridge_id;
    if (!bridge_id) return;

    const run_workflow = kind === 'workflows' && action === 'run';

    try {
      const params = { bridgeId: bridge_id, name };
      if (kind === 'context') params.path = name;
      await bridge_socket.request(`${kind}.${action}`, params);
    } catch (error) {
      await post_json(`/api/${kind}`, { bridgeId: bridge_id, action, name });
    }

    if (run_workflow) {
      this.store.update((state) => {
        const text = `/workflows run ${name}`;
        const with_user = append_user_message(state, text);
        const begun = begin_assistant_turn(with_user);
        return {
          ...begun,
          active_agent_session_id: null,
          last_prompt: text,
          retry_available: false,
          busy: true,
          stopping: false,
          busy_message: 'cecli is working\u2026',
          turn_state: 'running',
        };
      });
    }

    await this.refresh_state(bridge_id);
  }

  /** Ask the bridge for composer completion candidates. */
  async complete(text) {
    const bridge_id = this.store.active_bridge_id;

    try {
      return await bridge_socket.request('complete.get', { bridgeId: bridge_id, text });
    } catch (error) {
      return post_complete(bridge_id, text);
    }
  }
  /** Send composer text and optimistically start the turn. */
  async send_prompt(raw_text) {
    const text = String(raw_text || '').trim();
    const state = this.store.state;
    const bridge_id = this.store.active_bridge_id;
    const agent_id = state.active_agent_session_id;

    if (!bridge_id && state.sessions.length) {
      push_toast(this.store, 'No active session', 'error');
      return false;
    }
    if (!text) return false;

    if (this.store.state.status !== 'ready') {
      push_toast(this.store, 'cecli is not ready yet', 'error');
      return false;
    }

    if (agent_id) {
      try {
        await post_json('/api/subagent/message', {
          bridgeId: bridge_id,
          sessionId: agent_id,
          text,
        });
        this.store.update((current) => ({
          ...current,
          subagents: (current.subagents || []).map((agent) =>
            agent.sessionId === agent_id
              ? { ...agent, running: true, state: 'running' }
              : agent,
          ),
        }));
        return true;
      } catch (error) {
        push_toast(this.store, error.message, 'error');
        return false;
      }
    }

    if (this.store.state.busy) return false;

    try {
      await post_json('/api/prompt', bridge_id ? { bridgeId: bridge_id, text } : { text });
      this.store.update((current) => {
        const with_user = append_user_message(current, text);
        const begun = begin_assistant_turn(with_user);
        return {
          ...begun,
          last_prompt: text,
          retry_available: false,
          busy: true,
          stopping: false,
          busy_message: 'cecli is working\u2026',
          turn_state: 'running',
        };
      });
      return true;
    } catch (error) {
      this.store.update((current) => ({
        ...current,
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
    const agent_id = state.active_agent_session_id;

    if (agent_id) {
      const agent = (state.subagents || []).find((item) => item.sessionId === agent_id);
      if (!agent?.running) return;
      try {
        await post_json('/api/subagent/cancel', {
          bridgeId: this.store.active_bridge_id,
          sessionId: agent_id,
        });
      } catch (error) {
        push_toast(this.store, error.message, 'error');
      }
      return;
    }

    if (!state.busy || state.stopping) return;

    this.store.update((current) => ({
      ...current,
      stopping: true,
      busy_message: 'Stopping\u2026',
    }));

    try {
      await post_json('/api/cancel', { bridgeId: this.store.active_bridge_id });
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
    this.history_loaded.clear();
    this.store.update((state) => ({ ...state, new_chat_pending: true }));
    const workspace = this.store.state.workspace;

    try {
      await post_json('/api/new_session', {
        ...(this.store.active_bridge_id ? { bridgeId: this.store.active_bridge_id } : {}),
        ...(workspace ? { cwd: workspace } : {}),
      });
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
    this.history_loaded.clear();
    this.store.update((state) => ({ ...state, restart_pending: true }));

    try {
      await post_json('/api/restart', { bridgeId: this.store.active_bridge_id });
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
      await post_json('/api/config', {
        bridgeId: this.store.active_bridge_id,
        configId: config_id,
        value,
      });
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
    const state = this.store.state;
    const entry = state.permissions.find(
      (item) => String(item.request_id) === String(request_id),
    );
    if (!entry || entry.resolving || entry.resolved) return;

    const bridge_id = state.bridge_id || this.store.active_bridge_id;
    const key = entry.key;
    this.store.update((current) => set_permission_resolving(current, key, true));

    try {
      await post_json('/api/permission', {
        bridgeId: bridge_id,
        requestId: entry.request_id,
        optionId: option_id,
      });
      this.store.update((current) => mark_permission_resolved(current, key, option_id));
      this.store.update((current) => restore_turn_state(current));
      this.schedule_permission_cleanup(key, bridge_id);
    } catch (error) {
      const current = this.store.state.permissions.find((item) => item.key === key);
      if (current && current.resolved) return;

      this.store.update((value) => set_permission_resolving(value, key, false));
      push_toast(this.store, error.message, 'error');
    }
  }

  /** Remove a resolved card after the legacy five-second delay. */
  schedule_permission_cleanup(key, bridge_id = this.store.active_bridge_id) {
    if (this.permission_timers.has(key)) return;

    const timer = setTimeout(() => {
      this.permission_timers.delete(key);
      this.store.update_for(bridge_id, (state) => remove_permission(state, key));
      this.store.patch_session(bridge_id, {
        permissionCount: this.store
          .state_for(bridge_id)
          .permissions.filter((entry) => !entry.resolved).length,
      });
    }, PERMISSION_CLEANUP_MS);

    this.permission_timers.set(key, timer);
  }

  /** Cancel pending permission cleanup timers, optionally for one bridge. */
  clear_permission_cleanup(bridge_id = null) {
    const prefix = bridge_id ? `${bridge_id}:` : '';
    for (const [key, timer] of this.permission_timers) {
      if (prefix && !key.startsWith(prefix)) continue;
      clearTimeout(timer);
      this.permission_timers.delete(key);
    }
  }

  /** Fill the composer from an example or retry action. */
  _track_session_event(target, payload) {
    if (!target.patch_session) return;

    if (payload.type === 'update') {
      if (payload.sessionId && payload.sessionId !== target.state.session_id) return;
      const update = payload.update || {};
      if (update.sessionUpdate === 'state_update' && update.state) {
        target.patch_session({
          activity: update.state,
          busy: update.state === 'running' || update.state === 'requires_action',
        });
      } else if (update.sessionUpdate === 'tool_call' && update.title) {
        target.patch_session({ activityDetail: update.title });
      }
      return;
    }

    if (payload.type === 'permission' || payload.type === 'permission_resolved') {
      target.patch_session({
        permissionCount: target.state.permissions.filter((entry) => !entry.resolved).length,
      });
      return;
    }

    if (payload.type === 'prompt_done') {
      target.patch_session({ activity: 'idle', busy: false, permissionCount: 0 });
    }
  }

  set_thought_open(part_id, open, agent_id = null) {
    this.store.update((state) => set_thought_open(state, part_id, open, agent_id));
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
