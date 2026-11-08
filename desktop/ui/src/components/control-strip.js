import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { session } from '../core/session.js';
import { StoreController, store } from '../core/store.js';
import './config-picker.js';
import './log-drawer.js';
import './metrics-menu.js';
import './actions-menu.js';
import './registry-modal.js';
import './model-dialog.js';

export class ControlStrip extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._modal = null;
    this._model_open = false;
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const state = this._store.state;

    return html`
      <div class="control-strip" role="toolbar" aria-label="Session controls">
        <div class="strip-config">
          ${this._render_model(state)}
          ${this._render_pickers(state)}
        </div>
        <div class="strip-badges">
          <button
            type="button"
            class="strip-badge"
            title="Manage skills, MCP servers and context"
            @click=${() => this._open_modal('skills')}
          >
            Extensions
            <span>${state.skills.length + state.mcp_servers.length + state.context_files.length}</span>
          </button>
          ${state.auto_scroll
            ? nothing
            : html`<button
                type="button"
                class="strip-badge jump-badge"
                title="Jump to latest"
                @click=${this._jump_latest}
              >
                <span aria-hidden="true">↓</span> Jump to latest
              </button>`}
        </div>
        <div class="strip-actions">
          <metrics-menu></metrics-menu>
          <log-drawer></log-drawer>
          <actions-menu></actions-menu>
        </div>
      </div>
      <registry-modal
        .open=${Boolean(this._modal)}
        .tab=${this._modal || 'skills'}
        @close=${this._close_modal}
      ></registry-modal>
      <model-dialog
        .open=${this._model_open}
        .option=${this._model_option(this._store.state)}
        @close=${this._close_models}
      ></model-dialog>
    `;
  }

  _jump_latest() {
    session.jump_to_latest();
  }

  _open_modal(tab) {
    this._modal = tab;
    session.refresh_state();
    this.requestUpdate();
  }

  _close_modal() {
    this._modal = null;
    this.requestUpdate();
  }

  _render_model(state) {
    const option = this._model_option(state);
    if (!option) return nothing;

    return html`
      <button
        type="button"
        class="model-trigger"
        title="Search and choose a model"
        @click=${this._open_models}
      >
        <span class="model-trigger-value">${this._model_label(option)}</span>
      </button>
    `;
  }

  _render_pickers(state) {
    const pickers = state.config_options.filter(
      (option) =>
        option.id !== 'mode' && option.id !== 'model' && option.id !== 'reasoning_effort',
    );
    if (!pickers.length) {
      if (state.status === 'ready' && this._model_option(state)) return nothing;
      return html`<span class="strip-muted">${state.status === 'ready' ? 'No config options' : 'Connecting…'}</span>`;
    }

    return repeat(
      pickers,
      (option) => option.id,
      (option) => html`<config-picker .option=${option}></config-picker>`,
    );
  }

  _model_option(state) {
    return state.config_options.find((option) => option.id === 'model') || null;
  }

  _model_label(option) {
    const current = String(option.currentValue ?? '');
    const items = [];

    for (const group of option.options || []) {
      if (Array.isArray(group.options)) items.push(...group.options);
      else if (group && group.value !== undefined) items.push(group);
    }

    const match = items.find((item) => String(item.value) === current);
    return match?.name || current || 'Choose model';
  }

  _open_models() {
    this._model_open = true;
    session.refresh_state();
    this.requestUpdate();
  }

  _close_models() {
    this._model_open = false;
    this.requestUpdate();
  }

}
customElements.define('control-strip', ControlStrip);
