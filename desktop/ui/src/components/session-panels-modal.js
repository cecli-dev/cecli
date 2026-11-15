import { LitElement, html, nothing } from 'lit';

import { get_session_panels } from '../core/api.js';
import { StoreController, store } from '../core/store.js';

const TABS = [
  { id: 'plans', label: 'Plans' },
  { id: 'asides', label: 'Asides' },
];

export class SessionPanelsModal extends LitElement {
  static properties = {
    open: { type: Boolean },
    tab: { type: String },
  };

  constructor() {
    super();
    this.open = false;
    this.tab = 'plans';
    this._store = new StoreController(this, store);
    this._agents = [];
    this._asides = [];
    this._loading = false;
    this._error = '';
    this._loaded_bridge = null;
    this._load_seq = 0;
  }

  createRenderRoot() {
    return this;
  }

  willUpdate(changed) {
    if (changed.has('open') && this.open) this._loading = true;
  }

  updated(changed) {
    if (!this.open) return;

    const bridge_id = this._store.state.active_bridge_id;
    if ((changed.has('open') && this.open) || bridge_id !== this._loaded_bridge) {
      this._load();
    }

    if (changed.has('open')) this.querySelector('.session-panels-card')?.focus();
  }

  render() {
    if (!this.open) return nothing;

    return html`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card modal-card--wide session-panels-card"
          role="dialog"
          aria-modal="true"
          aria-label="Plans and asides"
          tabindex="-1"
          @click=${this._stop}
          @keydown=${this._on_keydown}
        >
          <div class="modal-tabs" role="tablist">
            ${TABS.map(
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
          <div class="modal-body">${this._render_body()}</div>
          ${this._error ? html`<p class="modal-error">${this._error}</p>` : nothing}
          <div class="modal-actions">
            <button
              type="button"
              class="modal-btn"
              ?disabled=${this._loading}
              @click=${this._load}
            >
              Refresh
            </button>
            <button type="button" class="modal-btn modal-btn--primary" @click=${this._close}>
              Done
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _render_body() {
    if (this._loading) return html`<p class="modal-empty">Loading plans and asides…</p>`;
    return this.tab === 'asides' ? this._render_asides() : this._render_plans();
  }

  _render_plans() {
    if (!this._agents.length) return html`<p class="modal-empty">No agents are active.</p>`;

    return html`
      <div class="session-plan-list">
        ${this._agents.map((agent) => {
          const entries = agent.todos || [];
          const completed = entries.filter((entry) => entry.status === 'completed').length;
          const label = agent.label || agent.name || agent.uuid || 'agent';
          const status = agent.status ? ` · ${agent.status}` : '';

          return html`
            <article class="plan-card session-plan-card">
              <div class="plan-head">
                <span class="session-plan-agent" title=${agent.uuid || ''}>
                  ${label}${status}
                </span>
                <span class="plan-count badge badge-ghost"
                  >${completed}/${entries.length}</span
                >
              </div>
              ${entries.length
                ? html`
                    <ul class="plan-list">
                      ${entries.map(
                        (entry) => html`
                          <li class="plan-item" data-status=${entry.status}>
                            <span class="plan-mark" aria-hidden="true"></span>
                            <span class="plan-text">${entry.content}</span>
                          </li>
                        `,
                      )}
                    </ul>
                  `
                : html`<p class="modal-empty session-plan-empty">No todo list.</p>`}
            </article>
          `;
        })}
      </div>
    `;
  }

  _render_asides() {
    if (!this._asides.length) return html`<p class="modal-empty">No asides yet.</p>`;

    const total = this._asides.length;
    const newest_first = [...this._asides].reverse();
    return html`
      <div class="session-aside-list">
        ${newest_first.map(
          (aside, index) => html`
            <article class="session-aside-card">
              <div class="session-aside-head">Aside ${total - index} of ${total}</div>
              <div class="session-aside-block">
                <span class="session-aside-label">Prompt</span>
                <p class="session-aside-text">${aside.prompt}</p>
              </div>
              <div class="session-aside-block">
                <span class="session-aside-label">Answer</span>
                <p class="session-aside-text">${aside.response}</p>
              </div>
            </article>
          `,
        )}
      </div>
    `;
  }

  /** Refetch both registries while the modal is open. */
  reload() {
    if (this.open) this._load();
  }

  async _load() {
    const bridge_id = this._store.state.active_bridge_id;
    if (!bridge_id) {
      this._agents = [];
      this._asides = [];
      this._loading = false;
      this._error = '';
      this._loaded_bridge = null;
      this.requestUpdate();
      return;
    }

    const seq = ++this._load_seq;
    this._loaded_bridge = bridge_id;
    this._loading = true;
    this._error = '';
    this.requestUpdate();

    try {
      const result = await get_session_panels(bridge_id);
      if (seq !== this._load_seq) return;
      this._agents = Array.isArray(result?.agents) ? result.agents : [];
      this._asides = Array.isArray(result?.asides) ? result.asides : [];
    } catch (error) {
      if (seq === this._load_seq) this._error = error.message;
    } finally {
      if (seq === this._load_seq) {
        this._loading = false;
        this.requestUpdate();
      }
    }
  }

  _select_tab(tab) {
    this.tab = tab;
    this.requestUpdate();
    this.dispatchEvent(new CustomEvent('tab-change', { detail: { tab }, bubbles: true, composed: true }));
  }

  _on_keydown(event) {
    if (event.key !== 'Escape') return;

    event.preventDefault();
    event.stopPropagation();
    this._close();
  }

  _on_backdrop() {
    this._close();
  }

  _stop(event) {
    event.stopPropagation();
  }

  _close() {
    this.open = false;
    this._error = '';
    this._loading = false;
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }
}

customElements.define('session-panels-modal', SessionPanelsModal);
