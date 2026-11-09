import { LitElement, html, nothing } from 'lit';

const MAX_LINES = 2000;

export class CliLogView extends LitElement {
  static properties = {
    entries: { attribute: false },
    workspace_key: { type: String },
  };

  constructor() {
    super();
    this.entries = [];
    this.workspace_key = '';
    this._rendered = [];
    this._follow = true;
    this._jump = false;
  }

  createRenderRoot() {
    return this;
  }

  updated() {
    this._sync_lines();
  }

  render() {
    return html`
      <div class="cli-log-wrap">
        <div class="cli-log" role="log" aria-live="polite" @scroll=${this._on_scroll}></div>
        ${this._jump
          ? html`<button class="cli-jump" type="button" @click=${this._to_bottom}>Jump to latest</button>`
          : nothing}
      </div>
    `;
  }

  _sync_lines() {
    const host = this.querySelector('.cli-log');
    if (!host) return;

    const limit = Math.max(0, this.entries.length - MAX_LINES);
    const visible = this.entries.slice(limit);
    const same_prefix = this._rendered.length <= visible.length
      && this._rendered.every((entry, index) => entry.seq === visible[index].seq);

    if (!same_prefix) {
      host.replaceChildren();
      this._rendered = [];
    }

    for (let index = this._rendered.length; index < visible.length; index += 1) {
      const entry = visible[index];
      host.append(line_element(entry));
      this._rendered.push(entry);
    }

    while (host.children.length > MAX_LINES) host.firstElementChild?.remove();
    if (this._follow) host.scrollTop = host.scrollHeight;
  }

  _on_scroll(event) {
    const host = event.currentTarget;
    const distance = host.scrollHeight - host.scrollTop - host.clientHeight;
    this._follow = distance <= 20;
    this._jump = !this._follow;
    this.requestUpdate();
  }

  _to_bottom() {
    const host = this.querySelector('.cli-log');
    if (host) host.scrollTop = host.scrollHeight;
    this._follow = true;
    this._jump = false;
    this.requestUpdate();
  }
}

function line_element(entry) {
  const line = document.createElement('div');
  line.className = 'cli-log-line';
  line.dataset.level = entry.level || 'info';
  line.dataset.seq = String(entry.seq ?? '');

  const stamp = format_time(entry.ts);
  line.textContent = `[${stamp}] ${String(entry.level || 'info').toUpperCase().padEnd(7)} ${entry.message || ''}`;
  return line;
}

function format_time(value) {
  const date = new Date(Number(value) || Date.now());
  return date.toLocaleTimeString([], { hour12: false });
}

customElements.define('cli-log-view', CliLogView);