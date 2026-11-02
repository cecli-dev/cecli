import { LitElement, html } from 'lit';

const BRAND_ART = `                     ▒▒╗▒▒╗
 ▒▒▒▒▒╗ ▒▒▒▒▒╗ ▒▒▒▒▒╗▒▒║╚═╝
▒▒╔═══╝▒▒▓▓▓▒║▒▒╔═══╝▒▒║▒▒╗
▒▒║    ▒▒╔═══╝▒▒║    ▒▒║▒▒║
╚▒▒▒▒▒╗╚▒▒▒▒▒╗╚▒▒▒▒▒╗▒▒║▒▒║
 ╚════╝ ╚════╝ ╚════╝╚═╝╚═╝`;

export class BrandLogo extends LitElement {
  createRenderRoot() {
    return this;
  }

  render() {
    return html`<pre class="cecli-logo" role="img" aria-label="cecli">${BRAND_ART}</pre>`;
  }
}

customElements.define('brand-logo', BrandLogo);
