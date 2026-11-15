import { LitElement, html, nothing } from 'lit';

const MAX_LINES = 2000;
const FOLLOW_SLACK_PX = 20;

export class CliLogView extends LitElement {
  static properties = {
    entries: { attribute: false },
    bridge_id: { type: String },
    floor: { type: Number },
    active: { type: Boolean },
  };

  constructor() {
    super();
    this.entries = [];
    this.bridge_id = '';
    this.floor = 0;
    this.active = false;
    this._rendered = [];
    this._follow = true;
    this._jump = false;
    this._scroll_frame = null;
  }

  createRenderRoot() {
    return this;
  }

  disconnectedCallback() {
    this._cancel_scroll();
    super.disconnectedCallback();
  }

  updated() {
    if (!this.active) return;

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

    const visible = this._visible_entries();
    const first_visible = visible.length ? Number(visible[0].seq) || 0 : Infinity;
    let dropped = 0;

    while (dropped < this._rendered.length && (Number(this._rendered[dropped].seq) || 0) < first_visible) {
      dropped += 1;
    }

    if (dropped && dropped >= this._rendered.length) {
      host.replaceChildren();
      this._rendered = [];
    } else if (dropped) {
      for (let index = 0; index < dropped; index += 1) host.firstElementChild?.remove();
      this._rendered = this._rendered.slice(dropped);
    }

    const aligned = !this._rendered.length || (
      this._rendered.length <= visible.length
      && this._rendered.every((entry, index) => entry.seq === visible[index].seq)
    );

    if (!aligned) {
      host.replaceChildren();
      this._rendered = [];
    }

    for (let index = this._rendered.length; index < visible.length; index += 1) {
      const entry = visible[index];
      host.append(line_element(entry));
      this._rendered.push(entry);
    }

    while (host.children.length > MAX_LINES) host.firstElementChild?.remove();
    if (this._rendered.length > MAX_LINES) this._rendered = this._rendered.slice(-MAX_LINES);

    if (this._rendered.length && this._follow) this._schedule_scroll(host);
  }

  _visible_entries() {
    const entries = this.entries || [];
    const bridge_id = this.bridge_id;
    const floor = Number(this.floor) || 0;

    return entries.filter((entry) => {
      if (entry.bridge_id && bridge_id && entry.bridge_id !== bridge_id) return false;
      return (Number(entry.seq) || 0) > floor;
    });
  }

  _schedule_scroll(host) {
    if (this._scroll_frame !== null || host.offsetParent === null) return;

    this._scroll_frame = requestAnimationFrame(() => {
      this._scroll_frame = null;

      if (!this.active || !this._follow) return;

      const current = this.querySelector('.cli-log');
      if (!current || current.offsetParent === null) return;

      current.scrollTop = current.scrollHeight;
    });
  }

  _cancel_scroll() {
    if (this._scroll_frame !== null) cancelAnimationFrame(this._scroll_frame);
    this._scroll_frame = null;
  }

  _on_scroll(event) {
    const host = event.currentTarget;
    const distance = host.scrollHeight - host.scrollTop - host.clientHeight;
    const follow = distance <= FOLLOW_SLACK_PX;

    if (follow === this._follow) return;

    this._follow = follow;
    this._jump = !follow;
    this.requestUpdate();
  }

  _to_bottom() {
    const host = this.querySelector('.cli-log');
    if (!host) return;

    this._follow = true;
    this._jump = false;
    host.scrollTop = host.scrollHeight;
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