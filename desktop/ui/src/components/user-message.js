import { LitElement, html } from 'lit';

export class UserMessage extends LitElement {
  static properties = {
    text: { type: String },
  };

  constructor() {
    super();
    this.text = '';
  }

  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <div class="msg msg--user">
        <div class="bubble">${this.text}</div>
      </div>
    `;
  }
}

customElements.define('user-message', UserMessage);
