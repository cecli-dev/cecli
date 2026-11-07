import { LitElement, html, nothing } from 'lit';

import { session } from '../core/session.js';
import { store } from '../core/store.js';

export class SessionDialog extends LitElement {
  static properties = {
    open: { type: Boolean },
  };

  constructor() {
    super();
    this.open = false;
    this._path = '';
    this._name = '';
    this._error = '';
    this._busy = false;
  }

  createRenderRoot() {
    return this;
  }

  willUpdate(changed) {
    if (changed.has('open') && this.open && !this._path) {
      this._path = store.state.workspace || '';
    }
  }

  updated() {
    if (!this.open) return;
    const input = this.querySelector('.modal-field input');
    if (input && document.activeElement !== input) input.focus();
  }

  render() {
    if (!this.open) return nothing;

    return html`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="session-dialog-title"
          @click=${this._stop}
        >
          <h2 id="session-dialog-title">New session</h2>
          <label class="modal-field">
            <span>Workspace path</span>
            <input
              type="text"
              .value=${this._path}
              placeholder="/path/to/project"
              @input=${this._on_path}
            />
          </label>
          <label class="modal-field">
            <span>Session name</span>
            <input
              type="text"
              .value=${this._name}
              placeholder="Optional label"
              @input=${this._on_name}
            />
          </label>
          ${this._error ? html`<p class="modal-error">${this._error}</p>` : nothing}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
            <button
              type="button"
              class="modal-btn modal-btn--primary"
              ?disabled=${this._busy}
              @click=${this._submit}
            >
              ${this._busy ? 'Creating…' : 'Create'}
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _on_backdrop() {
    if (!this._busy) this._close();
  }

  _on_path(event) {
    this._path = event.target.value;
  }

  _on_name(event) {
    this._name = event.target.value;
  }

  _stop(event) {
    event.stopPropagation();
  }

  async _submit() {
    const path = this._path.trim();
    if (!path) {
      this._error = 'A workspace path is required';
      return;
    }

    this._busy = true;
    this._error = '';
    try {
      const bridge_id = await session.create_session(path, this._name.trim() || null);
      if (!bridge_id) throw new Error('The bridge did not create a session');
      this._close();
    } catch (error) {
      this._error = error.message;
    } finally {
      this._busy = false;
      this.requestUpdate();
    }
  }

  _close() {
    this._path = '';
    this._name = '';
    this._error = '';
    this._busy = false;
    this.open = false;
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }
}

customElements.define('session-dialog', SessionDialog);