import { LitElement, html, nothing } from 'lit';

import { PLUS_ICON, SEND_ICON, STOP_ICON } from '../core/constants.js';
import { binding_label, matches_key_binding } from '../core/key-bindings.js';
import { get_prompt_history, paste_clipboard } from '../core/api.js';
import { context_path, group_context_files } from '../core/format.js';
import { push_toast } from '../core/notices.js';
import { session } from '../core/session.js';
import { StoreController, selectors, store } from '../core/store.js';

const HISTORY_LIMIT = 500;

export class ComposerBar extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._has_text = false;
    this._pasting = false;
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
    const context_files = selectors.active_context_files(state);
    const active_agent = selectors.active_agent(state);
    const busy = active_agent ? Boolean(active_agent.running) : state.busy;
    const status = selectors.composer_status(state);
    const retry_visible = selectors.retry_visible(state);
    const show_stop = busy && !this._has_text;
    const bindings = state.key_bindings;
    const submit_label = binding_label(bindings, 'submit');
    const newline_label = binding_label(bindings, 'newline');
    const stop_label = binding_label(bindings, 'stop');
    const disabled = show_stop
      ? false
      : this._sending || state.status !== 'ready' || !this._has_text;

    return html`
      <footer class="composer">
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
          <div class="composer-actions">
            <div class="composer-add">
              <button
                class="add-btn"
                type="button"
                aria-label="Manage extensions and context"
                @click=${this._open_extensions}
              >${PLUS_ICON}${context_files.length
                ? html`<span class="add-count" aria-hidden="true">
                    ${context_files.length}
                  </span>`
                : nothing}</button>
              ${this._render_context_popover(context_files)}
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
        </div>
        <div class="composer-meta">
          <span class="hint">${busy
            ? `${submit_label} to steer · ${newline_label} for newline · ↑ for history · ${stop_label} to stop`
            : `${submit_label} to send · ${newline_label} for newline · ↑ for history · ${stop_label} to stop`}</span>
          <div class="composer-state">
            <button
              class="retry-btn"
              type="button"
              ?hidden=${!retry_visible}
              @click=${this._retry}
            >Retry last</button>
            <span
              class="turn-status"
              data-state=${status.turn_state}
              data-kind=${status.kind}
            >
              ${status.turn_state === 'running'
                ? html`<span class="spinner" aria-hidden="true"></span>`
                : html`<span class="turn-dot" aria-hidden="true"></span>`}
              <span>${status.label}</span>
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

  _render_context_popover(files) {
    const groups = group_context_files(files).filter((group) => group.items.length);

    return html`
      <div class="composer-context-popover" role="tooltip">
        <h4 class="composer-context-title">Context</h4>
        ${groups.length
          ? groups.map(
              (group) => html`
                <section class="composer-context-section">
                  <h5 class="composer-context-section-title">${group.label}</h5>
                  <ul class="composer-context-list">
                    ${group.items.map((item) => {
                      const path = context_path(item);

                      return html`<li class="composer-context-item" title=${path}>${path}</li>`;
                    })}
                  </ul>
                </section>
              `,
            )
          : html`<p class="composer-context-empty">No files in context</p>`}
      </div>
    `;
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

  _insert_newline() {
    const textarea = this._textarea();
    if (!textarea) return;

    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    textarea.setRangeText('\n', start, end, 'end');
    this._on_input();
    this._scroll_caret_into_view(textarea);
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
        this._cycle_completion(event.key === 'ArrowDown' ? 1 : -1);
        return;
      }

      if (
        (event.key === 'Tab' || event.code === 'Tab') &&
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.isComposing
      ) {
        event.preventDefault();
        this._cycle_completion(event.shiftKey ? -1 : 1);
        return;
      }

      if (
        event.key === 'ArrowRight' &&
        !event.shiftKey &&
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.isComposing &&
        this._caret_at_end()
      ) {
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

    const bindings = this._store.state.key_bindings;
    if (matches_key_binding(bindings, 'submit', event)) {
      event.preventDefault();
      this._submit();
      return;
    }

    if (matches_key_binding(bindings, 'newline', event)) {
      event.preventDefault();
      this._insert_newline();
    }

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
    const bindings = this._store.state.key_bindings;

    if (matches_key_binding(bindings, 'paste', event)) {
      const textarea = this._textarea();
      const editable = event.target?.closest?.('input, textarea, [contenteditable="true"]');
      if (editable && editable !== textarea) return;

      event.preventDefault();
      this._paste_clipboard();
      return;
    }

    if (!matches_key_binding(bindings, 'stop', event) || !this._is_busy()) return;

    const textarea = this._textarea();
    if (document.activeElement === textarea && textarea.value.trim()) return;

    event.preventDefault();
    session.cancel_turn();
  }

  async _paste_clipboard() {
    if (this._pasting) return;
    this._pasting = true;

    try {
      const result = await paste_clipboard(store.state.bridge_id);
      if (result?.path) {
        push_toast(store, 'Pasted image into the chat', 'info');
      } else if (result?.text) {
        this._insert_text(result.text);
      } else {
        push_toast(store, 'No image or text in the clipboard', 'error');
      }
    } catch (error) {
      push_toast(store, error.message, 'error');
    } finally {
      this._pasting = false;
    }
  }

  _insert_text(text) {
    const textarea = this._textarea();
    if (!textarea) return;

    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    textarea.setRangeText(text, start, end, 'end');
    textarea.focus();
    this._on_input();
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
                  tabindex="-1"
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
        const result = await session.complete(
          value,
          this._store.state.active_agent_session_id,
        );
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

  _cycle_completion(delta) {
    const count = this._completions.length;
    if (!count) return;

    this._completion_index = (this._completion_index + delta + count) % count;
    this.requestUpdate();
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
    const mention = value[start] === '@';
    const quoted = mention && value[start + 1] === '"';
    const directory = choice.endsWith('/');
    let insert = choice;

    if (mention) {
      insert = quoted ? `@"${choice}${directory ? '' : '"'}` : choice;
      if (!directory) insert += ' ';
    } else if (choice.startsWith('/') && start === 0) {
      insert = `${choice} `;
    }

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

  _caret_at_end() {
    const textarea = this._textarea();
    if (!textarea) return false;

    const { selectionStart, selectionEnd, value } = textarea;
    return selectionStart === value.length && selectionEnd === value.length;
  }

  _scroll_caret_into_view(textarea) {
    const caret = textarea.selectionEnd ?? textarea.value.length;
    const style = window.getComputedStyle(textarea);
    const mirror = document.createElement('div');
    const properties = [
      'fontFamily',
      'fontSize',
      'fontStyle',
      'fontWeight',
      'letterSpacing',
      'lineHeight',
      'overflowWrap',
      'tabSize',
      'textTransform',
      'wordBreak',
      'wordSpacing',
    ];

    for (const property of properties) mirror.style[property] = style[property];

    const content_width =
      textarea.clientWidth -
      parseFloat(style.paddingLeft) -
      parseFloat(style.paddingRight);

    mirror.style.position = 'absolute';
    mirror.style.top = '0';
    mirror.style.left = '-9999px';
    mirror.style.boxSizing = 'content-box';
    mirror.style.width = `${content_width}px`;
    mirror.style.padding = '0';
    mirror.style.border = '0';
    mirror.style.visibility = 'hidden';
    mirror.style.whiteSpace = 'pre-wrap';
    mirror.textContent = textarea.value.slice(0, caret);

    const marker = document.createElement('span');
    marker.textContent = '\u200b';
    mirror.appendChild(marker);
    document.body.appendChild(mirror);

    const caret_top = marker.offsetTop;
    const line_height = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2;
    const view_top = textarea.scrollTop;
    const view_bottom = view_top + textarea.clientHeight;

    document.body.removeChild(mirror);

    if (caret_top < view_top) {
      textarea.scrollTop = caret_top;
    } else if (caret_top + line_height > view_bottom) {
      textarea.scrollTop = caret_top + line_height - textarea.clientHeight;
    }
  }
}

customElements.define('composer-bar', ComposerBar);
