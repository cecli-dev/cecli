import { LitElement, html } from 'lit';

import './brand-logo.js';

const EXAMPLES = [
  {
    prompt: 'Explain the structure of this repository and where I should start reading.',
    title: 'Explain this repo',
  },
  {
    prompt: 'Find a likely bug in the current changes and explain how to fix it.',
    title: 'Find a bug',
  },
  {
    prompt: 'Run the test suite and summarise any failures with likely causes.',
    title: 'Run the tests',
  },
];

export class EmptyState extends LitElement {
  createRenderRoot() {
    return this;
  }

  render() {
    return html`
      <section class="empty-state">
        <brand-logo></brand-logo>
        <h1>What can I help you build?</h1>
        <p>Ask a question, request a change, or start with one of these.</p>
        <div class="examples">
          ${EXAMPLES.map(
            (example) => html`
              <button
                class="example"
                type="button"
                data-prompt=${example.prompt}
                @click=${this._on_example}
              >
                <span class="example-glyph" aria-hidden="true"></span>
                <span class="example-text"><strong>${example.title}</strong></span>
              </button>
            `,
          )}
        </div>
      </section>
    `;
  }

  _on_example(event) {
    const button = event.currentTarget;
    this.dispatchEvent(
      new CustomEvent('example-select', {
        bubbles: true,
        composed: true,
        detail: { prompt: button.dataset.prompt },
      }),
    );
  }
}

customElements.define('empty-state', EmptyState);
