import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { SCROLL_LOCK_PX } from '../core/constants.js';
import { session } from '../core/session.js';
import { StoreController, selectors, store } from '../core/store.js';
import './agent-strip.js';
import './assistant-turn.js';
import './context-message.js';
import './empty-state.js';
import './user-message.js';

const JUMP_SCROLL_PASSES = 4;

export class TranscriptView extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._observer = null;
    this._scroll_frame = null;
    this._autoscrolling = false;
    this._scroll_target = null;
    this._last_transcript = undefined;
    this._last_transcript_key = undefined;
    this._last_auto_scroll = undefined;
  }

  createRenderRoot() {
    return this;
  }

  firstUpdated() {
    const transcript = this._transcript();
    if (!transcript) return;

    this._observer = new MutationObserver(() => this._schedule_autoscroll());
    this._observer.observe(transcript, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    this._resize_observer = new ResizeObserver(() => this._schedule_autoscroll());
    this._resize_observer.observe(transcript);
  }

  disconnectedCallback() {
    if (this._observer) this._observer.disconnect();
    this._observer = null;
    if (this._resize_observer) this._resize_observer.disconnect();
    this._resize_observer = null;
    this._cancel_autoscroll();
    super.disconnectedCallback();
  }
  updated() {
    const state = this._store.state;
    const transcript = selectors.visible_transcript(state);

    if (transcript === this._last_transcript && state.auto_scroll === this._last_auto_scroll) return;

    const key = `${state.active_agent_session_id || 'main'}:${transcript[0]?.id || ''}`;
    const reset = key !== this._last_transcript_key;

    this._last_transcript = transcript;
    this._last_transcript_key = key;
    this._last_auto_scroll = state.auto_scroll;

    if (state.auto_scroll) this._schedule_autoscroll({ retry: reset });
  }
  render() {
    const state = this._store.state;
    const transcript = selectors.visible_transcript(state);

    return html`
      <div class="transcript-frame">
        <div
          class="transcript"
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          tabindex="0"
          @scroll=${this._on_scroll}
          @transcript-layout=${this._schedule_autoscroll}
        >
          ${selectors.visible_busy(state) && transcript.length === 0
            ? html`<p class="history-note">
                This turn is running in the background; earlier transcript history is not
                replayed after a reload.
              </p>`
            : nothing}
          <empty-state
            ?hidden=${selectors.has_transcript(state) || selectors.visible_busy(state)}
            @example-select=${this._on_example}
          ></empty-state>
          ${repeat(
            transcript,
            (item) => item.id,
            (item) =>
              item.type === 'user'
                ? html`<user-message .text=${item.text}></user-message>`
                : item.type === 'context'
                  ? html`<context-message .item=${item}></context-message>`
                  : html`<assistant-turn
                    .item=${item}
                    .agentId=${state.active_agent_session_id}
                  ></assistant-turn>`,
          )}
        </div>
        <div class="transcript-dock">
          <agent-strip></agent-strip>
          ${state.auto_scroll
            ? nothing
            : html`<button
                type="button"
                class="strip-badge jump-badge jump-latest"
                title="Jump to latest"
                @click=${this._jump_latest}
              >
                <span aria-hidden="true">↓</span> Jump to latest
              </button>`}
        </div>
    `;
  }

  _transcript() {
    return this.querySelector('.transcript');
  }

  _near_bottom() {
    const transcript = this._transcript();
    if (!transcript) return true;

    const distance = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight;
    return distance < SCROLL_LOCK_PX;
  }

  _scroll_to_bottom() {
    const transcript = this._transcript();
    if (!transcript) return;

    transcript.scrollTop = transcript.scrollHeight;
  }

  _schedule_autoscroll(options = {}) {
    if (this._scroll_frame !== null || !this._store.state.auto_scroll) return;

    let passes = options.retry === true ? JUMP_SCROLL_PASSES : 1;
    this._autoscrolling = true;
    this._scroll_target = this._transcript()?.scrollTop ?? null;

    const step = () => {
      this._scroll_frame = null;

      if (!this._store.state.auto_scroll) {
        this._autoscrolling = false;
        this._scroll_target = null;
        return;
      }

      this._scroll_to_bottom();
      this._scroll_target = this._transcript()?.scrollTop ?? null;
      passes -= 1;

      // Placeholders resolving below the fold can grow scrollHeight after the write.
      if (passes <= 0 || this._near_bottom()) {
        this._autoscrolling = false;
        this._scroll_target = null;
        return;
      }

      this._scroll_frame = requestAnimationFrame(step);
    };

    this._scroll_frame = requestAnimationFrame(step);
  }

  _on_scroll(event) {
    if (this._autoscrolling) {
      const host = event?.currentTarget || this._transcript();
      const target = this._scroll_target;

      if (target === null || host === null || host.scrollTop >= target - 1) return;

      this._cancel_autoscroll();
      session.set_auto_scroll(false);
      return;
    }

    const at_bottom = this._near_bottom();
    if (this._store.state.auto_scroll === at_bottom) return;

    session.set_auto_scroll(at_bottom);
  }

  _cancel_autoscroll() {
    if (this._scroll_frame !== null) cancelAnimationFrame(this._scroll_frame);

    this._scroll_frame = null;
    this._autoscrolling = false;
    this._scroll_target = null;
  }

  _jump_latest() {
    session.jump_to_latest();

    this._cancel_autoscroll();
    this._schedule_autoscroll({ retry: true });
  }

  _on_example(event) {
    session.fill_composer(event.detail && event.detail.prompt);
  }
}

customElements.define('transcript-view', TranscriptView);
