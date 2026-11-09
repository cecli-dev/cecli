import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import './cli-tab-strip.js';
import './cli-terminal-view.js';
import './cli-background-view.js';
import './cli-log-view.js';
import './cli-stdin-composer.js';

import { BackgroundPoller } from '../core/background-poller.js';
import { close_cli, get_cli_state, send_cli_input } from '../core/cli-api.js';
import { subscribe_cli_event } from '../core/cli-bus.js';
import {
  MAX_INPUT_BYTES,
  apply_cli_event,
  archive_tab,
  auto_close_due,
  classify_input_error,
  close_tab,
  count_unread,
  create_default_tabs,
  input_byte_length,
  input_payload,
  logs_key,
  release_payload,
  reconcile_tabs,
  shell_key,
  workspace_key,
} from '../core/cli-tabs.js';
import { get_terminal_logs, push_terminal_log, subscribe_terminal_log } from '../core/log-bus.js';
import { StoreController, store } from '../core/store.js';
import { CHEVRON_ICON } from '../core/constants.js';

const COLLAPSE_KEY = 'cecli.cli.collapsed';
const LEGACY_COLLAPSE_KEY = 'cecli.terminal.collapsed';
const AUTO_CLOSE_KEY = 'cecli.cli.autoCloseFinished';
const AUTO_FOCUS_KEY = 'cecli.cli.autoFocusStdin';

export class CliPanel extends LitElement {
  static properties = {
    collapsed: { type: Boolean, state: true },
    active_key: { type: String, state: true },
    workspace_key: { type: String, state: true },
    bridge_id: { type: String, state: true },
    tabs: { attribute: false, state: true },
    header_state: { type: String, state: true },
    unread_total: { type: Number, state: true },
    stdin_tab_key: { type: String, state: true },
    notice: { type: String, state: true },
  };

  constructor() {
    super();
    this._store = new StoreController(this, store);
    this.collapsed = this._read_bool(COLLAPSE_KEY, this._read_bool(LEGACY_COLLAPSE_KEY, true));
    this.active_key = '';
    this.workspace_key = 'unassigned';
    this.bridge_id = '';
    this.tabs = [];
    this.header_state = 'idle';
    this.unread_total = 0;
    this.stdin_tab_key = '';
    this.notice = '';

    this._tabs_by_workspace = new Map();
    this._active_by_workspace = new Map();
    this._input_seq = new Map();
    this._log_floor = new Map();
    this._pending_kill = null;
    this._state_generation = 0;
    this._fetch_inflight = false;
    this._background_supported = true;
    this._log_unsub = null;
    this._cli_unsub = null;
    this._auto_timer = null;
    this._notice_timer = null;
    this._on_keydown = this._on_global_keydown.bind(this);
    this._on_visibility = this._on_visibility_change.bind(this);
    this._poller = new BackgroundPoller({
      fetch_state: (bridge) => get_cli_state(bridge),
      on_state: (result, meta) => this._on_poll_state(result, meta),
      on_error: (error) => this._on_poll_error(error),
      is_visible: () => !document.hidden && Boolean(this.bridge_id),
      is_collapsed: () => this.collapsed,
    });
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener('keydown', this._on_keydown);
    document.addEventListener('visibilitychange', this._on_visibility);
  }

  firstUpdated() {
    this._log_unsub = subscribe_terminal_log((entry) => this._on_log(entry));
    this._cli_unsub = subscribe_cli_event((payload) => this._on_cli_event(payload));
    this._auto_timer = setInterval(() => this._auto_close_tick(), 5000);
    this._sync_store();
    this._poller.start();

    if (document.fonts?.ready) document.fonts.ready.then(() => this._fit_all());
  }

  disconnectedCallback() {
    document.removeEventListener('keydown', this._on_keydown);
    document.removeEventListener('visibilitychange', this._on_visibility);
    this._log_unsub?.();
    this._cli_unsub?.();
    this._log_unsub = null;
    this._cli_unsub = null;
    this._poller.stop();
    if (this._auto_timer !== null) clearInterval(this._auto_timer);
    if (this._notice_timer !== null) clearTimeout(this._notice_timer);
    this._auto_timer = null;
    this._notice_timer = null;
    super.disconnectedCallback();
  }

  willUpdate() {
    this._sync_store();
  }

  updated() {
    this.toggleAttribute('data-collapsed', this.collapsed);
    if (!this.collapsed) this._fit_all();
  }

  render() {
    const state = this._store.state;
    const background = state.cliPane?.background !== false;
    const shell_enabled = this._terminal_enabled(state);
    const active = this._active_tab();

    return html`
      <section
        class="cli-panel"
        ?data-collapsed=${this.collapsed}
        aria-label="Command line"
        @focusout=${this._on_focusout}
      >
        <header class="cli-head" @click=${this._toggle_collapsed}>
          <span class="cli-heading">TERMINAL</span>
          <span class="cli-status">${this._status_label(shell_enabled, background)}</span>
          ${this.unread_total > 0
            ? html`<span class="cli-unread">${this.unread_total > 99 ? '99+' : this.unread_total}</span>`
            : nothing}
          <span class="cli-actions">
            ${active?.kind === 'logs'
              ? html`<button class="cli-action" type="button" title="Clear logs" @click=${this._on_clear_click}>Clear</button>`
              : nothing}
            ${active?.kind === 'shell'
              ? html`<button class="cli-action" type="button" title="Restart shell" @click=${this._on_restart_click}>Restart</button>`
              : nothing}
          </span>
          <button
            class="cli-chevron"
            type="button"
            aria-label=${this.collapsed ? 'Expand CLI' : 'Collapse CLI'}
            aria-expanded=${String(!this.collapsed)}
          >${CHEVRON_ICON}</button>
        </header>

        <div class="cli-body">
          <cli-tab-strip
            .tabs=${this.tabs}
            .active_key=${this.active_key}
            @tab-select=${this._on_tab_select_event}
            @tab-close=${this._on_tab_close_event}
          ></cli-tab-strip>

          <div class="cli-panes">
            <div
              class="cli-pane"
              id=${`cli-pane-${sanitize(logs_key(this.workspace_key))}`}
              role="tabpanel"
              ?hidden=${this.active_key !== logs_key(this.workspace_key)}
            >
              <cli-log-view
                .entries=${this._logs_for_workspace()}
                .workspace_key=${this.workspace_key}
              ></cli-log-view>
            </div>

            ${shell_enabled
              ? html`<div
                  class="cli-pane"
                  id=${`cli-pane-${sanitize(shell_key(this.workspace_key))}`}
                  role="tabpanel"
                  ?hidden=${this.active_key !== shell_key(this.workspace_key)}
                >
                  <cli-terminal-view
                    .bridge_id=${this.bridge_id}
                    .active=${this.active_key === shell_key(this.workspace_key)}
                    .terminal_meta=${state.terminal || {}}
                    .live_bridges=${this._live_bridges()}
                    @terminal-attention=${this._on_shell_attention}
                  ></cli-terminal-view>
                </div>`
              : nothing}

            ${repeat(this._all_bg_tabs(), (tab) => tab.key, (tab) => html`
              <div
                class="cli-pane cli-bg-pane"
                id=${`cli-pane-${sanitize(tab.key)}`}
                role="tabpanel"
                ?hidden=${this.active_key !== tab.key || this.workspace_key !== tab.workspace_key}
              >
                <cli-background-view
                  .tab=${tab}
                  .active=${this.active_key === tab.key && this.workspace_key === tab.workspace_key}
                  .raw_background=${state.cliPane?.rawBackground !== false}
                  @bg-exit=${this._on_bg_exit}
                  @bg-event=${this._on_bg_event}
                ></cli-background-view>
                <cli-stdin-composer
                  .tab=${tab}
                  .notice=''
                  @stdin-submit=${this._on_stdin_submit}
                ></cli-stdin-composer>
              </div>
            `)}
          </div>
        </div>

        ${this.notice ? html`<p class="cli-notice" role="status">${this.notice}</p>` : nothing}
      </section>
    `;
  }

  _sync_store() {
    const state = this._store.state;
    const bridge = state.bridge_id || store.active_bridge_id || '';
    const workspace = workspace_key(state);

    if (bridge === this.bridge_id && workspace === this.workspace_key) return;

    this._save_active();
    this.bridge_id = bridge;
    this.workspace_key = workspace;

    const tabs = this._tabs_by_workspace.get(workspace)
      || create_default_tabs(workspace, this._terminal_enabled(state));
    this._set_tabs(tabs, this._active_by_workspace.get(workspace) || logs_key(workspace));

    this._poller.set_bridge(bridge || null);

    if (state.cli?.background) {
      this._apply_state(state.cli.background, { baseline: true });
    }
    this._fetch_state(true);
  }

  async _fetch_state(baseline) {
    if (!this.bridge_id || this._fetch_inflight) return;

    const bridge = this.bridge_id;
    const generation = ++this._state_generation;
    this._fetch_inflight = true;

    try {
      const result = await get_cli_state(bridge);
      if (bridge !== this.bridge_id || generation !== this._state_generation) return;
      this._background_supported = true;
      if (result.workspace && result.workspace !== this.workspace_key) return;
      this._apply_state(result.background, { baseline });
    } catch (error) {
      if (bridge !== this.bridge_id) return;
      if (error?.status === 404 || error?.status === 501) this._background_supported = false;
    } finally {
      this._fetch_inflight = false;
    }
  }

  _on_poll_state(result, meta) {
    if (meta.bridge_id !== this.bridge_id) return;
    this._background_supported = true;
    this._apply_state(result.background, { baseline: meta.baseline });
  }

  _on_poll_error(error) {
    if (error?.status === 404 || error?.status === 501) {
      this._background_supported = false;
      this._set_notice('Background commands are unavailable for this session.');
    }
  }

  _apply_state(background, { baseline = false } = {}) {
    if (this._store.state.cliPane?.enabled === false) return;

    const result = reconcile_tabs(this.tabs, background, {
      workspace_key: this.workspace_key,
      bridge_id: this.bridge_id,
      terminal_enabled: this._terminal_enabled(this._store.state),
      baseline,
      active_key: this.active_key,
    });

    const active_exists = result.tabs.some((tab) => tab.key === this.active_key);
    this._set_tabs(result.tabs, active_exists ? this.active_key : logs_key(this.workspace_key));
  }

  _set_tabs(tabs, active_key = this.active_key) {
    const next = tabs || [];
    let next_active = active_key;
    if (!next.some((tab) => tab.key === next_active)) next_active = next[0]?.key || '';

    this.tabs = next;
    this.active_key = next_active;
    this.unread_total = count_unread(next);
    this._tabs_by_workspace.set(this.workspace_key, next);
    this._active_by_workspace.set(this.workspace_key, next_active);
  }

  _all_bg_tabs() {
    const by_key = new Map();
    for (const tabs of this._tabs_by_workspace.values()) {
      for (const tab of tabs) {
        if (tab.kind === 'bg') by_key.set(tab.key, tab);
      }
    }
    for (const tab of this.tabs) {
      if (tab.kind === 'bg') by_key.set(tab.key, tab);
    }
    return [...by_key.values()];
  }

  _active_tab() {
    return this.tabs.find((tab) => tab.key === this.active_key) || null;
  }

  _on_tab_select_event(event) {
    this._select_tab(event.detail);
  }

  _on_tab_close_event(event) {
    this._close_tab(event.detail);
  }

  _select_tab(key) {
    if (!key || key === this.active_key) return;
    if (!this.tabs.some((tab) => tab.key === key)) return;

    this._release_input(this._active_tab());
    this.active_key = key;
    this.tabs = this.tabs.map((tab) => (tab.key === key ? { ...tab, unread: 0 } : tab));
    this.unread_total = count_unread(this.tabs);
    this._active_by_workspace.set(this.workspace_key, key);
    this.requestUpdate();
  }

  _close_tab(key) {
    const tab = this.tabs.find((item) => item.key === key);
    if (!tab?.closeable) return;

    const running = ['starting', 'running', 'needs_input', 'stopping'].includes(tab.status);

    if (running) {
      if (this._pending_kill?.key !== key) {
        this._pending_kill = { key, at: Date.now() };
        this._set_notice(`Close ${tab.label}? Click close again to stop it.`);
        return;
      }

      this._pending_kill = null;
      this._release_input(tab);
      close_cli(tab.bridge_id, tab.cli_id).catch(() => {});
    } else {
      close_cli(tab.bridge_id, tab.cli_id).catch(() => {});
    }

    this._remove_tab_local(key);
  }

  _remove_tab_local(key) {
    const { tabs, active_key } = close_tab(this.tabs, key, this.active_key);
    this._tabs_by_workspace.set(this.workspace_key, tabs);
    this._set_tabs(tabs, active_key);
  }

  async _on_stdin_submit(event) {
    const detail = event.detail || {};
    const tab = this._active_tab();
    if (!tab || tab.kind !== 'bg') return;

    const text = String(detail.text || '');
    if (!text) return;

    if (input_byte_length(text) > MAX_INPUT_BYTES) {
      this._set_notice('Input exceeds the 64 KiB limit.');
      return;
    }

    const input_seq = (this._input_seq.get(tab.key) || 0) + 1;

    try {
      const response = await send_cli_input(input_payload({
        bridge_id: tab.bridge_id,
        cli_id: tab.cli_id,
        input_seq,
        text,
        newline: detail.newline !== false,
        owner: 'ui',
      }));

      this._input_seq.set(tab.key, input_seq);
      this._patch_tab(tab.key, {
        input_owner: response?.inputOwner ?? response?.input_owner ?? 'ui',
        input_hint: false,
        status: tab.status === 'needs_input' ? 'running' : tab.status,
      });
      event.target?.clear?.({ remember: true, secret: Boolean(detail.secret) });
      this._set_notice('');
    } catch (error) {
      const mapping = classify_input_error(error?.status, error?.body || error);
      this._set_notice(mapping.notice);

      if (mapping.action === 'lost') this._patch_tab(tab.key, { status: 'lost' });
      if (mapping.action === 'exited') this._patch_tab(tab.key, { status: 'exited', input_hint: false });
      if (mapping.action === 'locked') this._patch_tab(tab.key, { input_owner: 'agent' });
    }
  }

  _on_bg_event(event) {
    const detail = event.detail || {};
    const tab = this.tabs.find((item) => item.cli_id === detail.cli_id
      || (detail.command_key && item.command_key === detail.command_key));
    if (!tab) return;

    const patch = {};
    if (detail.event === 'needs_input') {
      patch.status = 'needs_input';
      patch.input_hint = true;
      patch.last_prompt = detail.lastPrompt ?? detail.last_prompt ?? '';
    } else if (detail.event === 'exited') {
      patch.status = 'exited';
      patch.exit_code = detail.code ?? detail.exitCode ?? null;
      patch.finished_at = Date.now();
      patch.input_hint = false;
    } else if (detail.event === 'started') {
      patch.status = 'running';
    } else if (detail.event === 'state' && detail.state) {
      patch.status = String(detail.state);
      if (detail.needsInput !== undefined) patch.input_hint = Boolean(detail.needsInput);
      if (detail.lastPrompt !== undefined) patch.last_prompt = detail.lastPrompt;
      if (detail.exitCode !== undefined) patch.exit_code = detail.exitCode;
      if (detail.endedAt !== undefined) patch.finished_at = detail.endedAt;
    } else if (detail.event === 'closed') {
      this._remove_tab_local(tab.key);
      return;
    } else {
      return;
    }

    this._patch_tab(tab.key, patch);

    if (detail.event !== 'state') {
      push_terminal_log({
        level: detail.event === 'exited' && patch.exit_code ? 'warning' : 'info',
        message: `${tab.command_key} ${detail.event}${detail.event === 'exited' && patch.exit_code !== null ? ` ${patch.exit_code}` : ''}`,
        source: 'cli',
        bridge_id: this.bridge_id,
      });
    }

    if (detail.event === 'needs_input') this._maybe_focus_stdin();
  }

  _on_bg_exit(event) {
    const cli_id = event.detail?.cli_id;
    const tab = this.tabs.find((item) => item.cli_id === cli_id);
    if (!tab) return;

    this._patch_tab(tab.key, {
      status: 'exited',
      exit_code: event.detail?.code ?? null,
      finished_at: Date.now(),
      input_hint: false,
    });
  }

  _patch_tab(key, patch) {
    const tabs = this.tabs.map((tab) => (tab.key === key ? { ...tab, ...patch } : tab));
    this._set_tabs(tabs, this.active_key);
  }

  _on_cli_event(payload) {
    if (payload?.bridgeId && this.bridge_id && payload.bridgeId !== this.bridge_id) return;

    const before = this.tabs;
    const next = apply_cli_event(before, payload, {
      workspace_key: this.workspace_key,
      bridge_id: this.bridge_id,
      active_key: this.active_key,
    });

    if (next !== before) this._set_tabs(next, this.active_key);

    const event = payload?.event;
    const command = payload?.key || '';
    if (event && command) {
      const suffix = event === 'exited' && payload.code !== undefined ? ` ${payload.code}` : '';
      push_terminal_log({
        level: event === 'exited' && payload.code ? 'warning' : 'info',
        message: `${command} ${event}${suffix}`,
        source: 'cli',
        bridge_id: this.bridge_id,
      });
    }

    if (event === 'needs_input') this._maybe_focus_stdin();
  }

  _on_log(entry) {
    if (entry?.bridge_id && this.bridge_id && entry.bridge_id !== this.bridge_id) return;

    if (this.active_key !== logs_key(this.workspace_key)) {
      this.tabs = this.tabs.map((tab) =>
        tab.kind === 'logs' ? { ...tab, unread: (tab.unread || 0) + 1 } : tab,
      );
      this.unread_total = count_unread(this.tabs);
    }

    this.requestUpdate();
  }

  _on_shell_attention() {
    if (this.active_key === shell_key(this.workspace_key)) return;
    this.tabs = this.tabs.map((tab) =>
      tab.kind === 'shell' ? { ...tab, unread: (tab.unread || 0) + 1 } : tab,
    );
    this.unread_total = count_unread(this.tabs);
    this.requestUpdate();
  }

  _logs_for_workspace() {
    const floor = this._log_floor.get(this.workspace_key) || 0;

    return get_terminal_logs().filter((entry) => {
      if (entry.bridge_id && this.bridge_id && entry.bridge_id !== this.bridge_id) return false;
      return (Number(entry.seq) || 0) > floor;
    });
  }

  _clear_logs() {
    const entries = this._logs_for_workspace();
    const last = entries[entries.length - 1];
    this._log_floor.set(this.workspace_key, Number(last?.seq) || 0);
    this.requestUpdate();
  }

  _on_clear_click(event) {
    event.stopPropagation();
    this._clear_logs();
  }

  _on_restart_click(event) {
    event.stopPropagation();
    this._shell_view()?.restart();
  }

  async _release_input(tab) {
    if (!tab || tab.kind !== 'bg') return;
    if (this._store.state.cliPane?.inputLease === false) return;
    if (tab.input_owner !== 'ui') return;

    try {
      await send_cli_input(release_payload({
        bridge_id: tab.bridge_id,
        cli_id: tab.cli_id,
        owner: 'ui',
      }));
    } catch (error) {
      /* lease expiry is the backstop */
    }

    this._patch_tab(tab.key, { input_owner: null });
  }

  _on_focusout(event) {
    if (event.relatedTarget && this.contains(event.relatedTarget)) return;
    this._release_input(this._active_tab());
  }

  _toggle_collapsed(event) {
    if (event) event.stopPropagation();

    if (!this.collapsed) this._release_input(this._active_tab());
    this.collapsed = !this.collapsed;
    this.toggleAttribute('data-collapsed', this.collapsed);
    this._persist_bool(COLLAPSE_KEY, this.collapsed);
    this._persist_bool(LEGACY_COLLAPSE_KEY, this.collapsed);
    this.requestUpdate();

    if (!this.collapsed) queueMicrotask(() => this._fit_all());
  }

  _maybe_focus_stdin() {
    if (this.collapsed || document.hidden || !document.hasFocus?.()) return;
    if (!this._read_bool(AUTO_FOCUS_KEY, true)) return;

    const tab = this._active_tab();
    if (!tab || tab.kind !== 'bg' || tab.status !== 'needs_input') return;

    queueMicrotask(() => this.querySelector('cli-stdin-composer')?.focus());
  }

  _auto_close_tick() {
    if (!this._read_bool(AUTO_CLOSE_KEY, false)) return;

    const keys = auto_close_due(this.tabs, {
      enabled: true,
      now: Date.now(),
      active_key: this.active_key,
    });

    for (const key of keys) {
      const { archived } = archive_tab(this.tabs, key);
      if (archived?.cli_id) close_cli(archived.bridge_id, archived.cli_id).catch(() => {});
      this._remove_tab_local(key);
    }
  }

  _on_global_keydown(event) {
    if (event.ctrlKey && event.key === '`') {
      const tag = event.target?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || event.target?.isContentEditable) return;
      event.preventDefault();
      this._toggle_collapsed();
      return;
    }

    if (!this.contains(event.target)) return;

    if (event.ctrlKey && (event.key === 'PageUp' || event.key === 'PageDown')) {
      event.preventDefault();
      const index = this.tabs.findIndex((tab) => tab.key === this.active_key);
      const delta = event.key === 'PageUp' ? -1 : 1;
      const next = this.tabs[(index + delta + this.tabs.length) % this.tabs.length];
      if (next) this._select_tab(next.key);
      return;
    }

    if (event.ctrlKey && /^[1-9]$/.test(event.key)) {
      const tab = this.tabs[Number(event.key) - 1];
      if (tab) {
        event.preventDefault();
        this._select_tab(tab.key);
      }
      return;
    }

    if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      this._clear_logs();
      return;
    }

    if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'r') {
      event.preventDefault();
      this._shell_view()?.restart();
    }
  }

  _on_visibility_change() {
    if (!this.bridge_id) return;

    if (document.hidden) {
      this._poller.stop();
      return;
    }

    this._poller.start();
    this._fit_all();
  }

  _fit_all() {
    this._shell_view()?.fit?.();
  }

  _shell_view() {
    return this.querySelector('cli-terminal-view');
  }

  _live_bridges() {
    if (!store.sessions?.length) return null;

    const ids = new Set(store.sessions.map((session) => session.bridgeId).filter(Boolean));
    if (this.bridge_id) ids.add(this.bridge_id);
    return [...ids];
  }

  _terminal_enabled(state) {
    const meta = state.terminal || {};
    return meta.enabled !== false && meta.available !== false;
  }

  _status_label(shell_enabled, background) {
    if (!this._store.state.connected) return 'offline';

    const running = this.tabs.filter((tab) => tab.kind === 'bg' && ['running', 'needs_input', 'starting'].includes(tab.status)).length;
    const shell = shell_enabled ? 'shell' : 'logs';

    if (!background) return shell;
    if (running) return `${shell} \u00b7 ${running} bg`;
    return shell;
  }

  _set_notice(message) {
    this.notice = message || '';
    if (this._notice_timer !== null) clearTimeout(this._notice_timer);
    this._notice_timer = null;

    if (!message) return;

    this._notice_timer = setTimeout(() => {
      this.notice = '';
      this._notice_timer = null;
      this.requestUpdate();
    }, 6000);
  }

  _save_active() {
    if (!this.workspace_key) return;
    this._tabs_by_workspace.set(this.workspace_key, this.tabs);
    if (this.active_key) this._active_by_workspace.set(this.workspace_key, this.active_key);
  }

  _read_bool(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : value === 'true';
    } catch (error) {
      return fallback;
    }
  }

  _persist_bool(key, value) {
    try {
      localStorage.setItem(key, value ? 'true' : 'false');
    } catch (error) {
      /* storage disabled */
    }
  }
}


function sanitize(value) {
  return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

customElements.define('cli-panel', CliPanel);