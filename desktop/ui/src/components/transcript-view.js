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
    this._scroll_frame = null;
    this._autoscrolling = false;
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
    if (this._scroll_frame !== null) cancelAnimationFrame(this._scroll_frame);
    this._scroll_frame = null;
    this._autoscrolling = false;
    super.disconnectedCallback();
  }
  updated() {
    this._schedule_autoscroll();
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

  _scroll_to_bottom(smooth) {
    const transcript = this._transcript();
    if (!transcript) return;

    transcript.scrollTo({
      top: transcript.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
  }

  _schedule_autoscroll() {
    if (this._scroll_frame !== null || !this._store.state.auto_scroll) return;

    let target = null;
    let passes = 0;
    this._autoscrolling = true;

    const finish = () => {
      this._autoscrolling = false;
    };

    const step = () => {
      this._scroll_frame = null;

      const transcript = this._transcript();
      if (!transcript) {
        finish();
        return;
      }

      if (target === null && !this._store.state.auto_scroll) {
        finish();
        return;
      }

      // A user scroll-up moves above the last programmatic target.
      if (target !== null && transcript.scrollTop < target - 1) {
        finish();
        session.set_auto_scroll(false);
        return;
      }

      this._scroll_to_bottom(false);
      target = transcript.scrollTop;
      passes += 1;

      // Offscreen content-visibility placeholders resolve over the next few frames.
      if (passes >= 4) {
        finish();
        return;
      }

      this._scroll_frame = requestAnimationFrame(step);
    };

    this._scroll_frame = requestAnimationFrame(step);
  }

  _on_scroll() {
    if (this._autoscrolling) return;

    const at_bottom = this._near_bottom();
    if (this._store.state.auto_scroll === at_bottom) return;

    session.set_auto_scroll(at_bottom);
  }

  _jump_latest() {
    session.jump_to_latest();
  }

  _on_example(event) {
    session.fill_composer(event.detail && event.detail.prompt);
  }
}

customElements.define('transcript-view', TranscriptView);
