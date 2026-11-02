/** Merge an authoritative /api/state snapshot into the store. */
import {
  adopt_session,
  apply_agent,
  apply_status,
  apply_usage,
  replace_config_options,
  restore_turn_state,
  set_workspace,
} from './events.js';
import { add_permission, finalize_assistant, has_pending_permissions } from './transcript.js';

export function apply_snapshot(store, snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return;

  store.update((state) => set_workspace(state, snapshot.workspace));
  if (snapshot.agent) store.update((state) => apply_agent(state, snapshot.agent));
  if (snapshot.modes) store.update((state) => ({ ...state, modes: snapshot.modes }));
  if (Array.isArray(snapshot.configOptions)) replace_config_options(store, snapshot.configOptions);
  adopt_session(store, snapshot.sessionId);

  if (typeof snapshot.busy === 'boolean') {
    store.update((state) => {
      if (snapshot.busy) {
        const pending = has_pending_permissions(state);
        let turn_state = 'running';
        let busy_message = 'cecli is working…';

        if (state.stopping) {
          busy_message = 'Stopping…';
        } else if (pending) {
          turn_state = 'requires_action';
          busy_message = 'Waiting for your approval';
        }

        return {
          ...state,
          busy: true,
          stopping: state.stopping,
          turn_state,
          busy_message,
        };
      }

      return {
        ...finalize_assistant(state),
        busy: false,
        stopping: false,
        turn_state: 'idle',
        busy_message: '',
      };
    });
  }

  if (snapshot.usage) store.update((state) => apply_usage(state, snapshot.usage));
  if (Array.isArray(snapshot.permissions)) {
    const keys = new Set(
      snapshot.permissions.map((permission) => String(permission.requestId)),
    );

    store.update((state) => {
      const permissions = state.permissions.filter((entry) => keys.has(entry.key));
      return permissions.length === state.permissions.length
        ? state
        : { ...state, permissions };
    });

    for (const permission of snapshot.permissions) {
      store.update((state) => add_permission(state, permission));
    }

    if (snapshot.permissions.length) {
      store.update((state) =>
        has_pending_permissions(state)
          ? {
              ...state,
              busy: true,
              turn_state: 'requires_action',
              busy_message: 'Waiting for your approval',
            }
          : state,
      );
    }
  }

  apply_status(store, snapshot.status);
  store.update((state) => (state.stopping ? state : restore_turn_state(state)));
}
