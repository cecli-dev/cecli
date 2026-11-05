import { LitElement, html } from 'lit';

export class AppBackdrop extends LitElement {
  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <div class="backdrop" aria-hidden="true">
        <span class="orb orb--indigo"></span>
        <span class="orb orb--violet"></span>
        <span class="orb orb--teal"></span>
        <span class="grain"></span>
      </div>
    `;
  }
}

customElements.define('app-backdrop', AppBackdrop);
