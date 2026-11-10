import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import './markdown-view.js';
import './plan-card.js';
import { CHEVRON_ICON, TOOL_ICONS } from '../core/constants.js';
import {
  diff_lines,
  is_pill_part,
  location_label,
  status_label,
  tool_output_text,
} from '../core/format.js';

export class AssistantTurn extends LitElement {
  static properties = {
    item: { attribute: false },
    agentId: { type: String },
  };

  constructor() {
    super();
    this._open_ids = new Set();
  }

  willUpdate() {
    const known_ids = new Set(this.item.parts.map((part) => part.id));

    for (const part_id of this._open_ids) {
      if (!known_ids.has(part_id)) this._open_ids.delete(part_id);
    }
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const pills = this.item.parts.filter(is_pill_part);
    const content = this.item.parts.filter((part) => !is_pill_part(part));

    return html`
      <div class="msg msg--assistant" data-turn=${this.item.turn}>
        <div class="msg-body">
          ${pills.length
            ? html`<div class="assistant-pills">
                ${repeat(
                  pills,
                  (part) => part.id,
                  (part) => this._render_pill(part),
                )}
              </div>`
            : nothing}
          ${repeat(
            pills.filter((part) => this._open_ids.has(part.id)),
            (part) => `${part.id}-panel`,
            (part) => this._render_panel(part),
          )}
          ${repeat(
            content,
            (part) => part.id,
            (part) => this._render_part(part),
          )}
        </div>
      </div>
    `;
  }

  _render_pill(part) {
    const active = this._open_ids.has(part.id);

    if (part.type === 'thought') {
      return html`
        <button
          type="button"
          class="assistant-pill"
          data-active=${active}
          aria-expanded=${String(active)}
          @click=${() => this._toggle(part.id)}
        >
          <span class="pill-label">Thinking</span>
          <span class="pill-chevron" aria-hidden="true">${CHEVRON_ICON}</span>
        </button>
      `;
    }

    if (part.type === 'diff') {
      return html`
        <button
          type="button"
          class="assistant-pill assistant-pill--diff"
          data-active=${active}
          aria-expanded=${String(active)}
          title=${part.file}
          @click=${() => this._toggle(part.id)}
        >
          <span class="tool-icon" data-kind="edit" aria-hidden="true">
            ${TOOL_ICONS.edit}
          </span>
          <span class="pill-label">Edited ${part.file}</span>
          <span class="pill-chevron" aria-hidden="true">${CHEVRON_ICON}</span>
        </button>
      `;
    }

    const icon = TOOL_ICONS[part.kind] || TOOL_ICONS.other;

    return html`
      <button
        type="button"
        class="assistant-pill assistant-pill--tool"
        data-active=${active}
        aria-expanded=${String(active)}
        title=${part.title}
        @click=${() => this._toggle(part.id)}
      >
        <span class="tool-icon" data-kind=${part.kind} aria-hidden="true">${icon}</span>
        <span class="pill-label">${part.title}</span>
        <span
          class="tool-status-dot"
          data-status=${part.status}
          title=${status_label(part.status)}
        ></span>
        <span class="pill-chevron" aria-hidden="true">${CHEVRON_ICON}</span>
      </button>
    `;
  }

  _render_panel(part) {
    if (!part) return nothing;

    if (part.type === 'thought') {
      return html`
        <div class="assistant-pill-panel">
          <div class="pill-panel-head"><span>Thinking</span></div>
          <div class="pill-panel-body thought-panel-text">${part.text}</div>
        </div>
      `;
    }

    if (part.type === 'diff') {
      return html`
        <div class="assistant-pill-panel">
          <div class="pill-panel-head"><span>Edited ${part.file}</span></div>
          <div class="diff-panel">
            ${repeat(
              diff_lines(part.diff),
              (line, index) => `${part.id}-${index}`,
              (line) => html`<span class="diff-line ${line.kind}">${line.text || ' '}</span>`,
            )}
          </div>
        </div>
      `;
    }

    const output = tool_output_text(part.content_text);
    const locations = (part.locations || []).filter(
      (location) => location && location.path,
    );

    return html`
      <div class="assistant-pill-panel">
        <div class="pill-panel-head">
          <span>${status_label(part.status)}</span>
          ${locations.map(
            (location) => html`<span class="tool-loc" title=${location.path}>
              ${location_label(location)}
            </span>`,
          )}
        </div>
        ${output
          ? html`<pre><code>${output}</code></pre>`
          : html`<p class="pill-panel-empty">No output yet.</p>`}
      </div>
    `;
  }

  _toggle(part_id) {
    const opening = !this._open_ids.has(part_id);

    if (opening) {
      this._open_ids.add(part_id);
    } else {
      this._open_ids.delete(part_id);
    }

    this.requestUpdate();

    if (opening) {
      this.dispatchEvent(
        new CustomEvent('transcript-layout', { bubbles: true, composed: true }),
      );
    }
  }

  _render_part(part) {
    if (part.type === 'text') {
      return html`<markdown-view
        .text=${part.text}
        .streaming=${part.streaming}
      ></markdown-view>`;
    }
    if (part.type === 'plan') {
      return html`<plan-card .part=${part}></plan-card>`;
    }
    return html``;
  }
}

customElements.define('assistant-turn', AssistantTurn);
