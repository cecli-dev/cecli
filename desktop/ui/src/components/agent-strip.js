import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { session } from '../core/session.js';
import { StoreController, store } from '../core/store.js';

export class AgentStrip extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const state = this._store.state;
    const agents = (state.subagents || []).filter((agent) => !agent.removed);
    if (!agents.length) return nothing;

    const active_id = state.active_agent_session_id;

    return html`
      <div class="agent-strip" role="tablist" aria-label="Agent transcripts">
        <button
          class="agent-pill"
          type="button"
          role="tab"
          data-active=${!active_id}
          aria-selected=${!active_id}
          @click=${() => session.select_agent(state.active_bridge_id, null)}
        >
          <span class="agent-dot" data-status=${state.busy ? 'running' : 'idle'} aria-hidden="true"></span>
          <span class="agent-name">Main</span>
        </button>
        ${repeat(
          agents,
          (agent) => agent.sessionId,
          (agent) => html`
            <button
              class="agent-pill"
              type="button"
              role="tab"
              data-active=${active_id === agent.sessionId}
              aria-selected=${active_id === agent.sessionId}
              title=${agent.description || agent.title || agent.name || agent.sessionId}
              @click=${() => session.select_agent(state.active_bridge_id, agent.sessionId)}
            >
              <span
                class="agent-dot"
                data-status=${agent.running ? 'running' : agent.state || 'idle'}
                aria-hidden="true"
              ></span>
              <span class="agent-name">${agent.title || agent.name || agent.sessionId}</span>
            </button>
          `,
        )}
      </div>
    `;
  }
}

customElements.define('agent-strip', AgentStrip);