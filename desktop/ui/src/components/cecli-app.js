import { LitElement, html } from 'lit';

import './app-backdrop.js';
import './app-header.js';
import './composer-bar.js';
import './control-strip.js';
import './permission-region.js';
import './toast-stack.js';
import './transcript-view.js';

export class CecliApp extends LitElement {
  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <app-backdrop></app-backdrop>
      <div class="app-shell">
        <app-header></app-header>
        <main class="chat-panel">
          <transcript-view></transcript-view>
          <permission-region></permission-region>
          <div class="composer-dock">
            <composer-bar></composer-bar>
            <control-strip></control-strip>
          </div>
        </main>
      </div>
      <toast-stack></toast-stack>
    `;
  }
}

customElements.define('cecli-app', CecliApp);
