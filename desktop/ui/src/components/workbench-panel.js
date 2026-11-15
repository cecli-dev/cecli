import { LitElement, html } from 'lit';

import './browser-panel.js';
import './cli-panel.js';

export class WorkbenchPanel extends LitElement {
  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <aside class="workbench-panel" aria-label="Browser and command line">
        <browser-panel></browser-panel>
        <cli-panel></cli-panel>
      </aside>
    `;
  }
}

customElements.define('workbench-panel', WorkbenchPanel);
