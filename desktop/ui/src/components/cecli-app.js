import { LitElement, html } from 'lit';

import './app-backdrop.js';
import './agent-strip.js';
import './app-header.js';
import './composer-bar.js';
import './control-strip.js';
import './permission-region.js';
import './session-dialog.js';
import './session-sidebar.js';
import './toast-stack.js';
import './transcript-view.js';

export class CecliApp extends LitElement {
  constructor() {
    super();
    this._session_dialog_open = false;
  }

  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <app-backdrop></app-backdrop>
      <div class="app-shell">
        <app-header></app-header>
        <div class="workspace-shell">
          <session-sidebar @new-session=${this._on_new_session}></session-sidebar>
          <main class="chat-panel">
            <transcript-view></transcript-view>
            <permission-region></permission-region>
            <div class="composer-dock">
              <agent-strip></agent-strip>
              <composer-bar></composer-bar>
              <control-strip></control-strip>
            </div>
          </main>
        </div>
      </div>
      <toast-stack></toast-stack>
      <session-dialog
        .open=${this._session_dialog_open}
        @close=${this._on_session_dialog_close}
      ></session-dialog>
    `;
  }

  _on_new_session() {
    this._session_dialog_open = true;
    this.requestUpdate();
  }

  _on_session_dialog_close() {
    this._session_dialog_open = false;
    this.requestUpdate();
  }
}

customElements.define('cecli-app', CecliApp);
