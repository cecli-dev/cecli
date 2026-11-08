import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { fetch_background_output, list_background_commands } from '../core/background-api.js';
import { CHEVRON_ICON } from '../core/constants.js';
import { StoreController, store } from '../core/store.js';

const POLL_INTERVAL_MS = 1000;
const MAX_TAIL_LINES = 500;
const MAX_LABEL_CHARS = 20;
const INTERPRETERS = new Set([
  'bash',
  'sh',
  'zsh',
  'fish',
  'dash',
  'node',
  'nodejs',
  'deno',
  'bun',
  'python',
  'python3',
  'py',
  'ruby',
  'perl',
  'php',
  'uv',
  'npx',
  'npm',
  'pnpm',
  'yarn',
  'cargo',
  'go',
  'java',
  'dotnet',
  'poetry',
  'pipenv',
]);

export class BackgroundPanel extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._commands = [];
    this._selected_key = null;
    this._output = '';
    this._follow = true;
    this._collapsed = false;
    this._list_error = '';
    this._output_error = '';
    this._bridge_id = null;
    this._bridge_dirty = false;
    this._list_timer = null;
    this._list_inflight = false;
    this._output_inflight_key = null;
    this._output_token = 0;
    this._output_signature = '';
    this._scroll_to_bottom_pending = false;
    this._pending_scroll_top = null;
    this._on_visibility_change = this._handle_visibility_change.bind(this);
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener('visibilitychange', this._on_visibility_change);

    if (this.hasUpdated) {
      this._sync_store_context();
      if (this._bridge_dirty) this.requestUpdate();
      this._sync_polling();
      this._tick();
    }
  }

  disconnectedCallback() {
    document.removeEventListener('visibilitychange', this._on_visibility_change);
    this._stop_polling();
    super.disconnectedCallback();
  }

  willUpdate() {
    this._sync_store_context();
  }

  updated() {
    this.toggleAttribute('data-collapsed', this._collapsed);
    this._sync_polling();

    if (this._bridge_dirty) {
      this._bridge_dirty = false;
      this._tick();
    }

    this._apply_scroll();
  }

  render() {
    const state = this._store.state;
    const commands = this._commands;
    const selected = this._selected_command();
    const note = this._list_error || this._output_error;

    return html`
      <section
        class="background-panel"
        aria-label="Background commands"
      >
        <header class="background-header" @click=${this._toggle_collapsed}>
          <span class="background-heading">Background</span>
          <span class="background-count" data-state=${this._header_state(state)}>${this._count_label(state)}</span>
          <button
            class="background-follow"
            type="button"
            data-active=${this._follow}
            aria-pressed=${this._follow}
            title=${this._follow ? 'Following output' : 'Follow output'}
            @click=${(event) => {
              event.stopPropagation();
              this._toggle_follow();
            }}
          >
            Follow
          </button>
          <button
            type="button"
            class="background-collapse"
            title=${this._collapsed ? 'Expand background' : 'Collapse background'}
            aria-label=${this._collapsed ? 'Expand background' : 'Collapse background'}
            aria-expanded=${!this._collapsed}
            @click=${this._toggle_collapsed}
          >${CHEVRON_ICON}</button>
        </header>

        ${note ? html`<p class="background-note" role="status">${note}</p>` : nothing}
        ${commands.length === 0
          ? html`<p class="background-empty">No active background commands.</p>`
          : html`
              <div class="background-tabs" role="tablist" aria-label="Background command tabs">
                ${repeat(
                  commands,
                  (command) => command.key,
                  (command) => html`
                    <button
                      class="background-tab"
                      type="button"
                      role="tab"
                      data-active=${command.key === this._selected_key}
                      aria-selected=${command.key === this._selected_key}
                      title=${command.command || command.key}
                      @click=${() => this._select(command.key)}
                    >
                      ${command_label(command)}
                    </button>
                  `,
                )}
              </div>
              <div class="background-command-line" title=${selected?.command || ''}>
                ${selected?.command || ''}
              </div>
              <pre
                class="background-output"
                aria-label="Background command output"
                tabindex="0"
                @scroll=${this._on_output_scroll}
              >${this._visible_output()}</pre>
            `}
      </section>
    `;
  }

  _select(command_key) {
    if (command_key === this._selected_key) return;

    this._selected_key = command_key;
    this._output = '';
    this._output_signature = '';
    this._output_error = '';
    this._pending_scroll_top = null;
    this._scroll_to_bottom_pending = this._follow;
    this._output_inflight_key = null;
    this._output_token += 1;
    this.requestUpdate();
    this._maybe_fetch_output();
  }

  _toggle_collapsed(event) {
    if (event) event.stopPropagation();
    this._collapsed = !this._collapsed;
    this.requestUpdate();
  }

  _toggle_follow() {
    this._follow = !this._follow;

    if (this._follow) {
      this._scroll_to_bottom_pending = true;
      this._pending_scroll_top = null;
    } else {
      const output = this._output_element();

      this._scroll_to_bottom_pending = false;
      this._pending_scroll_top = output ? output.scrollTop : null;
    }

    this.requestUpdate();
  }

  async _tick() {
    if (!this._bridge_id || !this._is_panel_visible() || this._list_inflight) return;

    const bridge_id = this._bridge_id;
    this._list_inflight = true;

    try {
      const commands = await list_background_commands(bridge_id);

      if (bridge_id !== this._bridge_id) return;

      this._list_error = '';
      this._apply_commands(commands);
    } catch (error) {
      if (bridge_id !== this._bridge_id) return;

      this._set_error('list', error);
      return;
    } finally {
      this._list_inflight = false;
    }

    await this._maybe_fetch_output();
  }

  _sync_polling() {
    const should_poll = Boolean(this._bridge_id) && this.isConnected && !document.hidden;

    if (!should_poll) {
      this._stop_polling();
      return;
    }

    if (this._list_timer !== null) return;

    this._list_timer = setInterval(() => this._tick(), POLL_INTERVAL_MS);
  }

  _sync_store_context() {
    const state = this._store.state;
    const next_bridge = state.connected ? store.active_bridge_id || state.bridge_id || null : null;

    if (next_bridge === this._bridge_id) return;

    this._bridge_id = next_bridge;
    this._bridge_dirty = true;
    this._reset_view();
  }

  _apply_commands(commands) {
    const active = commands.filter(is_active_command);
    const previous_key = this._selected_key;
    const selection_exists = active.some((command) => command.key === previous_key);

    this._commands = active;

    if (!selection_exists) {
      this._selected_key = active[0]?.key || null;

      if (this._selected_key !== previous_key) {
        this._output = '';
        this._output_signature = '';
        this._output_error = '';
        this._output_inflight_key = null;
        this._output_token += 1;
        this._pending_scroll_top = null;
        this._scroll_to_bottom_pending = this._follow;
      }
    }

    this.requestUpdate();
  }

  async _maybe_fetch_output() {
    const command = this._selected_command();

    if (!command || !this._bridge_id || !this._is_panel_visible()) return;
    if (this._output_inflight_key === command.key) return;

    const offset = command.total_chars ?? command.buffer_size;
    const signature = `${command.key}:${offset}`;

    if (signature === this._output_signature) return;

    await this._fetch_output(command.key, signature);
  }

  async _fetch_output(command_key, signature) {
    const bridge_id = this._bridge_id;
    const token = ++this._output_token;

    this._output_inflight_key = command_key;

    try {
      const result = await fetch_background_output(bridge_id, command_key);

      if (token !== this._output_token || command_key !== this._selected_key) return;

      this._output_error = '';
      this._output_signature = signature;
      this._set_output(result.output);
    } catch (error) {
      if (token !== this._output_token) return;

      this._set_error('output', error);
    } finally {
      if (token === this._output_token && this._output_inflight_key === command_key) {
        this._output_inflight_key = null;
      }
    }
  }

  _set_output(output) {
    const element = this._output_element();

    if (element && !this._follow) this._pending_scroll_top = element.scrollTop;

    this._output = output;
    this._scroll_to_bottom_pending = this._follow;
    this.requestUpdate();
  }

  _reset_view() {
    this._commands = [];
    this._selected_key = null;
    this._output = '';
    this._output_signature = '';
    this._list_error = '';
    this._output_error = '';
    this._output_inflight_key = null;
    this._output_token += 1;
    this._scroll_to_bottom_pending = false;
    this._pending_scroll_top = null;
  }

  _stop_polling() {
    if (this._list_timer === null) return;

    clearInterval(this._list_timer);
    this._list_timer = null;
  }

  _handle_visibility_change() {
    if (document.hidden) {
      this._stop_polling();
      return;
    }

    this._sync_polling();
    this._tick();
  }

  _set_error(scope, error) {
    const note = describe_error(error);

    if (scope === 'list') {
      if (this._list_error === note) return;

      this._list_error = note;
    } else {
      if (this._output_error === note) return;

      this._output_error = note;
    }

    this.requestUpdate();
  }

  _selected_command() {
    return this._commands.find((command) => command.key === this._selected_key) || null;
  }

  _visible_output() {
    const lines = this._output.split('\n');

    if (lines.length <= MAX_TAIL_LINES) return this._output;

    return lines.slice(-MAX_TAIL_LINES).join('\n');
  }

  _output_element() {
    return this.querySelector('.background-output');
  }

  _on_output_scroll(event) {
    const element = event.currentTarget;
    if (!element || !this._follow) return;

    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    if (distance <= 12) return;

    this._follow = false;
    this._scroll_to_bottom_pending = false;
    this.requestUpdate();
  }

  _apply_scroll() {
    const element = this._output_element();

    if (!element) return;

    if (this._scroll_to_bottom_pending && this._follow) {
      element.scrollTop = element.scrollHeight;
      this._scroll_to_bottom_pending = false;
      this._pending_scroll_top = null;
      return;
    }

    if (this._pending_scroll_top !== null) {
      element.scrollTop = this._pending_scroll_top;
      this._pending_scroll_top = null;
    }
  }

  _is_panel_visible() {
    if (!this.isConnected || this.hidden || document.hidden) return false;

    if (typeof this.checkVisibility === 'function') {
      return this.checkVisibility({ checkOpacity: false, checkVisibilityCSS: true });
    }

    return this.getClientRects().length > 0;
  }

  _count_label(state) {
    if (!state.connected) return 'offline';
    if (!this._commands.length) return 'idle';

    return `${this._commands.length} running`;
  }

  _header_state(state) {
    if (!state.connected) return 'offline';
    if (this._list_error || this._output_error) return 'unavailable';

    return this._commands.length ? 'running' : 'idle';
  }
}

function is_active_command(command) {
  if (!command.running) return false;

  if (command.persist && !command.continued_in_background) return false;

  return true;
}

function command_label(command) {
  const tokens = (command.command || '').trim().split(/\s+/).filter(Boolean);
  let value = tokens[0] || command.key;

  if (INTERPRETERS.has(basename(value)) && tokens[1] && !tokens[1].startsWith('-')) {
    value = tokens[1];
  }

  const label = basename(value) || command.key;

  return label.length > MAX_LABEL_CHARS ? `${label.slice(0, MAX_LABEL_CHARS - 1)}\u2026` : label;
}

function basename(value) {
  const trimmed = String(value).replace(/[\\/]+$/, '');
  const parts = trimmed.split(/[\\/]/);

  return parts[parts.length - 1] || trimmed;
}

function describe_error(error) {
  if (error?.status === 409) return 'Background commands unavailable for this session.';
  if (error?.unavailable) return 'Background service unavailable.';

  return error?.message || 'Background request failed.';
}

customElements.define('background-panel', BackgroundPanel);