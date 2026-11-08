import { LitElement, html } from 'lit';

import './app-backdrop.js';
import './agent-strip.js';
import './app-header.js';
import './composer-bar.js';
import './control-strip.js';
import './onboarding-dialog.js';
import './permission-region.js';
import './session-sidebar.js';
import './toast-stack.js';
import './transcript-view.js';
import './workbench-panel.js';
import './workspace-dialog.js';

import { session } from '../core/session.js';
import { StoreController, store } from '../core/store.js';

export class CecliApp extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._workspace_dialog_open = false;
    this._chat_collapsed = false;
    this._sidebar_collapsed = false;
    this._workbench_collapsed = false;
  }

  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <app-backdrop></app-backdrop>
      <div class="app-shell">
        <app-header
          .chatCollapsed=${this._chat_collapsed}
          .sidebarCollapsed=${this._sidebar_collapsed}
          .workbenchCollapsed=${this._workbench_collapsed}
          @toggle-pane=${this._on_toggle_pane}
        ></app-header>
        <div
          class="workspace-shell"
          data-chat-collapsed=${String(this._chat_collapsed)}
          data-sidebar-collapsed=${String(this._sidebar_collapsed)}
          data-workbench-collapsed=${String(this._workbench_collapsed)}
        >
          <session-sidebar @add-workspace=${this._on_add_workspace}></session-sidebar>
          <main class="chat-panel">
            <transcript-view></transcript-view>
            <permission-region></permission-region>
            <div class="composer-dock">
              <agent-strip></agent-strip>
              <composer-bar></composer-bar>
              <control-strip @open-onboarding=${this._open_onboarding}></control-strip>
            </div>
          </main>
          <workbench-panel></workbench-panel>
        </div>
      </div>
      <toast-stack></toast-stack>
      <workspace-dialog
        .open=${this._workspace_dialog_open}
        @close=${this._on_workspace_dialog_close}
      ></workspace-dialog>
      <onboarding-dialog .open=${Boolean(this._store.state.onboarding_open)}></onboarding-dialog>
    `;
  }

  _on_toggle_pane(event) {
    const pane = event.detail && event.detail.pane;
    if (pane === 'sidebar') {
      this._sidebar_collapsed = !this._sidebar_collapsed;
    } else if (pane === 'chat') {
      this._chat_collapsed = !this._chat_collapsed;
      if (this._chat_collapsed) this._workbench_collapsed = false;
    } else if (pane === 'workbench') {
      this._workbench_collapsed = !this._workbench_collapsed;
      if (this._workbench_collapsed) this._chat_collapsed = false;
    }
    this.requestUpdate();
  }

  _on_add_workspace() {
    this._workspace_dialog_open = true;
    this.requestUpdate();
  }

  _on_workspace_dialog_close() {
    this._workspace_dialog_open = false;
    this.requestUpdate();
  }

  _open_onboarding() {
    session.open_onboarding();
  }

}
customElements.define('cecli-app', CecliApp);
