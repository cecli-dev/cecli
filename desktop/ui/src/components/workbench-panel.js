import { LitElement, html } from 'lit';

import './background-panel.js';
import './browser-panel.js';

export class WorkbenchPanel extends LitElement {
  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <aside class="workbench-panel" aria-label="Browser and background commands">
        <browser-panel></browser-panel>
        <background-panel></background-panel>
      </aside>
    `;
  }
}

customElements.define('workbench-panel', WorkbenchPanel);
