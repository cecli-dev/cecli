import { LitElement, html, nothing } from 'lit';
import { repeat } from 'lit/directives/repeat.js';

import { session } from '../core/session.js';
import { push_toast } from '../core/notices.js';
import { StoreController, store } from '../core/store.js';


export class SessionSidebar extends LitElement {
  constructor() {
    super();
    this._store = new StoreController(this, store);
  }

  createRenderRoot() {
    return this;
  }

  render() {
    const state = this._store.state;
    const workflows = state.workflows || [];

    return html`
      <aside class="session-sidebar" aria-label="Sessions and registries">
        <div class="sidebar-head">
          <span class="sidebar-title">Sessions</span>
          <button
            class="sidebar-add"
            type="button"
            title="New session"
            ?disabled=${state.sessions.length >= state.max_sessions}
            @click=${this._create}
          >+</button>
        </div>

        <div class="session-tree">
          ${state.sessions.length
            ? repeat(
                state.sessions,
                (item) => item.bridgeId,
                (item) => this._render_session(item, state.active_bridge_id),
              )
            : html`<p class="sidebar-empty">No sessions yet</p>`}
        </div>

        <div class="sidebar-workflows">
          <div class="sidebar-workflows-head">
            <span class="sidebar-title">Workflows</span>
            <span class="sidebar-count">${workflows.length}</span>
          </div>
          ${workflows.length
            ? html`
                <ul class="workflow-list">
                  ${repeat(
                    workflows,
                    (item) => item.name || item.id || String(item),
                    (item) => this._render_workflow(item),
                  )}
                </ul>
              `
            : html`<p class="sidebar-empty">No workflows registered</p>`}
        </div>
      </aside>
    `;
  }

  _render_session(item, active_bridge_id) {
    const state = this._store.state;
    const active = item.bridgeId === active_bridge_id;
    const activity = this._activity_for(item, active);
    const live_subagents = (state.subagents || []).filter((agent) => !agent.removed);
    const subagents =
      active && live_subagents.length ? live_subagents : item.subagents || [];

    return html`
      <div class="session-node ${active ? 'is-active' : ''}">
        <div class="session-row" @click=${() => session.switch_session(item.bridgeId)}>
          <span class="status-dot" data-status=${item.status} aria-hidden="true"></span>
          <span class="session-name" title=${item.workspace || ''}>${item.title}</span>
          <span class="activity-badge" data-activity=${activity}>${activity}</span>
          ${item.permissionCount
            ? html`<span class="permission-badge" title="Pending permissions">${item.permissionCount}</span>`
            : nothing}
          <button
            class="session-close"
            type="button"
            title=${item.primary ? 'Primary session' : 'Close session'}
            ?hidden=${item.primary}
            ?disabled=${item.busy}
            @click=${(event) => this._close(event, item.bridgeId)}
          >×</button>
        </div>

        ${subagents.length
          ? html`
              <ul class="subagent-tree">
                ${repeat(
                  subagents,
                  (agent) => agent.sessionId,
                  (agent) => this._render_subagent(item, agent),
                )}
              </ul>
            `
          : nothing}

      </div>
    `;
  }
  _create() {
    this.dispatchEvent(new CustomEvent('new-session', { bubbles: true, composed: true }));
  }

  _close(event, bridge_id) {
    event.stopPropagation();
    session
      .close_session(bridge_id)
      .catch((error) => push_toast(store, error.message, 'error'));
  }

  _render_workflow(item) {
    const name = item.name || item.id || String(item);
    const description = item.description || item.title || '';

    return html`
      <li>
        <button
          type="button"
          class="workflow-row"
          title=${description || `Run ${name}`}
          @click=${() => session.registry_action('workflows', 'run', name)}
        >
          <span class="workflow-name">${name}</span>
          <span class="workflow-run">Run</span>
        </button>
      </li>
    `;
  }

  _select_agent(bridge_id, agent) {
    session.select_agent(bridge_id, agent.sessionId);
  }

  _render_subagent(item, agent) {
    const state = this._store.state;
    const live =
      item.bridgeId === state.active_bridge_id
        ? (state.subagents || []).find((candidate) => candidate.sessionId === agent.sessionId)
        : null;
    const current = live || agent;
    const activity = current.running ? 'running' : current.state || 'idle';

    return html`
      <li
        class="subagent-row"
        title="Open this agent's transcript"
        @click=${() => this._select_agent(item.bridgeId, current)}
      >
        <span
          class="status-dot"
          data-status=${current.running ? 'ready' : 'idle'}
          aria-hidden="true"
        ></span>
        <span class="subagent-name">
          ${current.title || current.name || current.sessionId}
        </span>
        <span class="subagent-state" data-activity=${activity}>${activity}</span>
      </li>
    `;
  }

  _activity_for(item, active) {
    const state = this._store.state;
    if (!active) return item.activity || item.status || 'idle';

    const subagents = (state.subagents || []).filter((agent) => !agent.removed);
    if (state.turn_state === 'requires_action') return 'requires action';
    if (state.busy || subagents.some((agent) => agent.running)) return 'running';

    return state.activity && state.activity !== 'starting'
      ? state.activity
      : item.activity || item.status || 'idle';
  }
}

customElements.define('session-sidebar', SessionSidebar);