import { LitElement, html, nothing } from 'lit';

import { ACTIONS_ICON, NEW_CHAT_ICON, RESTART_ICON } from '../core/constants.js';
import { session } from '../core/session.js';
import { StoreController, store } from '../core/store.js';

export class ActionsMenu extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._open = false;
    this._sending = false;
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    this._on_pointer_down = (event) => this._close_outside(event);
    document.addEventListener('pointerdown', this._on_pointer_down, true);
  }

  disconnectedCallback() {
    document.removeEventListener('pointerdown', this._on_pointer_down, true);
    super.disconnectedCallback();
  }

  render() {
    const state = this._store.state;
    const ready = state.status === 'ready';
    const clear_disabled = this._sending || state.new_chat_pending || state.busy || !ready;
    const reset_disabled = this._sending || state.restart_pending || state.busy || !ready;

    return html`
      <div
        class="strip-menu actions"
        @focusout=${this._on_focus_out}
        @keydown=${this._on_keydown}
      >
        <button
          type="button"
          class="strip-btn actions-trigger"
          title="Session actions"
          aria-label="Session actions"
          aria-haspopup="menu"
          aria-expanded=${this._open ? 'true' : 'false'}
          @click=${this._toggle}
        >
          <span class="actions-icon" aria-hidden="true">${ACTIONS_ICON}</span>
        </button>
        ${this._open ? html`
          <div class="actions-panel" role="menu" aria-label="Session actions">
            <button
              type="button"
              class="actions-item"
              role="menuitem"
              ?disabled=${clear_disabled}
              @click=${this._clear}
            >
              <span class="actions-item-icon" aria-hidden="true">${NEW_CHAT_ICON}</span>
              <span class="actions-item-text">
                <span class="actions-item-label">Clear</span>
                <span class="actions-item-hint">Send <code>/clear</code></span>
              </span>
            </button>
            <button
              type="button"
              class="actions-item"
              role="menuitem"
              ?disabled=${reset_disabled}
              @click=${this._reset}
            >
              <span class="actions-item-icon" aria-hidden="true">${RESTART_ICON}</span>
              <span class="actions-item-text">
                <span class="actions-item-label">Reset</span>
                <span class="actions-item-hint">Send <code>/reset</code></span>
              </span>
            </button>
          </div>
        ` : nothing}
      </div>
    `;
  }

  async _clear() {
    await this._send('/clear');
  }

  async _reset() {
    await this._send('/reset');
  }

  async _send(command) {
    if (this._sending) return;

    this._sending = true;
    this._close_panel();
    try {
      const sent = await session.send_prompt(command);
      if (sent !== false) session.reset_transcript_state();
    } finally {
      this._sending = false;
      this.requestUpdate();
    }
  }

  _toggle(event) {
    event.stopPropagation();

    if (this._open) {
      this._close_panel();
      return;
    }

    this._open = true;
    this.requestUpdate();
  }

  _close_panel() {
    if (!this._open) return;

    this._open = false;
    this.requestUpdate();
  }

  _focus_trigger() {
    this.querySelector('.actions-trigger')?.focus();
  }

  _on_focus_out(event) {
    const next = event.relatedTarget;
    if (next && this.contains(next)) return;
    this._close_panel();
  }

  _on_keydown(event) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      this._close_panel();
      this._focus_trigger();
      return;
    }

    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;

    const items = [...this.querySelectorAll('.actions-item:not(:disabled)')];
    if (!items.length) return;

    event.preventDefault();
    const index = items.indexOf(document.activeElement);
    const step = event.key === 'ArrowDown' ? 1 : -1;
    const next = index === -1 ? 0 : (index + step + items.length) % items.length;
    items[next].focus();
  }

  _close_outside(event) {
    if (!this._open) return;
    if (event.composedPath().includes(this)) return;
    this._close_panel();
  }
}

customElements.define('actions-menu', ActionsMenu);