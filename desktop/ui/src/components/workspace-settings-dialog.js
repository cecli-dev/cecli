import { LitElement, html, nothing } from 'lit';

import { session } from '../core/session.js';

export class WorkspaceSettingsDialog extends LitElement {
  static properties = {
    open: { type: Boolean },
    workspace: { type: Object },
  };

  constructor() {
    super();
    this.open = false;
    this.workspace = null;
    this._name = '';
    this._enabled = true;
    this._error = '';
    this._busy = false;
    this._focus_pending = false;
  }

  createRenderRoot() {
    return this;
  }

  willUpdate(changed) {
    if (!changed.has('open') && !changed.has('workspace')) return;
    if (!this.open || !this.workspace) return;

    this._name = this.workspace.name || '';
    this._enabled = this.workspace.enable_on_startup !== false;
    this._error = '';
    this._focus_pending = true;
  }

  updated() {
    if (!this.open || !this._focus_pending) return;
    this._focus_pending = false;
    this.querySelector('.workspace-name-input')?.focus();
  }

  render() {
    if (!this.open || !this.workspace) return nothing;

    return html`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="workspace-settings-title"
          @click=${this._stop}
        >
          <h2 id="workspace-settings-title">Workspace settings</h2>
          <p class="modal-hint workspace-settings-path">${this._path()}</p>
          <label class="modal-field">
            <span>Display name</span>
            <input
              class="workspace-name-input"
              type="text"
              .value=${this._name}
              placeholder="Optional label"
              @input=${this._on_name}
              @keydown=${this._on_keydown}
            />
          </label>
          <label class="workspace-toggle">
            <input
              type="checkbox"
              .checked=${this._enabled}
              @change=${this._on_enabled}
            />
            <span>
              <span class="workspace-toggle-title">Start when cecli desktop opens</span>
              <span class="workspace-toggle-hint">
                Load this workspace's session automatically at launch.
              </span>
            </span>
          </label>
          ${this._error ? html`<p class="modal-error">${this._error}</p>` : nothing}
          <div class="modal-actions modal-actions--split">
            <button
              type="button"
              class="modal-btn modal-btn--danger"
              ?disabled=${this._busy}
              @click=${this._remove}
            >Remove workspace</button>
            <span class="modal-actions-spacer"></span>
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
            <button
              type="button"
              class="modal-btn modal-btn--primary"
              ?disabled=${this._busy}
              @click=${this._submit}
            >${this._busy ? 'Saving\u2026' : 'Save'}</button>
          </div>
        </div>
      </div>
    `;
  }

  _path() {
    return this.workspace?.path || this.workspace?.workspace || '';
  }

  _on_backdrop() {
    if (!this._busy) this._close();
  }

  _on_name(event) {
    this._name = event.target.value;
  }

  _on_enabled(event) {
    this._enabled = event.target.checked;
  }

  _on_keydown(event) {
    if (event.key === 'Escape') this._close();
    if (event.key === 'Enter' && !event.isComposing) this._submit();
  }

  _stop(event) {
    event.stopPropagation();
  }

  async _submit() {
    if (this._busy) return;
    this._busy = true;
    this._error = '';
    try {
      await session.update_workspace(this._path(), {
        name: this._name.trim(),
        enable_on_startup: this._enabled,
      });
      this._close();
    } catch (error) {
      this._error = error.message;
    } finally {
      this._busy = false;
      this.requestUpdate();
    }
  }

  async _remove() {
    if (this._busy) return;
    const label = this._name.trim() || this._path();
    if (!window.confirm(`Remove workspace "${label}" from cecli desktop?`)) return;

    this._busy = true;
    this._error = '';
    try {
      await session.remove_workspace(this._path());
      this._close();
    } catch (error) {
      this._error = error.message;
    } finally {
      this._busy = false;
      this.requestUpdate();
    }
  }

  _close() {
    this.open = false;
    this._error = '';
    this._busy = false;
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }
}

customElements.define('workspace-settings-dialog', WorkspaceSettingsDialog);
