import { LitElement, html } from 'lit';

import './background-panel.js';
import './browser-panel.js';
import './cli-panel.js';
import './terminal-panel.js';

import { StoreController, store } from '../core/store.js';

export class WorkbenchPanel extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const enabled = Boolean(this._store.state.cliPane?.enabled);

    return html`
      <aside
        class="workbench-panel"
        data-legacy=${String(!enabled)}
        aria-label="Browser and command line"
      >
        <browser-panel></browser-panel>
        ${enabled
          ? html`<cli-panel></cli-panel>`
          : html`
              <background-panel></background-panel>
              <terminal-panel></terminal-panel>
            `}
      </aside>
    `;
  }
}

customElements.define('workbench-panel', WorkbenchPanel);
