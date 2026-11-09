import { LitElement, html, nothing } from 'lit';

const HISTORY_LIMIT = 50;

export class CliStdinComposer extends LitElement {
  static properties = {
    tab: { attribute: false },
    notice: { type: String },
  };

  constructor() {
    super();
    this.tab = null;
    this.notice = '';
    this._secret = false;
    this._history = new Map();
    this._history_index = null;
  }

  createRenderRoot() {
    return this;
  }

  focus() {
    this.querySelector('.cli-stdin-input')?.focus();
  }

  clear({ remember = true, secret = false } = {}) {
    const input = this.querySelector('.cli-stdin-input');
    if (!input) return;

    const text = input.value;
    if (remember && !secret && text.trim() && this.tab) {
      const history = this._history.get(this.tab.key) || [];
      history.push(text);
      while (history.length > HISTORY_LIMIT) history.shift();
      this._history.set(this.tab.key, history);
    }

    input.value = '';
    this._history_index = null;
    input.focus();
  }

  render() {
    const tab = this.tab;
    const enabled = Boolean(tab && ['running', 'needs_input'].includes(tab.status)
      && (tab.input_owner === null || tab.input_owner === 'ui'));
    const owner_note = tab?.input_owner && tab.input_owner !== 'ui'
      ? `Controlled by ${tab.input_owner}`
      : '';

    return html`
      <div class="cli-stdin" data-enabled=${String(enabled)}>
        <header class="cli-stdin-head">
          <span class="cli-stdin-heading">STDIN</span>
          <span class="cli-stdin-status">${owner_note || 'stdin'}</span>
          <span class="cli-stdin-actions">
            <button
              class="cli-stdin-secret"
              type="button"
              title="Secret input"
              aria-pressed=${String(this._secret)}
              ?disabled=${!enabled}
              @click=${this._toggle_secret}
            >${this._secret ? '\ud83d\udd12' : '\ud83d\udd13'}</button>
            <button
              class="cli-stdin-send"
              type="button"
              ?disabled=${!enabled}
              @click=${() => this._submit(true)}
            >Send</button>
          </span>
        </header>
        ${this.notice ? html`<p class="cli-notice" role="status">${this.notice}</p>` : nothing}
        <div class="cli-stdin-body">
          <textarea
            class="cli-stdin-input"
            rows="4"
            spellcheck="false"
            autocomplete="off"
            placeholder=${enabled ? 'Send input\u2026  Enter adds a newline; Ctrl+Enter sends as-is' : owner_note || 'Input unavailable'}
            ?disabled=${!enabled}
            @keydown=${this._on_keydown}
          ></textarea>
        </div>
      </div>
    `;
  }

  _toggle_secret() {
    this._secret = !this._secret;
    const input = this.querySelector('.cli-stdin-input');
    if (input) input.style.webkitTextSecurity = this._secret ? 'disc' : 'none';
    this.requestUpdate();
  }

  _on_keydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this._submit(!event.ctrlKey && !event.metaKey);
      return;
    }

    if (event.key === 'ArrowUp' && !this._secret) {
      event.preventDefault();
      this._navigate_history(-1);
      return;
    }

    if (event.key === 'ArrowDown' && !this._secret) {
      event.preventDefault();
      this._navigate_history(1);
    }
  }

  _submit(newline) {
    const input = this.querySelector('.cli-stdin-input');
    if (!input || input.disabled) return;

    const text = input.value;
    if (!text) return;

    this.dispatchEvent(new CustomEvent('stdin-submit', {
      detail: { text, newline, secret: this._secret },
      bubbles: true,
      composed: true,
    }));
  }

  _navigate_history(direction) {
    if (!this.tab) return;

    const history = this._history.get(this.tab.key) || [];
    if (!history.length) return;

    const input = this.querySelector('.cli-stdin-input');
    if (!input) return;

    if (this._history_index === null) this._history_index = history.length;
    this._history_index = Math.max(0, Math.min(history.length, this._history_index + direction));
    input.value = this._history_index >= history.length ? '' : history[this._history_index];
    input.setSelectionRange?.(input.value.length, input.value.length);
  }
}

customElements.define('cli-stdin-composer', CliStdinComposer);