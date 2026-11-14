import assert from 'node:assert/strict';
import test from 'node:test';

import { handle_event } from '../src/core/events.js';
import { apply_snapshot } from '../src/core/snapshot.js';
import { create_initial_state } from '../src/core/state.js';
import { Store, selectors } from '../src/core/store.js';

function create_store() {
  return new Store(create_initial_state());
}

test('no-op reducers do not bump the bridge revision', () => {
  const store = create_store();
  store.set_active('s1');
  const before = store.revision('s1');

  store.update((state) => state);
  store.update((state) => ({ ...state }));

  assert.equal(store.revision('s1'), before);
});

test('background events survive until the sessions frame arrives', () => {
  const store = create_store();
  store.update_for('s9', (state) => ({ ...state, status: 'ready', session_id: 'acp-9' }));

  store.set_sessions([{ bridgeId: 's9', status: 'ready', sessionId: 'acp-9' }], 8);

  assert.equal(store.active_bridge_id, 's9');
  assert.equal(store.state.status, 'ready');
  assert.equal(store.state.session_id, 'acp-9');
});

test('switching seeds a new view from the sidebar summary', () => {
  const store = create_store();
  store.set_sessions(
    [
      { bridgeId: 's1', title: 'one', status: 'ready', sessionId: 'a', busy: false },
      { bridgeId: 's2', title: 'two', status: 'ready', sessionId: 'b', busy: true },
    ],
    8,
  );

  store.set_active('s2');

  assert.equal(store.state.bridge_id, 's2');
  assert.equal(store.state.title, 'two');
  assert.equal(store.state.session_id, 'b');
  assert.equal(store.state.busy, true);
});

test('unknown bridges get a blank view instead of the active one', () => {
  const store = create_store();
  store.set_sessions([{ bridgeId: 's1', status: 'ready', sessionId: 'a' }], 8);

  assert.equal(store.state_for('missing').status, 'starting');
  assert.notEqual(store.state_for('missing').bridge_id, 's1');
});

test('a permission arriving during a snapshot fetch survives the prune', () => {
  const store = create_store();
  store.set_active('s1');
  store.update((state) => ({ ...state, session_id: 's1' }));
  const prune_keys = new Set(store.state.permissions.map((entry) => entry.key));
  handle_event(store, {
    type: 'permission',
    bridgeId: 's1',
    requestId: 7,
    sessionId: 's1',
    toolCall: {},
    options: [],
  });

  apply_snapshot(
    store,
    { status: 'ready', busy: true, sessionId: 's1', permissions: [] },
    's1',
    prune_keys,
  );

  assert.equal(store.state.permissions.length, 1);
});

test('root patch_session defaults to the active bridge', () => {
  const store = create_store();
  store.set_sessions([{ bridgeId: 's1', activity: 'idle' }], 8);

  store.patch_session({ activity: 'running', busy: true });

  assert.equal(store.sessions[0].activity, 'running');
  assert.equal(store.sessions[0].busy, true);
});

test('connection state is shared across bridge views', () => {
  const store = create_store();
  store.update((state) => ({ ...state, connected: true, had_connection: true }));
  store.set_sessions(
    [{ bridgeId: 's1' }, { bridgeId: 's2' }],
    8,
  );

  assert.equal(store.state.connected, true);
  assert.equal(store.state.had_connection, true);

  store.set_active('s2');
  assert.equal(store.state.connected, true);

  store.update((state) => ({ ...state, connected: false }));
  assert.equal(store.state_for('s1').connected, false);
  assert.equal(store.state_for('s2').connected, false);
});

test('reconnect updates the shared connection after switching bridges', () => {
  const store = create_store();
  store.set_sessions([{ bridgeId: 's1' }, { bridgeId: 's2' }], 8);
  store.update((state) => ({ ...state, connected: true, had_connection: true }));

  store.set_active('s2');
  store.update((state) => ({ ...state, connected: false }));
  store.set_active('s1');

  const revision = store.revision('s1');
  store.update((state) => ({
    ...state,
    connected: true,
    had_connection: true,
    disconnect_notified: false,
  }));

  assert.equal(store.state.connected, true);
  assert.equal(store.state.had_connection, true);
  assert.equal(store.revision('s1'), revision);
});

test('composer status labels a running main agent as running', () => {
  const store = create_store();

  store.update((state) => ({
    ...state,
    busy: true,
    turn_state: 'running',
    busy_message: 'cecli is working…',
  }));

  assert.deepEqual(selectors.composer_status(store.state), {
    turn_state: 'running',
    label: 'running',
    kind: 'state',
  });
});

test('composer status reflects the active sub-agent instead of the main turn', () => {
  const store = create_store();

  store.update((state) => ({
    ...state,
    busy: true,
    turn_state: 'idle',
    subagents: [{ sessionId: 'agent-1', running: true, state: 'running' }],
    active_agent_session_id: 'agent-1',
  }));

  assert.deepEqual(selectors.composer_status(store.state), {
    turn_state: 'running',
    label: 'running',
    kind: 'state',
  });
});

test('composer status keeps the stopping message while the turn winds down', () => {
  const store = create_store();

  store.update((state) => ({
    ...state,
    busy: true,
    stopping: true,
    turn_state: 'running',
    busy_message: 'Stopping…',
  }));

  assert.deepEqual(selectors.composer_status(store.state), {
    turn_state: 'running',
    label: 'Stopping…',
    kind: 'message',
  });
});

test('composer status keeps an approval prompt on the amber state', () => {
  const store = create_store();

  store.update((state) => ({
    ...state,
    busy: true,
    turn_state: 'requires_action',
    busy_message: 'Waiting for your approval',
  }));

  assert.deepEqual(selectors.composer_status(store.state), {
    turn_state: 'requires_action',
    label: 'Waiting for your approval',
    kind: 'message',
  });
});