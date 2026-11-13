import { LitElement, html, nothing } from 'lit';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

import { TerminalWriteQueue } from '../core/terminal-write-queue.js';
import { open_terminal_socket, start_terminal, stop_terminal } from '../core/terminal-api.js';
import { TerminalClient } from '../core/terminal-client.js';

const HIDDEN_CLOSE_MS = 5 * 60 * 1000;

export class CliTerminalView extends LitElement {
  static properties = {
    bridge_id: { type: String },
    terminal_id: { type: String },
    active: { type: Boolean },
    terminal_meta: { attribute: false },
    live_bridges: { attribute: false },
  };

  constructor() {
    super();
    this.bridge_id = '';
    this.terminal_id = '';
    this.active = false;
    this.terminal_meta = {};
    this.live_bridges = null;
    this._sessions = new Map();
    this._slot = null;
    this._attached = null;
  }

  createRenderRoot() {
    return this;
  }

  updated() {
    const slot = this.querySelector('.cli-shell-host-slot');
    if (slot) this._slot = slot;
    this._prune_sessions();
    if (!this.bridge_id || !this._slot) return;

    const session = this._session();
    if (session && this._attached !== session) {
      this._attached?.host.remove();
      this._slot.append(session.host);
      this._attached = session;
    }

    if (!this.active) {
      this._schedule_idle_close(session);
      return;
    }

    this._cancel_timer(session);
    this._ensure_open(session);
    this._fit_soon(session);
  }

  disconnectedCallback() {
    for (const session of this._sessions.values()) this._dispose_session(session);
    this._sessions.clear();
    this._attached = null;
    super.disconnectedCallback();
  }

  render() {
    const session = this._session();
    const meta = this.terminal_meta || {};
    const disabled = meta.enabled === false || meta.available === false;
    const waiting = this.active && session && !session.opened && !disabled;
    const status = session?.status || '';

    return html`
      <div class="cli-shell-wrap">
        ${disabled
          ? html`<p class="cli-note">The shell is disabled for this bridge. Logs and background tabs still work.</p>`
          : nothing}
        ${waiting ? html`<p class="cli-note">Starting shell\u2026</p>` : nothing}
        ${status ? html`<p class="cli-note" role="status">${status}</p>` : nothing}
        <div class="cli-shell-host-slot"></div>
      </div>
    `;
  }

  fit() {
    this._fit_soon(this._session());
  }

  restart() {
    const session = this._session();
    if (!session) return;

    session.queue?.reset();
    session.terminal?.reset();
    session.client?.close();
    session.client = null;
    session.socket_open = false;
    session.failed = false;
    session.opened = true;
    session.status = '';
    session.gap_attempts = 0;

    this._connect(session, true).catch((error) => {
      session.status = error.message;
      this.requestUpdate();
    });
  }

  async stop() {
    const session = this._session();
    if (!session) return;

    session.client?.close();
    session.client = null;
    session.socket_open = false;

    try {
      await stop_terminal(session.bridge_id, session.terminal_id);
    } catch (error) {
      /* already stopped */
    }

    session.status = 'stopped';
    this.requestUpdate();
  }

  _session() {
    if (!this.bridge_id) return null;
    const key = this._session_key();
    let session = this._sessions.get(key);

    if (!session) {
      const host = document.createElement('div');
      host.className = 'cli-xterm-host';
      host.dataset.bridge = this.bridge_id;
      host.dataset.terminal = this.terminal_id;
      session = {
        key, bridge_id: this.bridge_id, terminal_id: this.terminal_id,
        host, terminal: null, fit: null, client: null,
        queue: null, opened: false, starting: false, failed: false, socket_open: false,
        status: '', pending_since: null, resize_observer: null, idle_timer: null,
        gap_attempts: 0,
      };
      this._sessions.set(key, session);
    }

    return session;
  }

  _ensure_open(session) {
    if (!session || session.opened || session.starting) return;
    const meta = this.terminal_meta || {};
    if (meta.enabled === false || meta.available === false) return;

    session.opened = true;
    if (!session.terminal) this._mount(session);
    this._connect(session, false).catch((error) => {
      session.status = error.message;
      this.requestUpdate();
    });
  }

  _mount(session) {
    const terminal = new Terminal({
      convertEol: true,
      cursorBlink: true,
      disableStdin: false,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: 12,
      scrollback: 5000,
      theme: {
        background: '#0f1115',
        foreground: '#e6e7eb',
        cursor: '#e6e7eb',
        selectionBackground: '#3a4a66',
      },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(session.host);

    session.terminal = terminal;
    session.fit = fit;
    session.queue = new TerminalWriteQueue((data) => terminal.write(data));

    terminal.attachCustomKeyEventHandler((event) => {
      if (event.type !== 'keydown' || event.key !== 'Enter' || !event.shiftKey) return true;
      if (!this.active || this._session() !== session) return true;

      event.preventDefault();
      session.client?.send_input('\n');
      return false;
    });

    terminal.onData((data) => {
      if (this.active && this._session() === session) session.client?.send_input(data);
    });
    terminal.onResize(({ cols, rows }) => {
      if (this.active && this._session() === session) session.client?.resize(cols, rows);
    });
    terminal.onBell(() => {
      if (this._session() === session) {
        this.dispatchEvent(new CustomEvent('terminal-attention', {
          detail: { terminal_id: this.terminal_id },
          bubbles: true,
          composed: true,
        }));
      }
    });

    session.resize_observer = new ResizeObserver(() => this._fit_soon(session));
    session.resize_observer.observe(session.host);
    this._fit_soon(session);

    if (typeof document !== 'undefined' && document.fonts?.ready) {
      document.fonts.ready.then(() => this._fit_soon(session));
    }
  }

  async _connect(session, restart) {
    if (!session || session.client || session.failed) return;

    session.starting = true;

    try {
      if (restart) {
        try {
          await stop_terminal(session.bridge_id, session.terminal_id);
        } catch (error) {
          /* already stopped */
        }
      }

      const result = await start_terminal(session.bridge_id, session.terminal_id);
      this.dispatchEvent(new CustomEvent('terminal-state', {
        detail: result?.terminals || null,
        bubbles: true,
        composed: true,
      }));
      const since = session.pending_since ?? 0;
      session.pending_since = null;
      const socket = open_terminal_socket(session.bridge_id, since, session.terminal_id);

      session.client = new TerminalClient(socket, {
        on_data: (data) => session.queue?.enqueue(data),
        on_ready: (message) => {
          session.socket_open = true;
          session.status = '';
          session.gap_attempts = 0;
          this._fit_soon(session);
          if (message.cols && message.rows) session.client?.resize(message.cols, message.rows);
          if (this._session() === session) this.requestUpdate();
        },
        on_reset: () => {
          session.queue?.reset();
          session.terminal?.reset();
        },
        on_gap: ({ since: gap_since }) => {
          session.client?.close();
          session.client = null;
          session.socket_open = false;
          session.gap_attempts = (session.gap_attempts || 0) + 1;

          if (session.gap_attempts > 5) {
            session.status = 'Terminal unavailable — use Restart';
            session.failed = true;
            session.opened = true;
            if (this._session() === session) this.requestUpdate();
            return;
          }

          session.pending_since = gap_since;
          session.status = 'Resyncing output…';
          if (this._session() === session) this.requestUpdate();
          const delay = Math.min(300 * 2 ** (session.gap_attempts - 1), 3000);
          setTimeout(() => {
            if (this._sessions.get(session.key) === session) this._connect(session, false);
          }, delay);
        },
        on_exit: (message) => {
          session.socket_open = false;
          session.status = `exited ${message.code ?? ''}`.trim();
          if (this._session() === session) this.requestUpdate();
        },
        on_error: (message) => {
          session.socket_open = false;
          session.status = message;
          if (this._session() === session) this.requestUpdate();
        },
        on_close: () => {
          session.socket_open = false;
          if (this._session() === session) this.requestUpdate();
        },
      });
      session.starting = false;
      session.failed = false;
    } catch (error) {
      session.status = 'Terminal unavailable — use Restart';
      session.starting = false;
      session.opened = true;
      session.failed = true;
      if (this._session() === session) this.requestUpdate();
    }
  }

  _prune_sessions() {
    if (!Array.isArray(this.live_bridges) || !this.live_bridges.length) return;

    const live = new Set(this.live_bridges);
    if (this.bridge_id) live.add(this.bridge_id);

    for (const [key, session] of this._sessions) {
      if (live.has(session.bridge_id)) continue;
      this._dispose_session(session);
      this._sessions.delete(key);
      if (this._attached === session) this._attached = null;
    }
  }

  _fit_soon(session) {
    requestAnimationFrame(() => {
      if (!session || session !== this._session() || !this.active) return;
      if (!session.fit || !session.terminal) return;
      if (!session.host.isConnected || session.host.offsetParent === null) return;

      try {
        session.fit.fit();
        session.terminal.refresh(0, Math.max(0, session.terminal.rows - 1));
      } catch (error) {
        /* host not visible */
      }
    });
  }

  _schedule_idle_close(session) {
    if (!session?.client || session.idle_timer !== null) return;

    session.idle_timer = setTimeout(() => {
      session.idle_timer = null;
      if (this._session() === session && this.active) return;
      session.pending_since = session.client?.seq ?? 0;
      session.client?.close();
      session.client = null;
      session.socket_open = false;
    }, HIDDEN_CLOSE_MS);
  }

  _cancel_timer(session) {
    if (session?.idle_timer === null || session?.idle_timer === undefined) return;
    clearTimeout(session.idle_timer);
    session.idle_timer = null;
  }

  _session_key() {
    return `${this.bridge_id}::${this.terminal_id}`;
  }

  _dispose_session(session) {
    this._cancel_timer(session);
    session.resize_observer?.disconnect();
    session.resize_observer = null;
    session.client?.close();
    session.client = null;
    session.queue?.dispose();
    session.queue = null;
    session.terminal?.dispose();
    session.terminal = null;
    session.host.remove();
  }
}

customElements.define('cli-terminal-view', CliTerminalView);