import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { SCROLL_LOCK_PX } from '../core/constants.js';
import { session } from '../core/session.js';
import { StoreController, selectors, store } from '../core/store.js';
import './assistant-turn.js';
import './context-message.js';
import './empty-state.js';
import './user-message.js';

export class TranscriptView extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
    this._observer = null;
  }

  createRenderRoot() {
    return this;
  }

  firstUpdated() {
    const transcript = this._transcript();
    if (!transcript) return;

    this._observer = new MutationObserver(() => this._maybe_autoscroll());
    this._observer.observe(transcript, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    this._resize_observer = new ResizeObserver(() => this._maybe_autoscroll());
    this._resize_observer.observe(transcript);
  }

  disconnectedCallback() {
    if (this._observer) this._observer.disconnect();
    this._observer = null;
    if (this._resize_observer) this._resize_observer.disconnect();
    this._resize_observer = null;
    if (this._scroll_timer) clearTimeout(this._scroll_timer);
    this._scroll_timer = null;
    super.disconnectedCallback();
  }
  updated() {
    this._maybe_autoscroll();
    queueMicrotask(() => this._maybe_autoscroll());

    if (this._scroll_timer) clearTimeout(this._scroll_timer);
    this._scroll_timer = setTimeout(() => {
      this._scroll_timer = null;
      this._maybe_autoscroll();
    }, 0);
  }
  render() {
    const state = this._store.state;
    const transcript = selectors.visible_transcript(state);

    return html`
      <div
        class="transcript"
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        tabindex="0"
        @scroll=${this._on_scroll}
        @transcript-layout=${this._maybe_autoscroll}
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

  _scroll_to_bottom(smooth) {
    const transcript = this._transcript();
    if (!transcript) return;

    transcript.scrollTo({
      top: transcript.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
  }

  _maybe_autoscroll() {
    if (this._store.state.auto_scroll) this._scroll_to_bottom(false);
  }

  _on_scroll() {
    const at_bottom = this._near_bottom();
    if (this._store.state.auto_scroll === at_bottom) return;

    session.set_auto_scroll(at_bottom);
  }


  _on_example(event) {
    session.fill_composer(event.detail && event.detail.prompt);
  }
}

customElements.define('transcript-view', TranscriptView);
