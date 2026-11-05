import { LitElement, html } from 'lit';
import { classMap } from 'lit/directives/class-map.js';
import { repeat } from 'lit/directives/repeat.js';

import { StoreController, store } from '../core/store.js';

export class ToastStack extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
  }

  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <div class="toasts" aria-live="polite" aria-atomic="false">
        ${repeat(
          this._store.state.toasts,
          (toast) => toast.id,
          (toast) => html`
            <div
              class=${classMap({
                'toast-item': true,
                'toast-item--error': toast.kind === 'error',
                'toast-item--info': toast.kind !== 'error',
                'is-visible': toast.visible,
              })}
              role="status"
            >${toast.message}</div>
          `,
        )}
      </div>
    `;
  }
}

customElements.define('toast-stack', ToastStack);
