import { LitElement, html, nothing } from 'lit';

import { session } from '../core/session.js';

export class ModelDialog extends LitElement {
  static properties = {
    open: { type: Boolean },
    option: { attribute: false },
  };

  constructor() {
    super();
    this.open = false;
    this.option = null;
    this._query = '';
    this._error = '';
    this._busy = false;
  }

  createRenderRoot() {
    return this;
  }

  willUpdate(changed) {
    if (changed.has('open') && this.open) {
      this._query = '';
      this._error = '';
    }
  }

  updated() {
    if (!this.open) return;
    const input = this.querySelector('.model-search');
    if (input && document.activeElement !== input) input.focus();
  }

  render() {
    if (!this.open || !this.option) return nothing;

    const items = this._filtered_items();
    const current = String(this.option.currentValue || '');

    return html`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card modal-card--wide"
          role="dialog"
          aria-modal="true"
          aria-labelledby="model-dialog-title"
          @click=${this._stop}
        >
          <h2 id="model-dialog-title">Choose model</h2>
          <input
            class="model-search"
            type="search"
            .value=${this._query}
            placeholder="Search models…"
            aria-label="Search models"
            @input=${this._on_query}
            @keydown=${this._on_keydown}
          />
          <p class="modal-hint">${items.length} model${items.length === 1 ? '' : 's'}</p>
          ${items.length
            ? html`
                <ul class="registry-modal-list model-list">
                  ${items.map(
                    (item) => html`
                      <li>
                        <button
                          type="button"
                          class="registry-modal-row model-row"
                          data-active=${String(item.value) === current}
                          ?disabled=${this._busy}
                          @click=${() => this._select(item.value)}
                        >
                          <span class="registry-modal-name" title=${item.value}>${item.name}</span>
                          ${item.group
                            ? html`<span class="model-group">${item.group}</span>`
                            : nothing}
                          ${String(item.value) === current
                            ? html`<span class="registry-tag">current</span>`
                            : nothing}
                        </button>
                      </li>
                    `,
                  )}
                </ul>
              `
            : html`<p class="modal-empty">No models match that search.</p>`}
          ${this._error ? html`<p class="modal-error">${this._error}</p>` : nothing}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
          </div>
        </div>
      </div>
    `;
  }

  _on_backdrop() {
    if (!this._busy) this._close();
  }

  _stop(event) {
    event.stopPropagation();
  }

  _on_query(event) {
    this._query = event.target.value;
    this.requestUpdate();
  }

  _on_keydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      this._close();
      return;
    }

    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      const items = this._filtered_items();
      if (items.length) this._select(items[0].value);
    }
  }

  async _select(value) {
    if (this._busy) return;

    this._busy = true;
    this._error = '';
    try {
      const ok = await session.change_config(this.option.id, String(value));
      if (!ok) throw new Error('The bridge rejected the model change');
      this._close();
    } catch (error) {
      this._error = error.message;
    } finally {
      this._busy = false;
      this.requestUpdate();
    }
  }

  _close() {
    this._query = '';
    this._error = '';
    this._busy = false;
    this.open = false;
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }

  _filtered_items() {
    const query = this._query.trim().toLowerCase();

    return this._items().filter((item) => {
      if (!query) return true;
      return [item.value, item.name, item.description, item.group]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    });
  }

  _items() {
    const groups = Array.isArray(this.option?.options) ? this.option.options : [];
    const items = [];

    for (const group of groups) {
      if (Array.isArray(group.options)) {
        for (const item of group.options) {
          if (item && item.value !== undefined) items.push({ ...item, group: group.name || group.group || '' });
        }
      } else if (group && group.value !== undefined) {
        items.push({ ...group, group: '' });
      }
    }

    return items;
  }
}

customElements.define('model-dialog', ModelDialog);