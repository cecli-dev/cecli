import { LitElement, html, nothing } from 'lit';

import { PLUS_ICON, SEND_ICON, STOP_ICON } from '../core/constants.js';
import { get_prompt_history } from '../core/api.js';
import { session } from '../core/session.js';
import { StoreController, selectors, store } from '../core/store.js';

const HISTORY_LIMIT = 500;

export class ComposerBar extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._has_text = false;
    this._sending = false;
    this._applied_revision = 0;
    this._completions = [];
    this._completion_descriptions = {};
    this._completion_index = 0;
    this._completion_start = 0;
    this._completion_seq = 0;
    this._completion_scroll_key = null;
    this._completion_timer = null;
    this._prompt_history = [];
    this._history_index = null;
    this._history_draft = '';
    this._history_bridge_id = null;
    this._on_global_keydown = this._on_global_keydown.bind(this);
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener('keydown', this._on_global_keydown);
  }

  disconnectedCallback() {
    document.removeEventListener('keydown', this._on_global_keydown);
    super.disconnectedCallback();
  }

  updated() {
    this._scroll_active_completion();
    const state = this._store.state;
    this._sync_prompt_history(state.bridge_id);
    if (state.draft_revision === this._applied_revision) return;

    this._applied_revision = state.draft_revision;
    const textarea = this._textarea();
    if (!textarea) return;

    textarea.value = state.draft;
    this._history_index = null;
    this._history_draft = '';
    this._has_text = state.draft.trim().length > 0;
    this._auto_grow();
    textarea.focus();
  }

  render() {
    const state = this._store.state;
    const active_agent = selectors.active_agent(state);
    const busy = active_agent ? Boolean(active_agent.running) : state.busy;
    const retry_visible = selectors.retry_visible(state);
    const show_stop = busy && !this._has_text;
    const disabled = show_stop
      ? false
      : this._sending || state.status !== 'ready' || !this._has_text;

    return html`
      <footer class="composer">
        <div class="busy-indicator" ?hidden=${!busy}>
          <span class="spinner" aria-hidden="true"></span>
          <span>${selectors.busy_text(state)}</span>
        </div>
        ${this._render_completions()}
        <div class="composer-box">
          <textarea
            id="composer-input"
            rows="1"
            placeholder="Type your message…"
            aria-label="Type Message"
            autocomplete="off"
            spellcheck="true"
            @input=${this._on_input}
            @keydown=${this._on_keydown}
          ></textarea>
          <div class="composer-add">
            <button
              class="add-btn"
              type="button"
              aria-label="Manage extensions and context"
              @click=${this._open_extensions}
            >${PLUS_ICON}</button>
            ${this._render_context_popover(state)}
          </div>
          <button
            class="send-btn"
            type="button"
            data-mode=${show_stop ? 'stop' : 'send'}
            aria-label=${show_stop ? 'Stop this turn' : 'Send message'}
            ?disabled=${disabled}
            @click=${this._on_send_click}
          >${show_stop ? STOP_ICON : SEND_ICON}</button>
        </div>
        <div class="composer-meta">
          <span class="hint">${busy
            ? 'Enter to steer · Shift+Enter for newline · ↑ for history · Esc to stop'
            : 'Enter to send · Shift+Enter for newline · ↑ for history · Esc to stop'}</span>
          <div class="composer-state">
            <button
              class="retry-btn"
              type="button"
              ?hidden=${!retry_visible}
              @click=${this._retry}
            >Retry last</button>
            <span class="turn-status" data-state=${state.turn_state}>
              <span class="turn-dot" aria-hidden="true"></span>
              <span>${selectors.turn_label(state)}</span>
            </span>
          </div>
        </div>
      </footer>
    `;
  }

  _open_extensions() {
    document.dispatchEvent(
      new CustomEvent('cecli:open-registry', { detail: { tab: 'context' } }),
    );
  }

  _render_context_popover(state) {
    const files = state.context_files || [];

    return html`
      <div class="composer-context-popover" role="tooltip">
        <h4 class="composer-context-title">Context</h4>
        ${files.length
          ? html`
              <ul class="composer-context-list">
                ${files.map((item) => {
                  const path = this._context_path(item);

                  return html`<li class="composer-context-item" title=${path}>${path}</li>`;
                })}
              </ul>
            `
          : html`<p class="composer-context-empty">No files in context</p>`}
      </div>
    `;
  }

  _context_path(item) {
    return item?.path || item?.name || String(item);
  }

  _textarea() {
    return this.querySelector('#composer-input');
  }

  _auto_grow() {
    const textarea = this._textarea();
    if (!textarea) return;

    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }

  _on_input() {
    const textarea = this._textarea();
    if (!textarea) return;

    this._history_index = null;
    this._history_draft = '';
    this._has_text = textarea.value.trim().length > 0;
    this._auto_grow();
    this._schedule_completions(textarea.value);
    this.requestUpdate();
  }

  _on_keydown(event) {
    if (this._completions.length) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        const count = this._completions.length;
        this._completion_index = (this._completion_index + delta + count) % count;
        this.requestUpdate();
        return;
      }

      if ((event.key === 'Tab' || event.key === 'ArrowRight') && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        this._accept_completion();
        return;
      }

      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        this._dismiss_completions();
        return;
      }
    }

    if (this._handle_history_key(event)) return;

    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;

    event.preventDefault();
    this._submit();
  }

  _on_send_click() {
    if (this._is_busy() && !this._has_text) {
      session.cancel_turn();
      return;
    }

    this._submit();
  }

  async _submit() {
    const textarea = this._textarea();
    if (!textarea || this._sending) return;

    const text = textarea.value.trim();
    if (!text) return;

    this._sending = true;
    this.requestUpdate();

    let sent = false;
    try {
      sent = await session.send_prompt(text);
    } finally {
      this._sending = false;
    }

    if (sent) {
      this._remember_prompt(text);
      textarea.value = '';
      this._has_text = false;
      this._history_index = null;
      this._history_draft = '';
      this._auto_grow();
      this._dismiss_completions();
    }

    this.requestUpdate();
  }

  _retry() {
    const state = store.state;
    if (state.busy || !state.last_prompt) return;

    const textarea = this._textarea();
    if (!textarea) return;

    textarea.value = state.last_prompt;
    this._has_text = true;
    this._history_index = null;
    this._history_draft = '';
    this._auto_grow();
    this.requestUpdate();
    this._submit();
  }

  _on_global_keydown(event) {
    if (event.target?.closest?.('cli-panel')) return;
    if (event.key !== 'Escape' || !this._is_busy()) return;

    const textarea = this._textarea();
    if (document.activeElement === textarea && textarea.value.trim()) return;

    event.preventDefault();
    session.cancel_turn();
  }

  _is_busy() {
    const state = store.state;
    const agent_id = state.active_agent_session_id;
    if (agent_id) {
      const agent = (state.subagents || []).find((item) => item.sessionId === agent_id);
      return Boolean(agent?.running);
    }
    return Boolean(state.busy);
  }
  _render_completions() {
    if (!this._completions.length) return nothing;

    return html`
      <div class="completion-popover" role="listbox" aria-label="Completions">
        <ul class="completion-list">
          ${this._completions.map(
            (item, index) => html`
              <li>
                <button
                  type="button"
                  class="completion-item"
                  role="option"
                  data-active=${index === this._completion_index}
                  aria-selected=${index === this._completion_index}
                  @mousedown=${(event) => event.preventDefault()}
                  @click=${() => this._select_completion(index)}
                >
                  <span class="completion-label">${item}</span>
                  ${this._completion_descriptions[item]
                    ? html`<span class="completion-detail">
                        ${this._completion_descriptions[item]}
                      </span>`
                    : nothing}
                </button>
              </li>
            `,
          )}
        </ul>
      </div>
    `;
  }

  _schedule_completions(value) {
    clearTimeout(this._completion_timer);
    if (!value.trim()) {
      this._dismiss_completions();
      return;
    }

    const seq = ++this._completion_seq;
    this._completion_timer = setTimeout(async () => {
      try {
        const result = await session.complete(value);
        if (seq !== this._completion_seq) return;

        const suggestions = Array.isArray(result?.suggestions) ? result.suggestions : [];
        this._completions = suggestions;
        this._completion_descriptions = result?.descriptions || {};
        this._completion_start = Number.isFinite(result?.start) ? result.start : value.length;
        this._completion_index = 0;
        this.requestUpdate();
      } catch (error) {
        if (seq === this._completion_seq) this._dismiss_completions();
      }
    }, 120);
  }

  _select_completion(index) {
    this._completion_index = index;
    this._accept_completion();
  }

  _accept_completion() {
    const textarea = this._textarea();
    if (!textarea || !this._completions.length) return;

    const value = textarea.value;
    const choice = String(this._completions[this._completion_index]);
    const start = Math.max(0, Math.min(this._completion_start, value.length));
    const insert = choice.startsWith('/') && start === 0 ? `${choice} ` : choice;

    textarea.value = value.slice(0, start) + insert;
    const end = textarea.value.length;
    textarea.setSelectionRange(end, end);
    this._has_text = textarea.value.trim().length > 0;
    this._auto_grow();
    this._dismiss_completions();
    textarea.focus();
  }

  _dismiss_completions() {
    clearTimeout(this._completion_timer);
    this._completion_timer = null;
    this._completion_seq += 1;
    this._completions = [];
    this._completion_descriptions = {};
    this._completion_index = 0;
    this.requestUpdate();
  }

  _scroll_active_completion() {
    const list = this.querySelector('.completion-list');
    const active = this.querySelector('.completion-item[data-active="true"]');
    if (!list || !active) return;

    const scroll_key = `${this._completion_seq}:${this._completion_index}`;
    if (scroll_key === this._completion_scroll_key) return;

    this._completion_scroll_key = scroll_key;
    const list_rect = list.getBoundingClientRect();
    const active_rect = active.getBoundingClientRect();
    if (active_rect.top < list_rect.top) {
      list.scrollTop += active_rect.top - list_rect.top;
    } else if (active_rect.bottom > list_rect.bottom) {
      list.scrollTop += active_rect.bottom - list_rect.bottom;
    }
  }

  _sync_prompt_history(bridge_id) {
    const next_id = bridge_id || null;
    if (next_id === this._history_bridge_id) return;

    this._history_bridge_id = next_id;
    this._prompt_history = [];
    this._history_index = null;
    this._history_draft = '';
    if (!next_id) return;

    get_prompt_history(next_id)
      .then((result) => {
        if (this._history_bridge_id !== next_id) return;
        const fetched = Array.isArray(result?.history) ? result.history : [];
        this._prompt_history = this._merge_prompt_history(fetched);
        this._history_index = null;
      })
      .catch(() => {});
  }

  _merge_prompt_history(fetched) {
    const seen = new Set();
    return [...fetched, ...this._prompt_history]
      .filter((entry) => {
        if (seen.has(entry)) return false;
        seen.add(entry);
        return true;
      })
      .slice(-HISTORY_LIMIT);
  }

  _remember_prompt(text) {
    if (!text) return;
    if (this._prompt_history[this._prompt_history.length - 1] === text) return;

    this._prompt_history.push(text);
    if (this._prompt_history.length > HISTORY_LIMIT) this._prompt_history.shift();
    this._history_index = null;
  }

  _handle_history_key(event) {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return false;
    if (event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return false;

    const textarea = this._textarea();
    if (!textarea || !this._prompt_history.length) return false;

    const navigating = this._history_index !== null;
    if (!navigating && textarea.value.trim().length > 0) return false;

    event.preventDefault();
    this._navigate_history(event.key === 'ArrowUp' ? -1 : 1);
    return true;
  }

  _navigate_history(direction) {
    const textarea = this._textarea();
    if (!textarea || !this._prompt_history.length) return;

    const last = this._prompt_history.length - 1;
    const current = this._history_index;
    if (current === null && direction > 0) return;

    if (current === null) {
      this._history_draft = textarea.value;
      this._history_index = last;
    } else {
      this._history_index = current + direction;
    }

    let value;
    if (this._history_index < 0) {
      this._history_index = 0;
      value = this._prompt_history[0];
    } else if (this._history_index > last) {
      this._history_index = null;
      value = this._history_draft;
    } else {
      value = this._prompt_history[this._history_index];
    }

    textarea.value = value;
    const end = value.length;
    textarea.setSelectionRange(end, end);
    this._has_text = value.trim().length > 0;
    this._auto_grow();
    this.requestUpdate();
  }
}

customElements.define('composer-bar', ComposerBar);
