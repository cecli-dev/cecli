import { LitElement, html } from 'lit';

import { LOGS_ICON } from '../core/constants.js';
import { StoreController, store } from '../core/store.js';

export class LogDrawer extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
  }

  createRenderRoot() {
    return this;
  }

  updated() {
    const details = this.querySelector('details');
    const body = this.querySelector('.logs-body');
    if (details && details.open && body) body.scrollTop = body.scrollHeight;
  }

  render() {
    const logs = this._store.state.logs;

    return html`
      <details class="logs" id="logs-drawer" @toggle=${this._on_toggle}>
        <summary title="Logs" aria-label="Logs">
          <span class="logs-icon" aria-hidden="true">${LOGS_ICON}</span>
          <span class="logs-count" ?hidden=${logs.length === 0}>${logs.length}</span>
        </summary>
        <pre class="logs-body" aria-label="Server log output">${logs.join('\n')}</pre>
      </details>
    `;
  }

  _on_toggle() {
    this.requestUpdate();
  }
}

customElements.define('log-drawer', LogDrawer);
