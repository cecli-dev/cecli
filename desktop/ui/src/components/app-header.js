import { LitElement, html } from 'lit';

import { active_agent_location } from '../core/format.js';
import { StoreController, store } from '../core/store.js';
import { get_theme, subscribe_theme, toggle_theme } from '../core/theme.js';


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

const SUN_ICON = html`<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
  <circle cx="12" cy="12" r="4"></circle>
  <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path>
</svg>`;

const MOON_ICON = html`<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 7.5 7.5 0 1 0 20 14.5z"></path>
</svg>`;

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
    this._theme = get_theme();
  }

  connectedCallback() {
    super.connectedCallback();
    this._unsubscribe_theme = subscribe_theme((theme) => {
      this._theme = theme;
      this.requestUpdate();
    });
  }

  disconnectedCallback() {
    this._unsubscribe_theme?.();
    super.disconnectedCallback();
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


        <div class="pane-toggles" role="group" aria-label="View options">
          <button
            class="pane-toggle theme-toggle"
            type="button"
            data-theme=${this._theme}
            aria-pressed=${this._theme === 'dark'}
            aria-label=${this._theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            title=${this._theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            @click=${this._toggle_theme}
          >${this._theme === 'dark' ? SUN_ICON : MOON_ICON}</button>
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

  _toggle_theme() {
    this._theme = toggle_theme();
    this.requestUpdate();
  }

  _toggle_pane(pane) {
    this.dispatchEvent(
      new CustomEvent('toggle-pane', { detail: { pane }, bubbles: true, composed: true }),
    );
  }
}

customElements.define('app-header', AppHeader);
