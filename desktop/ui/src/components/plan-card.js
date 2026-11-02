import { LitElement, html } from 'lit';

export class PlanCard extends LitElement {
  static properties = {
    part: { attribute: false },
  };

  createRenderRoot() {
    return this;
  }

  render() {
    const entries = this.part.entries || [];
    const completed = entries.filter((entry) => entry.status === 'completed').length;

    return html`
      <article class="plan-card" ?hidden=${entries.length === 0}>
        <div class="plan-head">
          <span>Plan</span>
          <span class="plan-count badge badge-ghost">${completed}/${entries.length}</span>
        </div>
        <ul class="plan-list">
          ${entries.map(
            (entry) => html`
              <li class="plan-item" data-status=${entry.status}>
                <span class="plan-mark" aria-hidden="true"></span>
                <span class="plan-text">${entry.content}</span>
              </li>
            `,
          )}
        </ul>
      </article>
    `;
  }
}

customElements.define('plan-card', PlanCard);
