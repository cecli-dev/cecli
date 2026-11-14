import { LitElement, html } from 'lit';
import { repeat } from 'lit/directives/repeat.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';

import { MARKDOWN_THROTTLE_MS } from '../core/constants.js';
import { MarkdownStreamRenderer } from '../core/markdown.js';

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
  }

  createRenderRoot() {
    return this;
  }

  willUpdate(changed) {
    if (!changed.has('text') && !changed.has('streaming')) return;

    if (this.streaming) this._schedule_render();
    else this._render_now();
  }

  updated() {
    if (this.streaming) {
      this._attach_caret();
      return;
    }

    this._remove_caret();
  }

  disconnectedCallback() {
    clearTimeout(this._timer);
    this._timer = null;
    super.disconnectedCallback();
  }

  render() {
    return html`
      <div
        class="md ${this.streaming ? 'is-streaming' : ''}"
        @click=${this._on_click}
      >${repeat(
        this._blocks,
        (block, index) => index,
        (block) => unsafeHTML(block.html),
      )}</div>
    `;
  }

  _schedule_render() {
    if (this._timer) return;

    this._timer = setTimeout(() => {
      this._timer = null;
      this._render_blocks();
      this.requestUpdate();
    }, MARKDOWN_THROTTLE_MS);
  }

  _render_now() {
    clearTimeout(this._timer);
    this._timer = null;
    this._render_blocks();
  }

  _render_blocks() {
    const text = this.text || '';
    if (!text.startsWith(this._text_rendered)) this._renderer.reset();

    this._text_rendered = text;
    const blocks = this._renderer.render(text);
    const changed =
      blocks.length !== this._blocks.length ||
      blocks.some((block, index) => block.html !== this._blocks[index].html);

    this._blocks = blocks;
    if (changed) this._render_revision += 1;
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
