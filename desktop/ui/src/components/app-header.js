import { LitElement, html } from 'lit';

import { BRAND_ICON } from '../core/constants.js';
import { StoreController, selectors, store } from '../core/store.js';

export class AppHeader extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const state = this._store.state;
    const label = selectors.connection_label(state);

    return html`
      <header class="topbar">
        <div class="brand">
          <span class="brand-mark" aria-hidden="true">${BRAND_ICON}</span>
          <span class="brand-name">cecli</span>
        </div>

        <div class="workspace" title=${state.workspace || ''}>
          <span class="workspace-path">${state.workspace || '—'}</span>
        </div>

        <span
          class="connection-status"
          data-status=${label}
          role="status"
          aria-label=${`Connection status: ${label}`}
        >
          <span class="status-dot" aria-hidden="true"></span>
          <span class="status-label">${label}</span>
        </span>
      </header>
    `;
  }
}

customElements.define('app-header', AppHeader);
