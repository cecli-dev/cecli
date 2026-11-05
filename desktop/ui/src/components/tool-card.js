import { LitElement, html } from 'lit';

import { CHEVRON_ICON, TOOL_ICONS } from '../core/constants.js';
import { location_label, status_label, tool_output_text } from '../core/format.js';
import { store } from '../core/store.js';

export class ToolCard extends LitElement {
  static properties = {
    part: { attribute: false },
  };

  constructor() {
    super();
    this._open = false;
  }

  createRenderRoot() {
    return this;
  }

  willUpdate() {
    if (!this._has_output()) this._open = false;
  }

  render() {
    const has_output = this._has_output();
    const output = tool_output_text(this.part.content_text);
    const icon = TOOL_ICONS[this.part.kind] || TOOL_ICONS.other;

    return html`
      <article class="tool-card ${this._open ? 'is-open' : ''}" data-tool-id=${this.part.tool_id}>
        <div class="tool-head">
          <span class="tool-icon" data-kind=${this.part.kind} aria-hidden="true">${icon}</span>
          <div class="tool-title-wrap">
            <span class="tool-title">${this.part.title}</span>
            <span class="tool-locations">
              ${this._locations().map(
                (location) => html`
                  <span class="tool-loc" title=${location.path}>${location_label(location)}</span>
                `,
              )}
            </span>
          </div>
          <span class="chip badge badge-ghost" data-status=${this.part.status}>
            ${status_label(this.part.status)}
          </span>
          <button
            class="tool-toggle"
            type="button"
            aria-label="Toggle tool output"
            aria-expanded=${String(this._open && has_output)}
            ?disabled=${!has_output}
            @click=${this._toggle}
          >${CHEVRON_ICON}</button>
        </div>
        <div class="tool-body" ?hidden=${!this._open || !has_output}>
          <pre><code>${output}</code></pre>
        </div>
      </article>
    `;
  }

  _locations() {
    return (this.part.locations || []).filter((location) => location && location.path).slice(0, 4);
  }

  _has_output() {
    return tool_output_text(this.part.content_text).length > 0;
  }

  _toggle() {
    if (!this._has_output()) return;

    this._open = !this._open;
    this.requestUpdate();

    if (this._open && store.state.auto_scroll) {
      this.dispatchEvent(
        new CustomEvent('transcript-layout', { bubbles: true, composed: true }),
      );
    }
  }
}

customElements.define('tool-card', ToolCard);
