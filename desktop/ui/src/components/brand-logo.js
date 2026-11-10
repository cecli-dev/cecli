import { LitElement, html } from 'lit';

const BRAND_ART = `
 ▒▒▒▒▒╗ ▒▒▒▒▒╗
▒▒╔═══╝▒▒▓▓▓▒║
▒▒║    ▒▒╔═══╝
╚▒▒▒▒▒╗╚▒▒▒▒▒╗▒▒▒▒▒╗
 ╚════╝ ╚════╝╚════╝
`.replace(/^\n|\n[ \t]*$/g, '');;

export class BrandLogo extends LitElement {
  createRenderRoot() {
    return this;
  }

  render() {
    return html`<pre class="cecli-logo" role="img" aria-label="ce_">${BRAND_ART}</pre>`;
  }
}

customElements.define('brand-logo', BrandLogo);
