import { LitElement, html } from 'lit';
import { repeat } from 'lit/directives/repeat.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';

import {
  MARKDOWN_RENDER_SCALE,
  MARKDOWN_THROTTLE_MAX_MS,
  MARKDOWN_THROTTLE_MS,
} from '../core/constants.js';
import { MarkdownStreamRenderer } from '../core/markdown.js';

let visibility_observer = null;

export class MarkdownView extends LitElement {
  static properties = {
    text: { type: String },
    streaming: { type: Boolean },
  };

  constructor() {
    super();
    this.text = '';
    this.streaming = false;
    this._renderer = new MarkdownStreamRenderer();
    this._blocks = [];
    this._text_rendered = '';
    this._render_revision = 0;
    this._timer = null;
    this._caret_for = null;
    this._render_ms = 0;
    this._render_started = null;
    this._deferred = false;
    this._markdown_ready = false;
    this._visible = false;
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();

    if (!this._markdown_ready && this._can_defer()) observe_visibility(this);
  }

  willUpdate(changed) {
    if (!changed.has('text') && !changed.has('streaming')) return;

    if (this.streaming) {
      this._deferred = false;
      this._schedule_render();
      return;
    }

    if (!this._markdown_ready && (this._deferred || (this._can_defer() && !this._visible))) {
      this._deferred = true;
      if (this._can_defer()) observe_visibility(this);
      return;
    }

    this._render_now();
  }

  updated() {
    if (this._render_started !== null) {
      this._render_ms = performance.now() - this._render_started;
      this._render_started = null;
    }

    if (this.streaming) {
      this._attach_caret();
      return;
    }

    this._remove_caret();
  }

  disconnectedCallback() {
    clearTimeout(this._timer);
    this._timer = null;
    unobserve_visibility(this);
    super.disconnectedCallback();
  }

  render() {
    return html`
      <div
        class="md ${this.streaming ? 'is-streaming' : ''}"
        @click=${this._on_click}
      >${this._deferred
        ? html`<div class="md-pending">${this.text}</div>`
        : repeat(
          this._blocks,
          (block, index) => index,
          (block) => unsafeHTML(block.html),
        )}</div>
    `;
  }

  _schedule_render() {
    if (this._timer) return;

    const delay = Math.min(
      MARKDOWN_THROTTLE_MAX_MS,
      Math.max(MARKDOWN_THROTTLE_MS, Math.ceil(this._render_ms * MARKDOWN_RENDER_SCALE)),
    );

    this._timer = setTimeout(() => {
      this._timer = null;
      this._render_blocks();
      if (!this.streaming) this._deferred = false;
      this.requestUpdate();
    }, delay);
  }

  _render_now() {
    clearTimeout(this._timer);
    this._timer = null;
    this._render_blocks();
  }

  _render_blocks() {
    const started = performance.now();
    const text = this.text || '';
    if (!text.startsWith(this._text_rendered)) this._renderer.reset();

    this._text_rendered = text;
    const blocks = this._renderer.render(text);
    const changed =
      blocks.length !== this._blocks.length ||
      blocks.some((block, index) => block.html !== this._blocks[index].html);

    this._blocks = blocks;
    if (changed) this._render_revision += 1;

    this._render_started = started;
    this._markdown_ready = true;
  }

  _attach_caret() {
    if (this._caret_for === this._render_revision) return;

    const container = this.querySelector('.md');
    if (!container) return;

    this._remove_caret();

    const caret = document.createElement('span');
    caret.className = 'stream-caret';
    caret.setAttribute('aria-hidden', 'true');

    const last = container.lastElementChild;

    if (last && /^(P|LI|H1|H2|H3|BLOCKQUOTE)$/.test(last.tagName)) {
      last.appendChild(caret);
    } else {
      container.appendChild(caret);
    }

    this._caret_for = this._render_revision;
  }

  _remove_caret() {
    for (const caret of this.querySelectorAll('.stream-caret')) caret.remove();
    this._caret_for = null;
  }

  _can_defer() {
    return typeof IntersectionObserver === 'function';
  }

  _on_visible() {
    this._visible = true;
    unobserve_visibility(this);

    if (!this._deferred) return;

    this._deferred = false;
    this._render_now();
    this.requestUpdate();
  }

  _on_click(event) {
    const button = event.target.closest('.code-copy');
    if (button) this._copy_code(button);
  }

  async _copy_code(button) {
    const block = button.closest('.code-block');
    const code = block ? block.querySelector('code') : null;
    if (!code) return;

    try {
      await navigator.clipboard.writeText(code.textContent);
    } catch (error) {
      copy_fallback(code.textContent);
    }

    flash_button(button, 'Copied');
  }
}

/** Register a replay view to render markdown when it nears the viewport. */
function observe_visibility(element) {
  if (visibility_observer === null) {
    visibility_observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) entry.target._on_visible();
        }
      },
      { rootMargin: '800px 0px' },
    );
  }

  visibility_observer.observe(element);
}

function unobserve_visibility(element) {
  visibility_observer?.unobserve(element);
}

/** Clipboard fallback for non-secure contexts. */
function copy_fallback(text) {
  const helper = document.createElement('textarea');
  helper.value = text;
  helper.setAttribute('readonly', 'readonly');
  helper.style.position = 'fixed';
  helper.style.opacity = '0';
  document.body.appendChild(helper);
  helper.select();

  try {
    document.execCommand('copy');
  } catch (error) {
    return;
  } finally {
    helper.remove();
  }
}

/** Briefly swap a button label to confirm a copy. */
function flash_button(button, label) {
  const original = button.textContent;
  button.textContent = label;

  setTimeout(() => {
    if (button.isConnected) button.textContent = original;
  }, 1400);
}

customElements.define('markdown-view', MarkdownView);
