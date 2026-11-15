import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { context_path, group_context_files } from '../core/format.js';
import { group_hooks } from '../core/hooks.js';
import { session } from '../core/session.js';
import { StoreController, selectors, store } from '../core/store.js';

export const REGISTRY_TABS = [
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
    this._suggestions = [];
    this._suggestion_index = -1;
    this._completion_seq = 0;
    this._completion_timer = null;
  }

  createRenderRoot() {
    return this;
  }

  willUpdate(changed) {
    if (changed.has('open') && this.open) session.refresh_state();
  }

  disconnectedCallback() {
    clearTimeout(this._completion_timer);
    this._completion_timer = null;
    super.disconnectedCallback();
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
              REGISTRY_TABS,
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
        return this._render_context(selectors.active_context_files(state));
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
    const groups = group_context_files(items);

    return html`
      <div class="modal-inline-form">
        <div class="context-path-field">
          <input
            type="text"
            .value=${this._path}
            placeholder="Relative or absolute file path"
            autocomplete="off"
            @input=${this._on_path}
            @keydown=${this._on_path_keydown}
          />
          ${this._render_context_suggestions()}
        </div>
        <button type="button" class="modal-btn modal-btn--small" @click=${this._add_context}>
          Add
        </button>
      </div>
      <div class="registry-sections">
        ${groups.map(
          (group) => html`
            <section class="registry-section">
              <h3 class="registry-section-title">
                ${group.label}${group.items.length ? ` (${group.items.length})` : ''}
              </h3>
              ${group.items.length
                ? html`
                    <ul class="registry-modal-list">
                      ${group.items.map((item) => {
                        const path = context_path(item);
                        const read_only = Boolean(item.readOnly || item.read_only);

                        return html`
                          <li class="registry-modal-row">
                            <span class="registry-modal-name" title=${path}>${path}</span>
                            ${read_only
                              ? html`<span class="registry-tag">read-only</span>`
                              : nothing}
                            ${item.implicit || group.kind === 'rules'
                              ? nothing
                              : html`<button
                                  type="button"
                                  class="modal-btn modal-btn--small"
                                  @click=${() => this._remove_context(path)}
                                >
                                  Remove
                                </button>`}
                          </li>
                        `;
                      })}
                    </ul>
                  `
                : html`<p class="modal-empty">${group.empty}</p>`}
            </section>
          `,
        )}
      </div>
    `;
  }

  _render_context_suggestions() {
    if (!this._suggestions.length) return nothing;

    return html`
      <ul class="context-suggestions" role="listbox" aria-label="Path completions">
        ${this._suggestions.map((item, index) => {
          const path = String(item);

          return html`
            <li>
              <button
                type="button"
                class="context-suggestion"
                role="option"
                data-active=${index === this._suggestion_index}
                aria-selected=${index === this._suggestion_index}
                @mousedown=${(event) => event.preventDefault()}
                @click=${() => this._accept_context_suggestion(index)}
              >
                ${path}
              </button>
            </li>
          `;
        })}
      </ul>
    `;
  }

  _select_tab(tab) {
    this.tab = tab;
    this._error = '';
    this._path = '';
    this._dismiss_context_completions();
    this.dispatchEvent(new CustomEvent('tab-change', { detail: { tab }, bubbles: true, composed: true }));
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
    this._schedule_context_completions(this._path);
  }

  _on_path_keydown(event) {
    if (this._suggestions.length) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        const count = this._suggestions.length;
        this._suggestion_index = (this._suggestion_index + delta + count) % count;
        this.requestUpdate();
        return;
      }

      if (
        (event.key === 'Tab' || event.key === 'ArrowRight') &&
        !event.shiftKey &&
        !event.isComposing
      ) {
        event.preventDefault();
        this._accept_context_suggestion(this._suggestion_index);
        return;
      }

      if (event.key === 'Escape') {
        event.preventDefault();
        this._dismiss_context_completions();
        return;
      }
    }

    if (event.key !== 'Enter' || event.isComposing) return;
    event.preventDefault();
    this._add_context();
  }

  async _act(kind, action, name) {
    const agent_session_id =
      kind === 'context' ? this._store.state.active_agent_session_id : null;
    this._busy = true;
    this._error = '';
    try {
      await session.registry_action(kind, action, name, agent_session_id);
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
    this._dismiss_context_completions();
    this._path = '';
    this.requestUpdate();
  }

  async _remove_context(path) {
    await this._act('context', 'remove', path);
  }

  _schedule_context_completions(value) {
    clearTimeout(this._completion_timer);
    const seq = ++this._completion_seq;
    this._completion_timer = setTimeout(async () => {
      this._completion_timer = null;
      try {
        const result = await session.complete(
          `/add ${value}`,
          this._store.state.active_agent_session_id,
        );
        if (seq !== this._completion_seq) return;

        this._suggestions = Array.isArray(result?.suggestions) ? result.suggestions : [];
        this._suggestion_index = this._suggestions.length ? 0 : -1;
      } catch (error) {
        if (seq !== this._completion_seq) return;
        this._suggestions = [];
        this._suggestion_index = -1;
      }

      this.requestUpdate();
    }, 160);
  }

  _dismiss_context_completions() {
    clearTimeout(this._completion_timer);
    this._completion_timer = null;
    this._completion_seq += 1;
    this._suggestions = [];
    this._suggestion_index = -1;
    this.requestUpdate();
  }

  _accept_context_suggestion(index) {
    const choice = this._suggestions[index];
    if (!choice) return;

    this._dismiss_context_completions();
    this._path = String(choice);
    this.requestUpdate();

    this.updateComplete.then(() => {
      const input = this.querySelector('.context-path-field input');
      if (!input) return;

      input.focus();
      const end = input.value.length;
      input.setSelectionRange(end, end);
    });

    if (this._path.endsWith('/')) this._schedule_context_completions(this._path);
  }

  _close() {
    this._busy = false;
    this._error = '';
    this._path = '';
    this._dismiss_context_completions();
    this.open = false;
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }
}

customElements.define('registry-modal', RegistryModal);