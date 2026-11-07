import { LitElement, html } from 'lit';

export class ContextMessage extends LitElement {
  static properties = {
    item: { attribute: false },
  };

  createRenderRoot() {
    return this;
  }

  render() {
    const text = String(this.item.text || '');
    const preview = text.split('\n').find((line) => line.trim()) || '';

    return html`
      <details class="context-message">
        <summary>
          ${this.item.source
            ? html`<span class="context-message-source" title=${`Sent by ${this.item.source}`}>
                ${this.item.source}
              </span>`
            : ''}
          <span class="context-message-preview">${preview}</span>
        </summary>
        <div class="context-message-body">${text}</div>
      </details>
    `;
  }
}

customElements.define('context-message', ContextMessage);