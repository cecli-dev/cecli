import { LitElement, html } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { SCROLL_LOCK_PX } from '../core/constants.js';
import { session } from '../core/session.js';
import { StoreController, selectors, store } from '../core/store.js';
import './assistant-turn.js';
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
        <empty-state
          ?hidden=${selectors.has_transcript(state)}
          @example-select=${this._on_example}
        ></empty-state>
        ${repeat(
          state.transcript,
          (item) => item.id,
          (item) =>
            item.type === 'user'
              ? html`<user-message .text=${item.text}></user-message>`
              : html`<assistant-turn .item=${item}></assistant-turn>`,
        )}
      </div>
      <button class="jump-pill" type="button" ?hidden=${state.auto_scroll} @click=${this._jump}>
        <span aria-hidden="true">↓</span> Jump to latest
      </button>
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

  _jump() {
    session.jump_to_latest();
    this._scroll_to_bottom(true);
  }

  _on_example(event) {
    session.fill_composer(event.detail && event.detail.prompt);
  }
}

customElements.define('transcript-view', TranscriptView);
