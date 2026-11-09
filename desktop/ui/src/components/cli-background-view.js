import { LitElement, html, nothing } from 'lit';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

import { open_cli_stream } from '../core/cli-api.js';
import { CliStreamState } from '../core/cli-stream.js';
import { TerminalWriteQueue } from '../core/terminal-write-queue.js';

const HIDDEN_CLOSE_MS = 5 * 60 * 1000;
const RECONNECT_MS = 1000;

export class CliBackgroundView extends LitElement {
  static properties = {
    tab: { attribute: false },
    active: { type: Boolean },
    raw_background: { type: Boolean },
  };

  constructor() {
    super();
    this.tab = null;
    this.active = false;
    this.raw_background = true;
    this._terminal = null;
    this._fit = null;
    this._queue = null;
    this._state = null;
    this._source = null;
    this._host = null;
    this._opened = false;
    this._text = '';
    this._notice = '';
    this._idle_timer = null;
    this._reconnect_timer = null;
  }

  createRenderRoot() {
    return this;
  }

  updated() {
    const host = this.querySelector('.cli-xterm-host');
    if (host && host !== this._host) this._host = host;

    if (this.active) {
      this._cancel_timers();
      this._ensure_open();
      if (this._opened && !this._source) this._connect();
      this._fit_soon();
    } else {
      this._schedule_idle_close();
    }
  }

  disconnectedCallback() {
    this._cancel_timers();
    this.dispose();
    super.disconnectedCallback();
  }

  render() {
    const tab = this.tab;
    return html`
      <div class="cli-bg-wrap" data-readonly="true">
        ${this._notice ? html`<p class="cli-note" role="status">${this._notice}</p>` : nothing}
        ${this.raw_background
          ? html`<div class="cli-xterm-host cli-bg-host" data-active=${String(this.active)}></div>`
          : html`<pre class="cli-bg-pre" tabindex="0">${this._text}</pre>`}
        ${tab?.status === 'lost'
          ? html`<p class="cli-note" role="status">The background command was lost; showing the output retained in this tab.</p>`
          : nothing}
      </div>
    `;
  }

  reconnect() {
    this._close_source();
    this._state = null;
    this._connect();
  }

  dispose() {
    this._close_source();
    this._fit = null;
    this._terminal?.dispose();
    this._terminal = null;
    this._queue?.dispose();
    this._queue = null;
    this._opened = false;
  }

  _ensure_open() {
    if (this._opened || !this.tab) return;
    this._opened = true;

    if (this.raw_background && this._host) this._mount_terminal();
    this._connect();
  }

  _mount_terminal() {
    const terminal = new Terminal({
      convertEol: false,
      cursorBlink: false,
      disableStdin: true,
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
    terminal.open(this._host);

    this._terminal = terminal;
    this._fit = fit;
    this._queue = new TerminalWriteQueue((data) => terminal.write(data));
    this._replay_text();
  }

  _connect() {
    if (!this.tab || this._source) return;

    const since = this._state?.next_seq ?? 0;
    this._state = new CliStreamState({ since });
    this._source = open_cli_stream(this.tab.bridge_id, this.tab.cli_id, since);

    this._source.onmessage = (event) => this._on_message(event);
    this._source.onerror = () => {
      if (!this._source) return;
      this._close_source();
      this._schedule_reconnect();
    };
  }

  _on_message(event) {
    let message = null;

    try {
      message = JSON.parse(event.data);
    } catch (error) {
      return;
    }

    const action = this._state?.apply(message);
    if (!action) return;

    if (action.kind === 'ready' || action.kind === 'reset') {
      if (action.kind === 'reset') this._clear_output();
      this._notice = '';
      return;
    }

    if (action.kind === 'append') {
      this._append(action.data);
      return;
    }

    if (action.kind === 'gap') {
      this._notice = 'Resyncing output\u2026';
      this._close_source();
      this._schedule_reconnect(action.next_seq);
      return;
    }

    if (action.kind === 'state') {
      this.dispatchEvent(new CustomEvent('bg-event', {
        detail: {
          cli_id: this.tab?.cli_id,
          command_key: this.tab?.command_key,
          event: 'state',
          state: action.state,
          needsInput: action.needs_input,
          lastPrompt: action.last_prompt,
          exitCode: action.exit_code,
          endedAt: action.ended_at,
        },
        bubbles: true,
        composed: true,
      }));
      return;
    }

    if (action.kind === 'event') {
      if (action.event === 'exited' || action.event === 'closed') this._close_source();
      this.dispatchEvent(new CustomEvent('bg-event', {
        detail: {
          cli_id: this.tab?.cli_id,
          command_key: this.tab?.command_key,
          event: action.event,
          ...action.message,
        },
        bubbles: true,
        composed: true,
      }));
      return;
    }

    if (action.kind === 'exit') {
      this._close_source();
      this.dispatchEvent(new CustomEvent('bg-exit', {
        detail: { cli_id: this.tab?.cli_id, code: action.code, signal: action.signal },
        bubbles: true,
        composed: true,
      }));
      return;
    }

    if (action.kind === 'error') {
      this._notice = action.error;
      this.requestUpdate();
    }
  }

  _append(data) {
    if (this.raw_background) {
      this._queue?.enqueue(data);
      return;
    }

    this._text += new TextDecoder().decode(data);
    if (this._text.length > 2_000_000) this._text = this._text.slice(-1_000_000);
    this.requestUpdate();
  }

  _replay_text() {
    if (this._text) this._queue?.enqueue(new TextEncoder().encode(this._text));
  }

  _clear_output() {
    this._queue?.reset();
    this._terminal?.reset();
    this._text = '';
    if (!this.raw_background) this.requestUpdate();
  }

  _close_source() {
    if (!this._source) return;
    this._source.close();
    this._source = null;
  }

  _schedule_reconnect(since = null) {
    if (this._reconnect_timer !== null) return;

    this._reconnect_timer = setTimeout(() => {
      this._reconnect_timer = null;
      if (!this.tab || !this.active) return;
      if (since !== null) this._state = new CliStreamState({ since });
      this._connect();
    }, RECONNECT_MS);
  }

  _schedule_idle_close() {
    if (this._idle_timer !== null || !this._source) return;

    this._idle_timer = setTimeout(() => {
      this._idle_timer = null;
      this._close_source();
    }, HIDDEN_CLOSE_MS);
  }

  _cancel_timers() {
    if (this._idle_timer !== null) clearTimeout(this._idle_timer);
    if (this._reconnect_timer !== null) clearTimeout(this._reconnect_timer);
    this._idle_timer = null;
    this._reconnect_timer = null;
  }

  _fit_soon() {
    requestAnimationFrame(() => {
      if (!this.raw_background || !this.active || !this._fit || !this._terminal) return;
      if (!this._host || this._host.offsetParent === null) return;

      try {
        this._fit.fit();
      } catch (error) {
        /* host not visible */
      }
    });
  }
}

customElements.define('cli-background-view', CliBackgroundView);