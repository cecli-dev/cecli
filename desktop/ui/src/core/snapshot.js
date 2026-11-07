/** Merge an authoritative /api/state snapshot into one bridge view. */
import {
  apply_agent,
  apply_status,
  apply_usage,
  replace_config_options,
  restore_turn_state,
  set_workspace,
} from './events.js';
import { add_permission, has_pending_permissions } from './transcript.js';

export function apply_snapshot(store, snapshot, bridge_id = null, prune_keys = null) {
  if (!snapshot || typeof snapshot !== 'object') return;

  const target = bridge_id || snapshot.bridgeId || store.active_bridge_id || '';
  if (Array.isArray(snapshot.sessions)) {
    store.set_sessions(snapshot.sessions, snapshot.maxSessions);
  }
  if (!store.active_bridge_id && target) store.set_active(target);

  const scoped = store.scoped(target);
  scoped.update((state) => set_workspace(state, snapshot.workspace));
  scoped.update((state) => ({ ...state, bridge_id: target }));
  if (snapshot.sessionId !== undefined) {
    scoped.update((state) => ({ ...state, session_id: snapshot.sessionId }));
  }
  if (snapshot.title) scoped.update((state) => ({ ...state, title: snapshot.title }));
  if (snapshot.agent) scoped.update((state) => apply_agent(state, snapshot.agent));
  if (snapshot.modes) scoped.update((state) => ({ ...state, modes: snapshot.modes }));
  if (Array.isArray(snapshot.configOptions)) {
    replace_config_options(scoped, snapshot.configOptions);
  }

  scoped.update((state) => ({
    ...state,
    activity: snapshot.activity || state.activity,
    activity_detail: snapshot.activityDetail || '',
    subagents: Array.isArray(snapshot.subagents) ? snapshot.subagents : state.subagents,
    skills: Array.isArray(snapshot.skills) ? snapshot.skills : state.skills,
    mcp_servers: Array.isArray(snapshot.mcpServers) ? snapshot.mcpServers : state.mcp_servers,
    workflows: Array.isArray(snapshot.workflows) ? snapshot.workflows : state.workflows,
    context_files: Array.isArray(snapshot.contextFiles)
      ? snapshot.contextFiles
      : state.context_files,
    details_supported:
      snapshot.detailsSupported === undefined
        ? state.details_supported
        : snapshot.detailsSupported,
  }));

  if (typeof snapshot.busy === 'boolean') {
    scoped.update((state) => {
      if (snapshot.busy) {
        const pending = has_pending_permissions(state);
        return {
          ...state,
          busy: true,
          stopping: state.stopping,
          turn_state: pending ? 'requires_action' : 'running',
          busy_message: state.stopping
            ? 'Stopping…'
            : pending
              ? 'Waiting for your approval'
              : 'cecli is working…',
        };
      }

      return { ...state, busy: false, stopping: false, turn_state: 'idle', busy_message: '' };
    });
  }

  if (snapshot.usage) scoped.update((state) => apply_usage(state, snapshot.usage));
  if (Array.isArray(snapshot.permissions)) {
    const permissions = snapshot.permissions;
    scoped.update((state) => {
      const keys = new Set(
        permissions.map((permission) =>
          permission.bridgeId || target
            ? `${permission.bridgeId || target}:${permission.requestId}`
            : String(permission.requestId),
        ),
      );
      const kept = state.permissions.filter(
        (entry) =>
          prune_keys === null
            ? keys.has(entry.key)
            : !prune_keys.has(entry.key) || keys.has(entry.key),
      );
      return kept.length === state.permissions.length
        ? state
        : { ...state, permissions: kept };
    });

    for (const permission of permissions) {
      scoped.update((state) => add_permission(state, { ...permission, bridgeId: target }));
    }
  }

  apply_status(scoped, snapshot.status);
  scoped.update((state) => (state.stopping ? state : restore_turn_state(state)));
}
