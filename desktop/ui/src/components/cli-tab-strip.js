import { LitElement, html, nothing } from 'lit';

export class CliTabStrip extends LitElement {
  static properties = {
    tabs: { attribute: false },
    active_key: { type: String },
    can_new: { type: Boolean },
  };

  constructor() {
    super();
    this.tabs = [];
    this.active_key = '';
    this.can_new = false;
  }

  createRenderRoot() {
    return this;
  }

  updated() {
    const active = this.querySelector('.cli-tab[data-active="true"]');
    active?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }

  render() {
    return html`
      <div class="cli-tabstrip" role="tablist" aria-label="CLI tabs" @keydown=${this._on_keydown}>
        ${this.tabs.map((tab, index) => this._render_tab(tab, index))}
        ${this.can_new
          ? html`<button
              class="cli-tab-new"
              type="button"
              aria-label="New shell"
              title="New shell"
              @click=${this._new}
            >+</button>`
          : nothing}
      </div>
    `;
  }

  _render_tab(tab, index) {
    const active = tab.key === this.active_key;
    return html`
      <div
        class="cli-tab"
        role="tab"
        data-active=${String(active)}
        data-kind=${tab.kind}
        data-status=${tab.status || 'idle'}
        aria-selected=${String(active)}
        aria-controls=${`cli-pane-${sanitize(tab.key)}`}
        tabindex=${active ? '0' : '-1'}
        title=${tab.label}
        @click=${() => this._select(tab.key)}
      >
        <span class="cli-tab-label">${tab.label}</span>
        ${this._render_badge(tab)}
        ${tab.closeable
          ? html`<button
              class="cli-close"
              type="button"
              aria-label=${`Close ${tab.label}`}
              title=${`Close ${tab.label}`}
              @click=${(event) => this._close(event, tab.key)}
            >\u00d7</button>`
          : nothing}
      </div>
    `;
  }

  _render_badge(tab) {
    if (tab.unread > 0) {
      return html`<span class="cli-tab-badge" data-kind="unread">${tab.unread > 99 ? '99+' : tab.unread}</span>`;
    }

    if (tab.kind === 'bg') {
      if (tab.status === 'needs_input') return html`<span class="cli-tab-badge" data-kind="input">?</span>`;
      if (tab.status === 'lost' || tab.status === 'error') return html`<span class="cli-tab-badge" data-kind="error">!</span>`;
      if (tab.status === 'exited' || tab.status === 'failed') return html`<span class="cli-tab-badge" data-kind="done">\u2713</span>`;
      if (tab.status === 'starting' || tab.status === 'running' || tab.status === 'stopping') {
        return html`<span class="cli-tab-badge" data-kind="running" aria-label="running"></span>`;
      }
    }

    if (tab.kind === 'shell' && tab.status === 'running') {
      return html`<span class="cli-tab-badge" data-kind="running" aria-label="running"></span>`;
    }

    return nothing;
  }

  _select(key) {
    if (key === this.active_key) return;
    this.dispatchEvent(new CustomEvent('tab-select', { detail: key, bubbles: true, composed: true }));
  }

  _new(event) {
    event.stopPropagation();
    this.dispatchEvent(new CustomEvent('tab-new', { bubbles: true, composed: true }));
  }

  _close(event, key) {
    event.stopPropagation();
    this.dispatchEvent(new CustomEvent('tab-close', { detail: key, bubbles: true, composed: true }));
  }

  _on_keydown(event) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    if (event.target?.closest?.('.cli-close, .cli-tab-new')) return;

    const index = this.tabs.findIndex((tab) => tab.key === this.active_key);
    if (index < 0) return;

    event.preventDefault();

    let next = index;
    if (event.key === 'ArrowLeft') next = (index - 1 + this.tabs.length) % this.tabs.length;
    if (event.key === 'ArrowRight') next = (index + 1) % this.tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = this.tabs.length - 1;

    const tab = this.tabs[next];
    if (!tab) return;
    this._select(tab.key);
    queueMicrotask(() => this.querySelector(`[aria-controls="cli-pane-${sanitize(tab.key)}"]`)?.focus());
  }
}

function sanitize(value) {
  return String(value || '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

customElements.define('cli-tab-strip', CliTabStrip);