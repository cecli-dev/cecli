import { LitElement, html } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { session } from '../core/session.js';
import { StoreController, store } from '../core/store.js';
import './permission-card.js';

export class PermissionRegion extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const permissions = this._store.state.permissions;

    return html`
      <div class="permission-region" ?hidden=${permissions.length === 0}>
        ${repeat(
          permissions,
          (entry) => entry.key,
          (entry) => html`
            <permission-card
              .entry=${entry}
              @permission-resolve=${this._on_resolve}
            ></permission-card>
          `,
        )}
      </div>
    `;
  }

  _on_resolve(event) {
    const { request_id, option_id } = event.detail;
    session.resolve_permission(request_id, option_id);
  }
}

customElements.define('permission-region', PermissionRegion);
