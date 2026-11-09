import { LitElement, html, nothing } from 'lit';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

import { CHEVRON_ICON } from '../core/constants.js';
import {
  get_terminal_logs,
  subscribe_terminal_log,
} from '../core/log-bus.js';
import { StoreController, store } from '../core/store.js';
import {
  open_terminal_socket,
  start_terminal,
  stop_terminal,
} from '../core/terminal-api.js';
import { TerminalClient } from '../core/terminal-client.js';

const COLLAPSE_KEY = 'cecli.terminal.collapsed';
const MODE_KEY = 'cecli.terminal.mode';
const MAX_LOGS = 2000;

const LEVEL_COLORS = {
  error: '\x1b[31m',
  warning: '\x1b[38;5;130m',
  stderr: '\x1b[38;5;130m',
  info: '\x1b[38;5;24m',
};
const RESET = '\x1b[0m';

export class TerminalPanel extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._collapsed = this._read_bool(COLLAPSE_KEY, true);
    this._mode = this._read_mode();
    this._terminal = null;
    this._fit = null;
    this._host = null;
    this._client = null;
    this._socket_open = false;
    this._starting = false;
    this._unread = 0;
    this._status = '';
    this._log_unsub = null;
    this._resize_observer = null;
    this._on_keydown = this._on_global_keydown.bind(this);
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener('keydown', this._on_keydown);
    this._log_unsub = subscribe_terminal_log((entry) => this._on_log(entry));
  }

  disconnectedCallback() {
    document.removeEventListener('keydown', this._on_keydown);
    this._log_unsub?.();
    this._log_unsub = null;
    this._dispose_terminal();
    super.disconnectedCallback();
  }

  updated() {
    this.toggleAttribute('data-collapsed', this._collapsed);
    if (this._collapsed) return;

    const host = this.querySelector('.terminal-host');
    if (!host) return;
    if (this._host !== host) {
      this._host = host;
      this._mount_terminal(host);
    }
    this._sync_mode();
  }

  render() {
    const state = this._store.state;
    const meta = state.terminal || {};
    const disabled = meta.enabled === false || meta.available === false;
    const unread = this._unread > 0
      ? html`<span class="terminal-unread">${this._unread > 99 ? '99+' : this._unread}</span>`
      : nothing;

    return html`
      <section class="terminal-panel" aria-label="Terminal and logs">
        <header class="terminal-header" @click=${this._toggle_collapsed}>
          <span class="terminal-heading">Terminal</span>
          ${unread}
          <span class="terminal-status">${this._status_label(meta)}</span>
          <button
            class="terminal-chevron"
            type="button"
            aria-label=${this._collapsed ? 'Expand terminal' : 'Collapse terminal'}
            aria-expanded=${this._collapsed ? 'false' : 'true'}
          >${CHEVRON_ICON}</button>
        </header>
        ${this._collapsed ? nothing : html`
          <div class="terminal-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              class="terminal-tab"
              data-active=${this._mode === 'logs'}
              aria-selected=${this._mode === 'logs' ? 'true' : 'false'}
              @click=${() => this._set_mode('logs')}
            >Logs</button>
            <button
              type="button"
              role="tab"
              class="terminal-tab"
              data-active=${this._mode === 'shell'}
              aria-selected=${this._mode === 'shell' ? 'true' : 'false'}
              @click=${() => this._set_mode('shell')}
            >Shell</button>
            <span class="terminal-spacer"></span>
            <button
              type="button"
              class="terminal-action"
              title="Clear terminal"
              @click=${this._clear}
            >Clear</button>
            <button
              type="button"
              class="terminal-action"
              title="Restart shell"
              ?disabled=${disabled || this._starting}
              @click=${this._restart}
            >Restart</button>
          </div>
              ? 'The terminal is disabled for this bridge (non-loopback bind or --no-terminal).'
              : 'The configured shell is unavailable; logs still work here.'
            : nothing}
          <div class="terminal-host" data-mode=${this._mode}></div>
        `}
      </section>
    `;
  }

  _status_label(meta) {
    if (this._status) return this._status;
    if (!meta.enabled) return 'logs';
    if (meta.running) return 'shell';
    return meta.available ? 'idle' : 'off';
  }

  _toggle_collapsed() {
    this._collapsed = !this._collapsed;
    this._persist_bool(COLLAPSE_KEY, this._collapsed);
    if (!this._collapsed) this._unread = 0;
    this.requestUpdate();
  }

  _set_mode(mode) {
    if (this._mode === mode) return;
    this._mode = mode;
    this._persist_mode(mode);
    if (mode === 'logs') {
      this._unread = 0;
      this._write_log_history();
    }
    this.requestUpdate();
  }

  async _sync_mode() {
    if (this._mode === 'shell') {
      await this._ensure_shell();
    }
  }

  async _ensure_shell() {
    if (this._socket_open || this._starting) return;
    const bridge_id = this._store.state.bridge_id;
    const meta = this._store.state.terminal || {};
    if (!bridge_id || !meta.available) return;
    this._starting = true;
    try {
      const result = await start_terminal(bridge_id);
      const session = result.terminal || {};
      this._status = 'connecting';
      this.requestUpdate();
      const socket = open_terminal_socket(bridge_id, session.seq || 0);
      this._client = new TerminalClient(socket, {
        on_data: (data) => this._write_bytes(data),
        on_ready: (message) => {
          this._socket_open = true;
          this._status = '';
          this._fit_terminal();
          if (message.cols && message.rows) this._client?.resize(message.cols, message.rows);
          this.requestUpdate();
        },
        on_reset: () => this._terminal?.reset(),
        on_exit: (message) => {
          this._socket_open = false;
          this._status = `exited ${message.code ?? ''}`.trim();
          this._terminal?.write(`\r\n[terminal exited]\r\n`);
          this.requestUpdate();
        },
        on_error: (message) => {
          this._socket_open = false;
          this._status = message;
          this.requestUpdate();
        },
        on_close: () => {
          this._socket_open = false;
          this.requestUpdate();
        },
      });
      socket.onopen = () => {
        this._status = '';
      };
    } catch (error) {
      this._status = error.message;
    } finally {
      this._starting = false;
      this.requestUpdate();
    }
  }

  _mount_terminal(host) {
    if (this._terminal) return;
    const terminal = new Terminal({
      convertEol: true,
      cursorBlink: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: 12,
      scrollback: 5000,
      theme: {
        background: '#ffffff',
        foreground: '#111111',
        cursor: '#111111',
        selectionBackground: '#cfe3ff',
      },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(host);
    this._terminal = terminal;
    this._fit = fit;
    this._fit_terminal();

    terminal.onData((data) => {
      if (this._mode === 'shell') this._client?.send_input(data);
    });
    terminal.onResize(({ cols, rows }) => {
      if (this._mode === 'shell') this._client?.resize(cols, rows);
    });

    this._resize_observer = new ResizeObserver(() => this._fit_terminal());
    this._resize_observer.observe(host);

    this._write_log_history();
  }

  _dispose_terminal() {
    this._client?.close();
    this._client = null;
    this._socket_open = false;
    this._resize_observer?.disconnect();
    this._resize_observer = null;
    this._terminal?.dispose();
    this._terminal = null;
    this._fit = null;
    this._host = null;
  }

  _fit_terminal() {
    if (!this._fit || !this._terminal || this._host?.offsetParent === null) return;
    try {
      this._fit.fit();
    } catch (error) {
      /* host not visible */
    }
  }

  _write_bytes(data) {
    if (!this._terminal) return;
    this._terminal.write(data);
  }

  _write_text(text) {
    this._terminal?.write(text);
  }

  _write_log_history() {
    if (!this._terminal || this._mode !== 'logs') return;
    this._terminal.reset();
    for (const entry of get_terminal_logs().slice(-MAX_LOGS)) this._write_log(entry);
  }

  _on_log(entry) {
    this._write_log(entry);
    if (this._collapsed || this._mode !== 'logs') {
      this._unread += 1;
      this.requestUpdate();
    }
  }

  _write_log(entry) {
    if (!this._terminal || this._mode !== 'logs') return;
    const stamp = new Date(entry.ts).toLocaleTimeString([], { hour12: false });
    const color = LEVEL_COLORS[entry.level] || LEVEL_COLORS.info;
    this._terminal.write(`${color}[${stamp}] ${String(entry.level).padEnd(7)}${RESET} ${entry.message}\r\n`);
  }

  _clear() {
    if (this._mode === 'logs') {
      this._terminal?.reset();
      return;
    }
    this._terminal?.clear();
  }

  async _restart() {
    const bridge_id = this._store.state.bridge_id;
    if (!bridge_id) return;
    this._client?.close();
    this._client = null;
    this._socket_open = false;
    try {
      await stop_terminal(bridge_id);
    } catch (error) {
      /* already stopped */
    }
    this._status = '';
    this._terminal?.reset();
    await this._ensure_shell();
  }

  _on_global_keydown(event) {
    if (!event.ctrlKey || event.key !== '`') return;
    const tag = event.target?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || event.target?.isContentEditable) return;
    event.preventDefault();
    this._toggle_collapsed();
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

  _read_mode() {
    try {
      return localStorage.getItem(MODE_KEY) === 'shell' ? 'shell' : 'logs';
    } catch (error) {
      return 'logs';
    }
  }

  _persist_mode(mode) {
    try {
      localStorage.setItem(MODE_KEY, mode);
    } catch (error) {
      /* storage disabled */
    }
  }
}

customElements.define('terminal-panel', TerminalPanel);
