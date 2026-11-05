import { LitElement, html } from 'lit';

import { session } from '../core/session.js';

export class ThoughtBlock extends LitElement {
  static properties = {
    part: { attribute: false },
  };

  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <details class="thought" ?open=${this.part.open} @toggle=${this._on_toggle}>
        <summary>Thinking</summary>
        <div class="thought-text">${this.part.text}</div>
      </details>
    `;
  }

  _on_toggle(event) {
    const open = event.currentTarget.open;
    if (open === this.part.open) return;

    session.set_thought_open(this.part.id, open);
  }
}

customElements.define('thought-block', ThoughtBlock);
