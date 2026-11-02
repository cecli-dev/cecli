import { LitElement, html } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import './markdown-view.js';
import './plan-card.js';
import './thought-block.js';
import './tool-card.js';

export class AssistantTurn extends LitElement {
  static properties = {
    item: { attribute: false },
  };

  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <div class="msg msg--assistant" data-turn=${this.item.turn}>
        <div class="msg-avatar" aria-hidden="true">c</div>
        <div class="msg-body">
          ${repeat(
            this.item.parts,
            (part) => part.id,
            (part) => this._render_part(part),
          )}
        </div>
      </div>
    `;
  }

  _render_part(part) {
    switch (part.type) {
      case 'text':
        return html`<markdown-view
          .text=${part.text}
          .streaming=${part.streaming}
        ></markdown-view>`;
      case 'thought':
        return html`<thought-block .part=${part}></thought-block>`;
      case 'tool':
        return html`<tool-card .part=${part}></tool-card>`;
      case 'plan':
        return html`<plan-card .part=${part}></plan-card>`;
      default:
        return html``;
    }
  }
}

customElements.define('assistant-turn', AssistantTurn);
