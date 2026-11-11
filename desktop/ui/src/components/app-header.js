import { LitElement, html } from 'lit';

import { active_agent_location } from '../core/format.js';
import { StoreController, store } from '../core/store.js';


const PANE_ICONS = {
  sidebar: html`<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true">
    <rect x="1.5" y="2" width="13" height="12" rx="2"></rect>
    <path d="M5.5 2v12"></path>
  </svg>`,
  chat: html`<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true">
    <rect x="1.5" y="2" width="13" height="12" rx="2"></rect>
    <path d="M5.5 2v12M10.5 2v12"></path>
  </svg>`,
  workbench: html`<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true">
    <rect x="1.5" y="2" width="13" height="12" rx="2"></rect>
    <path d="M10.5 2v12"></path>
  </svg>`,
};

const BRAND_PHRASES = [
  "control everything _",
  // "complete everything _",
  // "control everywhere _",
  // "create efficiently _",
  // "continue evolving _"
];

const BRAND_PHRASE = BRAND_PHRASES[Math.floor(Math.random() * BRAND_PHRASES.length)];

export class AppHeader extends LitElement {
  static properties = {
    chatCollapsed: { type: Boolean },
    sidebarCollapsed: { type: Boolean },
    workbenchCollapsed: { type: Boolean },
  };
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this.chatCollapsed = false;
    this.sidebarCollapsed = false;
    this.workbenchCollapsed = false;
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const logo_url = `${import.meta.env.BASE_URL}cecli-temp-logo-favicon.svg`;
    const location = active_agent_location(this._store.state);

    return html`
      <header class="topbar">
        <div class="brand">
          <img class="brand-mark" src=${logo_url} alt="" aria-hidden="true" />
          <span class="brand-context">${BRAND_PHRASE}</span>
        </div>
        ${location
          ? html`<span class="brand-context" title=${location}>• ${location}</span>`
          : ''}


        <div class="pane-toggles" role="group" aria-label="Panel visibility">
          <button
            class="pane-toggle"
            type="button"
            data-collapsed=${this.sidebarCollapsed}
            aria-pressed=${!this.sidebarCollapsed}
            aria-label=${this.sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
            title=${this.sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
            @click=${() => this._toggle_pane('sidebar')}
          >${PANE_ICONS.sidebar}</button>
          <button
            class="pane-toggle"
            type="button"
            data-collapsed=${this.chatCollapsed}
            aria-pressed=${!this.chatCollapsed}
            aria-label=${this.chatCollapsed ? 'Show chat' : 'Hide chat'}
            title=${this.chatCollapsed ? 'Show chat' : 'Hide chat'}
            @click=${() => this._toggle_pane('chat')}
          >${PANE_ICONS.chat}</button>
          <button
            class="pane-toggle"
            type="button"
            data-collapsed=${this.workbenchCollapsed}
            aria-pressed=${!this.workbenchCollapsed}
            aria-label=${this.workbenchCollapsed ? 'Show browser panel' : 'Hide browser panel'}
            title=${this.workbenchCollapsed ? 'Show browser panel' : 'Hide browser panel'}
            @click=${() => this._toggle_pane('workbench')}
          >${PANE_ICONS.workbench}</button>
        </div>
      </header>
    `;
  }
  _toggle_pane(pane) {
    this.dispatchEvent(
      new CustomEvent('toggle-pane', { detail: { pane }, bubbles: true, composed: true }),
    );
  }
}

customElements.define('app-header', AppHeader);
