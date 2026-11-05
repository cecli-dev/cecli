import { LitElement, html } from 'lit';

import { format_cost, format_tokens } from '../core/format.js';
import { StoreController, selectors, store } from '../core/store.js';

export class UsageMeter extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const state = this._store.state;
    const percent = selectors.usage_percent(state);
    const level = selectors.usage_level(state);
    const { used, size, cost } = state.usage;
    const agent = state.agent.version
      ? `${state.agent.name} ${state.agent.version}`
      : state.agent.name;
    const title = `Context ${Math.round(percent)}% · ${format_tokens(used)} / ${format_tokens(size)}`
      + (cost ? ` · ${format_cost(cost)}` : '')
      + ` · ${agent}`;

    return html`
      <div class="usage" title=${title} aria-label=${title}>
        <span class="usage-text">${Math.round(percent)}%</span>
        <span
          class="usage-bar"
          role="progressbar"
          aria-label="Context usage"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow=${Math.round(percent)}
        >
          <span class="usage-fill" data-level=${level} style="width: ${percent.toFixed(1)}%"></span>
        </span>
      </div>
    `;
  }
}

customElements.define('usage-meter', UsageMeter);
