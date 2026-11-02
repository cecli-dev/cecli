import assert from 'node:assert/strict';
import test from 'node:test';

import { handle_event } from '../src/core/events.js';
import { apply_snapshot } from '../src/core/snapshot.js';
import { create_initial_state } from '../src/core/state.js';
import { Store } from '../src/core/store.js';

function create_store() {
  return new Store(create_initial_state());
}

function permission(store, request_id, session_id = 'live') {
  handle_event(store, {
    type: 'permission',
    requestId: request_id,
    sessionId: session_id,
    toolCall: {},
    options: [{ optionId: 'y', name: 'Yes' }],
  });
}

test('updates before a session is adopted are dropped', () => {
  const store = create_store();

  handle_event(store, {
    type: 'update',
    sessionId: 'stale',
    update: {
      sessionUpdate: 'agent_message_chunk',
      content: { type: 'text', text: 'old' },
    },
  });
  assert.equal(store.state.transcript.length, 0);

  handle_event(store, { type: 'session', sessionId: 'live' });
  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'agent_message_chunk',
      content: { type: 'text', text: 'new' },
    },
  });
  assert.equal(store.state.transcript.length, 1);
  assert.equal(store.state.transcript[0].parts[0].text, 'new');
});

test('permission cards for another session are ignored', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 'live' });

  permission(store, 1, 'stale');
  assert.equal(store.state.permissions.length, 0);

  permission(store, 2, 'live');
  assert.equal(store.state.permissions.length, 1);
});

test('resolving one permission keeps the other pending cards', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });
  permission(store, 1, 's1');
  permission(store, 2, 's1');

  handle_event(store, { type: 'permission_resolved', requestId: 1, optionId: 'y' });

  assert.equal(store.state.permissions.length, 2);
  assert.equal(store.state.permissions.find((item) => item.key === '1').resolved, true);
  assert.equal(store.state.permissions.find((item) => item.key === '2').resolved, false);
  assert.equal(store.state.turn_state, 'requires_action');
  assert.equal(store.state.busy, true);
});

test('a snapshot during a stop keeps the stopping state', () => {
  const store = create_store();
  store.update((state) => ({
    ...state,
    busy: true,
    stopping: true,
    turn_state: 'running',
    session_id: 's1',
  }));

  apply_snapshot(store, {
    status: 'ready',
    busy: true,
    sessionId: 's1',
    workspace: '/tmp/project',
    configOptions: [],
    modes: {},
    agent: { name: 'cecli', version: '1' },
    permissions: [],
  });

  assert.equal(store.state.stopping, true);
  assert.equal(store.state.busy_message, 'Stopping…');
});

test('a snapshot drops permission cards the bridge no longer lists', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });
  permission(store, 1, 's1');
  permission(store, 2, 's1');

  apply_snapshot(store, {
    status: 'ready',
    busy: true,
    sessionId: 's1',
    configOptions: [],
    modes: {},
    permissions: [{ requestId: 2, sessionId: 's1', toolCall: {}, options: [] }],
  });

  assert.equal(store.state.permissions.length, 1);
  assert.equal(store.state.permissions[0].key, '2');
});
test('a snapshot that prunes every card returns the turn to running', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });
  permission(store, 1, 's1');
  assert.equal(store.state.turn_state, 'requires_action');

  apply_snapshot(store, {
    status: 'ready',
    busy: true,
    sessionId: 's1',
    configOptions: [],
    modes: {},
    permissions: [],
  });

  assert.equal(store.state.permissions.length, 0);
  assert.equal(store.state.turn_state, 'running');
  assert.equal(store.state.busy_message, 'cecli is working…');
});
