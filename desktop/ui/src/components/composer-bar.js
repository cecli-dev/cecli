import { LitElement, html } from 'lit';

import { SEND_ICON, STOP_ICON } from '../core/constants.js';
import { session } from '../core/session.js';
import { StoreController, selectors, store } from '../core/store.js';

export class ComposerBar extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._has_text = false;
    this._sending = false;
    this._applied_revision = 0;
    this._on_global_keydown = this._on_global_keydown.bind(this);
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener('keydown', this._on_global_keydown);
  }

  disconnectedCallback() {
    document.removeEventListener('keydown', this._on_global_keydown);
    super.disconnectedCallback();
  }

  updated() {
    const state = this._store.state;
    if (state.draft_revision === this._applied_revision) return;

    this._applied_revision = state.draft_revision;
    const textarea = this._textarea();
    if (!textarea) return;

    textarea.value = state.draft;
    this._has_text = state.draft.trim().length > 0;
    this._auto_grow();
    textarea.focus();
  }

  render() {
    const state = this._store.state;
    const busy = state.busy;
    const retry_visible = selectors.retry_visible(state);
    const disabled = !busy && (this._sending || state.status !== 'ready' || !this._has_text);

    return html`
      <footer class="composer">
        <div class="busy-indicator" ?hidden=${!busy}>
          <span class="spinner" aria-hidden="true"></span>
          <span>${selectors.busy_text(state)}</span>
        </div>
        <div class="composer-box">
          <textarea
            id="composer-input"
            rows="1"
            placeholder="Ask cecli anything…"
            aria-label="Message cecli"
            autocomplete="off"
            spellcheck="true"
            @input=${this._on_input}
            @keydown=${this._on_keydown}
          ></textarea>
          <button
            class="send-btn"
            type="button"
            data-mode=${busy ? 'stop' : 'send'}
            aria-label=${busy ? 'Stop this turn' : 'Send message'}
            ?disabled=${disabled}
            @click=${this._on_send_click}
          >${busy ? STOP_ICON : SEND_ICON}</button>
        </div>
        <div class="composer-meta">
          <span class="hint">Enter to send · Shift+Enter for newline · Esc to stop</span>
          <div class="composer-state">
            <button
              class="retry-btn"
              type="button"
              ?hidden=${!retry_visible}
              @click=${this._retry}
            >Retry last</button>
            <span class="turn-status" data-state=${state.turn_state}>
              <span class="turn-dot" aria-hidden="true"></span>
              <span>${selectors.turn_label(state)}</span>
            </span>
          </div>
        </div>
      </footer>
    `;
  }

  _textarea() {
    return this.querySelector('#composer-input');
  }

  _auto_grow() {
    const textarea = this._textarea();
    if (!textarea) return;

    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }

  _on_input() {
    const textarea = this._textarea();
    if (!textarea) return;

    this._has_text = textarea.value.trim().length > 0;
    this._auto_grow();
    this.requestUpdate();
  }

  _on_keydown(event) {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;

    event.preventDefault();
    if (!store.state.busy) this._submit();
  }

  _on_send_click() {
    if (store.state.busy) {
      session.cancel_turn();
      return;
    }

    this._submit();
  }

  async _submit() {
    const textarea = this._textarea();
    if (!textarea || this._sending) return;

    const text = textarea.value.trim();
    if (!text || store.state.busy) return;

    this._sending = true;
    this.requestUpdate();

    let sent = false;
    try {
      sent = await session.send_prompt(text);
    } finally {
      this._sending = false;
    }

    if (sent) {
      textarea.value = '';
      this._has_text = false;
      this._auto_grow();
    }

    this.requestUpdate();
  }

  _retry() {
    const state = store.state;
    if (state.busy || !state.last_prompt) return;

    const textarea = this._textarea();
    if (!textarea) return;

    textarea.value = state.last_prompt;
    this._has_text = true;
    this._auto_grow();
    this.requestUpdate();
    this._submit();
  }

  _on_global_keydown(event) {
    if (event.key !== 'Escape' || !store.state.busy) return;

    const textarea = this._textarea();
    if (document.activeElement === textarea && textarea.value.trim()) return;

    event.preventDefault();
    session.cancel_turn();
  }
}

customElements.define('composer-bar', ComposerBar);
