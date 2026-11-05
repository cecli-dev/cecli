import { LitElement, html } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { NEW_CHAT_ICON, RESTART_ICON } from '../core/constants.js';
import { session } from '../core/session.js';
import { StoreController, store } from '../core/store.js';
import './config-picker.js';
import './log-drawer.js';
import './usage-meter.js';

export class ControlStrip extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const state = this._store.state;

    return html`
      <div class="control-strip" role="toolbar" aria-label="Session controls">
        <div class="strip-config">
          ${state.config_options.length
            ? repeat(
                state.config_options,
                (option) => option.id,
                (option) => html`<config-picker .option=${option}></config-picker>`,
              )
            : html`<span class="strip-muted">${state.status === 'ready' ? 'No config options' : 'Connecting…'}</span>`}
        </div>

        <div class="strip-actions">
          <usage-meter></usage-meter>
          <log-drawer></log-drawer>
          <button
            class="strip-btn"
            type="button"
            title="New chat"
            aria-label="New chat"
            ?disabled=${state.new_chat_pending}
            @click=${this._new_chat}
          >${NEW_CHAT_ICON}</button>
          <button
            class="strip-btn"
            type="button"
            title="Restart cecli"
            aria-label="Restart cecli"
            ?disabled=${state.restart_pending}
            @click=${this._restart}
          >${RESTART_ICON}</button>
        </div>
      </div>
    `;
  }

  _new_chat() {
    session.new_chat();
  }

  _restart() {
    session.restart_server();
  }
}

customElements.define('control-strip', ControlStrip);
