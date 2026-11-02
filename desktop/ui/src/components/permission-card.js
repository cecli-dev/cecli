import { LitElement, html } from 'lit';

import { PERMISSION_ICON } from '../core/constants.js';
import { option_class } from '../core/format.js';

export class PermissionCard extends LitElement {
  static properties = {
    entry: { attribute: false },
  };

  createRenderRoot() {
    return this;
  }

  render() {
    const entry = this.entry;
    const options = entry.options || [];
    const disabled = entry.resolving || entry.resolved;

    return html`
      <article
        class="permission-card ${entry.resolving ? 'is-submitting' : ''} ${entry.resolved ? 'is-resolved' : ''}"
        data-request-id=${entry.key}
      >
        <div class="perm-head">
          <span class="perm-icon" aria-hidden="true">${PERMISSION_ICON}</span>
          <div class="perm-titles">
            <h3 class="perm-title">Permission requested</h3>
            <p class="perm-tool">${entry.tool_call.title || 'Tool request'}</p>
          </div>
        </div>
        <p class="perm-question">
          ${entry.detail || 'cecli is asking for permission to continue.'}
        </p>
        <div class="perm-options">
          ${options.length
            ? options.map(
                (option) => html`
                  <button
                    class="perm-option ${option_class(option.kind)} ${entry.chosen === String(option.optionId) ? 'is-chosen' : ''}"
                    type="button"
                    data-option-id=${String(option.optionId)}
                    ?disabled=${disabled}
                    @click=${this._choose}
                  >${option.name || String(option.optionId)}</button>
                `,
              )
            : html`
                <button
                  class="perm-option perm-option--reject"
                  type="button"
                  ?disabled=${disabled}
                  @click=${this._dismiss}
                >Dismiss</button>
              `}
        </div>
        <p
          class="perm-status"
          ?hidden=${!entry.resolved}
          data-kind=${entry.status_kind}
        >${entry.status_text}</p>
      </article>
    `;
  }

  _choose(event) {
    const button = event.currentTarget;
    this._emit(button.dataset.optionId);
  }

  _dismiss() {
    this._emit(null);
  }

  _emit(option_id) {
    if (this.entry.resolving || this.entry.resolved) return;

    this.dispatchEvent(
      new CustomEvent('permission-resolve', {
        bubbles: true,
        composed: true,
        detail: { request_id: this.entry.request_id, option_id },
      }),
    );
  }
}

customElements.define('permission-card', PermissionCard);
