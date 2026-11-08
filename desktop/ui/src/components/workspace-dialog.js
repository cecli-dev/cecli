import { LitElement, html, nothing } from 'lit';

import { get_directory_suggestions } from '../core/api.js';
import { session } from '../core/session.js';

const SUGGESTION_DELAY = 120;

export class WorkspaceDialog extends LitElement {
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
    this._suggestions = [];
    this._suggestions_open = false;
    this._active_index = -1;
    this._suggest_timer = null;
    this._request_seq = 0;
    this._focus_pending = false;
    this._document_listener = null;
  }

  createRenderRoot() {
    return this;
  }

  disconnectedCallback() {
    this._stop_listening();
    clearTimeout(this._suggest_timer);
    super.disconnectedCallback();
  }

  willUpdate(changed) {
    if (!changed.has('open')) return;

    if (this.open) {
      this._error = '';
      this._focus_pending = true;
      this._start_listening();
      return;
    }

    this._stop_listening();
    this._close_suggestions();
  }

  updated() {
    if (!this.open || !this._focus_pending) return;
    this._focus_pending = false;
    this.querySelector('.workspace-path-input')?.focus();
  }

  render() {
    if (!this.open) return nothing;

    return html`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workspace-dialog-title"
          @click=${this._stop}
        >
          <h2 id="workspace-dialog-title">Add workspace</h2>
          <label class="modal-field">
            <span>Folder path</span>
            <input
              class="workspace-path-input"
              type="text"
              .value=${this._path}
              placeholder="/path/to/project"
              autocomplete="off"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded=${this._suggestions_open}
              aria-controls="workspace-path-suggestions"
              @input=${this._on_path}
              @focus=${this._on_path_focus}
              @keydown=${this._on_keydown}
            />
          </label>
          ${this._render_suggestions()}
          <label class="modal-field">
            <span>Display name</span>
            <input
              type="text"
              .value=${this._name}
              placeholder="Optional label"
              @input=${this._on_name}
              @focus=${this._on_name_focus}
              @keydown=${this._on_keydown}
            />
          </label>
          <p class="modal-hint">Saved to .cecli/conf.yml and opened as a new session.</p>
          ${this._error ? html`<p class="modal-error">${this._error}</p>` : nothing}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
            <button
              type="button"
              class="modal-btn modal-btn--primary"
              ?disabled=${this._busy}
              @click=${this._submit}
            >
              ${this._busy ? 'Adding\u2026' : 'Add workspace'}
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _render_suggestions() {
    if (!this._suggestions_open) return nothing;

    return html`
      <ul class="path-suggestions" id="workspace-path-suggestions" role="listbox">
        ${this._suggestions.map(
          (item, index) => html`
            <li role="option" aria-selected=${index === this._active_index}>
              <button
                type="button"
                class="path-suggestion"
                data-active=${index === this._active_index}
                @mousedown=${this._keep_focus}
                @click=${() => this._choose(item)}
              >
                <span class="path-suggestion-name">${item.name}</span>
                <span class="path-suggestion-path">${item.path}</span>
              </button>
            </li>
          `,
        )}
      </ul>
    `;
  }

  _on_backdrop() {
    if (!this._busy) this._close();
  }

  _on_path(event) {
    this._path = event.target.value;
    this._queue_suggestions();
  }

  _on_path_focus() {
    if (!this._suggestions_open) this._queue_suggestions(0);
  }

  _on_name(event) {
    this._name = event.target.value;
  }

  _on_name_focus() {
    this._close_suggestions();
  }

  _on_keydown(event) {
    const from_path = event.target.classList.contains('workspace-path-input');

    if (event.key === 'Escape') {
      if (this._suggestions_open) {
        this._close_suggestions();
        event.stopPropagation();
        return;
      }
      this._close();
      return;
    }

    if (from_path && this._suggestions_open && this._suggestions.length) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        this._move_active(1);
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        this._move_active(-1);
        return;
      }
      if (event.key === 'Tab' || event.key === 'Enter') {
        event.preventDefault();
        const index = this._active_index >= 0 ? this._active_index : 0;
        this._choose(this._suggestions[index]);
        return;
      }
    }

    if (event.key === 'Enter' && !event.isComposing) this._submit();
  }

  _stop(event) {
    event.stopPropagation();
  }

  _keep_focus(event) {
    event.preventDefault();
  }

  _queue_suggestions(delay = SUGGESTION_DELAY) {
    clearTimeout(this._suggest_timer);
    this._suggest_timer = setTimeout(() => this._fetch_suggestions(), delay);
  }

  async _fetch_suggestions() {
    const seq = ++this._request_seq;

    try {
      const result = await get_directory_suggestions(this._path);
      if (seq !== this._request_seq) return;

      this._suggestions = Array.isArray(result.entries) ? result.entries : [];
      this._suggestions_open = this._suggestions.length > 0;
      this._active_index = -1;
    } catch (error) {
      if (seq !== this._request_seq) return;
      this._suggestions = [];
      this._suggestions_open = false;
    }

    this.requestUpdate();
  }

  _move_active(delta) {
    const count = this._suggestions.length;
    if (!count) return;

    if (this._active_index < 0) {
      this._active_index = delta > 0 ? 0 : count - 1;
    } else {
      this._active_index = (this._active_index + delta + count) % count;
    }

    this.requestUpdate();
  }

  _choose(item) {
    this._path = item.path;
    if (!this._name.trim()) this._name = item.name;
    this._close_suggestions();
  }

  _close_suggestions() {
    this._suggestions = [];
    this._suggestions_open = false;
    this._active_index = -1;
    this.requestUpdate();
  }

  _start_listening() {
    if (this._document_listener) return;

    this._document_listener = (event) => {
      if (this.contains(event.target)) return;
      this._close_suggestions();
    };
    document.addEventListener('pointerdown', this._document_listener);
  }

  _stop_listening() {
    if (!this._document_listener) return;

    document.removeEventListener('pointerdown', this._document_listener);
    this._document_listener = null;
  }

  async _submit() {
    if (this._busy) return;
    const path = this._path.trim();
    if (!path) {
      this._error = 'A folder path is required';
      return;
    }

    this._busy = true;
    this._error = '';
    this._close_suggestions();
    try {
      await session.add_workspace(path, this._name.trim() || null);
      this._close();
    } catch (error) {
      this._error = error.message;
    } finally {
      this._busy = false;
      this.requestUpdate();
    }
  }

  _close() {
    clearTimeout(this._suggest_timer);
    this._path = '';
    this._name = '';
    this._error = '';
    this._busy = false;
    this._suggestions = [];
    this._suggestions_open = false;
    this._active_index = -1;
    this._stop_listening();
    this.open = false;
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }
}

customElements.define('workspace-dialog', WorkspaceDialog);