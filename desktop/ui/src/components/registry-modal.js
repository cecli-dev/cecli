import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { group_hooks } from '../core/hooks.js';
import { session } from '../core/session.js';
import { StoreController, store } from '../core/store.js';

const TABS = [
  { id: 'skills', label: 'Skills' },
  { id: 'mcp', label: 'MCP' },
  { id: 'hooks', label: 'Hooks' },
  { id: 'context', label: 'Context' },
];

export class RegistryModal extends LitElement {
  static properties = {
    open: { type: Boolean },
    tab: { type: String },
  };

  constructor() {
    super();
    this.open = false;
    this.tab = 'skills';
    this._store = new StoreController(this, store);
    this._path = '';
    this._error = '';
    this._busy = false;
  }

  createRenderRoot() {
    return this;
  }

  willUpdate(changed) {
    if (changed.has('open') && this.open) session.refresh_state();
  }

  render() {
    if (!this.open) return nothing;

    return html`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card modal-card--wide"
          role="dialog"
          aria-modal="true"
          aria-label="Session registries"
          @click=${this._stop}
        >
          <div class="modal-tabs" role="tablist">
            ${repeat(
              TABS,
              (item) => item.id,
              (item) => html`
                <button
                  type="button"
                  class="modal-tab"
                  role="tab"
                  data-active=${this.tab === item.id}
                  aria-selected=${this.tab === item.id}
                  @click=${() => this._select_tab(item.id)}
                >
                  ${item.label}
                </button>
              `,
            )}
          </div>
          <div class="modal-body">${this._render_body(this._store.state)}</div>
          ${this._error ? html`<p class="modal-error">${this._error}</p>` : nothing}
          <div class="modal-actions">
            <button type="button" class="modal-btn" @click=${this._close}>Done</button>
          </div>
        </div>
      </div>
    `;
  }

  _render_body(state) {
    switch (this.tab) {
      case 'mcp':
        return this._render_servers(state.mcp_servers || []);
      case 'hooks':
        return this._render_hooks(state.hooks || []);
      case 'context':
        return this._render_context(state.context_files || []);
      default:
        return this._render_skills(state.skills || []);
    }
  }

  _render_hooks(items) {
    const sections = group_hooks(items);
    if (!sections.length) return html`<p class="modal-empty">No hooks are registered.</p>`;

    return html`
      <div class="registry-sections">
        ${sections.map(
          (section) => html`
            <section class="registry-section">
              <h3 class="registry-section-title">${section.label}</h3>
              <ul class="registry-modal-list">
                ${section.hooks.map((hook) => {
                  const name = hook.name || String(hook);
                  const enabled = hook.enabled !== false;
                  const description = hook.description
                    ? html`<span class="registry-hook-description">${hook.description}</span>`
                    : nothing;

                  return html`
                    <li class="registry-modal-row">
                      <span class="status-dot" data-status=${enabled ? 'ready' : 'idle'}></span>
                      <span class="registry-modal-name" title=${name}>
                        ${name}
                        ${description}
                      </span>
                      <span class="registry-hook-meta">priority ${hook.priority ?? 10}</span>
                      <button
                        type="button"
                        class="modal-btn modal-btn--small"
                        @click=${() => this._act('hooks', enabled ? 'remove' : 'load', name)}
                      >
                        ${enabled ? 'Disable' : 'Enable'}
                      </button>
                    </li>
                  `;
                })}
              </ul>
            </section>
          `,
        )}
      </div>
    `;
  }

  _render_skills(items) {
    if (!items.length) return html`<p class="modal-empty">No skills are available.</p>`;

    return html`
      <ul class="registry-modal-list">
        ${items.map((item) => {
          const name = item.name || item.id || String(item);
          const active = item.loaded ?? item.enabled ?? item.status === 'loaded';

          return html`
            <li class="registry-modal-row">
              <span class="status-dot" data-status=${active ? 'ready' : 'idle'}></span>
              <span class="registry-modal-name" title=${name}>${name}</span>
              <button
                type="button"
                class="modal-btn modal-btn--small"
                @click=${() => this._act('skills', active ? 'remove' : 'load', name)}
              >
                ${active ? 'Remove' : 'Load'}
              </button>
            </li>
          `;
        })}
      </ul>
    `;
  }

  _render_servers(items) {
    if (!items.length) return html`<p class="modal-empty">No MCP servers are configured.</p>`;

    return html`
      <ul class="registry-modal-list">
        ${items.map((item) => {
          const name = item.name || item.id || String(item);
          const connected = item.connected ?? item.status === 'connected';

          return html`
            <li class="registry-modal-row">
              <span class="status-dot" data-status=${connected ? 'ready' : 'idle'}></span>
              <span class="registry-modal-name" title=${name}>${name}</span>
              <button
                type="button"
                class="modal-btn modal-btn--small"
                @click=${() => this._act('mcp', connected ? 'disconnect' : 'connect', name)}
              >
                ${connected ? 'Disconnect' : 'Connect'}
              </button>
            </li>
          `;
        })}
      </ul>
    `;
  }

  _render_context(items) {
    return html`
      <div class="modal-inline-form">
        <input
          type="text"
          .value=${this._path}
          placeholder="Relative or absolute file path"
          @input=${this._on_path}
          @keydown=${this._on_path_keydown}
        />
        <button type="button" class="modal-btn modal-btn--small" @click=${this._add_context}>
          Add
        </button>
      </div>
      ${items.length
        ? html`
            <ul class="registry-modal-list">
              ${items.map((item) => {
                const path = item.path || item.name || String(item);
                const read_only = Boolean(item.readOnly || item.read_only);

                return html`
                  <li class="registry-modal-row">
                    <span class="registry-modal-name" title=${path}>${path}</span>
                    ${read_only ? html`<span class="registry-tag">read-only</span>` : nothing}
                    <button
                      type="button"
                      class="modal-btn modal-btn--small"
                      @click=${() => this._remove_context(path)}
                    >
                      Remove
                    </button>
                  </li>
                `;
              })}
            </ul>
          `
        : html`<p class="modal-empty">No context files are attached.</p>`}
    `;
  }

  _select_tab(tab) {
    this.tab = tab;
    this._error = '';
    this.requestUpdate();
  }

  _on_backdrop() {
    if (!this._busy) this._close();
  }

  _stop(event) {
    event.stopPropagation();
  }

  _on_path(event) {
    this._path = event.target.value;
  }

  _on_path_keydown(event) {
    if (event.key !== 'Enter' || event.isComposing) return;
    event.preventDefault();
    this._add_context();
  }

  async _act(kind, action, name) {
    this._busy = true;
    this._error = '';
    try {
      await session.registry_action(kind, action, name);
    } catch (error) {
      this._error = error.message;
      session.refresh_state();
    } finally {
      this._busy = false;
      this.requestUpdate();
    }
  }

  async _add_context() {
    const path = this._path.trim();
    if (!path) return;

    await this._act('context', 'add', path);
    this._path = '';
    this.requestUpdate();
  }

  async _remove_context(path) {
    await this._act('context', 'remove', path);
  }

  _close() {
    this._busy = false;
    this._error = '';
    this._path = '';
    this.open = false;
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }
}

customElements.define('registry-modal', RegistryModal);