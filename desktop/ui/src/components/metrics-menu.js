import { LitElement, html, nothing } from 'lit';

import { METRICS_ICON } from '../core/constants.js';
import { format_cost, format_tokens } from '../core/format.js';
import { StoreController, store } from '../core/store.js';

const STAT_LABELS = {
  tokens_last_minute: 'Tokens last minute',
  max_single_request: 'Largest request',
  requests_per_minute: 'Requests per minute',
};

const ARRAY_STAT_LABELS = ['Tokens last minute', 'Largest request', 'Requests per minute'];

export class MetricsMenu extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._open = false;
    this._pinned = false;
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    this._on_pointer_down = (event) => this._close_outside(event);
    document.addEventListener('pointerdown', this._on_pointer_down, true);
  }

  disconnectedCallback() {
    document.removeEventListener('pointerdown', this._on_pointer_down, true);
    super.disconnectedCallback();
  }

  render() {
    const state = this._store.state;
    const usage = state.usage || {};
    const used = this._number(usage.context_used ?? usage.used);
    const size = this._number(usage.context_size ?? usage.size);
    const percent = size > 0 ? Math.min(Math.max(((used || 0) / size) * 100, 0), 100) : null;
    const rows = this._rows(state, usage, used, size, percent);
    const stats = this._render_stats(usage.stats);
    const title = 'Usage metrics';

    return html`
      <div
        class="strip-menu metrics"
        @mouseenter=${this._on_enter}
        @mouseleave=${this._on_leave}
        @focusin=${this._on_focus_in}
        @focusout=${this._on_focus_out}
        @keydown=${this._on_keydown}
      >
        <button
          type="button"
          class="strip-btn metrics-trigger"
          title=${title}
          aria-label=${title}
          aria-haspopup="true"
          aria-expanded=${this._open ? 'true' : 'false'}
          @click=${this._toggle}
        >
          <span class="metrics-icon" aria-hidden="true">${METRICS_ICON}</span>
        </button>
        ${this._open ? html`
          <div class="metrics-panel" role="region" aria-label="Usage metrics">
            <div class="strip-menu-head">Token usage</div>
            ${rows.length
              ? html`<dl class="metrics-grid">${rows}</dl>`
              : html`<p class="strip-menu-empty">No usage data yet.</p>`}
            ${stats}
          </div>
        ` : nothing}
      </div>
    `;
  }

  _rows(state, usage, used, size, percent) {
    const rows = [];
    const cost = this._format_cost(usage.cost);

    if (cost) rows.push(this._row('Total cost', cost));
    if (this._number(usage.tokens_sent) !== null) {
      rows.push(this._row('Tokens sent', format_tokens(usage.tokens_sent)));
    }
    if (this._number(usage.tokens_received) !== null) {
      rows.push(this._row('Tokens received', format_tokens(usage.tokens_received)));
    }
    if (this._number(usage.tokens_cached) !== null) {
      rows.push(this._row('Tokens cached', format_tokens(usage.tokens_cached)));
    }
    if (used !== null && size !== null && size > 0) {
      const suffix = percent === null ? '' : ` \u00b7 ${Math.round(percent)}%`;
      rows.push(this._row('Context', `${format_tokens(used)} / ${format_tokens(size)}${suffix}`));
    }

    const cache_ratio = this._cache_hit_ratio(usage);
    if (cache_ratio !== null) {
      rows.push(this._row('Cache hit ratio', `${(cache_ratio * 100).toFixed(1)}%`));
    }

    const model = usage.model || this._model_name(state);
    if (model) rows.push(this._row('Model', model));

    return rows;
  }

  _render_stats(stats) {
    if (!stats) return nothing;

    if (Array.isArray(stats)) {
      const values = stats.filter((value) => typeof value === 'number');
      if (!values.length) return nothing;

      const rows = values.map((value, index) =>
        this._row(ARRAY_STAT_LABELS[index] || `Stat ${index + 1}`, format_tokens(value)),
      );
      return this._stats_block(rows);
    }

    if (typeof stats !== 'object') return nothing;

    const entries = Object.entries(stats).filter(
      ([, value]) => value !== null && value !== undefined,
    );
    if (!entries.length) return nothing;

    const nested = entries.every(
      ([, value]) => value && typeof value === 'object' && !Array.isArray(value),
    );
    if (nested) {
      const groups = entries.map(([model, values]) => html`
        <div class="metrics-stats-group">
          <h4>${model}</h4>
          <dl class="metrics-grid">${this._stat_rows(values)}</dl>
        </div>
      `);
      return html`<div class="metrics-stats"><h3>Model stats</h3>${groups}</div>`;
    }

    return this._stats_block(this._stat_rows(stats));
  }

  _stats_block(rows) {
    if (!rows.length) return nothing;
    return html`<div class="metrics-stats"><h3>Model stats</h3><dl class="metrics-grid">${rows}</dl></div>`;
  }

  _stat_rows(stats) {
    return Object.entries(stats)
      .filter(([, value]) => value !== null && value !== undefined && typeof value !== 'object')
      .map(([key, value]) => this._row(this._stat_label(key), this._stat_value(value)));
  }

  _row(label, value) {
    return html`<div class="metrics-row"><dt>${label}</dt><dd>${value}</dd></div>`;
  }

  _format_cost(value) {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 4,
      }).format(value);
    }

    return format_cost(value);
  }

  _number(value) {
    if (value === null || value === undefined || value === '') return null;

    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? number : null;
  }

  _cache_hit_ratio(usage) {
    const explicit = this._number(usage.cache_hit_ratio);
    if (explicit !== null) return Math.min(Math.max(explicit, 0), 1);

    const sent = this._number(usage.tokens_sent);
    const cached = this._number(usage.tokens_cached);
    if (sent === null || sent <= 0 || cached === null) return null;

    return Math.min(cached / sent, 1);
  }

  _model_name(state) {
    const option = (state.config_options || []).find((item) => item.id === 'model');
    return option ? String(option.currentValue ?? '') : '';
  }

  _stat_label(key) {
    if (STAT_LABELS[key]) return STAT_LABELS[key];
    const label = String(key).replace(/_/g, ' ').trim();
    return label.charAt(0).toUpperCase() + label.slice(1);
  }

  _stat_value(value) {
    if (typeof value === 'number') return format_tokens(value);
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    return String(value);
  }

  _open_panel(pinned = false) {
    this._pinned = this._pinned || pinned;
    if (this._open) return;

    this._open = true;
    this.requestUpdate();
  }

  _close_panel() {
    if (!this._open && !this._pinned) return;

    this._open = false;
    this._pinned = false;
    this.requestUpdate();
  }

  _toggle(event) {
    event.stopPropagation();

    if (this._open && this._pinned) {
      this._close_panel();
      return;
    }

    this._open_panel(true);
  }

  _on_enter() {
    this._open_panel();
  }

  _on_leave() {
    if (!this._pinned) this._close_panel();
  }

  _on_focus_in() {
    this._open_panel();
  }

  _on_focus_out(event) {
    const next = event.relatedTarget;
    if (next && this.contains(next)) return;
    this._close_panel();
  }

  _on_keydown(event) {
    if (event.key !== 'Escape') return;

    event.stopPropagation();
    this._close_panel();
    this.querySelector('.metrics-trigger')?.focus();
  }

  _close_outside(event) {
    if (!this._open) return;
    if (event.composedPath().includes(this)) return;
    this._close_panel();
  }
}

customElements.define('metrics-menu', MetricsMenu);